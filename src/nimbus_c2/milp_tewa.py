# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Mixed-Integer Linear Program weapon–target assignment.

This is the **Stage-1 deliverable** of the Nimbus-C2 strategic
plan. It replaces the implicit soft constraints of the Hungarian
baseline with an explicit MILP formulation whose constraints are:

    C1   at most K_t effectors per threat        (multi-engage/cooperative fire)
    C2   at most capacity(b,e) shots per (b,e)   (hard inventory + reserve floor)
    C3   each (b,e,t) variable only created if feasible on range, timing,
         and minimum-Pk grounds                   (structural pruning)

Objective: maximise Σ u_{b,e,t} · x_{b,e,t}
            equivalently minimise Σ (-u_{b,e,t}) · x_{b,e,t}

Default solver backend: HiGHS via ``scipy.optimize.milp`` (free, open-
source, deterministic, bundled with SciPy ≥ 1.9).
Optional: Gurobi via ``BOREAL_SOLVER=gurobi`` environment variable.

Why MILP over Hungarian
-----------------------
The Hungarian algorithm solves the *assignment problem* — one shooter
to one target, one shot. Real TEWA has a richer structure that the
assignment formulation cannot express:

  * A high-value threat may warrant a **coordinated shoot-look-shoot**
    from two effectors (``K_t = 2``). Hungarian cannot model this.
  * **Reserve floors** are contractual, not preferences: "do not let
    inventory of capital SAMs drop below 4". Hungarian can only
    penalise this softly.
  * **Minimum-Pk** from commander's intent is a hard ROE floor.
    Hungarian tolerates sub-floor shots if nothing better exists;
    MILP structurally disallows them.

Parity with Hungarian
---------------------
When ``intent.max_effectors_per_threat == 1`` and no reserve floor is
set and ``intent.min_pk_for_engage`` is not binding, the MILP solves
the same LAP as Hungarian and returns the same objective value within
1e-6 (see ``tests/test_milp_parity.py``). Tie-breaking may differ
between solvers — this is expected and documented.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping, Sequence

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

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

# --------------------------------------------------------------------------- #
# Problem construction                                                        #
# --------------------------------------------------------------------------- #

def _build_problem(
    candidates: Sequence[Candidate],
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
) -> tuple[
    np.ndarray,                # c: objective coefficients
    LinearConstraint,          # constraints stacked as Ax <= b
    list[Candidate],           # feasible candidates, same order as columns
]:
    """Construct the MILP in scipy.optimize.milp canonical form.

    Only **feasible** candidates become decision variables — infeasible
    tuples are pruned at construction time, not added as zero-equality
    constraints. This halves matrix rows on dense scenarios and makes
    the feasibility reason surface-visible in
    ``TEWAResult.feasible_pairs``.
    """
    feasible = [c for c in candidates if c.feasible]
    n_vars = len(feasible)

    if n_vars == 0:
        return (
            np.zeros(0),
            LinearConstraint(np.zeros((0, 0)), ub=np.zeros(0)),
            feasible,
        )

    # Objective: minimise -utility ≡ maximise utility.
    c_obj = np.array([-cand.utility for cand in feasible], dtype=float)

    # ---- C1: at most K_t effectors per threat -----------------------------
    #
    # For each threat t, Σ_{b,e} x_{b,e,t} ≤ K_t.
    #
    # One row per threat; coefficient = 1 on every variable whose
    # candidate references this threat.
    len(threats)
    # Index threats by their stable id rather than by enumeration index
    # to stay agnostic to caller ordering.
    threat_order = sorted({c.threat_id for c in feasible})
    threat_row: dict[str, int] = {tid: i for i, tid in enumerate(threat_order)}

    # ---- C2: capacity per (base, effector) --------------------------------
    #
    # For each (b, e) with positive capacity, Σ_t x_{b,e,t} ≤ cap(b,e).
    be_keys = sorted({(c.base_name, c.effector_name) for c in feasible})
    be_row: dict[tuple[str, str], int] = {k: i for i, k in enumerate(be_keys)}

    n_c1 = len(threat_order)
    n_c2 = len(be_keys)
    n_rows = n_c1 + n_c2

    A = np.zeros((n_rows, n_vars), dtype=float)
    b_ub = np.zeros(n_rows, dtype=float)

    # Fill C1 rows.
    Kt = float(intent.max_effectors_per_threat)
    for i in range(n_c1):
        b_ub[i] = Kt

    # Fill C2 rows: capacity lookup.
    base_by_name: dict[str, Base] = {b.name: b for b in bases}
    for (bname, ename), i in be_row.items():
        cap = base_by_name[bname].capacity(ename)
        b_ub[n_c1 + i] = float(cap)

    # Populate coefficients.
    for col, cand in enumerate(feasible):
        A[threat_row[cand.threat_id], col] = 1.0
        A[n_c1 + be_row[(cand.base_name, cand.effector_name)], col] = 1.0

    constraints = LinearConstraint(A, ub=b_ub)
    return c_obj, constraints, feasible


