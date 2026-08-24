# DECISIONS.md — DepGuard (AgentBench-Live)

**Status:** FROZEN FOUNDATION (v1.3.0) — amended 2026-07-01 (orig. 2026-06-25). All downstream work (deterministic mocks, golden set, LangGraph graph, MCP server, OTel instrumentation, promptfoo gate) builds against the interfaces frozen here. Changes require a `schema_version` bump and a corpus re-freeze.

**Amendments (v1.1.0, 2026-06-30)** — owner review caught five issues, all applied: (1) **withdrawn advisories** now short-circuit so `compute_minimal_fix` never chases ghost fixes, and the **P1/P3 verifier contradiction is resolved** (`check_version_affected` returns raw `contained`; the withdrawn override lives only at the verdict layer, folded into `affected_gold`); (2) **plan-adherence** is now alert-grouped (no false penalty for valid alert reorderings); (3) **network error codes** (`RATE_LIMITED`/`TIMEOUT`/`UPSTREAM_*`) dropped — impossible in a corpus-only runtime — replaced with local snapshot-read errors; (4) **minimal-fix tier** is a strict ecosystem allowlist `{npm, crates.io, Go}` (PyPI/Maven/RubyGems never qualify, regardless of OSV range type); (5) **`corpus_snapshot_id`** no longer hashes `CURATION_REPORT.json` (cycle broken) — it hashes raw source bytes + a curation-ruleset version tag, and the id is embedded back into the report.

**Amendments (v1.2.0, 2026-06-30)** — a 22-subagent adversarial verification pass (each finding independently confirmed against the live file + web) validated all v1.1.0 fixes and the core mechanical-verifier property, and closed the four confirmed blockers: (1) **multi-`affected[]` aggregation** — §5 now selects the matching-ecosystem entry subset `E_A` and OR-aggregates containment (ECOSYSTEM/GIT entries abstain; empty `E_A` ⇒ excluded, not scored false); (2) **source-agreement input** pinned to RAW `contained` (not the withdrawn-adjusted `Verdict.affected`), fixing a regression the v1.1.0 withdrawn split introduced; (3) **plan-adherence denominator** pinned numerically (`n_alerts + 1` with the control group); (4) **deps.dev ToS** reframed from neutral to *presumptively NOT permitted* for raw cached bytes (Google API ToS §5), with a derived-extract default. Also removed an orphan error code (`ECOSYSTEM_RANGE_EXCLUDED`). Remaining MEDIUM/LOW items (pre-release eligibility, no-backing-advisory branch, license-enum scope, §7 cut-line, casing precision) are tracked as non-blocking follow-ups.

**Amendments (v1.3.0, 2026-07-01)** — a second owner consistency pass closed four cross-section mismatches: (1) **Tool 3's algorithm** (§2.4) now spells out the same `E_A` multi-entry OR-aggregation as §5, so the agent-called tool and the gold-labeler cannot diverge on multi-`affected[]` records; (2) **§0.5's `corpus_snapshot_id` formula** now matches the §1.7(b) default (hashes the derived deps.dev extract, not raw response bytes); (3) **Maven & RubyGems are CUT entirely** — no vetted comparator exists to decide their containment, so the corpus is exactly `{npm, PyPI, crates.io, Go}` (§0.4, §1.2, §7, §9); (4) fixed a §8 cross-reference (`tool_key_args.json` lives in §2.5, not §0). Also inlined the §10 open-decisions list (RubyGems marked resolved).

**Editorial notes (2026-07-01 — non-normative, exempt from the amendment rule; no interfaces changed):** (1) the 71–90% false-positive figure below is driven largely by call-graph *reachability* analysis, which DepGuard deliberately does not perform — DepGuard addresses the version-range-containment slice of triage (caveat inline below); (2) the CI gate ships as a **plain-pytest merge-blocking GitHub Action** — read "promptfoo" throughout this document as "the merge-blocking CI eval gate" (promptfoo entered acquisition by OpenAI, 2026-03); (3) in v0.1 the corpus is a hand-picked npm+PyPI micro-corpus, so `corpus_snapshot_id` (§0.5) hashes the micro-corpus record bytes ‖ deps.dev derived-extract bytes ‖ curation-ruleset tag — the `all.zip` operand applies from the v0.2 full freeze onward; (4) the trajectory schema adds `system_variant: "deterministic_script"` for the three-arm ablation (flagged in `schemas/README.md`).

**Domain — LOCKED:** **DepGuard**, a Dependency CVE/VEX Reconciliation agent. Input: a project dependency manifest (pinned versions) + scanner advisory alerts. Output per alert: (a) is the pinned version *actually* in the advisory's affected range? (b) the authoritative advisory + exact affected-range/event evidence, (c) the minimal safe upgrade version. Real pain: 71–90% scanner false-positive rates *(editorial caveat: figure driven largely by reachability analysis, which DepGuard deliberately excludes — DepGuard addresses the version-range-containment slice)*.

**Architecture (per spec §4):** LangGraph supervisor → planner → retriever → tool worker → verifier, traced with OpenTelemetry GenAI semconv, gated in CI by promptfoo, deployed to Cloud Run reading ONLY the frozen corpus.

---

## 0. The Canonical Name Registry (resolves all cross-lens naming conflicts)

This section is normative. The MCP server, the golden trajectories, the OTel `gen_ai.*` attributes, and every metric MUST use these exact strings. Raw string comparison on ecosystem/system is FORBIDDEN — use the map in §0.4.

### 0.1 Tool name set (the ONLY legal `tool_name` / `gen_ai.tool.name` values)

The trajectory-lens vocabulary (`osv_query`, `depsdev_query`, `semver_contains`, `min_fixed_version`) is **discarded**. The six tool-contract names are canonical:

| # | `tool_name` | Kind | Source |
|---|---|---|---|
| 1 | `parse_manifest` | PURE | local |
| 2 | `osv_query_package` | EXTERNAL (snapshot) | `osv` |
| 3 | `check_version_affected` | PURE | local |
| 4 | `resolve_published_versions` | EXTERNAL (snapshot) | `deps.dev` |
| 5 | `compute_minimal_fix` | PURE | local |
| 6 | `crosscheck_second_source` | EXTERNAL (snapshot) | `deps.dev` |

### 0.2 PlanAction enum (the ONLY legal `PlanStep.action` / `gen_ai.operation.name`-scoped values)

The 8-value trajectory enum is collapsed so **every action maps to exactly one tool** (plus the two non-tool control actions `plan`/`emit_verdict`). `check_withdrawn` and `reconcile_sources` are **removed** as standalone actions — withdrawn is derived inside `check_version_affected`/the verifier, and reconciliation is the *output interpretation* of `crosscheck_second_source`, not a separate tool step.

