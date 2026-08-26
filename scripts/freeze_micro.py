#!/usr/bin/env python3
"""Freeze the v0.1 npm+PyPI micro-corpus (DECISIONS.md §1.2/§1.4/§1.7, editorial note 3).

Deterministic: fetches a FIXED advisory-id list via single OSV GETs, curates each
record mechanically with `depguard.comparators` (the SAME comparator the runtime
oracle uses — so nothing in the corpus can be un-decidable at scoring time), and
emits everything the corpus test validates. Re-running on the same capture date
reproduces identical bytes unless upstream changed (documented in corpus/README.md).

deps.dev is committed ONLY as a derived non-substantial EXTRACT (§1.7b ToS default):
per package a published-version list + a bounded (version → advisory-key) table,
NEVER raw response bodies. This script IS the re-fetch script that reproduces it.

Provenance (implementation note, resolves a §1.7 underdetermination): a record whose
own id is `GHSA-*` is a GitHub advisory (CC-BY) even when fetched by id with only a
CVE alias — §1.7's alias/reference rule was written for the all.zip CVE-primary
layout. Extended rule: CC-BY iff id OR any alias starts with `GHSA-`, OR a reference
url contains `github.com/advisories`; else CC0-1.0.

Run:  python scripts/freeze_micro.py            (from the repo root; needs network)
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from bisect import bisect_left, bisect_right
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from depguard.comparators import VersionParseError, get_comparator  # noqa: E402
from depguard.corpus_snapshot import compute_snapshot_id, extract_filename  # noqa: E402

# --------------------------------------------------------------------------- #
# frozen freeze parameters
# --------------------------------------------------------------------------- #

CAPTURE_DATE = "2026-07-01"
CURATION_RULESET_VERSION = "curation-1.3.0"

CORPUS = REPO / "corpus"
OSV_DIR = CORPUS / "osv"
EXTRACT_DIR = CORPUS / "depsdev_extract"
ATTRIBUTION = REPO / "NOTICE" / "ATTRIBUTION.md"

SYSTEM = {"npm": "npm", "PyPI": "pypi", "crates.io": "cargo", "Go": "go"}
MINFIX = {"npm", "crates.io", "Go"}
# v0.3: crates.io and Go join the corpus. They were declared minimal-fix scoring
# ecosystems in verifier.py from the start but carried ZERO alerts, so two of the three
# tiers the verifier claims to score were never exercised by a single test.
CORPUS_ECOS = {"npm", "PyPI", "crates.io", "Go"}
MAX_KEYED_VERSIONS = 30  # cap per-version advisory-key GETs per package

# The frozen advisory-id list — hand-picked for diversity, each mechanically
# verified against the live APIs (see corpus/README.md for the selection rationale).
FREEZE_IDS = [
    # ---- npm: withdrawn ----
    "GHSA-7fhm-mqm4-2wp7",  # minimist (multi-entry too)
    "GHSA-crvj-3gj9-gm2p",  # qs
    "GHSA-9959-c6q6-6qp3",  # validator
    # ---- npm: multi-affected[] ----
    "GHSA-3xgq-45jj-v275",  # cross-spawn
    "GHSA-3g43-6gmg-66jw",  # axios
    "GHSA-3jfq-g458-7qm9",  # tar
    "GHSA-43f8-2h32-f4cj",  # hosted-git-info
    # ---- npm: no-fix (last_affected, open) ----
    "GHSA-2p57-rm9w-gvfp",  # ip
    # ---- npm: bounded (true-positive / false-positive material) ----
    "GHSA-35jh-r3h4-6jhm",  # lodash (the headline)
    "GHSA-29mw-wpgm-hmr9",  # lodash
    "GHSA-2328-f5f3-gj25",  # node-forge
    "GHSA-3w5v-p54c-f74x",  # ejs
    "GHSA-42xw-2xvc-qx8m",  # axios
    "GHSA-3949-f494-cm99",  # prismjs
    "GHSA-394c-5j6w-4xmx",  # ua-parser-js
    "GHSA-2mhh-w6q8-5hxw",  # ws
    "GHSA-2qvq-rjwj-gvw9",  # handlebars
    "GHSA-2r2c-g63r-vccr",  # node-forge
    # ---- PyPI: withdrawn ----
    "GHSA-56pw-mpj4-fxww",  # pillow
    "GHSA-h4pw-wxh7-4vjj",  # python-jose
    "GHSA-j7j6-7hfx-5522",  # waitress
    # ---- PyPI: multi-affected[] ----
    "GHSA-2gwj-7jmv-h26r",  # django
    "GHSA-24wv-mv5m-xv4h",  # redis
    # ---- PyPI: single-entry, GHSA-origin (CC-BY) ----
    "GHSA-pg2w-x9wp-vw92",  # requests
    "GHSA-v4w5-p2hg-8fh6",  # urllib3
    "GHSA-gmj6-6f8f-6699",  # jinja2
    "GHSA-cf7p-gm2m-833m",  # cryptography
    "GHSA-4grg-w6v8-c28g",  # flask
    "GHSA-q34m-jh98-gwm2",  # werkzeug (multi-entry)
    "GHSA-57qw-cc2g-pv5p",  # lxml
    "GHSA-p5w8-wqhj-9hhf",  # sqlparse
    "GHSA-248v-346w-9cwc",  # certifi
    "GHSA-7q8x-38mc-p84f",  # mako
    # ---- PyPI: PYSEC/OSV with GHSA aliases (still CC-BY under the rule) ----
    "PYSEC-2021-854",       # numpy
    "PYSEC-2022-269",       # oauthlib
    "PYSEC-2020-176",       # pyyaml
    "PYSEC-2022-183",       # httpx
    # ---- PyPI: GENUINE CC0 (no GHSA linkage) — exercises the CC0 branch ----
    "PYSEC-2021-107",       # ansible (CVE alias only)
    "OSV-2022-1074",        # pillow (no aliases at all — clean single_source)
    "PYSEC-2022-203",       # werkzeug (CVE alias only)
    # ---- crates.io (v0.3): a MINFIX-tier ecosystem that previously had no alerts ----
    "GHSA-r6v5-fh4h-64xc",  # time — bounded [0.3.6, 0.3.47)
    "GHSA-43w2-9j62-hq99",  # smallvec — bounded [0.6.3, 0.6.14)
    "GHSA-2grh-hm3w-w7hv",  # tokio — one-version window [1.8.0, 1.8.1), sharp FP/TP material
    "GHSA-5h46-h7hh-c6x9",  # hyper — open lower bound [0, 0.14.10)
    "RUSTSEC-2020-0071",    # time — 8 interleaved intervals w/ prerelease bounds ("0.2.7-0"),
                            # and a non-GHSA id, so it also exercises the CC0 provenance branch
    # ---- Go (v0.3): the other MINFIX ecosystem, plus v-prefix + pseudo-versions ----
    "GHSA-2c4m-59x9-fr2g",  # gin — pseudo-version LOWER bound
    "GHSA-w73w-5m7g-f7qc",  # jwt-go — last_affected 3.2.0 (inclusive, no fix available)
    "GHSA-3vm4-22fp-5rfm",  # x/crypto — pseudo-version UPPER bound
    "GO-2020-0017",         # jwt-go — open-ended (introduced only) + non-GHSA id
]


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #

def _get(url: str, tries: int = 4) -> dict:
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "depguard-freeze/0.1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as exc:  # noqa: BLE001 — one-shot dev script, retry all
            last = exc
            time.sleep(0.6 * (attempt + 1))
    raise RuntimeError(f"GET failed after {tries} tries: {url}\n  {last}")


def fetch_osv(advisory_id: str) -> dict:
    return _get(f"https://api.osv.dev/v1/vulns/{urllib.parse.quote(advisory_id)}")


def fetch_depsdev_package(system: str, name: str) -> dict:
    enc = urllib.parse.quote(name, safe="")
    return _get(f"https://api.deps.dev/v3/systems/{system}/packages/{enc}")


def fetch_depsdev_version(system: str, name: str, version: str) -> dict:
    enc = urllib.parse.quote(name, safe="")
    encv = urllib.parse.quote(version, safe="")
    return _get(f"https://api.deps.dev/v3/systems/{system}/packages/{enc}/versions/{encv}")


# --------------------------------------------------------------------------- #
# curation (§1.2) + provenance (§1.7)
# --------------------------------------------------------------------------- #

def curate(rec: dict):
    """Filter affected[] to §1.2-surviving npm/PyPI entries; return (eco, entries).

    Raises if the record survives in >1 ecosystem (micro-corpus keeps single-eco
    records) or in none.
    """
    by_eco: dict[str, list] = {}
    for e in rec.get("affected", []):
        pkg = e.get("package") or {}
        eco = pkg.get("ecosystem")
        if eco not in CORPUS_ECOS:
            continue
        cmp = get_comparator(eco)
        versions = e.get("versions") or []
        semver_ranges = [r for r in e.get("ranges") or [] if r.get("type") == "SEMVER"]
        if not semver_ranges and not versions:
            continue  # ECOSYSTEM/GIT-only, no versions -> excluded
        ok = True
        for v in versions:
            try:
                cmp.key(v)
            except VersionParseError:
                ok = False
        for r in semver_ranges:
            for ev in r.get("events", []):
                for k, val in ev.items():
                    if k in ("introduced", "fixed", "last_affected") and val != "0":
                        try:
                            cmp.key(val)
                        except VersionParseError:
                            ok = False
        if ok:
            by_eco.setdefault(eco, []).append(e)
    if not by_eco:
        raise ValueError(f"{rec['id']}: nothing survives curation")
    if len(by_eco) > 1:
        raise ValueError(f"{rec['id']}: multi-ecosystem survivor {sorted(by_eco)}")
    eco = next(iter(by_eco))
    return eco, by_eco[eco]


def is_ccby(rec: dict) -> bool:
    if rec["id"].startswith("GHSA-"):
        return True
    if any(a.startswith("GHSA-") for a in rec.get("aliases", [])):
        return True
    for r in rec.get("references", []):
        if "github.com/advisories" in (r.get("url") or ""):
            return True
    return False


def source_url_for(rec: dict) -> str:
    if rec["id"].startswith("GHSA-"):
        return f"https://github.com/advisories/{rec['id']}"
    for a in rec.get("aliases", []):
        if a.startswith("GHSA-"):
            return f"https://github.com/advisories/{a}"
    for r in rec.get("references", []):
        if "github.com/advisories" in (r.get("url") or ""):
            return r["url"]
    return f"https://osv.dev/vulnerability/{rec['id']}"


# --------------------------------------------------------------------------- #
# emit
# --------------------------------------------------------------------------- #

def _canonical(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build_curated_record(rec: dict, eco: str, entries: list) -> dict:
    tier = "membership_and_minfix" if eco in MINFIX else "membership_only"
    curated = dict(rec)
    curated["affected"] = [dict(e, scoring_tier=tier) for e in entries]
    curated["_provenance"] = {
        "source": "osv",
        "source_url": source_url_for(rec),
        "license": "CC-BY-4.0" if is_ccby(rec) else "CC0-1.0",
        "retrieved": CAPTURE_DATE,
    }
    return curated


def relevant_versions(pubs: list[str], cmp, records_for_pkg: list[tuple]) -> list[str]:
    """Boundary-adjacent + enumerated versions worth carrying advisory keys for."""
    parseable = []
    for v in pubs:
        try:
            cmp.key(v)
            parseable.append(v)
        except VersionParseError:
            continue
    ordered = cmp.sort(parseable)
    keys = [cmp.key(v) for v in ordered]
    rel: set[str] = set()

    def below(bound: str):
        try:
            i = bisect_left(keys, cmp.key(bound))
        except VersionParseError:
            return
        if i > 0:
            rel.add(ordered[i - 1])

    def above(bound: str):
        try:
            i = bisect_right(keys, cmp.key(bound))
        except VersionParseError:
            return
        if i < len(ordered):
            rel.add(ordered[i])

    for _eco, entries in records_for_pkg:
        for e in entries:
            for v in (e.get("versions") or [])[:8]:
                if v in parseable:
                    rel.add(v)
            for r in e.get("ranges") or []:
                if r.get("type") != "SEMVER":
                    continue
                for ev in r.get("events", []):
                    for k, val in ev.items():
                        if val == "0":
                            continue
                        if k in ("introduced", "fixed", "last_affected") and val in parseable:
                            rel.add(val)
                        if k == "fixed":
                            below(val)   # last affected — true-positive material
                            above(val)   # first safe
                        if k == "last_affected":
                            rel.add(val)
                            above(val)
    if ordered:
        rel.add(ordered[-1])  # latest — default-ish
    # keep it bounded, deterministically (comparator order)
    bounded = [v for v in ordered if v in rel][:MAX_KEYED_VERSIONS]
    return bounded


def main() -> int:
    for d in (OSV_DIR, EXTRACT_DIR, ATTRIBUTION.parent):
        d.mkdir(parents=True, exist_ok=True)

    print(f"Freezing {len(FREEZE_IDS)} advisories (capture {CAPTURE_DATE}) ...")
    curated_records: list[tuple[str, dict, str, list]] = []  # (eco, curated, name?, entries)
    pkg_records: dict[tuple[str, str], list] = {}  # (eco, name) -> [(eco, entries)]

    for aid in FREEZE_IDS:
        raw = fetch_osv(aid)
        eco, entries = curate(raw)
        curated = build_curated_record(raw, eco, entries)
        out = OSV_DIR / eco / f"{raw['id']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_canonical(curated))
        for e in entries:
            key = (eco, e["package"]["name"])
            pkg_records.setdefault(key, []).append((eco, [e]))
        curated_records.append((eco, curated, None, entries))
        time.sleep(0.12)
    print(f"  wrote {len(curated_records)} OSV records across "
          f"{len({r[0] for r in curated_records})} ecosystems")

    # deps.dev derived extracts
    window_start = None
    window_end = None
    print(f"Building deps.dev extracts for {len(pkg_records)} packages ...")
    for (eco, name), recs in sorted(pkg_records.items()):
        system = SYSTEM[eco]
        cmp = get_comparator(eco)
        pkg = fetch_depsdev_package(system, name)
        pubs, default_version = [], None
        for v in pkg.get("versions", []):
            vk = v.get("versionKey", {})
            ver = vk.get("version")
            if ver is None:
                continue
            pubs.append(ver)
            if v.get("isDefault"):
                default_version = ver
        pubs = sorted(set(pubs))
        rel = relevant_versions(pubs, cmp, recs)
        akbv: dict[str, list[str]] = {}
        for ver in rel:
            vdata = fetch_depsdev_version(system, name, ver)
            keys = sorted({k["id"] for k in vdata.get("advisoryKeys", []) if k.get("id")})
            akbv[ver] = keys
            time.sleep(0.05)
        extract = {
            "system": system,
            "name": name,
            "versions": pubs,
            "default_version": default_version,
            "advisory_keys_by_version": akbv,
            "captured_at": CAPTURE_DATE,
            "_provenance": {
                "source": "deps.dev",
                "source_url": f"https://api.deps.dev/v3/systems/{system}/packages/"
                              f"{urllib.parse.quote(name, safe='')}",
                "license": "CC-BY-4.0",
                "note": "derived non-substantial extract (§1.7b) — never raw responses",
            },
        }
        (EXTRACT_DIR / system).mkdir(parents=True, exist_ok=True)
        (EXTRACT_DIR / system / f"{extract_filename(name)}.json").write_bytes(_canonical(extract))
        window_start = window_start or CAPTURE_DATE
        window_end = CAPTURE_DATE
        print(f"  {system}/{name}: {len(pubs)} versions, {len(akbv)} keyed")

    # snapshot id from the exact bytes just written (§0.5)
    snapshot_id = compute_snapshot_id(CORPUS, CAPTURE_DATE, CURATION_RULESET_VERSION)

    # SNAPSHOT.lock (references the id; never hashed into it)
    osv_sha = {}
    import hashlib
    for p in sorted(OSV_DIR.rglob("*.json")):
        osv_sha[p.relative_to(CORPUS).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    ext_sha = {}
    for p in sorted(EXTRACT_DIR.rglob("*.json")):
        ext_sha[p.relative_to(CORPUS).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    n_by_eco: dict[str, int] = {}
    n_withdrawn = 0
    n_ccby = 0
    for eco, curated, _n, _e in curated_records:
        n_by_eco[eco] = n_by_eco.get(eco, 0) + 1
        if curated.get("withdrawn"):
            n_withdrawn += 1
        if curated["_provenance"]["license"] == "CC-BY-4.0":
            n_ccby += 1
    lock = {
        "capture_date": CAPTURE_DATE,
        "corpus_snapshot_id": snapshot_id,
        "curation_ruleset_version": CURATION_RULESET_VERSION,
        "depsdev_capture_window": {"start": window_start, "end": window_end},
        "counts": {
            "total_records": len(curated_records),
            "by_ecosystem": n_by_eco,
            "withdrawn": n_withdrawn,
            "cc_by": n_ccby,
            "cc0": len(curated_records) - n_ccby,
            "packages": len(pkg_records),
        },
        "osv_sha256": osv_sha,
        "depsdev_extract_sha256": ext_sha,
    }
    (CORPUS / "SNAPSHOT.lock").write_bytes(_canonical(lock))

    write_attribution(curated_records, pkg_records)
    write_readme(lock, curated_records)
    print(f"\ncorpus_snapshot_id = {snapshot_id}")
    print(f"  records={len(curated_records)}  packages={len(pkg_records)}  "
          f"withdrawn={n_withdrawn}  cc_by={n_ccby}  cc0={len(curated_records) - n_ccby}")
    return 0


def write_attribution(curated_records, pkg_records) -> None:
    lines = [
        "# ATTRIBUTION",
        "",
        "Auto-generated by `scripts/freeze_micro.py` (DECISIONS.md §1.7). Do not edit by hand.",
        "",
        "## OSV advisories (CC-BY-4.0)",
        "",
        "Records tagged CC-BY-4.0 originate from the GitHub Advisory Database "
        "(GHSA id, GHSA alias, or a `github.com/advisories` reference) and are "
        "redistributed under CC-BY-4.0 with attribution below. CC0-1.0 records "
        "(no GHSA linkage) are public-domain and not listed here.",
        "",
    ]
    for eco, curated, _n, _e in sorted(curated_records, key=lambda r: r[1]["id"]):
        if curated["_provenance"]["license"] != "CC-BY-4.0":
            continue
        url = curated["_provenance"]["source_url"]
        lines.append(f"- `{curated['id']}` ({eco}) — {url}")
    lines += [
        "",
        "## deps.dev derived extract (CC-BY-4.0)",
        "",
        "Published-version lists and `(version → advisory-key)` tables are a derived "
        "non-substantial extract of deps.dev (Open Source Insights), Google LLC, "
        "used under CC-BY-4.0. Source endpoints:",
        "",
    ]
    for (eco, name) in sorted(pkg_records):
        system = SYSTEM[eco]
        enc = urllib.parse.quote(name, safe="")
        lines.append(f"- {system}/{name} — https://api.deps.dev/v3/systems/{system}/packages/{enc}")
    lines.append("")
    ATTRIBUTION.write_text("\n".join(lines))


def write_readme(lock, curated_records) -> None:
    c = lock["counts"]
    withdrawn = [r[1]["id"] for r in curated_records if r[1].get("withdrawn")]
    multi = [r[1]["id"] for r in curated_records if len(r[1].get("affected", [])) >= 2]
    text = f"""# corpus/ — the frozen v0.1 micro-corpus

