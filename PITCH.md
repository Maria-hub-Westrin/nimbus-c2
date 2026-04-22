<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Nimbus-C2 — Saab Pitch

**The one-liner.** You don't want an AI that's always confident. You want one
that knows the edge of its envelope — and withdraws when it crosses that edge,
rather than making a confident, fatal error.

**What it is.** A reliability-aware command-and-control decision engine.
Deterministic mixed-integer-linear-programming core for weapon–target
assignment, situation-awareness assessment layer that gates the system
between autonomous execution, operator-in-the-loop advisory, and full human
control, and a three-alternative course-of-action generator that presents
commanders with explicit tradeoffs rather than a single recommendation.

**Why it matters to Saab.** Every signal in Saab's public positioning —
layered C-UAS, cost-aware doctrine, modular C2 integration, rapid AI without
safety compromise, Gripen on-prem deployability, LLM-for-language-not-decisions
— maps directly onto a module in this engine. See `docs/SAAB_ALIGNMENT.md` for
the signal-to-module crosswalk.

## The 90-second demo

Open `http://localhost:8000` with the backend running, open `frontend/index.html`.

**0–20 s — the clean picture.** Click *Clean picture — three bombers*.

> "Three bombers, high-quality tracks. Situation-awareness health above 80.
> System goes AUTONOMOUS. Three courses of action on the right: Recommended,
> Reserve-Conserving, Risk-Minimizing, each with quantified tradeoffs —
> coverage, follow-on risk, rounds spent. The engine always shows its work."

**20–50 s — degrade the picture.** Click *Swarm with fast-mover breakthrough*.

> "Fifteen tracks: drones, fast-movers, a ghost with ambiguous classification.
> Situation complexity jumps, stakes rise, SA-health drops. Autonomy mode shifts
> automatically to ADVISE. The engine now proposes; the commander confirms."

Point at the reasons list.

> "Every mode change names its cause — complexity above threshold, stakes near
> the engage boundary. No black-box autonomy decisions."

**50–75 s — the jammed scenario.** Click *Jammed sensors + high-value threats*.

> "Inbound hypersonic, multiple ghosts, blind spot over the primary track,
> sensor agreement at 45 %. SA-health collapses below 40. Mode: DEFER. The
> system hands the decision back to the human rather than shoot on degraded
> information."

Point at the alerts panel.

> "Surface-visible alerts: multi-sensor fusion agreement low, tracks in radar
> blind spot. Plus the forecast panel shows where the follow-on wave is most
> likely — the commander is given information, not a decision they can't audit."

**75–90 s — the closer.**

> "Three modes, one engine. Deterministic MILP at the core — 83 tests verify
> parity with the classical Hungarian baseline, 1000-run bit-identical
> determinism, all constraints enforced structurally rather than penalised.
> No proprietary solver dependency; runs on SciPy HiGHS. LLM is strictly
> optional and can only rewrite prose — never numbers. Air-gapped deployable.
> On-prem ready. This is a C2 engine you can put in a tactical cell this
> quarter, with a stage-gated roadmap to get the uncertainty layer, the
> offline-RL distillation, and the Rust performance port over the next seven
> weeks, each with measurable exit gates."

## Anticipated questions

**"How is this different from a regular optimiser?"**
Three things. First, scoring is expected damage averted, not summed preference
bonuses. Second, time-to-intercept versus time-to-asset is a hard feasibility
gate, not a penalty term. Third, the assurance layer owns the autonomy decision
independently of the optimiser — so the same optimiser can run in AUTONOMOUS
or DEFER mode without change to its logic. That separation is what makes the
system certifiable.

**"Is reinforcement learning making any live decisions?"**
No. Stage 3 introduces an offline-RL policy, but it is distilled into a
shallow decision tree before deployment, and that tree is wrapped in a
deterministic safety shield with formal veto predicates. Every deployed
decision is reducible to rules a human can read. See STRATEGY.md §Stage 3.

**"What if the LLM hallucinates?"**
It cannot, structurally. The LLM layer is opt-in and can only rewrite four
prose fields of the SITREP (headline, recommendation, assurance note,
follow-on note). Numeric fields — Pk estimates, counts, survival percentages
— come from the engine's structured output and are displayed from those
structures, not from the SITREP text. An LLM failure silently falls back to
the offline template. See `src/nimbus_c2/sitrep.py`.

**"Air-gapped deployment?"**
Core pipeline makes zero outbound calls. LLM rewriter is an opt-in env-var
feature. Drop the package on a workstation, run
`uvicorn nimbus_c2.api.app:app` with your effector and base configuration,
point CSV or JSON input at the endpoint. The core runtime dependency is
NumPy plus SciPy, both standard on every defense-sector Python deployment.

**"Extending to other mission types?"**
The assurance layer generalises over any triple of (track-quality,
complexity, stakes) signals. The scoring formula generalises over any Pk
matrix plus a value function. Swap the effector registry for maritime,
ground, or space, and the architecture holds.

**"Where's the Rust / C++ core you mentioned?"**
Stage 5 in the plan — conditional on telemetry showing the Python core
is the latency bottleneck. Measured p95 latency of the MILP solver is
16.5 ms at n=30 threats and 135 ms at n=100 threats on the CI baseline.
Not yet a bottleneck; therefore not yet worth porting. When the data
justifies the port, PyO3 bindings with Python-reference regression keep
the architecture unchanged.

## What "success" looks like

Five dimensions, each with a concrete observable that a Saab reviewer can
verify from the public repository:

| Dimension | Observable | Where to look |
|---|---|---|
| Determinism | Same input → same output, 1000 repeats | `tests/test_milp_determinism.py` (green in CI) |
| Measurable reliability | Stage 1 exit gate: latency + parity + extensions | `benchmarks/bench_milp.py`, `tests/test_milp_*.py` |
| Graceful degradation | Three scenarios → three modes, deterministically | `tests/test_api.py::test_*_scenario_is_*` |
| Explainability | Every decision renders to a rationale list | `AssuranceReport.reasons`, per-assignment rationale in COA |
| Production readiness | Clean MIT, no proprietary deps, PEP 621 package, CI matrix | `LICENSE`, `pyproject.toml`, `.github/workflows/ci.yml` |

All five turn green in CI on the first commit.

## The stage-gated roadmap

| Stage | Deliverable | Status |
|:-----:|---|:---:|
| 0 | Repository hygiene, clean MIT, attribution infrastructure | ✅ |
| 1 | Deterministic MILP TEWA core + Hungarian parity + demo UI | ✅ |
| 2 | Conformal prediction + OOD detection + aleatoric/epistemic decomposition | ⏳ |
| 3 | Offline RL → decision-tree distillation + safety shield | ⏳ |
| 4 | Protobuf/gRPC interface contract | ⏳ |
| 5 | Rust performance port (conditional on telemetry) | 🔒 |

See `STRATEGY.md` for the full plan. Every stage has an explicit exit gate
measured on the repo's own test infrastructure. No stage begins before the
prior stage's gate is empirically cleared.

---

*Author: Maria Westrin · Stockholm, SE · 2026. Licensed MIT. Cite per
`CITATION.cff`.*
