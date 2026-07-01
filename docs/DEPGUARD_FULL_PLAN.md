# DepGuard — Full Project Plan (v0.1 → v1.0)

> The complete, self-contained plan for the whole project — every item from the original `AgentBench-Live_Project.md` §7
> definition-of-done appears here, sequenced into three staged releases over ~6 weeks, plus the job-search workstream that
> runs alongside it. Supersedes `DEPGUARD_V01_PLAN.md` (its content is embedded as Phase 1) and the 4-week plan in the
> spec §6. `DECISIONS.md` v1.3.0 remains the design authority for all frozen interfaces.

**Owner:** Deepanathan Rajendiran
**Created:** 2026-07-01
**Timeline:** Phase 1 = Jul 2–15 (`v0.1`) · Phase 2 = Jul 16–29 (`v0.2`) · Phase 3 = Jul 30–Aug 12 (`v1.0`)
**Honest total:** ~6 weeks of build. The original "3–4 weeks for everything" was a 7–8.5-week scope in disguise; this plan
keeps ALL of it but stages it so a public, defensible artifact exists at the 2-week mark — because the job search is live now
and specs convert to zero interviews.
**One name everywhere:** **DepGuard**. "AgentBench-Live" is retired as a public name; the eval harness is "the proof," not a second product.

---

## 0. Ground rules (from the 2026-07-01 evaluation — unanimous across all three judges)

1. **Repo goes public by 2026-07-03** with spec + DECISIONS.md committed as-is.
2. **No further DECISIONS.md amendment without an attached failing test.** The v1.1.0→v1.3.0 loop is the project's #1 risk. From now on, code contact resolves open questions — not spec rounds.
3. **No un-measured number ever ships** on a README, resume, or demo. Every metric appears only after the run that produced it.
4. **Interviews outrank features.** After v0.1 ships, the decision gate (§6) governs how much of Phases 2–3 actually gets built.

### The reframed headline (correction, not descoping — applies to every phase)

> **"DepGuard: measuring when an LLM agent adds value over a solved deterministic pipeline — under a 100%-mechanical oracle."**

Why: (a) the generic "trajectory eval harness" was commoditized during planning (agentevals, LangSmith Align Evals, Langfuse OSS judge, Judgment Labs, HAL) — the scarce asset is the **mechanical 4-predicate verifier + frozen-corpus ground truth**; (b) the lethal interview objection — *"osv-scanner already does this deterministically, why an LLM?"* — is answered by making the ablation **three arms** (deterministic script vs single-agent vs multi-agent) and making that question the headline experiment. The script will likely tie or win; that honest result IS the story. (c) The 71–90% false-positive stat is driven by *reachability* analysis, which DepGuard excludes — always cite it with that caveat.

Recruiter pitch (no CVE/semver/OSV jargon in the first 30 words):

> "Security scanners cry wolf — most dependency alerts are false alarms and teams burn days triaging them by hand. DepGuard is an AI agent that proves which alerts are real, cites the exact evidence, names the smallest safe upgrade — and every answer is checked by a mechanical verifier, so I can tell you *exactly* how often it's right."

---

## 1. Phase map — where every original DoD item lands

| Original spec §7 item | Phase | Notes |
|---|---|---|
| Golden-trajectory dataset + deterministic mocks | **1** (25–30 cases) → **2** (40–60) | Phase 1 seeds genuine branching so metrics have variance |
| Single-vs-multi ablation with paired-bootstrap CIs | **1** | Upgraded to **three arms** (adds deterministic script) |
| Merge-blocking eval gate in CI | **1** | Plain pytest GitHub Action (promptfoo is mid-acquisition by OpenAI — churn risk) |
| Published typed MCP server | **1** | stdio in Phase 1; Streamable HTTP hardening Phase 2 |
| OpenTelemetry traces in Langfuse (screenshot) | **1** | |
| Live demo URL (Cloud Run) | **1** (basic) → **2** (hardened) | First thing cut in Phase 1 if slipping |
| Full frozen corpus (all.zip pipeline, 4 ecosystems) | **2** | Phase 1 uses a hand-picked 30–60 record npm+PyPI micro-corpus |
| Prompt-injection red-team set + block rate | **2** | ~20 prompts, measured before reported |
| Online evals (heuristics 100% + judge sample) | **2** | Needs the demo URL generating traces first |
| LLM-as-judge calibrated vs human audit | **2** | Reframed to have real surface (see D19–20) |
| Cost-per-task + p95 dashboard with alerting | **2** | Langfuse dashboards first; Grafana only if time allows |
| Adaptive model routing + cost/latency table | **2** | |
| pip-installable eval harness | **3** | As `depguard-eval`, honestly framed "built for DepGuard, thin reuse seam" |
| Thin Terraform module | **3** | Lowest interview value — deliberately last |
| README-leads-with-metrics, DECISIONS, LIMITATIONS, Loom | **1**, refreshed each release | |

