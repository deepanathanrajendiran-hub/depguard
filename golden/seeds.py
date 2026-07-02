"""Golden-set seed INPUTS (the source of truth; trajectories + expected are
generated from these by scripts/gen_golden.py). Each value is a §3 trajectory
`input` {manifest, alerts}. Grows across D5 (seed_01) → D6 (~10) → D7 (25–30).

Every case is a single-alert triage; the category each exercises (§4.2) is noted.
Gold is labeled by running the oracle — these inputs never carry expected answers.
"""


def _case(eco, name, version, advisory, sid):
    system = "pypi" if eco == "PyPI" else eco
    return {
        "manifest": [
            {"ecosystem": eco, "name": name, "pinned_version": version,
             "purl": f"pkg:{system}/{name}@{version}"}
        ],
        "alerts": [
            {"alert_id": f"{sid}-a1", "ecosystem": eco, "name": name,
             "pinned_version": version, "advisory_id": advisory, "source": "scanner"}
        ],
    }


SEED_INPUTS = {
    # scanner false positive: lodash 4.17.21 flagged for CVE-2021-23337, but 4.17.21
    # is the FIXED release ([0, 4.17.21) exclusive) → affected=False (the headline).
    "seed_01": _case("npm", "lodash", "4.17.21", "GHSA-35jh-r3h4-6jhm", "seed_01"),
    # true positive: 4.17.20 IS in range → affected=True, upgrade to 4.17.21.
    "tp_lodash": _case("npm", "lodash", "4.17.20", "GHSA-35jh-r3h4-6jhm", "tp_lodash"),
    # withdrawn-but-contained: minimist 1.2.0 is in [0,1.2.2) BUT the advisory was
    # withdrawn → affected=False despite containment (the withdrawn override, §1.5).
    "withdrawn_minimist": _case("npm", "minimist", "1.2.0", "GHSA-7fhm-mqm4-2wp7",
                                "withdrawn_minimist"),
    # no-fix-available: ip 2.0.1 is last_affected (inclusive) and the latest published
    # → affected=True, minimal_fixed=None (no published version clears it).
    "nofix_ip": _case("npm", "ip", "2.0.1", "GHSA-2p57-rm9w-gvfp", "nofix_ip"),
    # already-safe: node-forge 1.4.0 is the fix (not contained) → affected=False,
    # minimal_fixed = the current version itself.
    "already_safe_forge": _case("npm", "node-forge", "1.4.0", "GHSA-2328-f5f3-gj25",
                                "already_safe_forge"),
    # multi-affected[]: tar 5.0.1 is contained ONLY by the third of four affected
    # entries ([5.0.0,5.0.6)) → exercises E_A OR-aggregation; fix = 5.0.6.
    "multi_tar": _case("npm", "tar", "5.0.1", "GHSA-3jfq-g458-7qm9", "multi_tar"),
    # single_source: OSV-2022-1074 (pillow) has no aliases, so deps.dev never carries
    # its key → source_agreement=single_source (P4 passes by construction).
    "single_src_pillow": _case("PyPI", "pillow", "9.1.0", "OSV-2022-1074",
                               "single_src_pillow"),
    # PyPI true positive + multi-affected[] (membership_only, never minimal-fix
    # scored): django 2.2 enumerated in the [2.2,2.2.28) entry.
    "tp_django": _case("PyPI", "django", "2.2", "GHSA-2gwj-7jmv-h26r", "tp_django"),
    # PyPI false positive: requests 2.6.0 is the fix (not in the affected version
    # list) → affected=False.
    "fp_requests": _case("PyPI", "requests", "2.6.0", "GHSA-pg2w-x9wp-vw92", "fp_requests"),
    # withdrawn PyPI: pillow 8.0.0 is enumerated-affected by GHSA-56pw but the
    # advisory is withdrawn → affected=False.
    "withdrawn_pillow": _case("PyPI", "pillow", "8.0.0", "GHSA-56pw-mpj4-fxww",
                              "withdrawn_pillow"),

    # ---- D7 expansion: oracle-verified TP/FP cases spanning the corpus (§4.2) ---- #
    # npm (minimal-fix scored). A second lodash advisory exercises retrieval picking
    # the right record when osv_query returns >1 advisory for a package.
    "tp_lodash_29mw": _case("npm", "lodash", "4.15.0", "GHSA-29mw-wpgm-hmr9", "tp_lodash_29mw"),
    "tp_axios": _case("npm", "axios", "1.3.6", "GHSA-3g43-6gmg-66jw", "tp_axios"),
    "fp_axios": _case("npm", "axios", "1.15.2", "GHSA-3g43-6gmg-66jw", "fp_axios"),
    "tp_cross_spawn": _case("npm", "cross-spawn", "2.0.1", "GHSA-3xgq-45jj-v275", "tp_cross_spawn"),
    "fp_cross_spawn": _case("npm", "cross-spawn", "7.0.5", "GHSA-3xgq-45jj-v275", "fp_cross_spawn"),
    "tp_ws": _case("npm", "ws", "0.4.14", "GHSA-2mhh-w6q8-5hxw", "tp_ws"),
    "fp_handlebars": _case("npm", "handlebars", "4.7.9", "GHSA-2qvq-rjwj-gvw9", "fp_handlebars"),
    "tp_prismjs": _case("npm", "prismjs", "1.20.0", "GHSA-3949-f494-cm99", "tp_prismjs"),
    "fp_ua_parser": _case("npm", "ua-parser-js", "0.7.23", "GHSA-394c-5j6w-4xmx", "fp_ua_parser"),
    # PyPI (membership-only). Several score `agree` — the only genuine P4 signal
    # the corpus can give (see LIMITATIONS.md).
    "tp_redis": _case("PyPI", "redis", "4.3.4", "GHSA-24wv-mv5m-xv4h", "tp_redis"),
    "tp_flask": _case("PyPI", "flask", "3.1.0", "GHSA-4grg-w6v8-c28g", "tp_flask"),
    "tp_cryptography": _case("PyPI", "cryptography", "40.0.2", "GHSA-cf7p-gm2m-833m", "tp_cryptography"),
    "tp_jinja2": _case("PyPI", "jinja2", "3.1.0", "GHSA-gmj6-6f8f-6699", "tp_jinja2"),
    "fp_urllib3": _case("PyPI", "urllib3", "1.18.1", "GHSA-v4w5-p2hg-8fh6", "fp_urllib3"),
    "tp_sqlparse": _case("PyPI", "sqlparse", "0.4.1", "GHSA-p5w8-wqhj-9hhf", "tp_sqlparse"),
    "tp_numpy": _case("PyPI", "numpy", "1.9.2", "PYSEC-2021-854", "tp_numpy"),
    "tp_oauthlib": _case("PyPI", "oauthlib", "3.2.0", "PYSEC-2022-269", "tp_oauthlib"),
    "tp_pyyaml": _case("PyPI", "pyyaml", "5.1.1", "PYSEC-2020-176", "tp_pyyaml"),
    # a third withdrawn-contained case, PyPI side.
    "withdrawn_pyjose": _case("PyPI", "python-jose", "0.6.1", "GHSA-h4pw-wxh7-4vjj",
                              "withdrawn_pyjose"),
}
