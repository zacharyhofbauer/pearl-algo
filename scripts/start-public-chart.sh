#!/bin/bash
# ============================================================================
# Start Pearl Algo Web App with Public Access (pearlalgo.io)
# ============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "========================================"
echo "  Pearl Algo Web App (Public)"
echo "========================================"
echo ""

# 1. Start Web App (API + Frontend)
echo "Starting Web App..."
./scripts/pearlalgo_web_app/start.sh --market NQ &
CHART_PID=$!

# Wait for services to start
sleep 5

# 2. Start Cloudflare Tunnel
echo "Starting Cloudflare Tunnel..."
if pgrep -f "cloudflared tunnel run" > /dev/null; then
    echo "  Tunnel already running"
else
    nohup cloudflared tunnel run pearlalgo-miniapp > /tmp/cloudflared.log 2>&1 &
    sleep 3
    echo "  Tunnel started"
fi

echo ""
echo "========================================"
echo "  Web App is Public!"
echo "========================================"
echo ""
echo "  Local:  http://localhost:3001"
echo "  Public: https://pearlalgo.io"
echo ""
echo "  API Status:"
curl -s http://localhost:8000/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'    - Backend: OK {d}')" 2>/dev/null || echo "    - Backend: Not responding"
curl -s -o /dev/null -w "    - Tunnel: OK %{http_code}\n" https://pearlalgo.io/api/state --max-time 5 2>/dev/null || echo "    - Tunnel: Not accessible"
echo ""
echo "  Press Ctrl+C to stop."
echo ""

wait $CHART_PID
