# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Reference Hungarian (Linear Assignment Problem) weapon–target assignment.

This is the **conservative baseline** of the solver tier. It is what the
OOD-detector reverts to when the situation is flagged as out of
distribution, and it is the parity target for the MILP in the
trivialising configuration documented in STRATEGY.md §4.3.

The Hungarian algorithm solves
    min Σ c_ij · x_ij
    s.t.   Σ_j x_ij = 1  ∀i   (each shooter assigned to exactly one col)
           Σ_i x_ij = 1  ∀j   (each threat assigned to exactly one shooter)
           x_ij ∈ {0, 1}

TEWA is not naturally one-to-one: we may have more shooters than
threats, or vice versa. We handle this by padding the cost matrix with
dummy rows/columns at a neutral cost (zero). Assignments to dummy rows
or columns are discarded.

Infeasible pairs carry a large positive cost (``_BIG_M``) so the solver
will never choose them when any feasible alternative exists.
"""
from __future__ import annotations

import time
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from .models import (
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    TEWAResult,
    Threat,
)
from .scoring import (
    Candidate,
    candidate_to_assignment,
    enumerate_candidates,
)

# Large penalty for infeasible pairs. Chosen so that no realistic utility
# can approach it, but small enough to not cause float overflow when the
# LAP cost matrix is negated.
_BIG_M: float = 1.0e9


def _build_cost_matrix(
    candidates: Sequence[Candidate],
    n_threats: int,
) -> tuple[np.ndarray, list[tuple[str, str]]]:
    """Build a rectangular cost matrix for scipy.linear_sum_assignment.

    Rows are (base_name, effector_name) shooter identities; columns are
    threats (indexed by candidate.threat_idx). Each row has exactly one
    entry per threat column. Infeasible pairs receive ``_BIG_M``.

    Returns
    -------
    cost : np.ndarray, shape (n_shooters, n_cols)
        Cost matrix ready for ``linear_sum_assignment``.
    shooter_keys : List[(base_name, effector_name)]
        Row labels in the same order as matrix rows.
    """
    shooter_keys: list[tuple[str, str]] = sorted({
        (c.base_name, c.effector_name) for c in candidates
    })
    key_to_row: dict[tuple[str, str], int] = {
        k: i for i, k in enumerate(shooter_keys)
    }
    n_shooters = len(shooter_keys)

    if n_shooters == 0 or n_threats == 0:
        return np.zeros((0, 0)), shooter_keys

    # Square out the matrix with dummy rows/cols at zero cost, so
    # linear_sum_assignment (which requires a square matrix for the
    # one-to-one solution) yields a valid assignment in all cases.
    # When n_shooters != n_threats, scipy accepts rectangular input and
    # returns min(n_shooters, n_threats) matches; we rely on that and
    # discard matches with cost >= _BIG_M / 2.
    cost = np.full((n_shooters, n_threats), fill_value=_BIG_M, dtype=float)

    for c in candidates:
        if not c.feasible:
            continue
        r = key_to_row[(c.base_name, c.effector_name)]
        # Negate utility because Hungarian minimises.
        cost[r, c.threat_idx] = -c.utility

    return cost, shooter_keys


def solve_hungarian(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    weights: ScoringWeights | None = None,
) -> TEWAResult:
    """Run Hungarian WTA over the given state.

    Parameters
    ----------
    bases, effectors, threats, intent :
        Standard tactical state; see ``models.py``.
    weights :
        Scoring coefficients. ``None`` selects the canonical defaults.

    Returns
    -------
    TEWAResult
        Deterministic; identical input yields identical output across
        runs, process restarts, and Python versions (sans tie-breaking,
        which is guaranteed by the candidate enumeration order, not by
        the LAP itself).
    """
    if weights is None:
        weights = ScoringWeights()

    candidates = enumerate_candidates(
        bases, effectors, threats, intent, weights,
    )

    if not candidates or not threats:
        return TEWAResult(
            assignments=[],
            total_utility=0.0,
            solver="hungarian",
            wall_clock_ms=0.0,
            feasible_pairs=0,
        )

    # Look up candidate by (base, effector, threat_idx) for fast retrieval.
    cand_lookup: dict[tuple[str, str, int], Candidate] = {
        (c.base_name, c.effector_name, c.threat_idx): c
        for c in candidates
    }

    cost, shooter_keys = _build_cost_matrix(candidates, len(threats))

    t0 = time.perf_counter()
    if cost.size == 0:
        row_idx = np.array([], dtype=int)
        col_idx = np.array([], dtype=int)
    else:
        row_idx, col_idx = linear_sum_assignment(cost)
    t1 = time.perf_counter()

    chosen: list[Candidate] = []
    for r, c_col in zip(row_idx.tolist(), col_idx.tolist(), strict=False):
        cost_rc = cost[r, c_col]
        # Discard infeasible (BigM) matches: they are padding, not real.
        if cost_rc >= _BIG_M / 2:
            continue
        base_name, eff_name = shooter_keys[r]
        cand = cand_lookup.get((base_name, eff_name, c_col))
        if cand is None:
            continue
        chosen.append(cand)

    # Deterministic output ordering, independent of LAP internals.
    chosen.sort(key=lambda c: (c.base_name, c.effector_name, c.threat_id))

    feasible_count = sum(1 for c in candidates if c.feasible)
    return TEWAResult(
        assignments=[candidate_to_assignment(c) for c in chosen],
        total_utility=sum(c.utility for c in chosen),
        solver="hungarian",
        wall_clock_ms=(t1 - t0) * 1000.0,
        feasible_pairs=feasible_count,
    )


__all__ = ["solve_hungarian"]
