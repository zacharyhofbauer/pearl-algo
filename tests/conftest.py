"""
Pytest configuration and shared fixtures.

This file ensures all tests use actual production code dynamically
without duplicating files or code.

Key principles:
1. Tests import actual code from src/pearlalgo/ (no duplication)
2. Python path is configured so imports work automatically
3. Shared fixtures are available to all tests
4. Package must be installed in development mode: pip install -e .
"""

import sys
from pathlib import Path

# Ensure project root is in path so tests can import actual production code
project_root = Path(__file__).parent.parent
src_path = project_root / "src"

# Add src to path so tests can import actual production code
# This is done here as a fallback, but pytest.ini also configures pythonpath
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Ensure tests can import from tests package (for MockDataProvider, etc.)
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Pytest configuration
import pytest

# Auto-discover tests in tests/ directory
pytest_plugins = []

# Shared fixtures available to all tests
@pytest.fixture(scope="session")
def project_root_path():
    """Return the project root directory."""
    return project_root

@pytest.fixture(scope="session")
def src_path_fixture():
    """Return the src directory path."""
    return src_path