---

## 2. Phase 1 — `v0.1` "Ship the Oracle" (D1–D14, Jul 2–15)

**Goal:** a public, tagged, defensible release: micro-corpus + mechanical verifier + three-arm ablation with CIs + MCP server + Langfuse traces. Carries ~90% of the interview value.

| Day | Deliverable (committed by end of day) |
|---|---|
| **D1** (Jul 2) | Repo **public**: spec + DECISIONS.md committed, README stub with the cry-wolf pitch, ground rules in CONTRIBUTING. Transcribe the §0 registries: `ecosystem_system_map.json`, `plan_action_tool_map.json`, `tool_key_args.json`, `trajectory.schema.json`. (Week 1 is typing, not thinking — the design exists.) |
| **D2** | 3 pure tools (`parse_manifest` as a thin stub accepting a simple JSON manifest for now, `check_version_affected`, `compute_minimal_fix`) + `verifier.py` (4 predicates, E_A OR-aggregation) + pytest suite over semver boundary cases (`fixed` exclusive, `last_affected` inclusive, `"0"` = −∞, withdrawn short-circuit). |
| **D3** | **Micro-corpus frozen:** 30–60 hand-picked npm+PyPI OSV records, selection criteria documented against DECISIONS §1.2 (reads as a scope decision, not cherry-picking); deps.dev **derived extract** (§1.7b — version lists + `(version, advisory-key)` table + deterministic re-fetch script; legally load-bearing for a public repo); `SNAPSHOT.lock`, `corpus_snapshot_id`, `NOTICE/ATTRIBUTION.md`. |
| **D4** | 3 snapshot-backed tools (`osv_query_package`, `resolve_published_versions`, `crosscheck_second_source`) + envelope error paths (`SNAPSHOT_READ_ERROR`, `SNAPSHOT_MALFORMED`, `RANGE_UNRESOLVABLE`) + deterministic replay tests. |
| **D5** | LangGraph graph (supervisor → planner → retriever → tool_worker → verifier) runs end-to-end on the corpus, emitting Trajectory JSON + OTel GenAI spans; `seed_01` (a known scanner false positive) passes the first trajectory test. **DECISIONS §8 Week-1 bar met.** |
| **D6** | Golden set: 25–30 trajectories — true positives, scanner FPs, withdrawn, `no_fix_available`, `already_safe`, multi-`affected[]`, `disagree` cases, **plus branching seeds** (malformed manifest, alias-resolution dead end, corrupted snapshot file, unpinned versions). Gold labels generated by the verifier; `gold_ref` sidecar join. |
| **D7** | CI: plain-pytest **merge-blocking GitHub Action** (full graph on mocks vs golden set). Buffer/catch-up — protect this day. |
| **D8** | Ablation arms: deterministic script (osv-scanner-equivalent, ~300 lines) + single-agent ReAct baseline, both emitting Trajectory JSON so one verifier scores all three arms. |
| **D9** | **Run the three-arm ablation:** paired-bootstrap 95% CIs (reuse fine-tune project code verbatim), verdict-flip count, honest results table, first LIMITATIONS draft. Degenerate CIs (no variance) get reported plainly, not hidden. |
| **D10** | **MCP server** (stdio + Streamable HTTP) exposing the 6 tools, public install instructions, smoke test from a stock MCP client. |
| **D11** | Langfuse polish + trace screenshot. Demo surface: FastAPI + SSE "paste your `package.json`" page with **coverage-aware fallback** to 2–3 canned famous lockfiles (the micro-corpus will miss most real manifests — an empty result table is the real demo-death hazard). Cloud Run deploy. |
| **D12** | README rewrite leading with measured numbers; LIMITATIONS final (flip count, script-vs-agent result, corpus scope, reachability caveat); **red-CI trajectory-diff GIF** (break the planner prompt in a PR, capture the gate going red with the gold-vs-actual diff). |
| **D13** | 90-second Loom (paste-manifest moment + red-CI moment + honest ablation slide); resume bullets updated with real numbers (§7); **tag `v0.1`**. |
| **D14** | **Distribution day** (§5): referral-first outreach begins with the live artifact. Interview-proofing: whiteboard the 4 predicates + E_A OR-aggregation from memory; rehearse the "why an LLM at all" framing. |