| `PlanAction` | Maps to `tool_name` | `gen_ai.operation.name` | Notes |
|---|---|---|---|
| `plan` | *(none — control)* | `plan` | planner emits the plan-as-data |
| `parse_manifest` | `parse_manifest` | `execute_tool` | once per run |
| `retrieve_advisory` | `osv_query_package` | `execute_tool` / `retrieval` | per (pkg) |
| `resolve_versions` | `resolve_published_versions` | `execute_tool` | per (pkg) |
| `check_containment` | `check_version_affected` | `execute_tool` | per alert |
| `compute_minimal_fixed` | `compute_minimal_fix` | `execute_tool` | per alert |
| `cross_check_source` | `crosscheck_second_source` | `execute_tool` | per alert |
| `emit_verdict` | *(none — control)* | `invoke_agent` (verifier) | per alert |

This table is the single source of truth for the plan-adherence metric's alphabet **and** the tool-selection metric's alphabet — they are now reconciled. It ships as `schemas/plan_action_tool_map.json`.

### 0.3 Reconciliation-state enum (the ONLY legal `source_agreement` values)

Unified to **three** members (drop `second_source_silent` → folded into `single_source`; drop `conflict_unresolved` → it had no producer). Gold is defined for **every** member (see §5, P4). **Source-agreement is computed on RAW pre-withdrawn-override containment** (`check_version_affected.contained`), NOT the actionable `Verdict.affected` (v1.2.0): a withdrawn-but-contained alert whose deps.dev key is present scores `agree`, never a spurious `disagree` — the withdrawn override is an actionability rule, not a source conflict.

- `agree` — OSV and deps.dev both imply the same **raw-containment** boolean for the pinned version.
- `disagree` — they imply opposite **raw-containment** booleans on a real published version. `reconciliation_note` MUST be non-empty.
- `single_source` — deps.dev has no matching advisory key after full alias resolution (the "silent" case). **P4 passes by construction**; the alert is EXCLUDED from the agreement-rate metric (counted, reported separately).

### 0.4 Ecosystem ↔ deps.dev-system canonical map (ship as `schemas/ecosystem_system_map.json`)

OSV ecosystem casing is authoritative for `Dependency.ecosystem`, `parse_manifest`, and all OSV-side fields. deps.dev system strings are **lowercase** (confirmed live). Non-identity maps flagged.

| OSV `ecosystem` (canonical) | deps.dev `system` | semver-clean? | minimal-fix scorable? |
|---|---|---|---|
| `npm` | `npm` | yes | **yes** |
| `crates.io` | `cargo` | yes (strict) | **yes** |
| `Go` | `go` | yes | **yes** |
| `PyPI` | `pypi` | PEP440 (not semver2) | **no — membership-only** (never minfix, §1.2) |
| `Maven` | `maven` | no (qualifiers) | **EXCLUDED from corpus** — no vetted comparator (§1.2) |
| `RubyGems` | `rubygems` | semver-ish | **EXCLUDED from corpus** — no vetted comparator (§1.2) |
| `NuGet` | `nuget` | no | excluded from corpus |

### 0.5 Canonical snapshot id (resolves the 3-name / 3-place drift)

ONE field name everywhere: **`corpus_snapshot_id`**. The prior names `snapshot_id` and `retrieved_from_snapshot` are **renamed to `corpus_snapshot_id`** in tool envelopes and Evidence rows. It is a **single sha256 over the frozen SOURCE BYTES ONLY** — `sha256(OSV all.zip bytes ‖ <deps.dev frozen-slice bytes> ‖ curation_ruleset_version)`, where `<deps.dev frozen-slice bytes>` is whichever §1.7 path is in force: the **derived non-substantial extract bytes under the §1.7(b) DEFAULT**, or the raw deps.dev slice tarball only under §1.7(a) (legal sign-off). Either way it **EXCLUDES `CURATION_REPORT.json`**, which is a *derived* artifact: hashing it would create a chicken-and-egg cycle, since the report itself records the snapshot id. The `curation_ruleset_version` tag (a hash/semver of the curation code + config) is folded in so that re-running curation with **changed rules** still yields a new id on identical source bytes. The resulting `corpus_snapshot_id` is then **embedded as an attribute inside `CURATION_REPORT.json` and `SNAPSHOT.lock`** — a strict one-way dependency (artifacts reference the id; the id never depends on them). One hash still proves both source halves match. Form: `depguard-corpus-<YYYY-MM-DD>-<sha256[:12]>`.

ONE source field name everywhere: **`source`**, enum `{"osv","deps.dev","local"}`. `data.source_meta.source` and `ToolCall.source` MUST be equal; `ToolCall.source` is the authoritative copy in the trajectory.

---

## 1. Data & Corpus

### 1.1 OSV is the mechanical primary (Catch 1)

Depend on **OSV schema v1.x**. Read exactly these fields, ignore the rest: `id`; `modified` (RFC3339); `aliases[]` (CVE↔GHSA mapping); `withdrawn` (**RFC3339 TIMESTAMP, stored verbatim — NOT a boolean**, presence ⇒ withdrawn; see §1.5); `affected[].package.{ecosystem,name,purl}`; `affected[].ranges[].type` ∈ `{SEMVER,ECOSYSTEM,GIT}`; `affected[].ranges[].events[]` where **each event object carries EXACTLY ONE of** `introduced|fixed|last_affected|limit` (iterate events, switch on the key — never pair positionally); `affected[].versions[]`; `affected[].database_specific`; `severity[].{type∈CVSS_V3|CVSS_V4|CVSS_V2,score}`; `references[]`; `schema_version` (default `"1.0.0"`).

### 1.2 Corpus curation rule (Catch 2, tightened for minimal-fix per critique)

Filter is applied **per `affected[]` entry**, not per record (one record can keep some ecosystems and drop others). Two tiers, because membership-decidability ≠ ordering-decidability:

- **MEMBERSHIP-tier (eligible for containment scoring):** the entry's `ecosystem` MUST be one of the four with a vetted comparator — **`{npm, PyPI, crates.io, Go}`** (Maven/RubyGems/NuGet are excluded outright — see comparator policy). For those four, INCLUDE an affected entry if `ranges[].type == "SEMVER"` OR `affected.versions[]` is non-empty; every version string involved MUST parse under the ecosystem-vetted comparator (PyPI ⇒ `packaging.version`; npm/crates ⇒ `semver`; Go ⇒ Go module semver) — a `SEMVER`-typed range still needs the comparator to order `p` against its bounds. EXCLUDE any entry whose only range is `ECOSYSTEM`-typed or `GIT`-typed with no parseable `versions[]`.
- **MINIMAL-FIX-tier (eligible for minimal-fix scoring) — STRICT ECOSYSTEM ALLOWLIST:** an entry is `membership_and_minfix` **iff `ecosystem ∈ {npm, crates.io, Go}`** — the only ecosystems whose *native* version ordering IS semver. A `SEMVER`-typed range label that OSV happens to assign to a PyPI/Maven/RubyGems record does **NOT** grant minimal-fix eligibility: the candidate published versions can still contain PEP440/qualifier forms whose ordering we refuse to judge, so ordering an arbitrary not-in-list version stays a judgment call. **PyPI is ALWAYS `membership_only` (never minimal-fix), regardless of OSV range type; Maven, RubyGems, and NuGet are excluded from the corpus outright (no vetted comparator — see comparator policy below).** (This closes the prior contradiction where "`SEMVER`-typed range OR ecosystem" let a SEMVER-labelled PyPI record slip into the minimal-fix tier against the §0.4 table.) Each entry carries `scoring_tier: "membership_only" | "membership_and_minfix"`.

