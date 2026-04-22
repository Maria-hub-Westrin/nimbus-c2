<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Nimbus-C2 — Stage-Gated Research & Engineering Strategy

> _"We reject black-box AI in live defense environments. We build deterministic,
> explainable cores, measurable reliability layers, and graceful degradation —
> then, and only then, we optimize for speed."_

**Document status:** v1.0 — living document. Each stage gate is a merge boundary.
**Author:** Maria Westrin (2026).
**License:** MIT.
**Target:** Tier-one defense integration (Saab Smart Stridsledning track).
**Citation:** see `CITATION.cff`.

---

## 0. Design philosophy — why stage gates

The system under construction is a **C2 decision-support engine** operating in
an environment where a confident wrong answer is strictly worse than a correct
"I don't know". Three principles follow from this directly:

1. **Determinism before intelligence.** Every safety-critical decision must be
   reproducible given the same input. Stochastic components (RL, ML classifiers)
   are permitted only as *overlays* on a deterministic core, and only when
   wrapped in a deterministic shield.
2. **Measurable reliability before feature volume.** Every capability added to
   the pipeline must carry a reliability metric and a calibrated operating
   envelope. Capabilities without a reliability contract are not shipped.
3. **Graceful degradation before peak performance.** For every layer of
   sophistication, there must be a documented fallback path to a simpler, more
   conservative behavior. The system must be able to say "I don't know" and
   mean it.

These principles map onto a classical engineering gate model. Each stage has:

- an **objective** (what capability is added);
- a **minimum-viable artifact** (what actually ships);
- an **exit gate** (measurable conditions that must be met to proceed);
- a **rollback path** (if the gate is not met, what do we fall back to);
- a **downstream dependency** (what later stage this stage unlocks).

No stage begins before the prior stage's exit gate has been empirically
cleared on the project's own test and benchmarking infrastructure. This
stage-gated discipline mirrors the V&V (verification and validation)
lifecycle mandated for safety-critical airborne software by DO-178C
(Software Considerations in Airborne Systems and Equipment Certification)
and for functional safety more broadly by IEC 61508, and it is the reason
tier-one defense integrators take reliability research seriously in the
first place.

---

## 1. Target system architecture (end state)

```
                    ┌────────────────────────────────────────┐
                    │  Commander UI / Ground Control Station │
                    │  (JS / React, FastAPI gateway)         │
                    └────────────────┬───────────────────────┘
                                     │ gRPC / protobuf
                                     │ (Stage 4 contract)
                   ┌─────────────────▼──────────────────┐
                   │  ASSURANCE LAYER                   │
                   │  • SA health (TQI · complexity)    │
                   │  • Epistemic uncertainty gating    │
                   │    — Conformal prediction sets     │
                   │    — OOD detector (Mahalanobis)    │
                   │    — Aleatoric/epistemic split     │
                   │  → AutonomyMode: AUTO/ADVISE/DEFER │
                   └─────────────────┬──────────────────┘
                                     │
                   ┌─────────────────▼──────────────────┐
                   │  SAFETY SHIELD                     │
                   │  (deterministic, formally spec'd)  │
                   │  • no-track-no-fire                │
                   │  • min_Pk floor                    │
                   │  • reserve floor                   │
                   │  • geometry / fratricide           │
                   └─────────────────┬──────────────────┘
                                     │
               ┌─────────────────────▼────────────────────────┐
               │  SOLVER TIER (selected by AutonomyMode)      │
               │                                              │
               │  ┌──────────────────┐  ┌──────────────────┐  │
               │  │ Hungarian (LAP)  │  │ MILP (WTA)       │  │
               │  │ — conservative   │  │ — full-constraint│  │
               │  │   fallback       │  │   primary solver │  │
               │  └──────────────────┘  └─────────┬────────┘  │
               │                                  │           │
               │  ┌────────────────────────────────▼────────┐ │
               │  │ Distilled Decision Tree (Stage 3)       │ │
               │  │ — trained by Offline RL in sim,         │ │
               │  │   deployed as interpretable rules       │ │
               │  └──────────────────────────────────────────┘ │
               │                                              │
               │  ┌──────────────────────────────────────────┐│
               │  │ MCTS look-ahead (existing; Stage 1 keeps)││
               │  └──────────────────────────────────────────┘│
               └──────────────────────────────────────────────┘
                                     │
                   ┌─────────────────▼──────────────────┐
                   │  EXECUTION / SITREP                │
                   │  • Numeric fields engine-locked    │
                   │  • LLM rewrites prose only         │
                   │  • Offline template fallback       │
                   └────────────────────────────────────┘
```