**Cut order if Phase 1 slips:** Cloud Run → demo web page (keep CLI + Loom) → MCP HTTP transport (keep stdio) → golden set down to 20. **Never cut:** verifier, three-arm ablation with CIs, public repo, honest README.

---

## 3. Phase 2 — `v0.2` "Production Hardening" (D15–D28, Jul 16–29)

**Goal:** everything the original spec's Week-3 promised, built on a shipped foundation — full corpus, all four ecosystems, security rail, online evals, routing, dashboards. Applications are already out; this phase runs at ~80% build / 20% outreach.

| Days | Deliverable |
|---|---|
| **D15–17** | **Full corpus pipeline:** `freeze_osv.py` (all.zip download, per-entry §1.2 curation across the four vetted comparators — watch Go pseudo-versions and PEP440 edge cases), `freeze_depsdev.py` (derived-extract builder; cap per-package version fan-out for pathological npm packages), `curate.py` → `CURATION_REPORT.json` with per-record IN/OUT + drop reasons, new `corpus_snapshot_id`, CC-BY/CC0 provenance rule + the CI test that no GHSA-referencing record is tagged CC0. Target ~300–600 surviving entries; pin per-ecosystem counts in `corpus/README.md`. |
| **D18** | **crates.io + Go ecosystems live:** comparators wired, real manifest parsers (`package.json`, `requirements.txt`, `Cargo.toml`, `go.mod`) replacing the D2 stub, golden set expanded to **40–60 trajectories** across all four ecosystems; re-run the three-arm ablation on the full set; refresh CIs and flip count. |
| **D19–20** | **LLM-as-judge, calibrated with real surface:** judge (Sonnet + Haiku routing) scores narrative quality across ALL verdict explanations and `reconciliation_note`s — not just the handful of `disagree` notes — on a published rubric; 15–20-case human audit; report judge-human agreement. Judge stays OUT of the correctness path (that remains mechanical, and the README says so — that separation is itself the differentiator vs judge-everything platforms). |
| **D21–22** | **Prompt-injection rail:** input classifier + retrieval/output sanitization; ~20-prompt red-team set (injection via manifest comments, malicious package names, poisoned advisory text in the corpus); **measured** block rate reported — whatever it is. |
| **D23–24** | **Online evals on live traces:** heuristic checks on 100% of demo-URL traffic (envelope-error rate, schema validity, citation presence) + LLM-judge on a 10–20% sample, feeding Langfuse scores; document the offline→online loop (failing online cases become golden-set candidates). |
| **D25** | **Adaptive model routing:** cheap path (Haiku) vs agentic path (Sonnet) with an explicit routing rule; **measured cost/latency table** per arm and per route. |
| **D26** | **Dashboards + alerting:** Langfuse cost-per-task + p95 latency dashboards; regression alert on golden-set score drop in CI. Grafana/Prometheus ONLY if ahead of schedule — it duplicates Langfuse for interview purposes. |
| **D27** | Cloud Run hardening: concurrency/timeout budgets, cold-start note, request logging → the scale/SLA narrative (`docs/SYSTEM_DESIGN.md`: N docs / Q QPS / p95 / $-per-task) — the system-design interview ammo. |
| **D28** | **Tag `v0.2`**, README + LIMITATIONS refresh, second Loom take if the numbers changed materially, outreach wave 2 with the new numbers. |

---

## 4. Phase 3 — `v1.0` "Packaging & Reach" (D29–D42, Jul 30–Aug 12)

**Goal:** the reusable-artifact and audience layer. By now interviews should be landing — this phase yields to interview prep whenever they conflict (§6).

