#!/bin/bash
# ============================================================================
# Category: Testing
# Purpose: Run all unit tests with proper environment setup
# Usage: ./scripts/testing/run_tests.sh
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Resolve project root (repo root)
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

# Activate virtual environment if it exists
if [ -f .venv/bin/activate ]; then
    echo "Activating virtual environment..."
    source .venv/bin/activate
    echo "✅ Virtual environment activated"
    echo ""
else
    echo "⚠️  No virtual environment found"
    echo "   Consider creating one: python3 -m venv .venv"
    echo ""
fi

# Check if package is installed
if ! python3 -c "import pearlalgo" 2>/dev/null; then
    echo "📦 Installing package in development mode..."
    pip install -e . > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "✅ Package installed"
        echo ""
    else
        echo "❌ Failed to install package"
        echo "   Try: pip install -e ."
        exit 1
    fi
fi

# Ensure pytest is available
if ! python3 -c "import pytest" 2>/dev/null; then
    echo "❌ pytest is not installed in this Python environment."
    echo "   Install dev dependencies (recommended inside .venv):"
    echo "     pip install -e '.[dev]'"
    exit 1
fi

# Run unit tests via pytest (canonical suite under tests/)
echo "============================================================"
echo "Running Unit Tests (pytest)"
echo "============================================================"
echo ""
echo "Tip: For integration-style validation (Telegram/signals/service/arch), use:"
echo "  python3 scripts/testing/test_all.py [mode]"
echo ""

python3 -m pytest "$@"



