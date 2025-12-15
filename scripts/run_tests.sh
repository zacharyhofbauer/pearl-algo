#!/bin/bash
# Run All Tests with Proper Environment Setup

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# Run tests
echo "=" * 60
echo "Running Tests"
echo "=" * 60
echo ""

# Test 1: Telegram Notifications
echo "Test 1: Telegram Notifications..."
python3 scripts/test_telegram_notifications.py
echo ""

# Test 2: Signal Generation
echo "Test 2: Signal Generation..."
python3 scripts/test_signal_generation.py
echo ""

# Test 3: Full Service
echo "Test 3: Full Service (2 minutes)..."
python3 scripts/test_nq_agent_with_mock.py
echo ""

echo "=" * 60
echo "✅ All tests completed"
echo "=" * 60

