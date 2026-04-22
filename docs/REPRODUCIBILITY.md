<!--
SPDX-FileCopyrightText: 2026 Maria Westrin
SPDX-License-Identifier: MIT
-->
# Reproducibility Guide

This document explains how to reproduce any experimental result in Nimbus-C2.

## The reproducibility contract

Every experiment result in `results/` contains:

- A full copy of the `RunConfig` that produced it
- The git commit SHA of the code at run time
- A flag indicating whether the working tree was dirty
- The Python version used
- A timestamp

Together, these five pieces of information are **sufficient** to reproduce
the experiment bit-exactly on another machine, provided:

1. The git SHA exists in the repository (clone and checkout)
2. The working tree was NOT dirty (flag is `false`) at original run time
3. Python version is identical or in the same patch series (`3.12.x`)
4. All dependencies in `pyproject.toml` are installed

If `git_is_dirty: true` in a result, the result is provenance-compromised:
it depends on uncommitted edits that are not recoverable from git alone.
Treat such results as advisory, not authoritative.

## How to reproduce a specific result

Given `results/stage2b_conformal_validation_20260422T133045Z_7eceaa7.json`:

```bash
# 1. Extract the commit SHA
git_sha=$(jq -r .git_sha < results/stage2b_conformal_validation_20260422T133045Z_7eceaa7.json)

# 2. Check out that commit
git checkout $git_sha

# 3. Install the exact environment
python -m pip install -e ".[dev]"

# 4. Rerun with the exact same config. The stored RunConfig matches the
#    version-controlled config, so you can point at that:
python run_validation.py --config configs/stage2b_conformal_validation.yaml

# 5. Compare: results should match byte-exactly except for timestamp and
#    runtime_seconds fields.
```

## How to run a sensitivity analysis

Override the seed to probe stability:

```bash
python run_validation.py --config configs/stage2b_conformal_validation.yaml --seed 1
python run_validation.py --config configs/stage2b_conformal_validation.yaml --seed 7
python run_validation.py --config configs/stage2b_conformal_validation.yaml --seed 99
```

Each run produces a separate JSON file in `results/`. If coverage remains
within tolerance across seeds, the guarantee is robust, not a lucky seed.

## How to interpret coverage results

Each result contains `coverage_per_alpha`, one entry per alpha level:

- `alpha`: the miscoverage rate we targeted (e.g. 0.10 for 90% coverage)
- `target_coverage`: 1 - alpha
- `mean_coverage`: empirical coverage across n_scenarios scenarios
- `min_coverage`, `max_coverage`: spread across scenarios
- `mean_set_size`: average prediction set size (smaller = more confident)
- `q_hat_median`: median non-conformity threshold across scenarios
- `passes_guarantee`: true iff `mean_coverage >= target_coverage - 0.02`

The 2 percentage point tolerance is justified by the finite-sample analysis
in Angelopoulos & Bates (2023), which shows coverage fluctuates around
target within approximately 1-2pp for calibration sets of several hundred
samples.

## Determinism guarantees

These are the invariants we promise:

1. **Same config + same seed + same git SHA -> identical numerical outputs.**
   This is tested by `tests/test_experiments.py::test_determinism`.

2. **Different seeds on the same config produce statistically similar but
   not identical outputs.** By design — this is how we measure robustness.

3. **Same config on different Python minor versions (3.10 vs 3.11 vs 3.12)
   may produce slightly different outputs** due to upstream numerical library
   differences. This is tracked by storing `python_version` in every result.

## Anti-patterns to avoid

- **Do not edit files after running an experiment and expect git_sha to be
  accurate.** A dirty working tree is flagged for this reason.
- **Do not modify a config file and keep the same experiment_name.** If the
  semantics of the experiment change, the name must change too. Otherwise
  results from before and after become silently confusable.
- **Do not trust a result whose git_sha is `unknown`.** This means git was
  not available at run time. The experiment cannot be reproduced.

## References

- Angelopoulos, A. N., & Bates, S. (2023). *A Gentle Introduction to
  Conformal Prediction and Distribution-Free Uncertainty Quantification.*
  arXiv:2107.07511.
- Vovk, V., Gammerman, A., & Shafer, G. (2005). *Algorithmic Learning in
  a Random World.* Springer.
- Wilkinson, M. D., et al. (2016). "The FAIR Guiding Principles for
  scientific data management and stewardship." *Scientific Data* 3:160018.
  Provides the F-A-I-R framework that informs this module's design.
