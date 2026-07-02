"""D9 — paired-bootstrap statistics.

The ablation compares arms on the SAME golden trajectories, so per-trajectory deltas
d_i = m_A(t_i) − m_B(t_i) are paired — pairing cancels per-trajectory difficulty variance.
We resample the index set with replacement n_boot× and take the 95% percentile interval of
the mean delta; a difference is "significant" only when that interval excludes 0.

Fixtures are hand-computable: a CONSTANT delta collapses the CI to that constant exactly
(every resample has the same mean), independent of the RNG — the cleanest possible check.
"""

from __future__ import annotations

from depguard.stats import compare_arms, paired_bootstrap_delta


def test_constant_delta_collapses_ci_exactly():
    """All deltas equal ⇒ every resample mean is that constant ⇒ CI = [c, c] exactly."""
    r = paired_bootstrap_delta([0.25] * 10, n_boot=1000, seed=0)
    assert r["observed"] == 0.25
    assert r["ci_lo"] == 0.25 and r["ci_hi"] == 0.25
    assert r["significant"] is True  # interval excludes 0
    assert r["n"] == 10


def test_zero_delta_not_significant():
    r = paired_bootstrap_delta([0.0] * 8, n_boot=1000, seed=0)
    assert r["observed"] == 0.0
    assert r["ci_lo"] == 0.0 and r["ci_hi"] == 0.0
    assert r["significant"] is False  # 0 is inside [0,0]


def test_all_positive_delta_is_significant():
    """Every delta > 0 ⇒ every resample mean > 0 ⇒ lower bound > 0 ⇒ significant."""
    r = paired_bootstrap_delta([0.1, 0.2, 0.3, 0.15, 0.25], n_boot=2000, seed=1)
    assert r["observed"] > 0
    assert r["ci_lo"] > 0
    assert r["significant"] is True


def test_symmetric_delta_brackets_zero():
    """A symmetric ± spread has observed mean 0 and a CI straddling 0 ⇒ not significant."""
    r = paired_bootstrap_delta([0.5, -0.5] * 20, n_boot=2000, seed=2)
    assert abs(r["observed"]) < 1e-9
    assert r["ci_lo"] < 0 < r["ci_hi"]
    assert r["significant"] is False


def test_ordering_lo_le_observed_le_hi():
    r = paired_bootstrap_delta([0.4, 0.1, 0.9, -0.2, 0.3, 0.0], n_boot=2000, seed=3)
    assert r["ci_lo"] <= r["observed"] <= r["ci_hi"]


def test_deterministic_same_seed():
    a = paired_bootstrap_delta([0.4, 0.1, 0.9, -0.2], n_boot=2000, seed=7)
    b = paired_bootstrap_delta([0.4, 0.1, 0.9, -0.2], n_boot=2000, seed=7)
    assert a == b


def test_empty_is_degenerate():
    r = paired_bootstrap_delta([], n_boot=100, seed=0)
    assert r["observed"] is None and r["significant"] is False


def test_compare_arms_pairs_by_index():
    """compare_arms takes aligned per-trajectory score lists and bootstraps the delta."""
    r = compare_arms([1.0, 1.0, 1.0], [0.5, 0.5, 0.5], n_boot=500, seed=0)
    assert r["observed"] == 0.5
    assert r["ci_lo"] == 0.5 and r["ci_hi"] == 0.5


def test_compare_arms_length_mismatch_raises():
    try:
        compare_arms([1.0, 1.0], [0.5], n_boot=10, seed=0)
    except ValueError:
        return
    raise AssertionError("expected ValueError on unaligned arms")
