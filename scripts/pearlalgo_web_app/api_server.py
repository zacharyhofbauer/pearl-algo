#!/usr/bin/env python3
"""Wrapper script for backward compatibility. The API server has moved to src/pearlalgo/api/server.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from pearlalgo.api.server import (  # noqa: E402
    ConnectionManager,
    app,
    main,
    ws_manager,
)

if __name__ == "__main__":
    main()
