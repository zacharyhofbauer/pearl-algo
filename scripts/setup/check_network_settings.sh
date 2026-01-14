#!/bin/bash
# ============================================================================
# Network Settings Checker
# Purpose: Display current network settings (Linux equivalent of macOS WiFi settings)
# Usage: ./scripts/setup/check_network_settings.sh
# ============================================================================

set -euo pipefail

echo "=== Current Network Settings ==="
echo ""

# Get active connection
if command -v nmcli >/dev/null 2>&1; then
    ACTIVE_CONN=$(nmcli -t -f NAME connection show --active | head -1 || true)
    
    if [ -n "$ACTIVE_CONN" ]; then
        echo "📶 Active Connection: $ACTIVE_CONN"
        echo ""
        
        # Get connection details
        echo "=== Connection Details ==="
        nmcli connection show "$ACTIVE_CONN" | grep -E "connection\.|802-11-wireless\.|ipv4\.|ipv6\." | while IFS=: read -r key value; do
            key=$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            value=$(echo "$value" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
            
            case "$key" in
                "connection.id")
                    echo "   Network Name: $value"
                    ;;
                "802-11-wireless.ssid")
                    echo "   SSID: $value"
                    ;;
                "802-11-wireless.security")
                    if [ -n "$value" ]; then
                        echo "   Security: $value (🔒 Secured)"
                    else
                        echo "   Security: None (⚠️  Open network)"
                    fi
                    ;;
                "connection.autoconnect")
                    if [ "$value" = "yes" ]; then
                        echo "   Auto-connect: ✅ Enabled"
                    else
                        echo "   Auto-connect: ❌ Disabled"
                    fi
                    ;;
                "ipv4.method")
                    if [ "$value" = "auto" ]; then
                        echo "   IP Method: DHCP (Automatic)"
                    elif [ "$value" = "manual" ]; then
                        echo "   IP Method: Manual (Static)"
                    fi
                    ;;
            esac
        done
        echo ""
    fi
fi

# Get IP address information
echo "=== IP Address Information ==="
WIFI_IFACE=$(ip -o link show | grep -E "wlan|wifi" | awk -F': ' '{print $2}' | head -1 || true)

if [ -n "$WIFI_IFACE" ]; then
    echo "   Interface: $WIFI_IFACE"
    
    IP_ADDR=$(ip -4 addr show "$WIFI_IFACE" 2>/dev/null | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | head -1 || true)
    if [ -n "$IP_ADDR" ]; then
        echo "   IP Address: $IP_ADDR"
    else
        echo "   IP Address: Not assigned"
    fi
    
    GATEWAY=$(ip route | grep default | grep "$WIFI_IFACE" | awk '{print $3}' | head -1 || true)
    if [ -n "$GATEWAY" ]; then
        echo "   Router/Gateway: $GATEWAY"
    else
        GATEWAY=$(ip route | grep default | awk '{print $3}' | head -1 || true)
        if [ -n "$GATEWAY" ]; then
            echo "   Router/Gateway: $GATEWAY"
        fi
    fi
    
    MAC_ADDR=$(ip link show "$WIFI_IFACE" 2>/dev/null | grep -oP '(?<=link/ether\s)[a-f0-9:]+' | head -1 || true)
    if [ -n "$MAC_ADDR" ]; then
        echo "   MAC Address: $MAC_ADDR"
    fi
    echo ""
fi

# Check signal strength
if command -v iwconfig >/dev/null 2>&1 && [ -n "$WIFI_IFACE" ]; then
    echo "=== Signal Strength ==="
    SIGNAL=$(iwconfig "$WIFI_IFACE" 2>/dev/null | grep -oP 'Signal level=\K[^ ]+' || true)
    if [ -n "$SIGNAL" ]; then
        echo "   Signal: $SIGNAL"
    fi
    echo ""
fi

# Check auto-connect setting
if [ -n "${ACTIVE_CONN:-}" ] && command -v nmcli >/dev/null 2>&1; then
    AUTO_CONNECT=$(nmcli -t -f connection.autoconnect connection show "$ACTIVE_CONN" 2>/dev/null | cut -d: -f2 || true)
    echo "=== Connection Preferences ==="
    if [ "$AUTO_CONNECT" = "yes" ]; then
        echo "   ✅ Automatically join this network: Enabled"
    else
        echo "   ❌ Automatically join this network: Disabled"
        echo ""
        echo "   To enable auto-connect:"
        echo "   nmcli connection modify \"$ACTIVE_CONN\" connection.autoconnect yes"
    fi
    echo ""
fi

# Summary
echo "=== Quick Status ==="
if ping -c 1 -W 2 8.8.8.8 >/dev/null 2>&1; then
    echo "✅ Internet: Connected"
else
    echo "❌ Internet: Not connected"
fi

if [ -n "${IP_ADDR:-}" ]; then
    echo "✅ IP Address: $IP_ADDR"
else
    echo "❌ IP Address: Not assigned"
fi

if [ -n "${GATEWAY:-}" ]; then
    echo "✅ Gateway: $GATEWAY"
else
    echo "❌ Gateway: Not configured"
fi

echo ""
echo "=== Useful Commands ==="
echo "View all settings:     nmcli connection show \"$ACTIVE_CONN\""
echo "Edit connection:       nmcli connection edit \"$ACTIVE_CONN\""
echo "Forget network:        nmcli connection delete \"$ACTIVE_CONN\""
echo "List all networks:     nmcli device wifi list"
echo "Check status:          ./scripts/setup/verify_wifi_connection.sh"