| Days | Deliverable |
|---|---|
| **D29–31** | **`depguard-eval` pip package:** extract the harness (trajectory schema, four metrics, verifier protocol, bootstrap-CI runner) behind a thin adapter seam; honest framing — "built for DepGuard; bring your own mechanical oracle to reuse it." PyPI release + versioned docs. Do NOT genericize beyond the seam — framework-building is the failure mode. |
| **D32** | **Thin Terraform module** (Cloud Run + service account + secrets) — IaC literacy checkbox, deliberately last because nobody deep-dives new-grad Terraform. |
| **D33–34** | *Stretch (only if ahead):* **OpenVEX export** — DepGuard verdicts emitted as VEX documents consumable by Trivy/Grype; this plugs the project into the real industry triage workflow and is a strong enterprise talking point. |
| **D35–37** | **The writeup:** a technical post — *"When does an agent beat a script? Measuring agents under a mechanical oracle"* — leading with the three-arm ablation numbers and the flip count; publish on a personal blog + cross-post; this is the distribution asset for the F-1→H-1B public-artifact narrative. |
| **D38–39** | Launch push: Show HN / LinkedIn / r/MachineLearning post built around the red-CI GIF and the honest negative/positive result; submit to eval-focused newsletters. Stars are secondary — existence of a public artifact with users is what the visa narrative needs. |
| **D40–42** | **Tag `v1.0`.** Full DoD audit (§8). Portfolio site + resume final pass. Interview-prep sprint: rehearse the system-design narrative, the judge-vs-oracle separation story, and the three rehearsed defenses (§5). |

---

## 5. Parallel workstream — job search (starts D14, never pauses)

- **Lane (corrected by research):** FDE-*titled* roles need 3–7+ yrs (OpenAI 5+, Anthropic 3–4+) — not new-grad viable. Target **Agent Engineer / Agent SWE (New Grad)**: Sierra (New Grad + Early Career Agent Engineering), Decagon (Agent Software Engineer), **Palantir FDSE New Grad Commercial** (sponsors H-1B; avoid gov/clearance tracks on F-1), plus the broad Applied-AI/GenAI new-grad market. Frontier-lab FDE is the 1–2-years-out goal, not the entry point.
- **Cadence:** from D14 — referral-first outreach (cold apps convert <2%; referrals ~4×): short note + live URL + red-CI GIF; Loom for recruiters, README for engineers. Wave 2 at v0.2 (D28) with refreshed numbers; wave 3 at v1.0 launch (D38–39).
- **Visa notes (verify with counsel):** F-1 change-of-status petitions are currently exempt from the $100k new-petition fee; the Dec 2025 wage-weighted lottery rule cuts entry-level (Level I) odds to roughly half — STEM-OPT's 3-year runway and employers offering above Level I wages are the mitigations. Filter for Commercial (non-clearance) roles.
- **Three rehearsed defenses (required before any deep-dive):**
  1. *"Why an LLM at all?"* → the deliverable is the measurement under a mechanical oracle; the deterministic script is an ablation arm **on purpose**, and its result — win or tie — is the headline.
  2. **Whiteboard from memory:** the 4 predicates, E_A OR-aggregation, and why `corpus_snapshot_id` can't hash `CURATION_REPORT.json` (the polished spec WILL trigger an AI-authorship probe).
  3. **The FP-stat caveat:** 71–90% is driven by reachability analysis; DepGuard addresses the version-range slice of triage — say it before the interviewer does.

---

## 6. Decision gates (interviews outrank features)

- **Gate A (D14, v0.1 shipped):** if interview requests are arriving → Phase 2 proceeds at reduced pace and prep gets priority. If silence → 2 days diagnosing distribution (README first-screen, pitch, outreach targets) before building more. Features are never the fix for a distribution problem.
- **Gate B (D28, v0.2 shipped):** onsite-stage interviews → freeze features, Phase 3 shrinks to the writeup only (D35–37). No traction → reassess targeting with real market feedback before investing Phase 3.
- **Standing rule:** any live interview process beats any build task on the same day.

---

## 7. Resume bullets — final form (numbers filled ONLY after the runs that produce them)

