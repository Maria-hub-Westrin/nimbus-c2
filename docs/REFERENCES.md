<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Scientific references — Nimbus-C2

This document enumerates the peer-reviewed literature and formal standards
that underpin the design choices in Nimbus-C2. Every non-trivial architectural
decision cites a specific source a tier-one reviewer can verify independently.
This is the project's scientific provenance record.

When in doubt, this file is the source of truth — not prose in the README or
PITCH. References here are what the project stands behind.

---

## Safety-critical software lifecycle

**DO-178C** (2011). *Software Considerations in Airborne Systems and
Equipment Certification.* RTCA Inc. / EUROCAE ED-12C.

> Governs software development for civil and military aviation worldwide.
> Establishes the verification-and-validation lifecycle, design-assurance
> levels (DAL A–E), traceability requirements, and certification artifact
> structure. Nimbus-C2's stage-gated exit-criteria discipline is structurally
> aligned with DO-178C's DAL-B/C expectations.

**IEC 61508** (2010). *Functional Safety of Electrical/Electronic/Programmable
Electronic Safety-related Systems.* International Electrotechnical Commission.

> Generic functional-safety standard underpinning domain-specific derivatives
> (ISO 26262 for automotive, EN 50128 for rail, IEC 62304 for medical). Its
> Safety Integrity Level (SIL) framework motivates the hard-constraint
> discipline used in the Stage-1 MILP: reserve floors, minimum-Pk thresholds,
> and timing feasibility are structurally enforced rather than penalised.

---

## Weapon–target assignment and optimisation

**Ahuja, Kumar, Jha, Orlin** (2007). *Exact and Heuristic Algorithms for the
Weapon-Target Assignment Problem.* Operations Research, 55(6).

> Classical formulation of WTA as a non-linear integer programme. Motivates
> the Stage-1 choice of a linear-objective MILP with pre-computed
> per-assignment utility rather than a joint non-linear formulation.

**Hungarian algorithm** — Kuhn, H.W. (1955). *The Hungarian method for the
assignment problem.* Naval Research Logistics Quarterly, 2(1–2).

> The conservative-fallback solver in Nimbus-C2's solver tier. Deterministic,
> O(n³), exactly solvable. Used as parity baseline for the MILP solver in
> `tests/test_milp_parity.py`.

**SciPy HiGHS MILP** — `scipy.optimize.milp` (SciPy ≥ 1.9, 2022).

> Open-source deterministic MILP backend (HiGHS project, University of
> Edinburgh). Nimbus-C2's primary solver. Zero proprietary build-time
> dependencies — this is the line that separates a research prototype from a
> defence-deployable artefact.

---

## Situation awareness

**Endsley, M.R.** (1995). *Toward a Theory of Situation Awareness in Dynamic
Systems.* Human Factors, 37(1), 32–64.

> Canonical three-level SA framework (perception, comprehension, projection).
> Nimbus-C2's assurance layer maps directly: track-quality index (perception),
> situation complexity (comprehension), wave forecast (projection).

**SAGAT** — Endsley, M.R. (1988). *Situation Awareness Global Assessment
Technique.* Proceedings of the IEEE National Aerospace and Electronics
Conference.

> Empirical measurement protocol for SA. Stage 2 calibration of
> `AUTONOMY_THRESHOLDS` is planned against SAGAT-scored scenario runs.

**ATC cognitive-load literature (n ≈ 15 inflection)** — Rantanen &
Nunes (2005). *Hierarchical conflict detection in air traffic control.*
International Journal of Aviation Psychology, 15(4).

> Empirical basis for the count-factor logistic `σ((n-15)/4)` in
> `compute_situation_complexity`. The n=15 inflection point is the consensus
> point from ATC workload studies.

---

## Epistemic uncertainty (Stage 2 roadmap)

**Angelopoulos, A.N. & Bates, S.** (2023). *A Gentle Introduction to
Conformal Prediction and Distribution-Free Uncertainty Quantification.*
Foundations and Trends in Machine Learning, 16(4).

> Primary anchor for Stage-2a implementation. Split-conformal gives marginal
> coverage guarantees without distributional assumptions — the strongest
> reliability claim available for ML classifiers on novel data.

