#!/bin/bash
###############################################################################
# NUKE ALL SYSTEMD SERVICES
#
# Removes every pearlalgo/ibkr systemd service so that ./pearl.sh is the ONLY
# way to start/stop the stack.
#
# KEEPS: cloudflared-pearlalgo.service (Cloudflare tunnel)
#
# Usage:  sudo bash scripts/maintenance/nuke_services.sh
###############################################################################
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Run this with sudo:"
    echo "   sudo bash $0"
    exit 1
fi

echo "============================================"
echo "  NUKING ALL PEARLALGO SYSTEMD SERVICES"
echo "============================================"
echo ""

# Every service/timer file to remove (everything EXCEPT cloudflared)
UNITS=(
    ibgateway.service
    ibkr-gateway.service
    pearl.service
    pearlalgo-agent.service
    pearlalgo-agent-tv-paper.service
    pearlalgo-api.service
    pearlalgo-api-tv-paper.service
    pearlalgo-monitor.service
    pearlalgo-monitor.timer
    pearlalgo-telegram.service
    pearlalgo-webapp.service
)

# ── 1. Stop every unit ──
echo "1/5  Stopping all units..."
for u in "${UNITS[@]}"; do
    systemctl stop "$u" 2>/dev/null && echo "     stopped $u" || true
done
echo ""

# ── 2. Disable every unit ──
echo "2/5  Disabling all units..."
for u in "${UNITS[@]}"; do
    systemctl disable "$u" 2>/dev/null || true
done
echo ""

# ── 3. Delete unit files ──
echo "3/5  Deleting unit files..."
for u in "${UNITS[@]}"; do
    f="/etc/systemd/system/$u"
    if [ -f "$f" ]; then
        rm -f "$f"
        echo "     deleted $f"
    fi
done
echo ""

# ── 4. Reload systemd ──
echo "4/5  Reloading systemd..."
systemctl daemon-reload
systemctl reset-failed 2>/dev/null || true
echo "     done"
echo ""

# ── 5. Delete old /home/pearlalgo directory ──
echo "5/6  Deleting /home/pearlalgo (old user dir)..."
if [ -d /home/pearlalgo ]; then
    rm -rf /home/pearlalgo
    echo "     deleted /home/pearlalgo"
else
    echo "     already gone"
fi
echo ""

# ── 6. Kill all lingering processes from these services ──
echo "6/6  Killing lingering processes..."
# Kill ALL java (Gateway) processes
pkill -9 -f "java.*IBC" 2>/dev/null || true
pkill -9 -f "java.*ibgateway" 2>/dev/null || true
pkill -9 -f "java.*Jts" 2>/dev/null || true
# Kill Xvfb spawned by services
pkill -9 -f "Xvfb :99" 2>/dev/null || true
sleep 2

# Verify java is gone
if pgrep -f "java.*IBC\|java.*Jts" &>/dev/null; then
    echo "     force killing remaining java..."
    pkill -9 -f java 2>/dev/null || true
    sleep 2
fi
echo "     done"
echo ""

# ── Verify ──
echo "============================================"
echo "  VERIFICATION"
echo "============================================"
echo ""
remaining=$(ls /etc/systemd/system/*pearl* /etc/systemd/system/*ibkr* /etc/systemd/system/*ibgateway* 2>/dev/null | grep -v cloudflared || true)
if [ -z "$remaining" ]; then
    echo "  ✅ All service files removed (cloudflared kept)"
else
    echo "  ⚠️  Remaining files:"
    echo "$remaining"
fi
echo ""
active=$(systemctl list-units --type=service --all 2>/dev/null | grep -iE "pearl|ibkr|ibgateway|ibc" | grep -v cloudflared || true)
if [ -z "$active" ]; then
    echo "  ✅ No pearlalgo/ibkr services loaded"
else
    echo "  Remaining in systemd:"
    echo "$active"
fi
echo ""
echo "============================================"
echo "  DONE"
echo "============================================"
echo ""
echo "  ./pearl.sh is now the ONLY way to control the stack."
echo ""
echo "  Next steps (run as pearl, no sudo):"
echo "    cd /home/pearl/PearlAlgoProject"
echo "    ./pearl.sh start"
echo ""