- Built **DepGuard**, a dependency-CVE false-positive triage agent (LangGraph supervisor/worker, typed **MCP** tool contracts) whose every verdict is scored by a **100%-mechanical 4-predicate verifier** over a frozen OSV + deps.dev corpus — no LLM-judge in the correctness path.
- Ran a **three-arm ablation** — deterministic pipeline vs single-agent vs multi-agent — on a ⟨40–60⟩-case golden-trajectory set with **paired-bootstrap 95% CIs**, publishing the honest result (⟨which arm won; verdict-flip count⟩) and a LIMITATIONS analysis of what trajectory metrics can and cannot detect on a mechanically decidable task.
- Closed the offline→online eval gap: **OpenTelemetry GenAI traces** into **Langfuse**, heuristic evals on 100% of traffic + calibrated **LLM-judge** on a ⟨10–20⟩% sample (judge-human agreement ⟨x⟩ on a ⟨15–20⟩-case audit), **merge-blocking CI** that turns red on any regression with a gold-vs-actual trajectory diff, and adaptive Sonnet/Haiku routing with a **measured** cost/latency table.
- Hardened the agent surface: **published a typed MCP server** and a pip-installable eval harness (`depguard-eval`), added a prompt-injection rail measured against a ⟨20⟩-prompt red-team set (block rate ⟨x⟩/⟨n⟩ — reported as measured), and documented every tradeoff in DECISIONS.md with a scale/cost/latency design.

*(Banned until measured: any block rate, cost multiple, or "beat baseline" claim. The old spec §8 pre-written numbers are void.)*

## 8. Full definition of done (v1.0 — all original items, staged)

**Phase 1 (v0.1):** ☐ public repo (Jul 3) · ☐ micro-corpus + `corpus_snapshot_id` + deps.dev derived extract + attribution · ☐ 6 tools on the uniform envelope · ☐ 4-predicate verifier (labels gold AND scores) · ☐ 25–30 golden trajectories with branching seeds · ☐ three-arm ablation + paired-bootstrap CIs + flip count · ☐ merge-blocking pytest Action · ☐ published MCP server · ☐ Langfuse trace screenshot · ☐ README-with-numbers + LIMITATIONS + red-CI GIF + Loom · ☐ tagged `v0.1` (~Jul 15) · ☐ Cloud Run URL (if on schedule)

**Phase 2 (v0.2):** ☐ full frozen corpus (all.zip pipeline, `{npm, PyPI, crates.io, Go}`, CURATION_REPORT, provenance CI test) · ☐ real manifest parsers ×4 · ☐ golden set 40–60 · ☐ ablation re-run on full set · ☐ calibrated LLM-judge (rubric + human audit, outside the correctness path) · ☐ injection rail + measured block rate · ☐ online evals on live traces · ☐ adaptive routing + measured cost/latency table · ☐ dashboards + regression alerting · ☐ `SYSTEM_DESIGN.md` scale/SLA narrative · ☐ tagged `v0.2` (~Jul 29)

**Phase 3 (v1.0):** ☐ `depguard-eval` on PyPI · ☐ thin Terraform module · ☐ technical writeup published · ☐ launch posts · ☐ (stretch) OpenVEX export · ☐ tagged `v1.0` (~Aug 12)

## 9. Risk register

| Risk | Mitigation |
|---|---|
| **Planning relapse** (v1.4 spec rounds instead of commits) | Ground rules 1–2; public repo pressure; failing-test requirement for any amendment |
| **Script arm wins and is framed badly** ("I proved my agent unnecessary") | It likely will win/tie — rehearse the framing: the deliverable is the *measurement*; a negative result with CIs is the senior signal no other candidate demos |
| Degenerate trajectory metrics (no variance) | Branching seeds in the golden set (D6); if CIs still degenerate, LIMITATIONS says so plainly |
| Demo shows an empty table on a real manifest (coverage, not staleness) | Coverage-aware fallback to canned famous lockfiles (D11); full corpus in Phase 2 shrinks the gap |
| Corpus pipeline blowups (Go pseudo-versions, PEP440, npm version fan-out) | Micro-corpus first (Phase 1); drop-on-ambiguity rule; fan-out cap in `freeze_depsdev.py` |
| deps.dev ToS on raw bytes in a public repo | Derived non-substantial extract is the default from D3 onward (§1.7b); raw bytes only with written legal sign-off |
| AI-authorship suspicion in deep dives | Whiteboard drill (§5); the candidate designed these mechanisms — rehearsal, not risk |
| H-1B lottery odds at entry wages | STEM-OPT runway; prioritize employers paying above Level I; Commercial (non-clearance) roles only |
| Phase 2/3 crowding out interviews | Decision gates (§6); standing rule: interviews outrank features |
