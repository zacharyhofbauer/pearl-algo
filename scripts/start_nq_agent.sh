#!/bin/bash
# Start NQ Agent Service

echo "=== Starting NQ Intraday Agent Service ==="
echo ""

# Activate virtual environment if it exists
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# Change to project directory
cd "$(dirname "$0")/.."

# Run the service
python -m pearlalgo.nq_agent.main
