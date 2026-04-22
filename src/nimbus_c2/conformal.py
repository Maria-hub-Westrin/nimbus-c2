# SPDX-FileCopyrightText: 2026 Maria Westrin
# SPDX-License-Identifier: MIT
"""Split conformal prediction for classifier uncertainty quantification.

Implements the Angelopoulos & Bates (2023) split conformal procedure for
classification. Given a calibration set of (probabilities, true_label) pairs,
produces prediction sets with a provable marginal coverage guarantee:

    P(y_test ∈ prediction_set(x_test)) >= 1 - α

...where the probability is over the (exchangeable) draw of calibration and
test data. The guarantee holds for ANY underlying classifier, including
poorly-calibrated ones — in which case prediction sets simply grow larger to
absorb the miscalibration. That is the core property that makes this method
safe for assurance-critical decision systems.

This module is intentionally classifier-agnostic. Callers supply probabilities
from whatever model they choose (logistic regression, gradient boosting,
neural network) and receive conformal prediction sets in return.

References
----------
Angelopoulos, A. N., & Bates, S. (2023). "A Gentle Introduction to Conformal
Prediction and Distribution-Free Uncertainty Quantification." arXiv:2107.07511.

Vovk, V., Gammerman, A., & Shafer, G. (2005). "Algorithmic Learning in a
Random World." Springer.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class ConformalCalibration:
    """Frozen artefact of a split conformal calibration.

    The threshold q_hat is the (1-α)-quantile of the non-conformity scores
    computed on the calibration set. At inference time, any class whose
    softmax probability exceeds (1 - q_hat) is included in the prediction set.

    Attributes
    ----------
    alpha : float
        Target miscoverage rate. Coverage guarantee is >= 1 - alpha.
    q_hat : float
        Empirical (1-alpha)-quantile of non-conformity scores. In [0, 1].
    n_calibration : int
        Number of calibration samples used. Larger n tightens the guarantee.
    class_names : tuple[str, ...]
        Ordered class labels. The index in this tuple matches the column
        index in the probability arrays.
    """

    alpha: float
    q_hat: float
    n_calibration: int
    class_names: tuple[str, ...]


def _nonconformity_scores(
    probabilities: NDArray[np.float64],
    true_labels: NDArray[np.int64],
) -> NDArray[np.float64]:
    """Compute 1 - P(y_true | x) for each calibration point.

    This is the "classic" softmax non-conformity score. Lower scores indicate
    higher classifier confidence in the true label. The conformal threshold
    is then placed at the (1-α)-quantile of these scores.
    """
    if probabilities.ndim != 2:
        raise ValueError(
            f"probabilities must be 2-D (n_samples, n_classes); got shape "
            f"{probabilities.shape}"
        )
    if true_labels.ndim != 1:
        raise ValueError(
            f"true_labels must be 1-D; got shape {true_labels.shape}"
        )
    if len(probabilities) != len(true_labels):
        raise ValueError(
            f"probabilities ({len(probabilities)}) and true_labels "
            f"({len(true_labels)}) must have the same length"
        )
    if np.any(true_labels < 0) or np.any(
        true_labels >= probabilities.shape[1]
    ):
        raise ValueError(
            "true_labels must be in [0, n_classes); got out-of-range values"
        )

    n = len(probabilities)
    rows = np.arange(n)
    p_true = probabilities[rows, true_labels]
    return 1.0 - p_true


def calibrate(
    probabilities: NDArray[np.float64],
    true_labels: NDArray[np.int64],
    alpha: float,
    class_names: Sequence[str],
) -> ConformalCalibration:
    """Fit a conformal calibration on labelled (prob, label) pairs.

    Uses the finite-sample corrected (1-α) quantile:

        q_hat = Quantile_{ceil((n+1)(1-α)) / n}(scores)

    This correction ensures the coverage guarantee holds at finite n, not
    just asymptotically. See Angelopoulos & Bates 2023, Algorithm 1.

    Parameters
    ----------
    probabilities : NDArray[float64]
        Classifier softmax output, shape (n_samples, n_classes).
        Each row must sum to approximately 1.
    true_labels : NDArray[int64]
        Ground-truth class indices, shape (n_samples,), in [0, n_classes).
    alpha : float
        Target miscoverage rate in (0, 1). Common values: 0.05, 0.10.
    class_names : sequence of str
        Human-readable class labels. length must equal probabilities.shape[1].

    Returns
    -------
    ConformalCalibration
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    if len(class_names) != probabilities.shape[1]:
        raise ValueError(
            f"class_names has {len(class_names)} entries but probabilities "
            f"has {probabilities.shape[1]} columns"
        )

    scores = _nonconformity_scores(probabilities, true_labels)
    n = len(scores)

    # Finite-sample correction: use ceil((n+1)(1-alpha)) / n quantile level.
    q_level = min(np.ceil((n + 1) * (1.0 - alpha)) / n, 1.0)
    q_hat = float(np.quantile(scores, q_level, method="higher"))

    return ConformalCalibration(
        alpha=alpha,
        q_hat=q_hat,
        n_calibration=n,
        class_names=tuple(class_names),
    )


def predict_set(
    probabilities: NDArray[np.float64],
    calibration: ConformalCalibration,
) -> list[frozenset[str]]:
    """Produce conformal prediction sets for each sample.

    A class c is included in the prediction set iff:

        P(c | x) >= 1 - q_hat

    i.e. the non-conformity score for class c is <= q_hat.

    Parameters
    ----------
    probabilities : NDArray[float64]
        shape (n_samples, n_classes). Must match n_classes in calibration.
    calibration : ConformalCalibration
        Fitted calibration from :func:`calibrate`.

    Returns
    -------
    list[frozenset[str]]
        One prediction set per sample. Empty frozensets are possible if no
        class exceeds the threshold (rare; indicates extreme miscalibration).
    """
    if probabilities.ndim != 2:
        raise ValueError(
            f"probabilities must be 2-D; got shape {probabilities.shape}"
        )
    if probabilities.shape[1] != len(calibration.class_names):
        raise ValueError(
            f"probabilities has {probabilities.shape[1]} classes but "
            f"calibration was fit with {len(calibration.class_names)}"
        )

    threshold = 1.0 - calibration.q_hat
    # Broadcast: (n_samples, n_classes) >= scalar -> boolean mask
    mask = probabilities >= threshold
    class_names = calibration.class_names

    return [
        frozenset(c for c, include in zip(class_names, row, strict=True) if include)
        for row in mask
    ]


def empirical_coverage(
    probabilities: NDArray[np.float64],
    true_labels: NDArray[np.int64],
    calibration: ConformalCalibration,
) -> float:
    """Fraction of test samples whose prediction set contains the true label.

    For a valid conformal procedure on exchangeable data, this should be
    approximately >= 1 - alpha. Used for empirical validation.
    """
    sets = predict_set(probabilities, calibration)
    class_names = calibration.class_names
    hits = sum(
        1
        for s, y in zip(sets, true_labels, strict=True)
        if class_names[int(y)] in s
    )
    return hits / len(sets) if sets else 0.0


def mean_set_size(
    probabilities: NDArray[np.float64],
    calibration: ConformalCalibration,
) -> float:
    """Average prediction set cardinality.

    Smaller is better (more confident). When classifier is well-calibrated
    and well-separated, mean set size approaches 1. When ambiguous, grows
    toward n_classes. This metric, together with empirical coverage, fully
    characterises conformal performance.
    """
    sets = predict_set(probabilities, calibration)
    return float(np.mean([len(s) for s in sets])) if sets else 0.0
