"""
Pearl AI 3.0 - Compatibility Shim.

The actual implementation has moved to ``pearlalgo.pearl_ai``.
This shim re-exports everything so existing ``from pearl_ai import ...``
statements continue to work while the codebase is gradually migrated.
"""

from pearlalgo.pearl_ai import *  # noqa: F401,F403
from pearlalgo.pearl_ai import __version__, __all__  # noqa: F401
