#!/bin/bash
# ============================================================================
# Ensure Auto-Connect for XPRS Network
# Purpose: Verify and enable auto-connect so server connects automatically at new location
# Usage: ./scripts/setup/ensure_auto_connect.sh
# ============================================================================

set -euo pipefail

SSID="XPRS"
PASSWORD="Express1"

echo "=== Ensuring Auto-Connect for XPRS Network ==="
echo ""

# Find XPRS connection (case-insensitive)
XPRS_CONN=$(nmcli -t -f NAME connection show | grep -i "$SSID" | head -1 || true)

if [ -z "$XPRS_CONN" ]; then
    echo "⚠️  No saved XPRS connection found"
    echo ""
    echo "Creating new connection with auto-connect enabled..."
    
    # Create new connection with auto-connect
    if nmcli connection add \
        type wifi \
        con-name "XPRS" \
        wifi.ssid "$SSID" \
        wifi-sec.key-mgmt wpa-psk \
        wifi-sec.psk "$PASSWORD" \
        connection.autoconnect yes \
        connection.autoconnect-priority 10 \
        ipv4.method auto 2>/dev/null; then
        
        echo "✅ Created XPRS connection with auto-connect enabled"
        XPRS_CONN="XPRS"
    else
        echo "❌ Failed to create connection"
        exit 1
    fi
else
    echo "✅ Found existing connection: $XPRS_CONN"
    echo ""
    echo "Checking auto-connect setting..."
    
    AUTO_CONNECT=$(nmcli -t -f connection.autoconnect connection show "$XPRS_CONN" 2>/dev/null | cut -d: -f2 || echo "no")
    
    if [ "$AUTO_CONNECT" = "yes" ]; then
        echo "✅ Auto-connect is already ENABLED"
    else
        echo "⚠️  Auto-connect is DISABLED"
        echo "   Enabling auto-connect..."
        
        if nmcli connection modify "$XPRS_CONN" connection.autoconnect yes; then
            echo "✅ Auto-connect ENABLED"
        else
            echo "❌ Failed to enable auto-connect"
            exit 1
        fi
    fi
fi

echo ""
echo "=== Verifying Settings ==="
echo ""

# Show connection details
echo "Connection: $XPRS_CONN"
echo ""
nmcli connection show "$XPRS_CONN" | grep -E "connection\.(id|autoconnect|autoconnect-priority)|802-11-wireless\.ssid|wifi-sec\.key-mgmt" | while IFS=: read -r key value; do
    key=$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    value=$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
    
    case "$key" in
        "connection.id")
            echo "   Name: $value"
            ;;
        "connection.autoconnect")
            if [ "$value" = "yes" ]; then
                echo "   ✅ Auto-connect: ENABLED"
            else
                echo "   ❌ Auto-connect: DISABLED"
            fi
            ;;
        "connection.autoconnect-priority")
            echo "   Priority: $value (higher = preferred)"
            ;;
        "802-11-wireless.ssid")
            echo "   SSID: $value"
            ;;
        "wifi-sec.key-mgmt")
            echo "   Security: $value"
            ;;
    esac
done

echo ""
echo "=== Testing Connection ==="
echo ""

# Check if WiFi interface is available
WIFI_DEVICE=$(nmcli -t -f DEVICE,TYPE device | grep -E "wifi|wireless" | cut -d: -f1 | head -1 || true)

if [ -z "$WIFI_DEVICE" ]; then
    echo "⚠️  No WiFi device detected"
    echo "   This is normal if WiFi is disabled or not available"
    echo "   Auto-connect will work when WiFi is enabled at new location"
else
    echo "✅ WiFi device: $WIFI_DEVICE"
    
    # Check if currently connected
    CURRENT_CONN=$(nmcli -t -f NAME connection show --active | head -1 || true)
    if [ -n "$CURRENT_CONN" ]; then
        CURRENT_SSID=$(nmcli -t -f 802-11-wireless.ssid connection show "$CURRENT_CONN" 2>/dev/null | cut -d: -f2 || true)
        if [ "$CURRENT_SSID" = "$SSID" ]; then
            echo "✅ Currently connected to XPRS"
        else
            echo "ℹ️  Currently connected to: $CURRENT_SSID"
            echo "   XPRS will auto-connect when available"
        fi
    else
        echo "ℹ️  Not currently connected"
        echo "   XPRS will auto-connect when available"
    fi
fi

echo ""
echo "=== Summary ==="
echo ""
echo "✅ XPRS connection is configured with auto-connect ENABLED"
echo ""
echo "When you plug in the server at the new location:"
echo "  1. Server will automatically detect XPRS network"
echo "  2. Server will automatically connect using saved credentials"
echo "  3. No manual intervention needed!"
echo ""
echo "To verify after moving:"
echo "  ./scripts/setup/verify_wifi_connection.sh"
echo ""
echo "If connection doesn't work automatically:"
echo "  ./scripts/setup/connect_xprs.sh"
