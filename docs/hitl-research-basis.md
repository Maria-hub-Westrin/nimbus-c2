<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Research basis — Human-in-the-loop and epistemic autonomy

Nimbus-C2 is not an invention from first principles. The system implements a small, intentional synthesis of established research lines from human factors, autonomy, explainable AI, and uncertainty quantification. This document records the foundations so reviewers can verify the provenance of each design choice.

## 1. The autonomy ladder (chi-3 / chi-2 / chi-1)

The three-level ladder (AUTONOMOUS -> ADVISE -> DEFER) is a condensation of the ten-level scale introduced by **Parasuraman, Sheridan, and Wickens (2000)** in *"A model for types and levels of human interaction with automation"* (IEEE Transactions on Systems, Man and Cybernetics - Part A, 30(3), 286-297). Nimbus-C2 collapses their ten levels into three operational bands matched to a reliability metric (rho-SA), keeping the key claim intact: **authority should track capability, not be fixed by policy**.

Earlier work by **Sheridan and Verplank (1978)** (*"Human and computer control of undersea teleoperators"*, MIT Man-Machine Systems Laboratory) originated the idea of supervisory control as a sliding scale.

## 2. Situational awareness as a measurable quantity

The term **rho-SA** is grounded in **Endsley (1995)**, *"Toward a theory of situation awareness in dynamic systems"* (Human Factors, 37(1), 32-64). Endsley''s three levels (perception, comprehension, projection) map onto the three SA components tracked in the console: sensor integrity (perception), fusion quality (comprehension), and wave forecast (projection).

Measurement methodologies - SAGAT, SPAM - come from the same literature and are what a Stage 3 validation would use (see validation-roadmap.md).

## 3. Meaningful human control

The phrase "authority remains with the operator" is not rhetorical; it references the *meaningful human control* framework of **Santoni de Sio and van den Hoven (2018)**, *"Meaningful human control over autonomous systems: a philosophical account"* (Frontiers in Robotics and AI, 5:15). Their twin conditions - *tracking* (the system must track the reasons humans have for action) and *tracing* (the system must be traceable to a competent human agent) - are the reason Nimbus-C2 keeps a deterministic, auditable COA engine rather than an end-to-end learned policy.

This also matches **Article 14 of the EU AI Act**, which requires human oversight proportional to risk for high-risk AI systems.

## 4. Explainability without decision authority

The operator advisory dialog follows the separation principle laid out by **Miller (2019)**, *"Explanation in artificial intelligence: Insights from the social sciences"* (Artificial Intelligence, 267, 1-38): explanations are communicative acts aimed at understanding, not at decision-making. Conflating the two causes *automation bias* and *over-trust*.

The DARPA **XAI program** (Gunning et al., 2019, *"XAI - Explainable artificial intelligence"*, Science Robotics 4(37)) is the operational precedent for separating the "decider" from the "explainer" in defense contexts.

## 5. Epistemic humility - knowing what you do not know

The reliability gating is fundamentally an **abstention** mechanism, placing Nimbus-C2 in the selective-prediction literature:

- **Geifman and El-Yaniv (2017)**, *"Selective classification for deep neural networks"* (NeurIPS 2017) - formalized when a classifier should abstain rather than answer.
- **Huellermeier and Waegeman (2021)**, *"Aleatoric and epistemic uncertainty in machine learning"* (Machine Learning, 110, 457-506) - distinguishes irreducible noise (aleatoric) from ignorance (epistemic), which is the distinction behind rho-SA.

The system''s live Epistemic State panel (Known / Known-unknowns / Unknown-unknowns) is a direct visualization of this taxonomy, drawing informally on the **Rumsfeld taxonomy** but rooted in the **Dempster-Shafer theory of evidence** (Shafer 1976) - where belief and plausibility are tracked separately.

## 6. Trust calibration as a design target

The goal is *calibrated* trust, not maximum trust. The classical reference is **Lee and See (2004)**, *"Trust in automation: designing for appropriate reliance"* (Human Factors, 46(1), 50-80). An operator who over-trusts an automated system is dangerous; an operator who under-trusts is inefficient. Nimbus-C2''s downshift behaviour (ADVISE/DEFER) is designed to keep trust appropriate to current reliability, not globally inflated.

## 7. What this document does not claim

Implementing a principle is not the same as validating it. Nimbus-C2 at Stage 2b **implements** the design choices above; it has **not** yet been empirically validated. The roadmap for empirical validation - operator studies, threshold calibration, mode-confusion testing, explainability user studies - is in validation-roadmap.md.

This document is deliberately honest about that gap. The strongest claim a Stage 2b prototype can make is *"design is consistent with the literature."* Any stronger claim would misrepresent the maturity of the system.
