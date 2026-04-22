<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Nimbus-C2

A reliability-aware command-and-control decision engine with epistemic
uncertainty gating and a deterministic safety shield. Research software
targeting defence decision-support integration.

**Author:** Maria Westrin · Stockholm, SE · 2026.
**Licence:** [MIT](LICENSE).
**Citation:** [`CITATION.cff`](CITATION.cff) (GitHub renders this as a
"Cite this repository" button).
**Status:** Stages 0 and 1 complete with a working FastAPI demo UI.
**Roadmap:** [`STRATEGY.md`](STRATEGY.md) · [`PITCH.md`](PITCH.md) ·
[`MIGRATION.md`](MIGRATION.md)

---

## What this is

Nimbus-C2 is a tactical threat-evaluation-and-weapon-assignment (TEWA)
engine built around three commitments that distinguish defence-grade
decision support from research prototypes:

1. **Determinism before intelligence.** The primary solver is a mixed-
   integer linear programme with reproducible output across 1000 runs.
   Stochastic components (reinforcement learning, learned classifiers)
   are only permitted as *overlays* on the deterministic core, and only
   when wrapped in a deterministic safety shield.
2. **Measurable reliability before feature volume.** Every capability
   ships with a reliability metric and a calibrated operating envelope.
   Stage 2 introduces conformal prediction, out-of-distribution
   detection, and deep-ensemble aleatoric/epistemic decomposition —
   each with a published coverage contract.
3. **Graceful degradation before peak performance.** Every layer has a
   documented fallback. When the system detects it is outside its
   competence envelope, it transfers control to the human operator —
   rather than making a confident, fatal error.

## 60-second demo

```bash
# Terminal 1 — backend
pip install -e ".[dev]"
uvicorn nimbus_c2.api.app:app --reload --port 8000

# Terminal 2 — frontend (any static server will do)
cd frontend && python -m http.server 5173
# then open http://localhost:5173 in a browser
```

You'll see three demo scenarios in the left panel. Click each:

- **Clean picture → AUTONOMOUS** · high track quality, balanced threats.
- **Swarm with fast-mover → ADVISE** · complexity rises, stakes elevated.
- **Jammed sensors + high-value threats → DEFER** · SA collapses, system
  withdraws to operator control.

See [`PITCH.md`](PITCH.md) for the full 90-second pitch script.

## Repository layout

```
nimbus-c2/
├── STRATEGY.md, PITCH.md, MIGRATION.md       # the plan, the pitch, the migration
├── LICENSE, NOTICE, CITATION.cff             # IP & attribution
├── SECURITY.md, CONTRIBUTING.md,             # governance
│   CODE_OF_CONDUCT.md, AUTHORS
├── pyproject.toml, .github/workflows/ci.yml  # packaging & CI
├── src/
│   └── nimbus_c2/
│       ├── models.py             # typed dataclasses
│       ├── scoring.py            # shared feasibility + utility
│       ├── hungarian_tewa.py     # conservative LAP baseline
│       ├── milp_tewa.py          # Stage-1 primary MILP solver
│       ├── assurance.py          # SA health + autonomy gating
│       ├── wave_forecaster.py    # per-sector follow-on forecast
│       ├── coa_generator.py      # 3 COAs with tradeoffs
│       ├── sitrep.py             # deterministic SITREP template
│       ├── pipeline.py           # end-to-end evaluate()
│       └── api/
│           ├── app.py            # FastAPI gateway
│           └── demo_data.py      # three canned scenarios
├── frontend/
│   └── index.html                # single-file operator console
├── tests/
│   ├── test_milp_parity.py       # MILP ≡ Hungarian in trivialising config
│   ├── test_milp_extensions.py   # coordinated fire, capacity, Pk floor
│   ├── test_milp_determinism.py  # 1000-run bit-identical output
│   ├── test_pipeline.py          # assurance, forecast, COA, SITREP, e2e
│   └── test_api.py               # FastAPI integration tests
├── benchmarks/
│   └── bench_milp.py             # latency distribution per fleet size
└── scripts/
    └── repo_hygiene.py           # SPDX headers + line-ending normalisation
```

