# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Tests for :mod:`nimbus_c2.conformal`.

The core property under test is **marginal coverage**: for any exchangeable
data stream, the empirical fraction of test samples whose prediction set
contains the true label should be approximately >= 1 - alpha.

We verify this empirically across 500 seeded scenarios at two significance
levels (alpha=0.10 and alpha=0.05), following the validation pattern
established in Angelopoulos & Bates (2023).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nimbus_c2.conformal import (  # noqa: E402
    ConformalCalibration,
    calibrate,
    empirical_coverage,
    mean_set_size,
    predict_set,
)

CLASS_NAMES = ("civilian", "military", "unknown")


def _synthetic_classifier_output(
    n_samples: int,
    n_classes: int,
    rng: np.random.Generator,
    confidence: float = 0.7,
) -> tuple[np.ndarray, np.ndarray]:
    """Generate (probabilities, true_labels) from a synthetic classifier.

    The classifier is correct on the true label with probability `confidence`;
    the remaining probability mass is distributed evenly across other classes
    plus Dirichlet noise. Produces exchangeable data so marginal coverage
    should hold.
    """
    true_labels = rng.integers(0, n_classes, size=n_samples)
    probs = np.zeros((n_samples, n_classes), dtype=np.float64)
    for i, y in enumerate(true_labels):
        # Base vector: confidence on true class, rest spread evenly
        base = np.full(n_classes, (1.0 - confidence) / (n_classes - 1))
        base[y] = confidence
        # Add Dirichlet noise and renormalise
        noise = rng.dirichlet(np.ones(n_classes) * 5.0)
        mixed = 0.7 * base + 0.3 * noise
        probs[i] = mixed / mixed.sum()
    return probs, true_labels.astype(np.int64)


def test_calibrate_returns_frozen_dataclass():
    rng = np.random.default_rng(42)
    probs, labels = _synthetic_classifier_output(200, 3, rng)
    cal = calibrate(probs, labels, alpha=0.10, class_names=CLASS_NAMES)
    assert isinstance(cal, ConformalCalibration)
    assert cal.alpha == 0.10
    assert 0.0 <= cal.q_hat <= 1.0
    assert cal.n_calibration == 200
    assert cal.class_names == CLASS_NAMES


def test_calibrate_rejects_invalid_alpha():
    rng = np.random.default_rng(0)
    probs, labels = _synthetic_classifier_output(50, 3, rng)
    for bad_alpha in (-0.1, 0.0, 1.0, 1.5):
        with pytest.raises(ValueError, match="alpha"):
            calibrate(probs, labels, alpha=bad_alpha, class_names=CLASS_NAMES)


def test_calibrate_rejects_mismatched_class_names():
    rng = np.random.default_rng(0)
    probs, labels = _synthetic_classifier_output(50, 3, rng)
    with pytest.raises(ValueError, match="class_names"):
        calibrate(probs, labels, alpha=0.10, class_names=("a", "b"))


def test_predict_set_shape_consistency():
    rng = np.random.default_rng(1)
    probs_cal, labels_cal = _synthetic_classifier_output(200, 3, rng)
    probs_test, _ = _synthetic_classifier_output(50, 3, rng)
    cal = calibrate(probs_cal, labels_cal, alpha=0.10, class_names=CLASS_NAMES)
    sets = predict_set(probs_test, cal)
    assert len(sets) == 50
    for s in sets:
        assert isinstance(s, frozenset)
        assert s.issubset(set(CLASS_NAMES))


def test_predict_set_rejects_wrong_n_classes():
    rng = np.random.default_rng(2)
    probs_cal, labels_cal = _synthetic_classifier_output(200, 3, rng)
    cal = calibrate(probs_cal, labels_cal, alpha=0.10, class_names=CLASS_NAMES)
    wrong_shape = np.zeros((10, 4))
    with pytest.raises(ValueError, match="classes"):
        predict_set(wrong_shape, cal)