# --------------------------------------------------------------------------- #
# Solver entry points                                                         #
# --------------------------------------------------------------------------- #

def _solve_highs(
    c_obj: np.ndarray,
    constraints: LinearConstraint,
    n_vars: int,
) -> np.ndarray:
    """Solve with scipy.optimize.milp (HiGHS backend).

    Returns the binary solution vector. Raises ``RuntimeError`` if the
    solver reports a status other than "optimal".
    """
    if n_vars == 0:
        return np.zeros(0)

    # HiGHS supports presolve/LP-relaxation defaults that are
    # deterministic. We pass no options beyond the integrality
    # specification; that's sufficient for reproducibility.
    res = milp(
        c=c_obj,
        constraints=constraints,
        integrality=np.ones(n_vars, dtype=int),
        bounds=Bounds(lb=0.0, ub=1.0),
    )
    if not res.success:
        raise RuntimeError(
            f"HiGHS MILP solver failed: status={res.status} message={res.message!r}"
        )
    if res.x is None:
        raise RuntimeError(
            f"HiGHS MILP returned success but no solution vector "
            f"(status={res.status})"
        )
    # Round to binary — MILP with integrality=1 returns values that are
    # already integral, but we round to defend against float drift.
    return np.rint(res.x).astype(int)


def _solve_gurobi(
    c_obj: np.ndarray,
    constraints: LinearConstraint,
    n_vars: int,
) -> np.ndarray:
    """Solve with Gurobi if available. Optional accelerator, not required."""
    try:
        import gurobipy as gp
        from gurobipy import GRB
    except ImportError as exc:  # pragma: no cover — optional dep
        raise RuntimeError(
            "Gurobi backend requested (BOREAL_SOLVER=gurobi) but gurobipy is "
            "not installed. Install gurobipy and ensure a valid licence."
        ) from exc

    if n_vars == 0:
        return np.zeros(0)

    model = gp.Model("nimbus_tewa")
    model.Params.OutputFlag = 0
    model.Params.Seed = 0                # deterministic tie-breaking
    model.Params.Threads = 1             # deterministic timing
    x = model.addMVar(shape=n_vars, vtype=GRB.BINARY, name="x")
    model.setObjective(c_obj @ x, GRB.MINIMIZE)
    A = constraints.A
    b_ub = constraints.ub
    model.addConstr(A @ x <= b_ub)       # all constraints are upper-bound
    model.optimize()
    if model.status != GRB.OPTIMAL:
        raise RuntimeError(f"Gurobi MILP solver failed: status={model.status}")
    return np.rint(x.X).astype(int)


def solve_milp(
    bases: Sequence[Base],
    effectors: Mapping[str, Effector],
    threats: Sequence[Threat],
    intent: CommandersIntent,
    weights: ScoringWeights | None = None,
    solver: str | None = None,
) -> TEWAResult:
    """Solve the MILP weapon-target-assignment problem.

    Parameters
    ----------
    bases, effectors, threats, intent :
        Standard tactical state; see ``models.py``.
    weights :
        Scoring coefficients. ``None`` selects canonical defaults.
    solver :
        ``"highs"`` (default) or ``"gurobi"``. If ``None``, read from
        the ``BOREAL_SOLVER`` environment variable, defaulting to
        ``"highs"``.

    Returns
    -------
    TEWAResult
        Deterministic; same input yields bit-identical assignment set.
    """
    if weights is None:
        weights = ScoringWeights()

    if solver is None:
        solver = os.environ.get("BOREAL_SOLVER", "highs").lower()

    candidates = enumerate_candidates(
        bases, effectors, threats, intent, weights,
    )

    if not candidates or not threats:
        return TEWAResult(
            assignments=[],
            total_utility=0.0,
            solver=f"milp_{solver}",
            wall_clock_ms=0.0,
            feasible_pairs=0,
        )

    c_obj, constraints, feasible = _build_problem(
        candidates, bases, effectors, threats, intent,
    )
    n_vars = len(feasible)

    t0 = time.perf_counter()
    if solver == "highs":
        x_sol = _solve_highs(c_obj, constraints, n_vars)
    elif solver == "gurobi":
        x_sol = _solve_gurobi(c_obj, constraints, n_vars)
    else:
        raise ValueError(
            f"Unknown solver {solver!r}. Expected 'highs' or 'gurobi'."
        )
    t1 = time.perf_counter()

    chosen: list[Candidate] = [
        feasible[i] for i, v in enumerate(x_sol.tolist()) if v == 1
    ]
    chosen.sort(key=lambda c: (c.base_name, c.effector_name, c.threat_id))

    feasible_count = len(feasible)
    return TEWAResult(
        assignments=[candidate_to_assignment(c) for c in chosen],
        total_utility=sum(c.utility for c in chosen),
        solver=f"milp_{solver}",
        wall_clock_ms=(t1 - t0) * 1000.0,
        feasible_pairs=feasible_count,
    )


__all__ = ["solve_milp"]