## Quick start — full end-to-end

### Linux / macOS
```bash
git clone https://github.com/<your-username>/nimbus-c2.git
cd nimbus-c2
pip install -e ".[dev]"
pytest
python benchmarks/bench_milp.py
uvicorn nimbus_c2.api.app:app --port 8000
```

### Windows PowerShell
```powershell
git clone https://github.com/<your-username>/nimbus-c2.git
Set-Location nimbus-c2
python -m pip install -e ".[dev]"
python -m pytest
python benchmarks\bench_milp.py
python -m uvicorn nimbus_c2.api.app:app --port 8000
```

Expected output — every test green, every latency figure inside the
Stage-1 exit gate:

```
============================ 110 passed ============================
  n_threats=30           MILP p95 =   16.48 ms   target  50.0 ms   [PASS]
  n_threats=100          MILP p95 =  134.87 ms   target 200.0 ms   [PASS]
```

## Using the solver directly

```python
from nimbus_c2 import (
    Base, Threat, Effector, CommandersIntent, evaluate,
)

bases = [
    Base(name="Alpha", x=0, y=0,
         inventory={"sam": 8, "fighter": 4, "drone": 6},
         is_capital=True),
]
effectors = {
    "sam": Effector(name="sam", speed_kmh=3000, cost_weight=80,
                    pk_matrix={"bomber": 0.95, "drone": 0.9},
                    range_km=400, response_time_sec=10),
}
threats = [
    Threat(id="T01", x=120, y=80, speed_kmh=800, heading_deg=200,
           estimated_type="bomber", threat_value=95.0),
]
intent = CommandersIntent(min_pk_for_engage=0.55, min_safety_margin_sec=5.0)

result = evaluate(bases, effectors, threats, intent)

print(result.assurance.autonomy_mode.value)
print(result.sitrep.recommendation)
for coa in result.coas:
    print(coa.label.value, coa.predicted_coverage, coa.risk_if_follow_on)
```

## Design contracts (verified by the test suite)

- **Reproducibility.** Same input, same output, across runs, processes,
  and Python versions. Verified by
  [`tests/test_milp_determinism.py`](tests/test_milp_determinism.py)
  (1000 repeats on both solvers) and
  [`tests/test_pipeline.py::TestPipelineE2E::test_evaluate_deterministic`](tests/test_pipeline.py).
- **Hard safety constraints.** Reserve floors, minimum-Pk thresholds,
  per-cycle launcher capacity, and timing feasibility are enforced
  structurally (as infeasibility), not softly (as large penalties).
  See [`tests/test_milp_extensions.py`](tests/test_milp_extensions.py).
- **Parity with the conservative baseline.** In the trivialising
  configuration, MILP and Hungarian produce the same objective value
  to 1e-6 across 70 seeded scenarios. See
  [`tests/test_milp_parity.py`](tests/test_milp_parity.py).
- **Mode-correctness on representative scenarios.** The three demo
  scenarios drive the system into AUTONOMOUS / ADVISE / DEFER
  deterministically. See [`tests/test_api.py`](tests/test_api.py).

## Citing

If you use Nimbus-C2 in academic or technical work, please cite it via
the [`CITATION.cff`](CITATION.cff) record. Plain-text form:

> Westrin, M. (2026). *Nimbus-C2: a reliability-aware
> command-and-control decision engine with epistemic uncertainty
> gating and deterministic safety shield.* GitHub repository.

## Reporting issues

- **Security:** private disclosure per [`SECURITY.md`](SECURITY.md).
- **Bugs and enhancements:** GitHub issues.
- **Contributing:** [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Licence

MIT — see [`LICENSE`](LICENSE). Attribution expected via
[`NOTICE`](NOTICE) on redistribution, and via citation in academic and
technical publications.
