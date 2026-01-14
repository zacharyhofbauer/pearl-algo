#!/bin/bash
# ============================================================================
# XPRS WiFi Connection Script
# Purpose: Connect to XPRS network at new location
# Usage: ./scripts/setup/connect_xprs.sh
# ============================================================================

set -euo pipefail

SSID="XPRS"
PASSWORD="Express1"

echo "=== Connecting to XPRS Network ==="
echo ""

# Check if already connected to XPRS
CURRENT_SSID=$(nmcli -t -f 802-11-wireless.ssid connection show --active 2>/dev/null | head -1 || true)

if [ "$CURRENT_SSID" = "$SSID" ]; then
    echo "✅ Already connected to $SSID"
    echo ""
    echo "Current connection details:"
    nmcli connection show --active | grep -E "connection\.id|802-11-wireless\.ssid|ipv4\.address" || true
    echo ""
    echo "Verifying connectivity..."
    ./scripts/setup/verify_wifi_connection.sh
    exit 0
fi

# Check if XPRS is a known/saved network
KNOWN_CONN=$(nmcli -t -f NAME connection show | grep -i "$SSID" | head -1 || true)

if [ -n "$KNOWN_CONN" ]; then
    echo "✅ Found saved connection: $KNOWN_CONN"
    echo "   Attempting to connect..."
    
    # Try to activate the saved connection
    if nmcli connection up "$KNOWN_CONN" 2>/dev/null; then
        echo "✅ Connected to $SSID using saved connection"
        sleep 3
        ./scripts/setup/verify_wifi_connection.sh
        exit 0
    else
        echo "⚠️  Saved connection exists but couldn't activate"
        echo "   Will try connecting with password..."
    fi
fi

# Connect to XPRS network
echo "Connecting to $SSID..."
echo ""

if nmcli device wifi connect "$SSID" password "$PASSWORD"; then
    echo ""
    echo "✅ Successfully connected to $SSID"
    echo ""
    echo "Waiting for IP assignment..."
    sleep 5
    
    # Verify connection
    echo ""
    ./scripts/setup/verify_wifi_connection.sh
else
    echo ""
    echo "❌ Failed to connect to $SSID"
    echo ""
    echo "Troubleshooting steps:"
    echo "1. Check if network is in range:"
    echo "   nmcli device wifi list | grep -i $SSID"
    echo ""
    echo "2. Check WiFi interface:"
    echo "   nmcli device status"
    echo ""
    echo "3. Try manual connection:"
    echo "   nmcli device wifi connect \"$SSID\" password \"$PASSWORD\""
    exit 1
fi