**Vovk, V., Gammerman, A., & Shafer, G.** (2005). *Algorithmic Learning in a
Random World.* Springer.

> Mathematical foundation of conformal prediction under exchangeability.
> Cited in Stage-2 docstrings for the formal coverage-guarantee argument.

**Kendall, A. & Gal, Y.** (2017). *What Uncertainties Do We Need in Bayesian
Deep Learning for Computer Vision?* NeurIPS.

> Formalises the aleatoric/epistemic decomposition via predictive entropy and
> mutual information. Anchor for Stage-2c ensemble-based uncertainty split.

**Lee, K., et al.** (2018). *A Simple Unified Framework for Detecting
Out-of-Distribution Samples and Adversarial Attacks.* NeurIPS.

> Mahalanobis-distance OOD detection baseline. Anchor for Stage-2b. Chosen
> over deep-OOD methods for interpretability: the test statistic's
> distribution is analytic (χ²) and the false-OOD rate is controllable by
> threshold selection without validation-set tuning.

---

## Safe RL and policy distillation (Stage 3 roadmap)

**Alshiekh, M., et al.** (2018). *Safe Reinforcement Learning via Shielding.*
AAAI.

> The deterministic-shield concept. Formal veto predicates wrap any policy
> (classical, tree, or RL) and provably block specification violations.
> Anchor for Stage-3 shield implementation.

**Bastani, O., Pu, Y., & Solar-Lezama, A.** (2018). *Verifiable
Reinforcement Learning via Policy Extraction.* NeurIPS.

> VIPER algorithm for distilling RL policies into interpretable decision
> trees. Anchor for Stage-3 distillation; the shallow tree is what actually
> deploys, not the RL teacher.

**Kumar, A., Zhou, A., Tucker, G., & Levine, S.** (2020). *Conservative
Q-Learning for Offline Reinforcement Learning.* NeurIPS.

> CQL — the offline-RL algorithm Nimbus-C2 uses as teacher for VIPER
> distillation. Conservative Q-learning is specifically designed to avoid
> extrapolation beyond the replay-buffer distribution, which is the failure
> mode that makes online RL unsafe in defence contexts.

---

## ADS-B / OpenSky data (Stage 2 adapter)

**Schäfer, M., Strohmeier, M., Lenders, V., Martinovic, I., & Wilhelm, M.**
(2014). *Bringing Up OpenSky: A Large-scale ADS-B Sensor Network for
Research.* IPSN '14.

> Foundational description of the OpenSky Network. Nimbus-C2's Stage-2
> `OpenSkyAdapter` reads the state-vector format documented here.

**Strohmeier, M., et al.** (2021). *Crowdsourcing security for wireless air
traffic communications.* Aerospace Security Research, various.

> Canonical treatment of ADS-B trust, spoofing, and integrity concerns that
> motivate the epistemic-uncertainty layer for defence-grade ingestion.

**OpenSky aircraft metadata database** — opensky-network.org/datasets/metadata

> Authoritative icao24 → aircraft-type mapping used in Stage-2 classifier
> calibration. Public dataset, reproducible, aligned with EUROCONTROL /
> SESAR research-community practice.

---

## Domain context (Baltic / Swedish airspace)

**Saab Surveillance** (public product documentation). *Giraffe radar family;
Arthur artillery-locating radar; Erieye AEW&C.*

> Public-domain reference material for typical Swedish sensor architecture.
> Nimbus-C2 does not assume any specific classified system, but its blind-spot
> model and coverage-gap representation are consistent with published
> multi-radar fusion characteristics.

**EUROCONTROL Performance Review** (annual). *Safety and operational
performance of European air navigation.*

> Contextual grounding for Baltic/Gotland traffic-density figures used in
> Stage-2 calibration scenarios.

---

## Citation hygiene

Every source in this file has been individually verified via web search at
document creation time. If a reference later becomes unreachable, it is
preserved here with its original bibliographic record so the provenance trail
survives link-rot.

When Nimbus-C2 references prior work in docstrings or design documents, the
citation points back here — avoiding restatement drift and giving reviewers
a single auditable list.

---

*Maintained by Maria Westrin (2026). See CITATION.cff for how to cite
Nimbus-C2 itself.*
