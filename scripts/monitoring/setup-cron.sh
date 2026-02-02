#!/bin/bash
# Setup cron-based monitoring (alternative to systemd timer)
# Run: ./setup-cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
HEALTH_CHECK="$PROJECT_ROOT/scripts/monitoring/health_check.py"
PYTHON="$PROJECT_ROOT/.venv/bin/python"

echo "=== PearlAlgo Cron Monitoring Setup ==="

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "health_check.py"; then
    echo "Health check cron job already exists"
    echo ""
    echo "Current crontab entries:"
    crontab -l | grep -E "(health_check|pearlalgo)"
    echo ""
    echo "To remove: crontab -e and delete the line"
    exit 0
fi

# Add cron job (runs every 5 minutes)
echo "Adding health check cron job..."
(crontab -l 2>/dev/null || true; echo "*/5 * * * * cd $PROJECT_ROOT && $PYTHON $HEALTH_CHECK >> /tmp/pearlalgo-health.log 2>&1") | crontab -

echo ""
echo "=== Cron Job Added ==="
echo "Health check runs every 5 minutes"
echo ""
echo "View logs: tail -f /tmp/pearlalgo-health.log"
echo "Remove: crontab -e and delete the pearlalgo line"
echo ""