**Comparator policy (resolves the "PyPI is semver" fiction):** ship vetted comparators only — `packaging.version` for PyPI, `semver` crate-equivalent for npm/crates.io, Go's module semver for Go. **Ecosystems with NO vetted comparator — Maven, RubyGems, NuGet — are EXCLUDED from the corpus ENTIRELY** (v1.3.0): a `SEMVER`-typed range label does not make them decidable, because ordering the pinned version against the range bounds still needs an ecosystem comparator we do not ship, which would reintroduce a judgment call. **Surviving ecosystems = exactly `{npm, PyPI, crates.io, Go}`.** **Drop-on-ambiguity:** if any version string in a surviving entry fails its comparator, the entire entry is dropped (`NON_SEMVER_VERSION_STRING`).

**Practical target:** ~300–600 surviving affected-entries across **npm + PyPI + crates.io + Go**. Exact surviving count per ecosystem and per scoring_tier is pinned in `corpus/README.md` AFTER the freeze run. Emit `corpus/CURATION_REPORT.json` recording per source record: IN/OUT, scoring_tier, and drop reason (`ECOSYSTEM_RANGE_ONLY` | `GIT_ONLY` | `NON_SEMVER_VERSION_STRING` | `NO_VETTED_COMPARATOR` [Maven/RubyGems/NuGet]).

### 1.3 Second source = deps.dev v3 GetVersion (Catch 3) — honest framing

**Locked: deps.dev v3 `GetVersion advisoryKeys[]` + the enumerated published-version list.** NOT GHSA, NOT deps.dev `GetAdvisory` (both are OSV-format re-servings → circular).

