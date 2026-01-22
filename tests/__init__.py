"""
Test package marker.

This package contains all tests that use actual production code dynamically.

Key principles:
1. All tests import actual code from src/pearlalgo/ (no duplication)
2. Tests use conftest.py for shared fixtures and configuration
3. MockDataProvider is a test helper (not production code duplication)
4. Tests are run via pytest which automatically discovers and runs them
5. Package must be installed in development mode: pip install -e .

Usage:
    # Run all tests
    pytest
    # or
    ./scripts/testing/run_tests.sh
    
    # Run specific test file
    pytest tests/test_config_loader.py
    
    # Run with coverage
    pytest --cov=pearlalgo --cov-report=html
"""

# Ensure tests can import from tests package
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
src_path = project_root / "src"

# Add src to path so tests can import actual production code
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))


















