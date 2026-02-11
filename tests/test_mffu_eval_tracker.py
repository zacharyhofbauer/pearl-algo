"""
DEPRECATED: This module has been renamed to test_tv_paper_eval_tracker.py.

This shim re-exports all tests so existing test runners still discover them.
Remove after all CI/tooling references are updated.
"""

import warnings

warnings.warn(
    "test_mffu_eval_tracker is deprecated — use test_tv_paper_eval_tracker instead",
    DeprecationWarning,
    stacklevel=2,
)

from tests.test_tv_paper_eval_tracker import *  # noqa: F401,F403