**Honest independence statement (resolves the "multi-agent theater" critique):**
- The **genuinely independent** signal is the deps.dev **enumerated published-version list** (registry ground truth). It legitimately grounds minimal-fix (the next *actually published* safe version) and is the reason multi-agent is not pure theater. THIS IS THE LOAD-BEARING SECOND SIGNAL.
- The advisory-key cross-check (`source_agreement`) is **partly circular** — deps.dev's `advisoryKeys[]` are GHSA ids it ingests from GitHub Advisory DB, which is published in OSV format. Matching them mostly checks that two re-servings of the same GHSA record agree (near-tautological), and deps.dev gives a per-version *boolean*, not an independent *range*.
- **Therefore:** a genuine `disagree` is ONLY recorded when deps.dev's per-version `advisoryKeys[]` for a **real published version** contradicts OSV's computed containment on that exact version (e.g. OSV's range says v is affected, but v is published and deps.dev attaches no matching advisory key — or vice versa). This is the only `disagree` the data can honestly produce.
- **Mandatory ablation honesty (spec pitfall #3):** the Week-2 ablation MUST report the count of golden verdicts that multi-agent reconciliation **flips** vs single-agent. **If reconciliation flips 0 golden verdicts, we report that in LIMITATIONS** and state the second source's real value is version-grounding for minimal-fix, NOT a second opinion. We do not claim a second opinion the data cannot give.

**deps.dev endpoints (HTTPS, no auth):**
- Versions list: `GET https://api.deps.dev/v3/systems/{system}/packages/{name}` → `versions[].versionKey.version`, `isDefault`, `isDeprecated`, `publishedAt`.
- Per-version: `GET .../packages/{name}/versions/{version}` → `advisoryKeys[]:{id:"GHSA-..."}`, `licenses[]`.
- Advisory (severity only): `GET https://api.deps.dev/v3/advisories/{id}` → `cvss3Score` (see §1.6 on severity).

**Alias resolution (resolves false-silent):** before declaring `agree`/`disagree`/`single_source`, normalize the FULL alias graph (CVE ↔ GHSA ↔ OSV id) from `OSVRecord.aliases[]`. Only after the OSV id and all aliases fail to appear in `advisoryKeys[]` may `single_source` be recorded.

### 1.4 Freeze rule (Catch 4) + reproducibility (critique)

Freeze a committed, date-stamped tarball: a frozen OSV slice + a frozen deps.dev slice, single capture date, per-record provenance. **The runtime tool layer and CI mocks read ONLY from `corpus/` — never the network.**

- **OSV:** download `gs://osv-vulnerabilities/all.zip` (includes withdrawn records — needed for withdrawn test cases). No internal version stamp, so stamp ourselves: copy `modified_id.csv` + `ecosystems.txt` as version markers; record `all.zip` sha256 in `SNAPSHOT.lock`.
- **deps.dev:** for every `(system,name)` in the curated OSV slice, cache the version-list + per-version JSON on the same capture date; record per-endpoint capture timestamps in `SNAPSHOT.lock` as `depsdev_capture_window`.
- **REPRODUCIBILITY (critique):** **commit (or release-asset-pin) the actual `all.zip` and the deps.dev slice tarball**, not just hashes — re-running the freeze changes the sha256 and orphans old gold labels. `corpus_snapshot_id` hashes BOTH slices (§0.5). *(deps.dev half: under the §1.7 ToS default, commit a derived non-substantial EXTRACT + a deterministic re-fetch script instead of raw response bytes; `corpus_snapshot_id` then hashes the extract.)*
- **Layout:**
  ```
  corpus/
    osv/<ECOSYSTEM>/<ID>.json
    depsdev/<system>/<name>/versions.json
    depsdev/<system>/<name>/<version>.json
    SNAPSHOT.lock          # capture_date, all.zip sha256, depsdev_capture_window, corpus_snapshot_id
    CURATION_REPORT.json
    all.zip                # the actual frozen bytes (release asset if too large for git)
    README.md              # surviving counts per ecosystem/tier, pinned post-freeze
  NOTICE/ATTRIBUTION.md     # auto-generated, aggregates all CC-BY source URLs
  ```

### 1.5 `withdrawn` is a TIMESTAMP everywhere; bool derived only at Verdict (critique)

Store the RFC3339 string verbatim in the corpus, in `OSVRecord.withdrawn`, and in `Evidence.withdrawn` (`str|null`, null = active). Derive the boolean ONLY at `Verdict.withdrawn`. `check_version_affected` emits `withdrawn_timestamp: str|null` (renamed from the prior `withdrawn:boolean`). **Scoring convention (must be declared in the published rubric):** *a withdrawn advisory is non-actionable, so a verdict on a withdrawn advisory MUST report `affected=false` regardless of range containment.* This is an injected DepGuard product rule, not an OSV fact — declaring it preserves the "zero human judgment" claim by making the one judgment explicit.

### 1.6 Severity (resolves the half-specified CVSS dead-field)

**Decision: severity is DISPLAY-ONLY, never scored.** `crosscheck_second_source` and `osv_query_package` may surface `cvss3_score: number|null` for the UI, and it is stored on `Verdict.cvss3_score: number|null`. It is NOT a verifier predicate and NOT a metric. This keeps the field from being a dead value while keeping the verifier mechanical.

### 1.7 Licensing & attribution (Catch 4 + critique determinism)

- **Deterministic GHSA-origin provenance rule (replaces the heuristic):** an OSV record/affected entry is tagged **`CC-BY-4.0`** iff it has a `GHSA-*` entry in `aliases[]` **OR** any `references[].url` matches `github.com/advisories`. Otherwise **`CC0-1.0`**. A **CI test asserts no record carrying a GHSA reference is tagged CC0**, and that multi-sourced CVEs (GHSA + ecosystem) are tagged CC-BY (attribution wins on conflict).
- **ALL deps.dev-derived rows are `CC-BY-4.0`** with `source_url` to `api.deps.dev`, enforced at row level (not hardcoded examples).
- Every frozen record carries `_provenance:{source, source_url, license:"CC0-1.0"|"CC-BY-4.0", retrieved:"<date>"}`. CC-BY rows preserve the original GHSA advisory URL as `source_url`.
- **`NOTICE/ATTRIBUTION.md` is AUTO-GENERATED by the freeze job** (a build step asserts it exists and lists every CC-BY `source_url`).
- **Redistribution gate (verification 2026-06-30 — PRESUMPTIVE FINDING; release blocker for the public-repo path):** Google API ToS §5 bars copying/redistributing/publicly displaying API content to third parties beyond cache-header limits, and deps.dev use is "subject to" those terms — so committing or release-asset-pinning **raw cached deps.dev response bytes** to a PUBLIC repo is presumptively **NOT permitted** (asset-pinning does not escape this). OSV `all.zip` (first-party CC0/CC-BY) is unaffected — the constraint is the deps.dev half only. Resolve by EITHER (a) affirmative written legal sign-off before any public freeze, OR (b) **default:** commit a derived **non-substantial extract** for the deps.dev half — the enumerated published-version list per `(system,name)` + a `(version, advisory-key)` boolean table — plus a deterministic re-fetch script and captured per-endpoint timestamps; under (b) `corpus_snapshot_id` (§0.5) hashes the **derived extract bytes**, not raw responses. The private-corpus runtime and the derived-extract build both keep the eval buildable today; this gates only PUBLIC release.
- **README disclosure:** the snapshot may contain advisories upstream has since withdrawn/deleted; the demo reflects the frozen snapshot, not live accuracy.

---

## 2. Tool Contract — 6 typed tools on a uniform envelope

### 2.1 Uniform envelope (spec §line 119/160)

```json
{ "ok": true,  "data": { ... , "source_meta": {"source": "...", "corpus_snapshot_id": "...", "license": "CC0-1.0|CC-BY-4.0", "source_url": "...|null"} }, "error": null }
{ "ok": false, "data": null, "error": {"code": "...", "message": "...", "retryable": false} }
```

Exactly two branches: `ok==true` ⇒ `data` non-null, `error` null; `ok==false` ⇒ `data` null, `error` non-null. **Tools never throw — all failures are envelope errors.** Because the runtime tool layer and CI mocks read ONLY from the frozen `corpus/` (§1.4), **transient network errors are physically impossible and are NOT in the contract** — there is nothing on local disk to rate-limit, time out, or find "upstream-unavailable." `error.code` closed enum: `BAD_INPUT, NOT_FOUND, SNAPSHOT_READ_ERROR, SNAPSHOT_MALFORMED, RANGE_UNRESOLVABLE`. `SNAPSHOT_READ_ERROR` = the expected corpus file is missing/unreadable; `SNAPSHOT_MALFORMED` = the snapshot JSON failed to parse. **`retryable` is always `false` in corpus mode** (nothing local is transient); the field is retained only so a future *live-mode* MCP deployment could reintroduce a separate `{RATE_LIMITED, TIMEOUT, UPSTREAM_UNAVAILABLE}` set without a schema break. This removes the dead retry paths an agent could otherwise loop around. Every `data` carries `source_meta` (uses canonical `corpus_snapshot_id`, §0.5).

### 2.2 Pipeline order

`parse_manifest` → `osv_query_package` → `resolve_published_versions` → `check_version_affected` → `compute_minimal_fix` → `crosscheck_second_source`. Three PURE (`parse_manifest`, `check_version_affected`, `compute_minimal_fix`) = the mechanical verifier oracle; three EXTERNAL snapshot-backed (`osv_query_package` on OSV, `resolve_published_versions` + `crosscheck_second_source` on deps.dev).

### 2.3 Shared type — `OSVRecord` (the verifier subset)

```json
{ "id": "string", "modified": "RFC3339", "withdrawn": "RFC3339|null",
  "aliases": ["string"], "summary": "string|null",
  "affected": [{ "package": {"ecosystem":"string","name":"string","purl":"string|null"},
                 "ranges": [{"type":"SEMVER|ECOSYSTEM|GIT",
                             "events":[{"introduced?":"s","fixed?":"s","last_affected?":"s","limit?":"s"}]}],
                 "versions": ["string"], "scoring_tier":"membership_only|membership_and_minfix" }],
  "references": [{"type":"string","url":"string"}], "database_specific": "object|null" }
```

### 2.4 The six tools

**1. `parse_manifest` (PURE)** — in `{ecosystem, manifest_filename, manifest_text}` → out `{dependencies:[{ecosystem,name,version,pinned:bool}], unparsed_lines:[string]}`. `ecosystem` ∈ OSV casing (§0.4). `name` ecosystem-canonical (npm scoped `@org/pkg`, PyPI PEP503-normalized lowercase, Go module path; corpus ecosystems only, §1.2). Ranges/caret/tilde ⇒ `pinned=false` with best-effort version. Err: `BAD_INPUT` on unknown ecosystem / empty text. Deterministic.

**2. `osv_query_package` (EXTERNAL)** — in `{ecosystem, name, version:string|null}` → out `{advisories:[OSVRecord], excluded:[{id,reason}], corpus_snapshot_id}`. Maps to OSV `POST /v1/query`. Enforces curation rule (§1.2): ECOSYSTEM-only-no-versions records moved to `excluded[]`. Reads frozen snapshot only. `NOT_FOUND` ⇒ `ok:true, advisories:[]` (not an error). `SNAPSHOT_READ_ERROR`/`SNAPSHOT_MALFORMED` on a missing/corrupt corpus file. Idempotent given `corpus_snapshot_id`.

**3. `check_version_affected` (PURE — verifier core, Catch 1)** — in `{ecosystem, name, version, osv_record}` → out `{contained:bool, matched_by:"versions_list"|"semver_range"|null, matched_range:{introduced,fixed,last_affected}|null, withdrawn_timestamp:string|null}`. Computes **RAW range containment ONLY** — it deliberately does **NOT** apply the withdrawn override (that product rule lives at the verdict layer, §3.3 / §5-P1); it merely surfaces `withdrawn_timestamp` so the verdict layer can apply it. Algorithm (mirrors the §5 `E_A` entry-selection rule — the SAME oracle logic, so the tool the agent calls at inference and the gold-labeler cannot diverge on multi-entry records): **(0)** `E_A` = entries of `osv_record.affected[]` whose `package.ecosystem == ecosystem` AND `package.name == name` (§0.4 canonical). **(1)** `withdrawn_timestamp = osv_record.withdrawn` (record-level). **(2) OR-aggregate over `E_A`** — an entry is `contained` if `version ∈ entry.versions[]` (comparator-EQUALITY, `matched_by:"versions_list"`) OR `version` falls in any `SEMVER` interval of `entry.ranges` (`introduced` opens, `"0"`=−∞; `fixed` closes exclusive `[introduced,fixed)`; `last_affected` closes inclusive `[introduced,last_affected]`, via the ecosystem-vetted comparator; `matched_by:"semver_range"`). Output `contained` = OR across `E_A`; `matched_range` echoes the bounding events of the FIRST entry that produced `true`, for citation. **(3)** ECOSYSTEM/GIT-only entries **ABSTAIN** — skipped in the OR, never failing the verdict. **(4)** if `E_A` is empty ⇒ `contained:false, matched_by:null`; if `E_A` is non-empty but EVERY matching entry is ECOSYSTEM/GIT-only (should not occur post-curation, §1.2) ⇒ `error RANGE_UNRESOLVABLE` (never silently produce a judgment-call verdict). Deterministic. *(v1.1.0: output field renamed `affected`→`contained` to keep raw containment auditable and distinct from the actionable `Verdict.affected`.)*

**4. `resolve_published_versions` (EXTERNAL)** — in `{ecosystem, name}` → out `{versions:[string], default_version:string|null, source:"deps.dev", corpus_snapshot_id}`. Wraps deps.dev `GET /v3/systems/{system}/packages/{name}`; `versions` sorted ascending by the ecosystem comparator. `NOT_FOUND` ⇒ `ok:true, versions:[]`. CC-BY-4.0 tagged. Idempotent.

**5. `compute_minimal_fix` (PURE)** — in `{ecosystem, name, current_version, osv_record, published_versions}` → out `{minimal_fixed_version:string|null, reason:"published_version_clears"|"no_fix_available"|"already_safe"|"withdrawn_non_actionable", candidates_considered:[string]}`. **WITHDRAWN SHORT-CIRCUIT (v1.1.0, Catch 1):** if `osv_record.withdrawn != null`, return IMMEDIATELY `{minimal_fixed_version: null, reason: "withdrawn_non_actionable", candidates_considered: []}` — a withdrawn advisory is non-actionable, so the tool never chases a fix for a vulnerability that no longer legally exists. **LOCKED definition (resolves the two-definition conflict):** otherwise minimal_fixed = the **smallest PUBLISHED version V (from deps.dev `published_versions`) such that `V >= current_version` AND `check_version_affected(V, osv_record).contained == false`**. This grounds the answer in real releases (never invents a version). `already_safe` if current is already not contained. `no_fix_available` if no published version clears the record. **DATA-DEPENDENCY DECLARATION:** this makes the gold minimal-fix label DEPEND on the deps.dev snapshot — therefore `corpus_snapshot_id` hashes both slices (§0.5), and minimal-fix scoring is restricted to `scoring_tier == "membership_and_minfix"` entries (§1.2). Err `RANGE_UNRESOLVABLE` if record is ECOSYSTEM-only.

**6. `crosscheck_second_source` (EXTERNAL — Catch 3)** — in `{ecosystem, name, version, osv_verdict:{contained:bool, advisory_id:string, aliases:[string]}}` → out `{agreement:"agree"|"disagree"|"single_source", second_source:"deps.dev", second_source_advisory_keys:[string], per_version_affected_bool:bool, cvss3_score:number|null, corpus_snapshot_id}`. Wraps deps.dev per-version `advisoryKeys[]`. After full alias normalization (§1.3): `agree` if a matching key is present iff OSV reports raw `contained` (fed from `check_version_affected.contained`, NOT the withdrawn-adjusted `Verdict.affected`; no withdrawn short-circuit needed here); `disagree` if deps.dev's per-version boolean contradicts OSV on a real published version; `single_source` if no matching key after alias resolution. CC-BY-4.0. Idempotent.

### 2.5 Per-tool scored-arg key registry (schema gap fix) — `schemas/tool_key_args.json`

Tool-selection accuracy matches gold on a per-tool key subset; that subset is now a committed artifact, not prose:

```json
{
  "parse_manifest":            ["ecosystem", "manifest_filename"],
  "osv_query_package":         ["ecosystem", "name"],
  "check_version_affected":    ["ecosystem", "name", "version", "osv_record.id"],
  "resolve_published_versions":["ecosystem", "name"],
  "compute_minimal_fix":       ["ecosystem", "name", "current_version", "osv_record.id"],
  "crosscheck_second_source":  ["ecosystem", "name", "version", "osv_verdict.advisory_id"]
}
```

---

## 3. Trajectory Schema (the shared spine: OTel spans ⇄ eval harness)

One canonical Trajectory JSON object per run, persisted JSONL (`golden/trajectories/*.jsonl`), JSON Schema at `schemas/trajectory.schema.json`, `schema_version` `"1.0.0"`.

```json
{
  "schema_version": "1.0.0",
  "trajectory_id": "string (== gen_ai.conversation.id)",
  "created_at": "RFC3339",
  "system_variant": "single_agent | multi_agent",
  "model_route": "string",
  "corpus_snapshot_id": "string (hashes BOTH OSV+deps.dev slices)",
  "gold_ref": "string (== gold sidecar key; see §4.5)",
  "otel": {"trace_id": "string", "root_span_id": "string"},
  "input": {
    "manifest": [{"ecosystem": "npm|PyPI|crates.io|Go", "name": "string", "pinned_version": "string", "purl": "string|null"}],
    "alerts":   [{"alert_id": "string", "ecosystem": "string", "name": "string", "pinned_version": "string", "advisory_id": "GHSA-...|CVE-...", "source": "scanner"}]
  },
  "plan": [{"step_index": 0, "action": "PlanAction (§0.2)", "alert_id": "string|null", "rationale": "string",
            "status": "planned|executed|skipped", "produced_verdict_for": "alert_id|null"}],
  "tool_calls": [{
    "tool_call_id": "string (== gen_ai.tool.call.id)", "span_id": "string", "parent_span_id": "string",
    "agent": "planner|retriever|tool_worker|verifier (== gen_ai.agent.name)",
    "tool_name": "one of §0.1 (== gen_ai.tool.name)", "tool_type": "function",
    "arguments": {}, "result": {"ok": true, "data": {}, "error": null},
    "status": "ok|error", "started_at": "RFC3339", "ended_at": "RFC3339",
    "source": "osv|deps.dev|local", "corpus_snapshot_id": "string"
  }],
  "evidence": [ /* OSV variant OR deps.dev variant, see §3.2 */ ],
  "verdicts": [ /* §3.3 */ ],
  "final_answer": {"verdicts_summary": {"n_alerts": 0, "n_true_positive": 0, "n_false_positive": 0}, "per_alert": [], "emitted_at": "RFC3339"}
}
```

### 3.1 Join keys & OTel mirroring

`alert_id` is the deterministic join key across `plan`, `tool_calls`, `evidence`, `verdicts`. `tool_calls` mirror OTel `execute_tool` spans 1:1; `result` stores the `{ok,data,error}` envelope verbatim. OTel mapping is literal: `gen_ai.operation.name`, `gen_ai.agent.name`, `gen_ai.tool.name`, `gen_ai.tool.call.id`, `gen_ai.tool.type`, `gen_ai.conversation.id` (confirmed against OTel GenAI semconv).

`PlanStep.produced_verdict_for` (schema gap fix) records which `alert_id` a step advanced to a verdict — makes action-advancement mechanically computable.

### 3.2 `Evidence[]` — two variants (schema gap fix: deps.dev had no backing fields for P4)

**OSV variant:**
```json
{"evidence_id":"string","alert_id":"string","tool_call_id":"string","source":"osv","advisory_id":"string",
 "withdrawn":"RFC3339|null","affected_package":{"ecosystem":"s","name":"s"},
 "range_type":"SEMVER|ECOSYSTEM|GIT","range_events":[{"introduced?":"","fixed?":"","last_affected?":"","limit?":""}],
 "enumerated_versions":["string"]|null,"references":[{"type":"","url":""}],
 "license":"CC0-1.0|CC-BY-4.0","attribution_url":"string|null","corpus_snapshot_id":"string"}
```
**deps.dev variant (NEW):**
```json
{"evidence_id":"string","alert_id":"string","tool_call_id":"string","source":"deps.dev","advisory_id":"string|null",
 "checked_version":"string","second_source_advisory_keys":["GHSA-..."],"per_version_affected_bool":true,
 "published_versions":["string"],"license":"CC-BY-4.0","attribution_url":"https://api.deps.dev/...","corpus_snapshot_id":"string"}
```
Only ingest OSV records where `range_type==SEMVER` OR `enumerated_versions` non-empty (Catch 2). `corpus_snapshot_id` on every Evidence row MUST equal `traj.corpus_snapshot_id` (verifier §6 refuses to score on mismatch).

### 3.3 `Verdict[]` (one per alert) — the verifier's scoring unit

```json
{"alert_id":"string","affected":false,"minimal_fixed_version":"string|null",
 "withdrawn":false,                       // DERIVED bool: evidence.withdrawn != null
 "cvss3_score":"number|null",             // display-only (§1.6)
 "evidence_ids":["string"],
 "source_agreement":"agree|disagree|single_source",   // §0.3
 "reconciliation_note":"string"}          // MUST be non-empty iff source_agreement=="disagree"
```
`Verdict.affected == true` iff `check_version_affected` reports `contained==true` for some affected range AND `withdrawn==false` (the withdrawn override is applied HERE at the verdict layer, not inside the tool — §1.5). `Verdict.minimal_fixed_version` is `null` whenever `withdrawn==true` (`reason: "withdrawn_non_actionable"`, §2.4 tool 5).

---

## 4. Eval Metrics, Golden Set, Verifier (the headline artifact)

### 4.1 Four mechanical metrics (per-trajectory score ∈ [0,1] + fail-list; paired-bootstrap over per-trajectory deltas)

1. **TOOL-SELECTION ACCURACY** = set-match of `tool_calls` vs gold, where a call is correct iff `tool_name` matches AND scored args (per `schemas/tool_key_args.json`, §2.5) match. Order-insensitive; report precision/recall/F1 (spurious calls hurt precision).
2. **ACTION-ADVANCEMENT** = |advancing executed steps| / |executed steps|, where a step advances iff `status=="executed"` AND `produced_verdict_for` is a previously-unverdicted alert (redundant repeats don't count).
3. **PLAN-ADHERENCE (alert-grouped — v1.1.0):** the set of alerts is treated as **UNORDERED** (processing Alert B before Alert A incurs NO penalty); order is enforced only *within* each alert's dependency chain. Compute: partition executed `PlanStep`s by `alert_id`; for each alert score its sub-sequence vs that alert's gold sub-sequence as `1 − normalizedLevenshtein(exec_sub, gold_sub)`; PLAN-ADHERENCE = mean of per-group scores over ALL groups, where each non-null `alert_id` forms one group and ALL `alert_id==null` steps (run-level control actions such as the top-level `plan`) form exactly **one** additional control group — **denominator = `n_alerts + 1` when ≥1 control step exists, else `n_alerts`** (`emit_verdict` steps carry a non-null `alert_id` per §0.2 and join their alert's group). This replaces a *global* Levenshtein over the whole action stream, which falsely imposed a large penalty when the planner validly interleaved or reordered independent alerts. Same `PlanAction` alphabet as tool-selection (§0.2); join key is `PlanStep.alert_id` (§3).
4. **FINAL-ANSWER GROUNDEDNESS** = fraction of verdicts whose every claim (`affected`, `minimal_fixed_version`) is entailed by a cited Evidence row under the verifier rule. **CORRECTNESS** (reported separately) = fraction of verdicts exactly matching gold.

### 4.2 Golden-trajectory set (spec: 40–60 examples)

40–60 trajectories spanning npm/PyPI/crates.io/Go, deliberately seeded with: true-positives, scanner false-positives (pinned version NOT in range — the headline pain), withdrawn advisories, `no_fix_available`, `already_safe`, multi-affected-entry records, and **`disagree` cases** (deps.dev contradicts OSV on a real published version) so the ablation has something to flip. Gold labels are generated by the verifier (§5) — same code labels gold and scores predictions, so the eval cannot drift from the oracle.

### 4.3 LLM-as-judge (calibrated, NOT in the correctness path)

LLM-judge (Claude Sonnet + Haiku routing) scores ONLY soft narrative quality (e.g. clarity of `reconciliation_note`) on a **published rubric**, calibrated against a **15–20 case human audit**. It NEVER scores verdict correctness — that is mechanical (§5).

### 4.4 Single-vs-multi ablation (spec DoD)

Run single-agent ReAct baseline vs multi-agent on the golden set; report all four metrics with **paired-bootstrap 95% CIs** over per-trajectory deltas. **MUST report verdict-flip count** from reconciliation; if 0, say so in LIMITATIONS (§1.3).

### 4.5 Gold reference binding (schema gap fix)

Gold lives in `golden/expected/*.jsonl` keyed by `gold_ref` (= sha256 of `input`). Each gold record holds `{gold_ref, gold_plan_actions:[PlanAction], gold_tool_calls:[{tool_name, scored_args}], gold_verdicts:[Verdict]}`. The trajectory's `gold_ref` is the join; metrics fail loudly if no gold record matches.

---

## 5. Verifier Definition — four TOTAL predicates, zero human judgment (Catch 1)

For verdict `V` on alert `A`, pinned version `p`, evidence from frozen snapshot `S` (the cited OSV record). **Same code labels gold AND scores predictions.**

**Entry selection & aggregation (v1.2.0 — multi-`affected[]` records):** an OSV record's `affected[]` is a LIST and curation tiers are per-entry (§1.2), so define `E_A` = the subset of `S.affected[]` whose `package.ecosystem == e` AND `package.name == n` (after §0.4 canonicalization). All predicates operate over `E_A`, not one flat entry: (a) `contained_gold` = **OR over `E_A`** of (`p` in `entry.versions[]` by comparator-EQUALITY) OR (`p` in any `SEMVER` range of `entry.ranges` by the P1 event algorithm), citing the specific `(entry, matched_range)` that produced `true`; (b) ECOSYSTEM/GIT-only entries **ABSTAIN** (skipped in the OR — they never fail the whole verdict; the per-entry `RANGE_UNRESOLVABLE` case of §2.4 tool 3); (c) effective `scoring_tier` = `membership_and_minfix` iff `e ∈ {npm, crates.io, Go}` — ecosystem-keyed, so all of `E_A` shares one tier (no npm-vs-PyPI conflict); (d) if `E_A` is **empty** after the membership filter, the alert is **EXCLUDED** from scoring (counted/reported), NOT scored `false`. `S.withdrawn` is record-level (one value). `check_version_affected` (§2.4 tool 3) applies the same `E_A` selection.

- **P1 CONTAINMENT (actionable affected — withdrawn folded in, v1.1.0):** `contained_gold` = the **`E_A` OR-aggregate** defined in the entry-selection rule above (per-entry: `p` in any `SEMVER` range by the event algorithm — `introduced` opens, `fixed` closes exclusive, `last_affected` closes inclusive, `"0"`=−∞ — OR comparator-EQUALITY membership in `entry.versions[]`; ECOSYSTEM/GIT entries abstain). Then `affected_gold = contained_gold AND (S.withdrawn == null)` — the withdrawn override is applied HERE so P1 and P3 cannot contradict. (Previously P1 demanded `V.affected == contained` while P3 demanded `false` for a withdrawn-but-contained version — a direct contradiction that would fail a correct verdict.) Require `V.affected == affected_gold`.
- **P2 MINIMAL-FIXED (LOCKED, published-grounded):** if `S.withdrawn != null` ⇒ `min_fixed_gold = null` (`withdrawn_non_actionable`; not scored as a fix). Otherwise `min_fixed_gold` = smallest published version `V'` (deps.dev frozen list) with `V' >= p` AND `check_version_affected(V').contained == false`. `null` if none ⇒ `no_fix_available`. Require exact equality. **Scored ONLY on `scoring_tier=="membership_and_minfix"` entries**, i.e. `ecosystem ∈ {npm, crates.io, Go}` (§1.2). **Declared data-dependency:** gold depends on the deps.dev snapshot (§0.5).
- **P3 WITHDRAWN:** `withdrawn_gold = (S.withdrawn != null)`. Require `V.withdrawn == withdrawn_gold`. The affected-override for withdrawn records is already enforced in P1 (via `affected_gold`), so P3 no longer restates it — this is what eliminates the prior P1/P3 contradiction. **Declared scoring CONVENTION** (§1.5) — the one injected judgment, stated in the rubric.
- **P4 SOURCE-AGREEMENT (TOTAL — critique fix):** after full alias normalization (CVE↔GHSA↔OSV), compute `agreement_gold`:
  - both sources imply the same **raw-containment** bool (OSV `contained` from §2.4 tool 3, NOT the withdrawn-adjusted `Verdict.affected`) ⇒ `agree` — and a **withdrawn-but-contained alert with a matching deps.dev key scores `agree`, not `disagree`** (the withdrawn override is actionability, not a source conflict);
  - deps.dev per-version `advisoryKeys[]` contradicts OSV on a real published version ⇒ `disagree` (require `reconciliation_note` non-empty);
  - no matching key after alias resolution ⇒ **`single_source`: P4 PASSES BY CONSTRUCTION**, and the alert is EXCLUDED from the agreement-rate metric (counted/reported separately). P4 is now defined for every member, so `CORRECT = P1∧P2∧P3∧P4` is total.

No LLM, no rubric, no human in this path.

---

## 5.1 P5 — SEMANTIC-RANGE-EQUIVALENCE (the prose slice, v1.2.0)

**Why this predicate exists.** §5's four predicates run on a task that is mechanically decidable from the frozen bytes. That was the right choice for building a shared-oracle verifier, but it has a consequence the v0.1 report understated: the deterministic script *is* the reference implementation of the label function, so it scores 1.0000 by construction, and the LLM arms could at best **tie**. They did. A comparison whose best possible outcome is "no difference" carries no information about the agent, and the `[0,0]` CI it produces is an identity, not an estimate. (Measured: the `deterministic_script` and `multi_agent` trajectories are byte-identical across verdicts, evidence, tool sequence, tool arguments and tool results — 174 tool calls each; the only differing content is 232 free-text `rationale` strings that no metric reads.)

P5 adds a slice where the deterministic path **provably cannot compete**, without weakening the mechanical verifier.

**The transform.** `redact.redact_ranges(record)` drops `ranges` and `versions` from every `affected[]` entry and keeps package, id, aliases, `withdrawn`, `summary`, `details`, `references`. It is a pure function of already-frozen bytes: the `corpus/` directory is never written, `corpus_snapshot_id` is unchanged, every v0.1 number remains reproducible, and the slice is byte-reproducible because redaction is deterministic. The affected range now survives **only in the `details` prose** — all 40 corpus records carry non-empty details (median 414 chars), 34 of 40 carry a version token.

**Why the script provably fails.** Per §5's entry-selection rule, an entry decides containment by `versions[]` membership or a `SEMVER` range, and ECOSYSTEM/GIT-only entries **abstain**. Redaction removes both, so every entry in `E_A` abstains and `record_containment` raises `RANGE_UNRESOLVABLE`. This is a raised exception asserted by a committed test (`tests/test_prose_slice.py::test_script_arm_cannot_decide_redacted`), not a measured shortfall open to argument.

**P5 definition.** For a proposal `P = {events, versions, abstain}` over package `(e, n)` with frozen published list `L`:

- `gold_abstain` = the prose (`summary + details`) contains **no version token**. Determined mechanically by regex over frozen bytes — no human judgement enters the label.
- If `P.abstain` (or `P` is absent): `P5 = gold_abstain`.
- If `gold_abstain` and `P` proposes a range: **`P5 = false`** (invention).
- Otherwise materialise `P` against `L` — union of `P.versions` and the OSV-semantics expansion of `P.events`, intersected with `L` — into a record carrying that version set, then require **bitvector equality**:

  `∀ v ∈ L : record_containment(S_true, e, n, v).contained == record_containment(S_materialized, e, n, v).contained`

  Versions unparseable by the ecosystem comparator, and versions the true record itself cannot decide, leave the bitvector on both sides.

**Two properties this buys.** (a) It scores **behaviour, not text**: `last_affected: 4.17.20` and `fixed: 4.17.21` are different strings denoting the same set of real releases, and P5 calls them equal — exactly when no published release separates them. Equivalence is defined relative to `L` on purpose, because containment over real releases is the only thing the verdict and minimal-fix consume. (b) The **abstention asymmetry** (abstaining is correct iff `gold_abstain`) means neither an always-abstain nor an always-guess extractor can farm the metric.

**Shared-oracle status.** Preserved more literally here than anywhere else in the system: gold and prediction differ *only* in which record was passed to one identical `record_containment` call. No LLM judge touches the correctness path, in this predicate or any other.

**Arms.** `deterministic_script` (no prose parser — abstains by construction), `regex_baseline` (a good-faith non-LLM grammar, present so that "you should have written the parser" is answered with a number rather than an opinion), and `llm_extractor`. Reported by `scripts/run_prose_slice.py` into `results/prose_slice.{json,md}`.

---

## 6. Snapshot Determinism

Every trajectory records `corpus_snapshot_id`; every Evidence row records `corpus_snapshot_id`. Verifier asserts `all(e.corpus_snapshot_id == traj.corpus_snapshot_id)`; mismatch ⇒ trajectory invalid (scored 0, flagged) — prevents live-API contamination of gold labels. `corpus_snapshot_id` hashes BOTH frozen slices (§0.5), so one hash proves both halves match. CI mock server replays ONLY this snapshot.

---

## 7. Scope Table (MUST / SHRINK / CUT)

| Item | Decision | Why |
|---|---|---|
| OSV primary, semver-decidable curation, frozen snapshot | **MUST** | Mechanical verifier (Catch 1/2/4) |
| 6 typed tools + uniform envelope + MCP server | **MUST** | Spec DoD; testable boundary |
| Canonical trajectory schema + 4 metrics + 4-predicate verifier | **MUST** | Headline artifact |
| deps.dev version-list grounding for minimal-fix | **MUST** | Genuine independence (Catch 3) |
| 40–60 golden trajectories + gold sidecar + paired-bootstrap CIs | **MUST** | Spec DoD |
| promptfoo merge-blocking gate, OTel tracing, injection rail, Cloud Run | **MUST** | Spec DoD |
| deps.dev advisory-key `source_agreement` cross-check | **SHRINK** | Partly circular; keep but report honestly; do not over-claim |
| Maven / RubyGems / NuGet ecosystems | **CUT** | No vetted comparator → containment not mechanically decidable; corpus = `{npm, PyPI, crates.io, Go}` only (§1.2) |
| PyPI minimal-fix scoring | **SHRINK** | Membership-only; excluded from minimal-fix metric |
| Severity/CVSS scoring | **CUT** (display-only) | Not mechanical-verifier material (§1.6) |
| `GetAdvisory`/GHSA as second source | **CUT** | Circular |
| Browser/computer-use worker | **CUT** (stretch only) | Spec pitfall #6 |

---

## 8. Week-1 First-Runnable Slice (concrete first files)

**Goal (spec Week 1):** graph runs end-to-end on mocks; one passing/failing trajectory test exists; OTel wired day one.

First files to create, in order:
1. `schemas/ecosystem_system_map.json` + `schemas/plan_action_tool_map.json` (§0 registries) and `schemas/tool_key_args.json` (§2.5) — the committed vocabulary artifacts (no logic; lock the names first).
2. `schemas/trajectory.schema.json` — §3 JSON Schema.
3. `corpus/freeze_osv.py` + `corpus/freeze_depsdev.py` + `corpus/curate.py` → produces `corpus/` (§1.4) + `CURATION_REPORT.json` + `SNAPSHOT.lock` + `NOTICE/ATTRIBUTION.md`. Run once; pin `corpus_snapshot_id`.
4. `depguard/tools/` — the 6 tools (§2). Start with the 3 PURE ones (`parse_manifest`, `check_version_affected`, `compute_minimal_fix`) — they need no snapshot and are the verifier oracle.
5. `depguard/tools/mocks.py` — deterministic snapshot-replay mocks for the 3 EXTERNAL tools (read `corpus/` only).
6. `depguard/graph.py` — minimal LangGraph supervisor→planner→retriever→tool_worker→verifier emitting a Trajectory object + OTel spans.
7. `golden/trajectories/seed_01.jsonl` + `golden/expected/seed_01.jsonl` — ONE end-to-end golden trajectory (a known scanner false-positive) + its gold.
8. `tests/test_trajectory_seed_01.py` — runs the graph on mocks, scores against gold via the verifier; this is the first passing/failing trajectory test.
9. `depguard/verifier.py` — the four predicates (§5); imported by both the labeler and the scorer.

**Week-1 deliverable check:** `pytest tests/test_trajectory_seed_01.py` runs the whole graph offline on `corpus/` and the verifier scores it.

---

## 9. Top Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Multi-agent is theater (reconciliation flips 0 verdicts) | Seed golden set with real `disagree` cases; MUST report flip count; if 0, state it in LIMITATIONS (§1.3) — honesty is the senior signal |
| PyPI ordering sneaks a judgment call into "mechanical" verifier | Scoring tiers (§1.2): PyPI is membership-only (comparator-decidable via `packaging.version`); minimal-fix only on npm/crates/Go; Maven/RubyGems/NuGet excluded outright (no comparator); drop-on-ambiguity |
| Gold labels unreproducible (all.zip re-freeze changes sha256) | Commit/release-asset-pin actual frozen bytes; `corpus_snapshot_id` over both slices (§1.4) |
| CC-BY attribution stripped on GHSA-origin records | Deterministic provenance rule + CI test that no GHSA-referencing record is CC0 (§1.7) |
| deps.dev ToS forbids committing cached responses | **Presumptive: NOT permitted** for raw bytes (Google API ToS §5). Default to a derived non-substantial extract + re-fetch script (hash the extract; §1.7/§0.5); legal sign-off required for any raw-bytes public freeze. **Release-path blocker, not a build blocker.** |
| Naming drift silently mis-scores every trajectory | §0 canonical registries are committed artifacts referenced by MCP server, golden set, OTel attrs, metrics |
| minimal-fix gold disagrees with predicted (two definitions) | Single locked published-grounded definition (§2.4 tool 5, §5 P2) |

---

## 10. Open Decisions (for owner)

The decisions below still need an explicit owner call. Defaults are in force where noted; the rest are genuine forks.

1. **deps.dev redistribution (§1.7).** Pursue legal sign-off to commit raw cached bytes (§1.7 a), or accept the **derived non-substantial extract** default (§1.7 b, in force). Only gates a PUBLIC repo. *Default in force: extract.*
2. **Ablation honesty (§1.3, §4.4).** Confirm you will ship the honest result even if multi-agent reconciliation flips **0** golden verdicts (reframing deps.dev's value as version-grounding for minimal-fix), rather than padding the golden set to manufacture disagreements. *Recommended: accept.*
3. ~~RubyGems keep/cut~~ — **RESOLVED v1.3.0: CUT** (no vetted comparator; corpus = `{npm, PyPI, crates.io, Go}`). Reversible only by shipping + vetting a RubyGems comparator.
4. **OSV `all.zip` storage.** Commit the (large) `all.zip` into git vs pin it as a GitHub release asset — both satisfy reproducibility. *Default: release-asset-pin.*
5. **Minimal-fix UX** when no published version clears the advisory → surface a distinct `no_fix_available` verdict state (vs `null`). *Default in force: `no_fix_available`.*
6. **Severity/CVSS is display-only** (§1.6), never scored or gated. Confirm — a later severity-weighted metric would need a `schema_version` bump. *Default in force: display-only.*
