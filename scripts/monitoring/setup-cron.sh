#!/bin/bash
# Setup cron-based monitoring (alternative to systemd timer)
# Run: ./setup-cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
MONITOR="$PROJECT_ROOT/scripts/monitoring/monitor.py"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

echo "=== PearlAlgo Cron Monitoring Setup ==="

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "monitor.py"; then
    echo "Monitor cron job already exists"
    echo ""
    echo "Current crontab entries:"
    crontab -l | grep -E "(monitor\.py|pearlalgo)"
    echo ""
    echo "To remove: crontab -e and delete the line"
    exit 0
fi

# Add cron job (runs every 5 minutes)
echo "Adding monitor cron job..."
(crontab -l 2>/dev/null || true; echo "*/5 * * * * cd $PROJECT_ROOT && $PYTHON $MONITOR --market NQ >> /tmp/pearlalgo-monitor.log 2>&1") | crontab -

echo ""
echo "=== Cron Job Added ==="
echo "Monitor runs every 5 minutes"
echo ""
echo "View logs: tail -f /tmp/pearlalgo-monitor.log"
echo "Remove: crontab -e and delete the pearlalgo line"
echo ""