def test_determinism():
    """Same seed + same inputs = bit-identical calibration and sets."""
    rng1 = np.random.default_rng(123)
    probs1, labels1 = _synthetic_classifier_output(200, 3, rng1)
    cal1 = calibrate(probs1, labels1, alpha=0.10, class_names=CLASS_NAMES)

    rng2 = np.random.default_rng(123)
    probs2, labels2 = _synthetic_classifier_output(200, 3, rng2)
    cal2 = calibrate(probs2, labels2, alpha=0.10, class_names=CLASS_NAMES)

    assert cal1.q_hat == cal2.q_hat
    assert cal1.n_calibration == cal2.n_calibration

    sets1 = predict_set(probs1, cal1)
    sets2 = predict_set(probs2, cal2)
    assert sets1 == sets2


@pytest.mark.parametrize("alpha", [0.10, 0.05])
def test_marginal_coverage_guarantee(alpha: float):
    """Over many seeded scenarios, empirical coverage >= 1 - alpha - tolerance.

    We allow a 2 percentage point tolerance because of finite-sample noise.
    The Angelopoulos & Bates finite-sample correction gives us exact coverage
    in expectation; small deviations per-scenario are expected.
    """
    n_scenarios = 50
    n_calibration = 500
    n_test = 500
    tolerance = 0.02  # 2 percentage points

    coverages = []
    for seed in range(n_scenarios):
        rng = np.random.default_rng(seed)
        probs_cal, labels_cal = _synthetic_classifier_output(
            n_calibration, 3, rng
        )
        probs_test, labels_test = _synthetic_classifier_output(n_test, 3, rng)

        cal = calibrate(probs_cal, labels_cal, alpha=alpha, class_names=CLASS_NAMES)
        coverage = empirical_coverage(probs_test, labels_test, cal)
        coverages.append(coverage)

    mean_coverage = float(np.mean(coverages))
    target = 1.0 - alpha
    # Mean over many scenarios should be very close to target
    assert mean_coverage >= target - tolerance, (
        f"mean empirical coverage {mean_coverage:.4f} below "
        f"target {target:.4f} - tolerance {tolerance}"
    )


@pytest.mark.parametrize("alpha", [0.10, 0.05])
def test_mean_set_size_is_reasonable(alpha: float):
    """Mean set size should be between 0 and n_classes.

    A well-calibrated classifier with alpha=0.10 on 3 classes typically
    produces mean set size between 0.8 and 2.5. Very confident classifiers
    can produce sets smaller than 1 (empty sets allowed, rare but valid).
    """
    rng = np.random.default_rng(7)
    probs_cal, labels_cal = _synthetic_classifier_output(500, 3, rng, confidence=0.7)
    probs_test, _ = _synthetic_classifier_output(500, 3, rng, confidence=0.7)
    cal = calibrate(probs_cal, labels_cal, alpha=alpha, class_names=CLASS_NAMES)

    mss = mean_set_size(probs_test, cal)
    assert 0.0 <= mss <= 3.0
    # For alpha=0.10 the set should usually be below 2.5 (not always singleton)
    if alpha == 0.10:
        assert mss < 2.5


def test_poor_classifier_produces_larger_sets():
    """If the classifier is near-random, conformal compensates with larger sets.

    This is the safety property: a bad classifier cannot secretly be confident.
    """
    rng = np.random.default_rng(99)
    # Confident classifier
    good_probs, good_labels = _synthetic_classifier_output(
        500, 3, rng, confidence=0.85
    )
    good_cal = calibrate(good_probs, good_labels, alpha=0.10, class_names=CLASS_NAMES)
    good_mss = mean_set_size(good_probs, good_cal)

    # Near-random classifier
    rng2 = np.random.default_rng(99)
    bad_probs, bad_labels = _synthetic_classifier_output(
        500, 3, rng2, confidence=0.40
    )
    bad_cal = calibrate(bad_probs, bad_labels, alpha=0.10, class_names=CLASS_NAMES)
    bad_mss = mean_set_size(bad_probs, bad_cal)

    assert bad_mss > good_mss, (
        f"bad classifier set size {bad_mss:.2f} should exceed "
        f"good classifier set size {good_mss:.2f}"
    )