**Rust/C++ performance-critical port is _not_ in the end-state diagram as a
first-class element.** It is a Stage 5 implementation detail invisible to the
architecture above. See §Stage 5 for why this sequencing matters.

---

## 2. Honest reality-check of the proposed upgrades

This section is part of the strategy because the single most valuable thing a
tier-one defense reviewer sees is evidence the designer rejects their own
ideas when evidence points that way.

| Proposed upgrade | Verdict | Stage |
|---|---|---|
| MILP with commercial solver (Gurobi/CPLEX) | Right idea, **wrong build-time dependency**. Build on `scipy.optimize.milp` (HiGHS) or OR-Tools (CBC); both are free, deterministic, widely audited. Add Gurobi as an **optional accelerator** behind a feature flag so deployments that have a license benefit, but the reference pipeline never depends on a proprietary solver. | **1** |
| Offline RL with decision-tree distillation | Right idea and well-precedented (VIPER, Bastani et al. 2018). The tree is what ships; the RL is research-internal. | **3** |
| Safe RL with shield | Right idea (Alshiekh et al. 2018). Shield is a **deterministic, formally specified layer** that wraps any policy — tree, RL, or MILP output. | **2–3** |
| Conformal prediction on classifier output | Right idea. Split conformal gives marginal coverage guarantees at O(30 LOC). Directly feeds the assurance layer. | **2** |
| OOD detection | Right idea. Mahalanobis on the calibrated feature distribution is interpretable and sufficient; deep-OOD methods are not yet justified by the threat model. | **2** |
| Aleatoric/epistemic uncertainty decomposition | Right idea. Deep ensemble (5 models) gives epistemic; existing `class_confidence` captures aleatoric. | **2** |
| C++/Rust core from day one | **Wrong sequencing.** The current Python core runs the whole TEWA pipeline in 80–250 ms for realistic fleet sizes (per project's own architecture doc). Rewriting before the algorithm surface is stable means rewriting twice. What _is_ cheap and valuable now is a **protobuf interface contract** (Stage 4) that makes a future port trivial. The port itself is Stage 5, **conditional on telemetry** showing the Python core as the system bottleneck. | **4 (contract), 5 (port)** |

---

## 3. Stage 0 — Repository hygiene & IP infrastructure

**Context.** The current repository on GitHub has a catastrophic line-ending
corruption: every `.py` and `.md` file has had its newlines collapsed to
spaces, causing `ast.parse()` to return zero top-level nodes across the
entire codebase. A fresh clone is not executable. This is almost certainly
a botched git merge with a CRLF normalization pre-hook. Before any new
capability is added, the repository must be restored to a state where a
fresh `git clone && pip install -e . && pytest` succeeds.

In parallel, the IP / attribution layer must be brought up to the standard
a tier-one integrator would pass through legal review without flagging.

### 3.1 Objective
Restore executable baseline; install professional attribution infrastructure.

### 3.2 Minimum-viable artifact
1. `scripts/repo_hygiene.py` — idempotent reformatter that (a) normalizes line
   endings, (b) collapses the jammed duplicated copyright headers into a single
   SPDX header, (c) runs on every `.py`, `.md`, `.toml`, `.yaml` file in the repo.
2. Clean `LICENSE` (OSI-standard MIT text, exactly).
3. `NOTICE` file carrying the attribution requirement in a form downstream
   users _actually_ reference (e.g. Apache-NOTICE pattern).
4. `CITATION.cff` — GitHub-rendered "Cite this repository" button with DOI
   placeholder for post-Zenodo archive.
5. `SECURITY.md` — responsible-disclosure contact and CVE process.
6. `CONTRIBUTING.md` — DCO sign-off, branch model, review requirements.
7. `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1.
8. `AUTHORS` — authoritative authorship list.
9. `SPDX-HEADER.txt` — canonical per-file header template.
10. `README.md` — rewritten, conflict-marker-free, professional tone.
11. `.github/workflows/ci.yml` — CI that runs `pytest` on push to main and
    on all PRs; failure gates all merges.
12. `pyproject.toml` — PEP 621 packaging so `pip install -e .` works.

### 3.3 Exit gate
- `git clone <fresh>` → `pip install -e .` → `pytest` — all green, in CI, on
  Python 3.10, 3.11, 3.12 on ubuntu-latest.
- `python -c "import ast, sys; [sys.exit(1) if not ast.parse(open(f).read()).body else None for f in src_files]"` returns 0.
- GitHub renders `CITATION.cff` as "Cite this repository".
- `scripts/repo_hygiene.py --check` exits 0.

### 3.4 Rollback
Stage 0 has no rollback — it is purely additive and restorative. If the
hygiene script misbehaves, the pre-merge commit is the fallback.

### 3.5 IP / attribution stance

The project uses **clean OSI-MIT** rather than a custom-modified MIT. Rationale:

- OSI-MIT already requires copyright notice preservation (clause 1). Custom
  "no alteration without written permission" clauses trigger legal review at
  every integrator and are of **doubtful enforceability** on top of MIT's
  otherwise permissive terms.
- Professional attribution protection is achieved through **three
  independently strong channels** rather than one fragile one:
  1. **License notice** (MIT clause 1, which every copy must preserve).
  2. **`NOTICE` file** with canonical attribution text that every derivative
     is expected to carry forward, per Apache-NOTICE convention.
  3. **Academic citeability** — `CITATION.cff` + Zenodo-archived release with
     a DOI. Citations in papers, technical reports, and conference
     submissions compound over time and are observable through Google Scholar.

This pattern is what Meta AI (FAIR), DeepMind, Google Research, and most
top-tier labs use for research code they want attributed. It is
indistinguishable from the professional standard while remaining fully MIT.

---

## 4. Stage 1 — Deterministic MILP TEWA core

### 4.1 Objective
Replace implicit assumptions in the Hungarian weapon-target assignment with
an explicit, deterministically-solved mixed-integer linear program that
supports, as **hard constraints**:

- multi-effector-per-target (coordinated fire, up to $K_t$ effectors);
- inventory capacity per `(base, effector)`;
- reserve floor on high-value effector types (not a soft penalty — hard);
- minimum-Pk threshold from commander's intent;
- geometric feasibility (range, min-engage-radius);
- timing feasibility (TTA − TTI ≥ safety margin).

### 4.2 Mathematical formulation

**Decision variable.** Binary $x_{bet} \in \{0, 1\}$ for each tuple
$(b, e, t)$ of base, effector class, threat, where $x_{bet} = 1$ iff one
unit of effector $e$ based at $b$ is assigned to intercept threat $t$.

**Per-assignment utility** (linear in $x$ — direct port of scoring from
`docs/ARCHITECTURE.md`):

$$u_{bet} = w_v \cdot p_{bet} \cdot V_t
          + w_m \cdot 15 \cdot \sigma(m_{bet} / 60)
          - 0.05 \cdot c_e$$

where $\sigma$ is the logistic sigmoid and $m_{bet}$ is the pre-computed
safety margin in seconds. All per-tuple terms are pre-computed, keeping the
objective strictly linear.

**Objective.** $\max \sum_{b,e,t} u_{bet} \cdot x_{bet}$, equivalently
$\min \sum -u_{bet} \cdot x_{bet}$ (scipy / HiGHS convention).

**Constraints.**

| # | Constraint | Form |
|---|---|---|
| C1 | At most $K_t$ effectors per threat | $\sum_{b,e} x_{bet} \le K_t \quad \forall t$ |
| C2 | Effector capacity per base | $\sum_t x_{bet} \le I_{be} - R_{be} \quad \forall b, e$ |
| C3 | Feasibility pruning | $x_{bet} = 0$ if any of: $\text{dist}(b,t) > \text{range}_e$, $\text{dist}(b,t) < \text{min\_engage}_e$, $m_{bet} < \text{margin}_{\min}$, $p_{bet} < p_{\min}$ |

Constraint C3 is handled at problem-build time by **not creating the
variable** rather than adding zero-equality constraints, which halves
solver work on dense scenarios.

**Solver.** `scipy.optimize.milp` with `HighsOptions` (deterministic,
bundled with SciPy ≥ 1.9, no license, deterministic given fixed input
order). Optional Gurobi adapter behind `BOREAL_SOLVER=gurobi` env var.

### 4.3 Parity contract with Hungarian

When the MILP is instantiated with $K_t = 1$, $I_{be}$ large, $R_{be} = 0$,
$p_{\min} = 0$, and the margin constraint satisfied for all $(b,e,t)$, the
MILP solves the same linear assignment problem as Hungarian. Under this
configuration the **objective value returned by MILP must equal that of
Hungarian within floating-point tolerance** (1e-6). Assignment identity
may differ when ties exist in the cost matrix — that is expected and
non-blocking.

### 4.4 Minimum-viable artifact
1. `src/core/models.py` — reference dataclasses (Threat, Base, Effector,
   CommandersIntent, Assignment, TEWAResult).
2. `src/core/hungarian_tewa.py` — clean reference implementation of the
   existing Hungarian solver.
3. `src/core/milp_tewa.py` — the MILP solver, scipy-HiGHS primary,
   Gurobi-adapter optional.
4. `tests/test_milp_parity.py` — parity suite (≥50 seeded scenarios).
5. `tests/test_milp_extensions.py` — MILP-only constraint tests
   (coordinated fire, hard capacity, hard Pk floor, reserve floor).
6. `tests/test_milp_determinism.py` — same input → same output across
   1000 invocations with identical seed.
7. `benchmarks/bench_milp.py` — latency distribution across fleet sizes
   $n \in \{5, 10, 20, 30, 50, 100\}$; reports p50, p95, p99.

### 4.5 Exit gate
- **Parity:** $\ge 1000$ seeded scenarios with the trivializing
  configuration, MILP objective equal to Hungarian to 1e-6 in 100 % of cases.
- **Extension correctness:** MILP-only constraint tests all pass.
- **Determinism:** 1000 repeated runs on identical input yield
  bit-identical result ordering (modulo ties; assignment set identical).
- **Latency:** p95 < 50 ms for $n_{\text{threats}} \le 30$,
  p95 < 200 ms for $n \le 100$, measured on CI baseline hardware
  (ubuntu-latest, default runner).
- **CI:** all Stage-1 tests run on every push.

### 4.6 Rollback
If MILP latency exceeds the envelope on real data, Hungarian remains the
default solver and MILP becomes an advisory parallel computation that
writes to SITREP as "MILP recommended alternative: …". The end-state
architecture explicitly supports both solvers in parallel — this is not a
true rollback, merely a role reassignment.

### 4.7 Downstream dependencies this unlocks
Stages 2 and 3 — the uncertainty gating and distilled policies — depend on
a deterministic solver to produce reproducible ground truth against which
uncertainty thresholds can be calibrated.

---

## 5. Stage 2 — Epistemic uncertainty layer

### 5.1 Objective
Give the system the ability to say "I don't know" with mathematical rigor,
not heuristics. Three independent signals feed `assurance.decide_autonomy`
as new DEFER triggers.

### 5.2 Sub-stages

**2a — Split conformal prediction over threat classification.**

Given a calibration set $\{(x_i, y_i)\}_{i=1}^n$ drawn from the same
distribution as deployment data, and a classifier producing softmax
scores $\hat{p}(y \mid x)$, the split-conformal prediction set at
miscoverage $\alpha$ is:

$$C_\alpha(x) = \{y : \hat{p}(y \mid x) \ge \hat{q}_\alpha\}$$

where $\hat{q}_\alpha$ is the empirical $\lfloor\alpha(n+1)\rfloor$-th
smallest calibration score. Under exchangeability,
$\mathbb{P}(y \in C_\alpha(x)) \ge 1 - \alpha$ marginally.

**Decision rule:** if $|C_\alpha(x)| > 1$ for any classified threat,
route to ADVISE; if $|C_\alpha(x)| \ge 3$ or includes a civilian class,
route to DEFER.

**2b — Out-of-distribution detection.**

Fit a single Gaussian $\mathcal{N}(\mu, \Sigma)$ to the calibration set's
track feature vectors (kinematic profile, sensor-fusion agreement,
classification softmax entropy, track age, radar cross-section estimate).
Test statistic is Mahalanobis distance:

$$D^2(x) = (x - \mu)^T \Sigma^{-1} (x - \mu)$$

Under the null of in-distribution, $D^2 \sim \chi^2_d$. Threshold at the
$0.01$-tail of $\chi^2_d$ gives a calibrated 1 % false-OOD rate.

**Decision rule:** OOD-flagged track → revert the threat from the MILP
input to a conservative Hungarian-only treatment; surface alert to
commander; if $\ge 2$ tracks OOD, DEFER autonomy entirely.

**2c — Aleatoric / epistemic decomposition.**

Train a deep ensemble of 5 classifiers on bootstrap-resampled training
folds. For an input $x$, compute:

- **Predictive entropy** $H[\bar{p}(y \mid x)]$ (total uncertainty).
- **Expected entropy** $\mathbb{E}_{i \sim 1..5}[H[p_i(y \mid x)]]$
  (aleatoric — irreducible, sensor-noise-like).
- **Mutual information**
  $I = H[\bar{p}] - \mathbb{E}_i[H[p_i]]$ (epistemic — reducible,
  "models disagree with each other").

**Decision rule:** if $I / H[\bar{p}] > 0.4$ (epistemic dominates), freeze
autonomous execution and surface "models disagree — unfamiliar pattern"
to commander.

### 5.3 Minimum-viable artifact
- `src/core/conformal.py` — split-conformal wrapper around the existing
  classifier, with fit/predict_set/coverage methods.
- `src/core/ood.py` — Mahalanobis OOD detector.
- `src/core/epistemic.py` — ensemble training + MI computation.
- `src/core/assurance.py` patched — three new DEFER triggers with
  per-signal reasons in `AssuranceReport.reasons`.
- Calibration scenarios in `data/calibration/` (held out from training).
- Novel-tactic synthetic scenarios in `data/ood_validation/`.

### 5.4 Exit gate
- **Conformal:** empirical coverage on held-out calibration = $1 - \alpha \pm 2$
  percentage points for $\alpha \in \{0.05, 0.10\}$ across 500 seeded
  scenarios.
- **OOD:** false-OOD rate on in-distribution held-out $\le 1.5$ %;
  true-OOD rate on synthetic novel-tactic scenarios $\ge 90$ %.
- **Epistemic:** on synthetic novel tactics the epistemic fraction
  $I / H[\bar{p}]$ exceeds 0.4 in $\ge 85$ % of cases; on in-distribution
  held-out it exceeds 0.4 in $\le 10$ % of cases.
- **Integration:** synthetic composite scenarios (mix of nominal and
  novel) produce AUTO / ADVISE / DEFER at the rates documented in the
  calibration plan with $\chi^2$ goodness-of-fit $p > 0.1$.

### 5.5 Rollback
Each of 2a/2b/2c is independently gated. If any fails calibration, it is
disabled at runtime (env flag) while the others ship. The Hungarian
fallback and the Stage-1 MILP both remain operational without any
Stage-2 component.

---

## 6. Stage 3 — Offline RL with decision-tree distillation + safety shield

### 6.1 Objective
Discover tactics the hand-designed scoring cannot express, without ever
deploying black-box RL in a live environment. The deployed artifact is a
**decision tree** distilled from the RL policy and wrapped in a
**deterministic shield**.

### 6.2 Method

**Offline RL training.** Train a conservative Q-learning agent (CQL or
BCQ) on a replay buffer generated by:

- the Hungarian baseline on nominal scenarios (low-variance demonstrations);
- the MILP solver on hard-constraint scenarios (correctness-anchored);
- the existing red-team simulation (adversarial coverage).

Conservative offline RL is specifically designed to avoid extrapolation
beyond the replay distribution — the failure mode that makes online RL
unsafe in defense contexts.

**Distillation via VIPER.** Given trained policy $\pi^*$, iteratively
extract a decision tree $\hat{\pi}$ using DAgger-style aggregation:

```
D ← {}
for k = 1..K:
    roll out current tree π̂_k in sim; collect states
    query π*(s) on every collected state → label
    D ← D ∪ {(s, π*(s))}
    fit shallow tree (depth ≤ 6) on D → π̂_{k+1}
return π̂_K
```

The shallow-depth constraint makes the resulting policy
**inspectable** — it renders to a readable flowchart and can be
walked-through by a certification reviewer.

**Safety shield.** Every action proposed by any policy (Hungarian,
MILP, tree, or any future RL) is filtered through a deterministic
shield with formally-specified veto predicates:

- No engagement on a track with $\text{classification confidence} < \tau_{\text{fire}}$.
- No engagement with predicted $p_k < p_{\min}$ from intent.
- No engagement that would breach the reserve floor.
- No engagement within a fratricide cone of a friendly track.
- No engagement on a track within a protected civilian-airspace volume
  without explicit human authorization.

Each predicate is pure-Python, $O(1)$ per check, and carries a
reference to the specification document clause it enforces.

### 6.3 Minimum-viable artifact
- `src/core/offline_rl.py` — CQL training on the replay buffer.
- `src/core/viper.py` — DAgger-style tree distillation.
- `src/core/shield.py` — deterministic shield with formal spec in docstring.
- `tests/test_shield.py` — 10 000 adversarial rollouts; shield blocks
  100 % of spec-violating actions.
- `reports/tree_flowchart.svg` — rendered distilled policy for inspection.

### 6.4 Exit gate
- **Shield:** 100 % block rate on the 10 k adversarial suite. Zero false
  vetoes on 10 k nominal scenarios. (Both rates measured; 100 % veto on
  bad, $< 0.1$ % veto on good.)
- **Tree quality:** distilled tree depth $\le 6$; reward within 3 % of
  RL teacher on held-out sim scenarios; matches or beats Hungarian on
  the same scenarios.
- **Interpretability:** every leaf of the tree maps to a
  human-readable rule ("if threat_type = hypersonic AND reserve_pct
  $< 0.3$ AND TQI $> 0.7$ → use fighter-bomber engagement").
- **Red-team:** tree + shield pipeline passes the existing
  `tests/test_red_team.py` suite at $\ge 95$ % success.

### 6.5 Rollback
The tree is an **overlay**, not a replacement. MILP remains the
default solver. The tree's role is to reorder ties and handle
multi-wave situations the static scoring doesn't capture. If the
tree fails any exit criterion, it is simply not loaded at startup
and the MILP continues to drive decisions.

---

## 7. Stage 4 — Protobuf / gRPC interface contract

### 7.1 Objective
Decouple the core decision engine from its transport (currently
FastAPI + WebSocket) so that a future language-agnostic port, alternate
deployment target, or simulator integration can consume the same
interface without touching business logic.

### 7.2 Method
Define a protobuf schema for the core contract:

- `TEWARequest`: threats, bases, effectors, commander's intent, track
  qualities, blind spots, assurance context.
- `TEWAResponse`: assurance report, forecast, COA list with rationales,
  SITREP, engine trace.

Core implementation stays in Python. FastAPI becomes a **gateway** that
transcodes HTTP/JSON ↔ protobuf and delegates to the core. In-process
gRPC keeps latency at the current level; cross-process gRPC becomes
opt-in for distributed deployments.

### 7.3 Minimum-viable artifact
- `proto/nimbus_v1.proto` — contract, semantically versioned.
- `src/core/grpc_server.py` — in-process gRPC server exposing the core.
- `src/core/grpc_client.py` — client library for external consumers.
- FastAPI handlers rewritten to call gRPC client (same process by default).

### 7.4 Exit gate
- All existing end-to-end tests green against the new contract.
- Schema buf-lint clean; no breaking changes between commits after the
  first tagged contract release.
- Documentation of the contract in `proto/README.md` with `.pyi` type
  stubs auto-generated.

### 7.5 Rollback
None needed — the direct-call Python API is preserved as
`src/core/direct_api.py` for simulation and offline analysis. The
protobuf layer is strictly additive.

---

## 8. Stage 5 — Rust performance port (conditional)

### 8.1 Gating condition
Stage 5 begins only if **telemetry from Stage 4 shows the Python core
is the system bottleneck on realistic workload**, specifically:

- p95 end-to-end latency $> 500$ ms, **and**
- profiling attributes $> 60$ % of that latency to `milp_tewa` or `mcts`
  inner loops, **and**
- the operational requirement (battlefield deployment, on-edge Gripen
  integration, or similar) actually requires lower latency than Python
  can deliver.

If any of these conditions fails, Stage 5 does not begin. Python stays.
This discipline exists because a Rust port is a 4–8 week engineering
effort that loses optionality on algorithm iteration.

### 8.2 Objective
Port the two inner-loop hot spots — the MILP problem build and the
MCTS rollouts — to Rust, exposed via PyO3 bindings. Everything else
stays in Python.

### 8.3 Method
- Rust implementation of the MILP builder (solver calls remain HiGHS
  via its C API or Gurobi via its C API).
- Rust implementation of the MCTS tree search.
- PyO3 bindings. Cargo workspace under `rust/`.
- Python reference implementation preserved, used for regression.

### 8.4 Exit gate
- **Bit-exact regression:** Rust core matches Python core on 10 000
  seeded scenarios. Assignment identity (modulo ties) and objective
  value exact.
- **Performance:** $\ge 10\times$ p95 speedup on the bottleneck workload.
- **Memory safety:** `cargo miri` clean; `cargo clippy -- -D warnings` clean.
- **CI:** Rust workspace builds and tests on Linux, macOS, Windows.

### 8.5 Rollback
Python reference implementation is preserved in perpetuity. A runtime
flag `BOREAL_USE_RUST_CORE=0` disables the Rust path. The architecture
is Python-reference-authoritative; the Rust core is an optimization, not
a redesign.

---

## 9. Cross-cutting requirements

### 9.1 Reproducibility
Every stage produces a `VALIDATION_REPORT.md` committed alongside the
code, containing: the seeds used, the hardware profile, the git SHA, the
exact command line, and the exit-gate metrics. A later reviewer must be
able to re-run the validation bit-for-bit.

### 9.2 Calibration discipline
Every threshold in the codebase is either (a) derived from an equation
documented in the architecture, or (b) calibrated on held-out data with
the calibration procedure documented in `docs/CALIBRATION.md`. No magic
numbers without provenance.

### 9.3 Single-source-of-truth principle
The `docs/ARCHITECTURE.md` scoring formula is the ground truth. Any
divergence between it and the code is a defect in the code, not the
doc. When the math changes, the doc changes first, then the code, then
the tests.

### 9.4 Traceability
Every test names the requirement (stage, section, predicate) it verifies.
Every commit message references the stage number it progresses.

### 9.5 Open-science posture
All simulation scenarios and their generators are public (MIT). All
calibration data is public. All results and VALIDATION_REPORT artifacts
are public. Reproducibility by an independent third party is the goal.

---

## 10. Timeline (indicative)

| Stage | Work | Calendar weeks (contiguous, solo) |
|---|---|---|
| 0 | Repo hygiene, IP layer | 0.5 |
| 1 | MILP TEWA + parity tests | 1.5 |
| 2a | Conformal prediction | 0.5 |
| 2b | OOD detector | 0.5 |
| 2c | Aleatoric/epistemic split | 1.0 |
| 3 | Offline RL + VIPER + shield | 2.0 |
| 4 | Protobuf interface contract | 1.0 |
| 5 | Rust port (**conditional**) | 4–8 |

Non-conditional track totals 7 calendar weeks of contiguous solo work.
With buffer for validation iterations and doc-writing, budget 10 weeks.

---

## 11. What "success" looks like to Saab

A tier-one defense integrator evaluates a research codebase along five
dimensions. Each dimension has a concrete observable.

| Dimension | Observable | Delivered by |
|---|---|---|
| Determinism | Same input → same output, in CI, over 1000 runs | Stage 1 (MILP determinism gate) |
| Measurable reliability | Conformal coverage $\ge 1 - \alpha$ empirically verified | Stage 2a |
| Graceful degradation | Composite "novel + nominal" scenarios produce correct AUTO/ADVISE/DEFER distribution | Stage 2 integration gate |
| Explainability | Every deployed decision renders to human-readable rationale | Stages 3 (tree) + existing rationale |
| Productionability | Language-agnostic contract; deployable offline; no proprietary build deps | Stage 0 (clean MIT, no Gurobi required) + Stage 4 (protobuf) |

When all five observables are green in CI on the public repository, the
project is pitchable as a tier-one candidate.

---

## 12. Document history

- **v1.0** (2026-04-21) — Initial stage-gated strategy.

*Copyright (c) 2026 Maria Westrin. Licensed under the MIT License
(see `LICENSE`). Attribution preserved via `NOTICE` and `CITATION.cff`.*
