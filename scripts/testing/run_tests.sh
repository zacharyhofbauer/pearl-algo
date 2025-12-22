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

# Run tests using unified test runner
echo "=" * 60
echo "Running Tests (Unified Test Runner)"
echo "=" * 60
echo ""
echo "Note: This script uses the unified test runner (test_all.py)"
echo "For individual test modes, run: python3 scripts/testing/test_all.py [mode]"
echo ""

python3 scripts/testing/test_all.py

echo ""
echo "=" * 60
echo "✅ All tests completed"
echo "=" * 60



