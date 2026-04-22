# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""
Stage-1 latency benchmark.

Produces the numbers the Stage-1 exit gate requires:

    p95 < 50 ms for n_threats <= 30
    p95 < 200 ms for n_threats <= 100

Run:
    python benchmarks/bench_milp.py

Output is written to stdout and (optionally) to
``benchmarks/results/stage1_latency.json`` for the validation report.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.models import (  # noqa: E402
    Base,
    CommandersIntent,
    Effector,
    ScoringWeights,
    Threat,
)
from nimbus_c2.hungarian_tewa import solve_hungarian  # noqa: E402
from nimbus_c2.milp_tewa import solve_milp  # noqa: E402


_EFFECTORS = {
    "fighter": Effector(
        name="fighter", speed_kmh=2000.0, cost_weight=50.0,
        pk_matrix={"drone": 0.7, "bomber": 0.9, "fast-mover": 0.8},
        range_km=1200.0, min_engage_km=0.0, response_time_sec=60.0,
    ),
    "sam": Effector(
        name="sam", speed_kmh=3000.0, cost_weight=80.0,
        pk_matrix={"drone": 0.9, "bomber": 0.95, "fast-mover": 0.7},
        range_km=400.0, min_engage_km=0.0, response_time_sec=10.0,
    ),
    "drone": Effector(
        name="drone", speed_kmh=400.0, cost_weight=10.0,
        pk_matrix={"drone": 0.8, "bomber": 0.4, "fast-mover": 0.1},
        range_km=300.0, min_engage_km=0.0, response_time_sec=30.0,
    ),
}


def _scenario(seed: int, n_bases: int, n_threats: int):
    rng = random.Random(seed)
    bases = [
        Base(
            name=f"B{i:02d}",
            x=rng.uniform(-200, 200),
            y=rng.uniform(-200, 200),
            inventory={"fighter": 10, "sam": 20, "drone": 15},
            is_capital=(i == 0),
        )
        for i in range(n_bases)
    ]
    types = ["drone", "bomber", "fast-mover"]
    threats = [
        Threat(
            id=f"T{j:03d}",
            x=rng.uniform(-250, 250),
            y=rng.uniform(-250, 250),
            speed_kmh=rng.uniform(200, 1500),
            heading_deg=rng.uniform(0, 359),
            estimated_type=rng.choice(types),
            threat_value=rng.uniform(10, 100),
            class_confidence=rng.uniform(0.6, 1.0),
            kinematic_consistency=rng.uniform(0.6, 1.0),
            sensor_agreement=rng.uniform(0.7, 1.0),
            age_sec=rng.uniform(0, 25),
        )
        for j in range(n_threats)
    ]
    return bases, threats


def _percentile(xs: List[float], p: float) -> float:
    xs_sorted = sorted(xs)
    k = p * (len(xs_sorted) - 1)
    f = int(k)
    c = min(f + 1, len(xs_sorted) - 1)
    return xs_sorted[f] + (xs_sorted[c] - xs_sorted[f]) * (k - f)


def _measure(solver_fn, bases, effectors, threats, intent, weights, n_runs: int):
    # Warm-up, excluded from statistics.
    for _ in range(3):
        solver_fn(bases, effectors, threats, intent, weights)
    latencies_ms: List[float] = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        solver_fn(bases, effectors, threats, intent, weights)
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)
    return {
        "p50": _percentile(latencies_ms, 0.50),
        "p95": _percentile(latencies_ms, 0.95),
        "p99": _percentile(latencies_ms, 0.99),
        "mean": statistics.fmean(latencies_ms),
        "min": min(latencies_ms),
        "max": max(latencies_ms),
        "n_runs": n_runs,
    }


def run_benchmark() -> Dict:
    intent = CommandersIntent(
        min_pk_for_engage=0.3,
        min_safety_margin_sec=5.0,
        max_effectors_per_threat=1,
    )
    weights = ScoringWeights()

    fleet_sizes = [5, 10, 20, 30, 50, 100]
    results: Dict = {}

    for n_threats in fleet_sizes:
        n_bases = max(3, n_threats // 5)
        bases, threats = _scenario(seed=42, n_bases=n_bases, n_threats=n_threats)
        n_runs = 100 if n_threats <= 30 else 30

        h = _measure(solve_hungarian, bases, _EFFECTORS, threats,
                     intent, weights, n_runs)
        m = _measure(solve_milp, bases, _EFFECTORS, threats,
                     intent, weights, n_runs)

        results[f"n_threats={n_threats}"] = {
            "n_bases": n_bases,
            "hungarian": h,
            "milp_highs": m,
        }
        print(f"n={n_threats:3d} bases={n_bases:2d}  "
              f"H p50/p95/p99 = {h['p50']:6.2f} / {h['p95']:6.2f} / {h['p99']:6.2f} ms   "
              f"MILP p50/p95/p99 = {m['p50']:6.2f} / {m['p95']:6.2f} / {m['p99']:6.2f} ms")

    return results


if __name__ == "__main__":
    print("Stage-1 latency benchmark — scipy.optimize.milp (HiGHS)")
    print("=" * 72)
    results = run_benchmark()

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "stage1_latency.json"
    out.write_text(json.dumps(results, indent=2))
    print()
    print(f"Saved: {out}")

    # Exit gate evaluation.
    print()
    print("Stage-1 exit gate:")
    gate_pass = True
    for key, row in results.items():
        n = int(key.split("=")[1])
        p95 = row["milp_highs"]["p95"]
        target = 50.0 if n <= 30 else 200.0
        status = "PASS" if p95 < target else "FAIL"
        if status == "FAIL":
            gate_pass = False
        print(f"  {key:20s}  MILP p95 = {p95:7.2f} ms   target {target:5.1f} ms   [{status}]")

    sys.exit(0 if gate_pass else 1)