**`corpus_snapshot_id`: `{lock['corpus_snapshot_id']}`**  ·  capture {lock['capture_date']}

The runtime tool layer and CI read ONLY this directory — never the network
(DECISIONS.md §1.4). Regenerate with `python scripts/freeze_micro.py`.

## What this is (and is not)

A deliberately SMALL, hand-picked npm + PyPI slice ({c['total_records']} advisories)
chosen to exercise every branch of the mechanical verifier — NOT a representative
sample of the vulnerability landscape and NOT a benchmark leaderboard. The full
`gs://osv-vulnerabilities/all.zip` freeze is a v0.2 item (DECISIONS.md editorial
note 3); v0.1 hashes these record bytes ‖ the deps.dev extract bytes ‖ the
curation-ruleset tag.

## Selection criteria

Every advisory was fetched by id from `api.osv.dev`, curated per §1.2 with the
runtime comparators (`depguard.comparators`), and kept only if it survives in
exactly one corpus ecosystem. Package popularity was a selection filter so each
name resolves on deps.dev; the set was seeded to include the §4.2 categories:
true-positives, scanner false-positives, withdrawn advisories, no-fix-available,
already-safe, and multi-`affected[]` records.

## Counts (pinned post-freeze)

| Metric | Value |
|---|---|
| total records | {c['total_records']} |
| by ecosystem | {c['by_ecosystem']} |
| withdrawn | {c['withdrawn']} |
| CC-BY-4.0 / CC0-1.0 | {c['cc_by']} / {c['cc0']} |
| deps.dev packages | {c['packages']} |

- withdrawn: {', '.join(sorted(withdrawn))}
- multi-`affected[]`: {', '.join(sorted(multi))}

## Layout

```
corpus/
  osv/<ECOSYSTEM>/<ID>.json          curated OSV record: surviving affected[]
                                     entries only, each annotated scoring_tier,
                                     plus _provenance {{source,license,url,retrieved}}
  depsdev_extract/<system>/<name>.json   DERIVED extract (§1.7b): published-version
                                     list + bounded (version -> advisory-key) table.
                                     NEVER raw deps.dev response bodies (ToS §5).
  SNAPSHOT.lock                      capture_date, corpus_snapshot_id, per-file
                                     sha256, curation_ruleset_version, capture window
  README.md                          this file
NOTICE/ATTRIBUTION.md                auto-generated CC-BY attribution
```

## Reproducibility

Re-running on {lock['capture_date']} reproduces identical bytes unless upstream
data changed (OSV may re-issue a `modified` timestamp; deps.dev may publish new
versions). Any such drift changes `corpus_snapshot_id` and is expected — old gold
labels pin to the old id (DECISIONS.md §1.4, §6).
"""
    (CORPUS / "README.md").write_text(text)


if __name__ == "__main__":
    raise SystemExit(main())
