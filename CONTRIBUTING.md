<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->

# Contributing to Nimbus-C2

Thank you for your interest in contributing. This project follows the
stage-gated research and engineering plan documented in `STRATEGY.md`.
Contributions that move the project forward on its current stage, or
that harden the existing stages against regressions, are welcome.

## Philosophy

Three rules, in order of priority:

1. **Determinism is not optional.** Code that introduces randomness
   must do so via explicit, test-seeded RNGs, and must document why
   the randomness exists and where its downstream impact is bounded.
2. **Every capability carries a reliability metric.** A pull request
   that adds a capability must also add a test that measures its
   operating envelope on held-out data.
3. **Graceful degradation, not peak performance.** Any path that can
   fail must have a documented fallback. Tests must exercise both the
   primary path and the fallback.

## What's in scope

- Bug fixes, test additions, and documentation improvements for the
  current stage (see `STRATEGY.md` for the active stage).
- Forward-compatible API additions that do not break the existing
  stage exit gates.
- New calibration scenarios in `data/` that stress the current
  uncertainty thresholds.

## What's out of scope

- Jumping ahead to later stages before the current stage's exit
  gate has cleared.
- Additions that introduce proprietary build-time dependencies
  (Gurobi, CPLEX, CUDA-specific kernels). These are welcome as
  *optional* accelerators behind feature flags.
- Binary assets larger than 500 KB without justification.
- Changes that touch the safety shield specification without a
  formal review entry in `docs/SHIELD_REVIEW_LOG.md`.

## Developer certificate of origin (DCO)

All commits must be signed off with the Developer Certificate of
Origin (DCO), per the Linux kernel convention. Append this line to
every commit message:

    Signed-off-by: Your Name <your.email@example.com>

Using `git commit -s` adds this automatically once `user.name` and
`user.email` are configured. The DCO is a lightweight, well-understood
alternative to a Contributor Licence Agreement and asserts that the
contributor has the right to submit their work under the project's
MIT licence.

## Branching and review

- `main` is the always-green branch. Direct pushes are not permitted.
- Feature branches are named `stageN/<short-descriptor>`, e.g.
  `stage2/conformal-coverage-tightening`.
- Pull requests require (a) all CI checks green, (b) all existing
  stage exit-gate tests still green, (c) a description referencing
  the section of `STRATEGY.md` the change advances.
- Rebase, don't merge. Linear history is part of the reviewability
  contract.

## Local development

```bash
git clone <fork>
cd nimbus-c2
pip install -e .[dev]
pytest
python scripts/repo_hygiene.py --check
```

Before opening a pull request:

```bash
python scripts/repo_hygiene.py --write   # normalise headers, line endings
pytest                                    # all green
python benchmarks/bench_milp.py           # stage-1 gate stays green
```

## Code style

- Python: PEP 8. Lines ≤ 100 columns. Type annotations on every
  public function. `mypy --strict` clean on `src/core/`.
- Commit messages: imperative present tense, reference stage and
  section in `STRATEGY.md` where relevant.
- Docstrings: numpydoc format on every public API.

## Review turnaround

Maintainer review aims for initial response within five business
days. Security-related contributions are prioritised (see
`SECURITY.md`).

## Citation

If your contribution is used in a publication, cite the project per
`CITATION.cff` and — where appropriate — mention your own contribution
in the paper's acknowledgements. Listing yourself in `AUTHORS` is
expected after a first merged contribution.
