# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Experiment runners: pure functions from RunConfig to ExperimentResult.

Each runner is a single function that:
1. Consumes a RunConfig.
2. Seeds all RNG deterministically.
3. Executes the experiment.
4. Captures provenance metadata.
5. Returns an ExperimentResult.

No hidden state. No globals modified. Two calls with the same RunConfig and
the same git_sha produce bit-identical ExperimentResults (up to timestamps
and runtime, which are captured in metadata but not in comparisons).
"""
from __future__ import annotations

import time
import warnings
from datetime import datetime, timezone

import numpy as np

from ..conformal import calibrate, empirical_coverage, mean_set_size
from .config import RunConfig
from .provenance import git_sha_with_status, python_version
from .result import CoverageResult, ExperimentResult

# Tolerance for coverage-guarantee assertion: 2 percentage points.
# This matches the conformal literature (Angelopoulos & Bates 2023) which
# shows finite-sample coverage fluctuates within ~1-2pp around target.
COVERAGE_TOLERANCE = 0.02


def _synthetic_classifier_output(
    n_samples: int,
    n_classes: int,
    rng: np.random.Generator,
    confidence: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate (probabilities, true_labels) pairs for synthetic validation.

    The classifier places `confidence` mass on the true class and distributes
    the remaining (1 - confidence) across other classes, then mixes in
    Dirichlet noise for realism. Produces exchangeable data so marginal
    coverage should hold.
    """
    true_labels = rng.integers(0, n_classes, size=n_samples)
    probs = np.zeros((n_samples, n_classes), dtype=np.float64)
    for i, y in enumerate(true_labels):
        base = np.full(n_classes, (1.0 - confidence) / (n_classes - 1))
        base[y] = confidence
        noise = rng.dirichlet(np.ones(n_classes) * 5.0)
        mixed = 0.7 * base + 0.3 * noise
        probs[i] = mixed / mixed.sum()
    return probs, true_labels.astype(np.int64)


def run_conformal_validation(config: RunConfig) -> ExperimentResult:
    """Execute the canonical Stage 2b conformal coverage-guarantee validation.

    For each alpha level:
        Run n_scenarios independent seeded scenarios. In each, generate a
        calibration set and test set from the synthetic classifier, fit a
        conformal calibration, and measure empirical coverage on the test
        set. Aggregate across scenarios.

    The experiment passes if mean empirical coverage >= (1 - alpha) - tolerance
    for each alpha level.

    Parameters
    ----------
    config : RunConfig
        Specification. Only config.data_source == 'synthetic' is currently
        supported; real OpenSky data integration arrives with Stage 2b live
        calibration.

    Returns
    -------
    ExperimentResult
    """
    if config.data_source != "synthetic":
        raise NotImplementedError(
            f"data_source={config.data_source!r} not yet supported; "
            f"use 'synthetic' for now"
        )

    start_time = time.monotonic()
    captured_warnings: list[str] = []

    with warnings.catch_warnings(record=True) as w_list:
        warnings.simplefilter("always")

        git = git_sha_with_status(warn_on_dirty=True)

        n_classes = len(config.class_names)
        coverage_per_alpha: list[CoverageResult] = []

        for alpha in config.alpha_levels:
            coverages: list[float] = []
            set_sizes: list[float] = []
            q_hats: list[float] = []

            for scenario_idx in range(config.n_scenarios):
                # Deterministic seed per scenario: config.seed + scenario_idx
                # This keeps scenarios independent while being reproducible.
                scenario_seed = config.seed + scenario_idx
                rng = np.random.default_rng(scenario_seed)

                probs_cal, labels_cal = _synthetic_classifier_output(
                    config.n_calibration,
                    n_classes,
                    rng,
                    config.classifier_confidence,
                )
                probs_test, labels_test = _synthetic_classifier_output(
                    config.n_test,
                    n_classes,
                    rng,
                    config.classifier_confidence,
                )

                cal = calibrate(
                    probs_cal,
                    labels_cal,
                    alpha=alpha,
                    class_names=config.class_names,
                )
                coverage = empirical_coverage(probs_test, labels_test, cal)
                mss = mean_set_size(probs_test, cal)

                coverages.append(coverage)
                set_sizes.append(mss)
                q_hats.append(cal.q_hat)

            target = 1.0 - alpha
            mean_cov = float(np.mean(coverages))
            coverage_per_alpha.append(
                CoverageResult(
                    alpha=alpha,
                    target_coverage=target,
                    mean_coverage=mean_cov,
                    min_coverage=float(np.min(coverages)),
                    max_coverage=float(np.max(coverages)),
                    mean_set_size=float(np.mean(set_sizes)),
                    q_hat_median=float(np.median(q_hats)),
                    passes_guarantee=mean_cov >= target - COVERAGE_TOLERANCE,
                )
            )

        # Collect any warnings that fired during the run
        for captured in w_list:
            captured_warnings.append(
                f"{captured.category.__name__}: {captured.message}"
            )

    runtime = time.monotonic() - start_time
    timestamp = datetime.now(timezone.utc).isoformat()

    return ExperimentResult(
        config=config,
        git_sha=git.sha,
        git_branch=git.branch,
        git_is_dirty=git.is_dirty,
        python_version=python_version(),
        timestamp_utc=timestamp,
        runtime_seconds=runtime,
        coverage_per_alpha=coverage_per_alpha,
        coverage_tolerance=COVERAGE_TOLERANCE,
        warnings=captured_warnings,
    )
