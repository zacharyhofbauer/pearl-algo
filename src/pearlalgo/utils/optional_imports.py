"""
Optional ML Library Imports

Centralizes try/except import patterns for optional ML dependencies.
This avoids repeating the same boilerplate across multiple modules.

Usage:
    from pearlalgo.utils.optional_imports import (
        SKLEARN_AVAILABLE,
        LIGHTGBM_AVAILABLE,
        XGBOOST_AVAILABLE,
        sklearn,
        lgb,
        xgb,
    )

    if SKLEARN_AVAILABLE:
        from sklearn.linear_model import LogisticRegression
        # ... use sklearn
"""

from __future__ import annotations

from typing import Any, Optional

# =============================================================================
# scikit-learn
# =============================================================================
try:
    import sklearn
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import cross_val_score

    SKLEARN_AVAILABLE = True
except ImportError:
    sklearn = None  # type: ignore
    LogisticRegression = None  # type: ignore
    StandardScaler = None  # type: ignore
    CalibratedClassifierCV = None  # type: ignore
    cross_val_score = None  # type: ignore
    SKLEARN_AVAILABLE = False

# =============================================================================
# LightGBM
# =============================================================================
try:
    import lightgbm as lgb
    from lightgbm import LGBMClassifier

    LIGHTGBM_AVAILABLE = True
except ImportError:
    lgb = None  # type: ignore
    LGBMClassifier = None  # type: ignore
    LIGHTGBM_AVAILABLE = False

# =============================================================================
# XGBoost
# =============================================================================
try:
    import xgboost as xgb
    from xgboost import XGBClassifier

    XGBOOST_AVAILABLE = True
except ImportError:
    xgb = None  # type: ignore
    XGBClassifier = None  # type: ignore
    XGBOOST_AVAILABLE = False

# =============================================================================
# NumPy (usually always available, but handle gracefully)
# =============================================================================
try:
    import numpy as np

    NUMPY_AVAILABLE = True
except ImportError:
    np = None  # type: ignore
    NUMPY_AVAILABLE = False


def get_best_classifier() -> tuple[Optional[Any], str]:
    """
    Get the best available classifier class and its name.

    Returns:
        Tuple of (classifier_class, name) where classifier_class may be None
        if no ML library is available.

    Priority: XGBoost > LightGBM > sklearn LogisticRegression
    """
    if XGBOOST_AVAILABLE:
        return XGBClassifier, "xgboost"
    elif LIGHTGBM_AVAILABLE:
        return LGBMClassifier, "lightgbm"
    elif SKLEARN_AVAILABLE:
        return LogisticRegression, "sklearn"
    else:
        return None, "none"


def get_available_libraries() -> dict[str, bool]:
    """
    Get availability status of all optional ML libraries.

    Returns:
        Dictionary mapping library names to availability status.
    """
    return {
        "sklearn": SKLEARN_AVAILABLE,
        "lightgbm": LIGHTGBM_AVAILABLE,
        "xgboost": XGBOOST_AVAILABLE,
        "numpy": NUMPY_AVAILABLE,
    }
