#!/bin/bash
# ============================================================================
# WiFi Connection Verification Script
# Purpose: Verify network connectivity after moving server to new location
# Usage: ./scripts/setup/verify_wifi_connection.sh
# ============================================================================

set -euo pipefail

echo "=== WiFi Connection Verification ==="
echo ""

# Check if WiFi interface exists
WIFI_INTERFACE=""
if command -v nmcli >/dev/null 2>&1; then
    WIFI_INTERFACE=$(nmcli -t -f DEVICE,TYPE device | grep -E "wifi|wireless" | cut -d: -f1 | head -1 || true)
elif [ -d /sys/class/net ]; then
    WIFI_INTERFACE=$(ls /sys/class/net | grep -E "wlan|wifi" | head -1 || true)
fi

if [ -z "$WIFI_INTERFACE" ]; then
    echo "⚠️  Could not detect WiFi interface"
    echo "   Available interfaces:"
    ip -o link show | awk '{print $2}' | sed 's/:$//' | sed 's/^/   - /'
else
    echo "✅ WiFi Interface: $WIFI_INTERFACE"
fi

echo ""

# Check WiFi connection status
if command -v nmcli >/dev/null 2>&1; then
    echo "=== NetworkManager Status ==="
    nmcli device status
    echo ""
    
    CONNECTION=$(nmcli -t -f NAME connection show --active | head -1 || true)
    if [ -n "$CONNECTION" ]; then
        echo "✅ Active Connection: $CONNECTION"
        SSID=$(nmcli -t -f 802-11-wireless.ssid connection show "$CONNECTION" 2>/dev/null | cut -d: -f2 || true)
        if [ -n "$SSID" ]; then
            echo "   SSID: $SSID"
        fi
    else
        echo "❌ No active connection"
    fi
    echo ""
fi

# Check IP address
echo "=== IP Address Configuration ==="
if [ -n "$WIFI_INTERFACE" ]; then
    IP_ADDR=$(ip -4 addr show "$WIFI_INTERFACE" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1 || true)
    if [ -n "$IP_ADDR" ]; then
        echo "✅ IP Address: $IP_ADDR"
    else
        echo "❌ No IP address assigned"
    fi
else
    echo "⚠️  Could not determine WiFi interface"
    echo "   All IP addresses:"
    ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | sed 's/^/   - /'
fi
echo ""

# Check gateway/DNS
echo "=== Network Connectivity ==="
GATEWAY=$(ip route | grep default | awk '{print $3}' | head -1 || true)
if [ -n "$GATEWAY" ]; then
    echo "✅ Default Gateway: $GATEWAY"
    if ping -c 1 -W 2 "$GATEWAY" >/dev/null 2>&1; then
        echo "   ✅ Gateway is reachable"
    else
        echo "   ❌ Gateway is NOT reachable"
    fi
else
    echo "❌ No default gateway configured"
fi
echo ""

# Test DNS resolution
if command -v nslookup >/dev/null 2>&1; then
    echo "Testing DNS resolution..."
    if nslookup google.com >/dev/null 2>&1; then
        echo "✅ DNS resolution working"
    else
        echo "❌ DNS resolution failed"
    fi
    echo ""
fi

# Test internet connectivity
echo "Testing internet connectivity..."
if ping -c 2 -W 3 8.8.8.8 >/dev/null 2>&1; then
    echo "✅ Internet connectivity: OK"
else
    echo "❌ Internet connectivity: FAILED"
fi
echo ""

# Check IBKR Gateway connectivity (if running)
echo "=== IBKR Gateway Connectivity ==="
if pgrep -f "java.*IBC.jar" >/dev/null 2>&1; then
    echo "✅ IBKR Gateway is running"
    if ss -tuln 2>/dev/null | grep -q ":4002"; then
        echo "✅ Gateway API port (4002) is listening"
    else
        echo "⚠️  Gateway API port not yet listening"
    fi
else
    echo "ℹ️  IBKR Gateway is not running"
fi
echo ""

# Check systemd services that need network
echo "=== Network-Dependent Services ==="
SERVICES=("nq-agent.service" "telegram-bot.service")
for service in "${SERVICES[@]}"; do
    if systemctl list-units --type=service --all 2>/dev/null | grep -q "$service"; then
        STATUS=$(systemctl is-active "$service" 2>/dev/null || echo "inactive")
        if [ "$STATUS" = "active" ]; then
            echo "✅ $service: $STATUS"
        else
            echo "ℹ️  $service: $STATUS"
        fi
    fi
done
echo ""

# Summary
echo "=== Summary ==="
if [ -n "${IP_ADDR:-}" ] && [ -n "${GATEWAY:-}" ] && ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
    echo "✅ Network connectivity: OK"
    echo ""
    echo "Next steps:"
    echo "  1. Verify IBKR Gateway can connect:"
    echo "     ./scripts/gateway/gateway.sh status"
    echo "  2. Test NQ Agent connectivity:"
    echo "     ./scripts/testing/smoke_test_ibkr.py"
    echo "  3. Check Telegram bot connectivity (if configured)"
else
    echo "❌ Network connectivity issues detected"
    echo ""
    echo "Troubleshooting:"
    echo "  1. Check WiFi connection:"
    echo "     nmcli device wifi list"
    echo "     nmcli device wifi connect <SSID> password <PASSWORD>"
    echo "  2. Restart NetworkManager:"
    echo "     sudo systemctl restart NetworkManager"
    echo "  3. Check WiFi interface:"
    echo "     ip link show"
    echo "     sudo ip link set <interface> up"
fi
