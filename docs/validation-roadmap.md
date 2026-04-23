<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Validation roadmap - from Stage 2b prototype to empirically grounded system

## Purpose

This document specifies what empirical validation Nimbus-C2 would require to claim more than *"design-consistent with the literature."* It is a deliberate statement of **what the system does not yet know about itself**, in the same spirit as the epistemic-state panel in the console.

Stage 2b (current) delivers a working prototype whose behaviour matches the principles in hitl-research-basis.md. Stage 3 would close the gap between *implementation* and *validation*.

## Known gaps, explicitly

### Gap 1 - Thresholds are design assumptions, not data
rho >= 0.80 -> AUTONOMOUS, 0.40 <= rho < 0.80 -> ADVISE, rho < 0.40 -> DEFER. These cutoffs are reasonable but **not derived from operator performance data**. They need to be calibrated empirically against where actual operator performance degrades under reduced SA.

### Gap 2 - No operator performance data
The system''s behaviour has been developed without measurement of the humans it is supposed to support. Reaction time, decision accuracy, trust calibration, workload (NASA-TLX), and situation-awareness retention (SAGAT, SPAM) are all unmeasured.

### Gap 3 - Automation-bias and mode-confusion risks are unquantified
The literature (Parasuraman & Manzey 2010; Sarter & Woods 1995) documents that mode-transition interfaces can *cause* error rather than prevent it. Nimbus-C2''s three-mode ladder has not been stress-tested for whether operators correctly perceive mode transitions.

### Gap 4 - The advisory LLM is unevaluated
Plausibility is not correctness. The operator advisory dialog has not been tested for whether its explanations improve decisions, leave them unchanged, or actively mislead (a known XAI failure mode; see Bansal et al. 2021, *"Does the whole exceed its parts?"*).

### Gap 5 - Failure modes are unobserved
The system is designed to degrade gracefully - rho drops, authority returns to operator - but no systematic failure-injection testing has confirmed this in adversarial conditions (jamming, spoofing, sensor-drift, contradictory inputs).

## Proposed Stage 3 studies

### Study A - Threshold calibration against operator performance
**Question:** At what rho-SA does operator decision accuracy actually degrade?
**Method:** Present operators with simulated tactical pictures across a grid of reliability levels (rho in [0.2, 1.0] in 0.1 steps). Measure decision accuracy and reaction time.
**Outcome:** Data-driven cutoffs replacing the current 0.40 / 0.80 design assumptions.
**Reference:** Endsley & Kaber (1999), *"Level of automation effects on performance, situation awareness and workload in a dynamic control task"*.

### Study B - Mode-transition comprehension
**Question:** Do operators correctly perceive and act on AUTONOMOUS -> ADVISE -> DEFER transitions?
**Method:** Within-subjects design, counterbalanced scenarios with mode transitions. Measure transition-detection latency and post-transition compliance errors.
**Outcome:** Validated UI conventions for mode transitions (or a redesign if detection is poor).
**Reference:** Sarter, Woods & Billings (1997), *"Automation surprises"*.

### Study C - Advisory dialog utility
**Question:** Does the LLM explainability layer improve decision quality, or only subjective confidence?
**Method:** Three-arm comparison: (i) no explanations, (ii) template explanations, (iii) LLM advisory. Measure both objective accuracy and subjective trust. Include forced-wrong-advice trials to measure *calibrated* trust.
**Outcome:** Empirical evidence for or against including the LLM layer in a production system.
**Reference:** Bansal et al. (2021), *"Does the whole exceed its parts? The effect of AI explanations on complementary team performance"*.

### Study D - Trust calibration over time
**Question:** Do operators develop calibrated trust - trusting the system more when it is reliable and less when it is not - or do they settle into fixed global trust?
**Method:** Longitudinal study across multiple sessions, with varied reliability. Measure trust (Jian-Bisantz-Drury scale) against actual system accuracy.
**Outcome:** Validation that rho-SA-based authority transfer actually produces calibrated trust, not disuse or over-trust.
**Reference:** Lee & See (2004), *"Trust in automation"*.

### Study E - Adversarial degradation
**Question:** Does the system maintain safe behaviour under active deception (spoofing, jamming, sensor-contradiction)?
**Method:** Red-team adversarial testing with injected faults. Measure whether the system correctly downshifts authority or whether it silently fails.
**Outcome:** Validated degradation envelope.
**Reference:** Hendrycks et al. (2022), *"Unsolved problems in ML safety"*.

## Deliverables by stage

| Stage | Deliverable | Required evidence |
|---|---|---|
| 2b (current) | Working prototype with documented research basis | Passes CI, demonstrates principles in simulation |
| 3a | Threshold calibration | Study A complete, cutoffs data-driven |
| 3b | Mode-transition validation | Study B complete, >= 85% transition-detection |
| 3c | Explainability validation | Study C complete, decision-quality delta measured |
| 3d | Trust calibration | Study D complete, longitudinal calibration demonstrated |
| 3e | Adversarial robustness | Study E complete, degradation envelope published |
| 4 | Deployment-candidate | All of Stage 3 + independent replication |

## Honest statement of current maturity

Nimbus-C2 is at **TRL 3-4** in the NASA/DoD Technology Readiness scale - experimental proof-of-concept validated in a relevant laboratory environment. The research basis is solid; the empirical validation is absent. Progression to TRL 5 and above requires the studies above.

No claim of deployment-readiness is made, should be made, or would be defensible at this stage.

---

*For collaborators interested in running any of these studies, contact the maintainer. The reliability-aware framework is designed to accept calibration data as an input - the system is meant to learn the thresholds of the humans it serves.*
