"""Paired-bootstrap significance for the three-arm ablation (DECISIONS.md §4.4; D9).

Comparing two noisy metric means has no error bar. The fix is to PAIR: score the same
golden trajectories with both arms, take the per-trajectory delta d_i = m_A(t_i) − m_B(t_i),
and bootstrap its mean — pairing cancels per-trajectory difficulty variance so smaller real
differences surface. A difference is significant only when the 95% percentile interval on
the mean delta excludes 0.

Pure stdlib (a seeded `random.Random`), no numpy: 10k resamples over ~30 items is trivial,
and keeping the dependency surface minimal matters more than micro-speed (house rule: no
scope creep). Adapted from the owner's prior art (~/Documents/SFT/compare_recall.py), which
did the same resample-and-percentile over numpy arrays.
"""

from __future__ import annotations

import random


def _percentile(sorted_xs: list[float], q: float) -> float:
    """Linear-interpolation percentile (numpy default), q in [0,1]. `sorted_xs` ascending."""
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    pos = q * (len(sorted_xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_xs) - 1)
    frac = pos - lo
    return sorted_xs[lo] * (1.0 - frac) + sorted_xs[hi] * frac


def paired_bootstrap_delta(
    deltas: list[float],
    *,
    n_boot: int = 10000,
    seed: int = 0,
    alpha: float = 0.05,
) -> dict:
    """Bootstrap the mean of paired per-trajectory deltas.

    Returns {observed, ci_lo, ci_hi, n, n_boot, alpha, significant, degenerate}.
    `significant` is True iff the (1−alpha) percentile interval of the resampled mean
    excludes 0 (i.e. ci_lo > 0 OR ci_hi < 0). Empty input ⇒ a degenerate all-None
    result, not an error.

    `degenerate` is True when the delta vector has ZERO VARIANCE — every trajectory
    produced the same delta. Resampling a constant can only return that constant, so
    the interval collapses onto it and says nothing about sampling uncertainty. It is a
    RENDERING flag and deliberately does NOT change `significant`: a constant non-zero
    delta is a real, maximally consistent effect and must still read as significant.
    What it guards against is the v0.1 report printing
    `deterministic_script − multi_agent = +0.0000 [0, 0]` on every metric, where the
    tight interval invited readers to see a precise estimate rather than an identity —
    both arms scored a constant 1.0 on all 29 trajectories. Callers must label a
    degenerate result rather than typeset it as a hypothesis test; see
    `ablation._fmt_ci`."""
    n = len(deltas)
    if n == 0:
        return {"observed": None, "ci_lo": None, "ci_hi": None, "n": 0,
                "n_boot": n_boot, "alpha": alpha, "significant": False,
                "degenerate": True}
    degenerate = min(deltas) == max(deltas)
    observed = sum(deltas) / n
    if degenerate:
        # Resampling a constant is a no-op; skip 10k pointless draws. The interval is
        # exactly [c, c], which is what the general path would compute anyway.
        return {"observed": observed, "ci_lo": observed, "ci_hi": observed, "n": n,
                "n_boot": n_boot, "alpha": alpha,
                "significant": observed != 0.0, "degenerate": True}
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += deltas[rng.randrange(n)]
        means.append(s / n)
    means.sort()
    ci_lo = _percentile(means, alpha / 2.0)
    ci_hi = _percentile(means, 1.0 - alpha / 2.0)
    significant = ci_lo > 0.0 or ci_hi < 0.0
    return {"observed": observed, "ci_lo": ci_lo, "ci_hi": ci_hi,
            "n": n, "n_boot": n_boot, "alpha": alpha, "significant": significant,
            "degenerate": False}


def compare_arms(
    scores_a: list[float],
    scores_b: list[float],
    **kwargs,
) -> dict:
    """Paired-bootstrap the (A − B) delta from two per-trajectory score lists aligned by
    index (same golden set, same order). Raises ValueError if the lists misalign."""
    if len(scores_a) != len(scores_b):
        raise ValueError(
            f"arms are not paired: {len(scores_a)} vs {len(scores_b)} trajectories")
    deltas = [a - b for a, b in zip(scores_a, scores_b)]
    return paired_bootstrap_delta(deltas, **kwargs)
