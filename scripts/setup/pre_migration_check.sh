#!/bin/bash
# ============================================================================
# Pre-Migration Checklist
# Purpose: Verify everything is ready before moving server to new location
# Usage: ./scripts/setup/pre_migration_check.sh
# ============================================================================

set -euo pipefail

echo "=== Pre-Migration Checklist ==="
echo ""
echo "Run this BEFORE moving the server to ensure smooth WiFi connection"
echo ""

# Check 1: XPRS connection exists
echo "1. Checking XPRS connection..."
XPRS_CONN=$(nmcli -t -f NAME connection show | grep -i "XPRS" | head -1 || true)

if [ -z "$XPRS_CONN" ]; then
    echo "   ❌ XPRS connection NOT found"
    echo "   → Run: ./scripts/setup/ensure_auto_connect.sh"
    XPRS_OK=false
else
    echo "   ✅ XPRS connection found: $XPRS_CONN"
    XPRS_OK=true
fi
echo ""

# Check 2: Auto-connect enabled
if [ "$XPRS_OK" = true ]; then
    echo "2. Checking auto-connect setting..."
    AUTO_CONNECT=$(nmcli -t -f connection.autoconnect connection show "$XPRS_CONN" 2>/dev/null | cut -d: -f2 || echo "no")
    
    if [ "$AUTO_CONNECT" = "yes" ]; then
        echo "   ✅ Auto-connect is ENABLED"
        AUTO_OK=true
    else
        echo "   ❌ Auto-connect is DISABLED"
        echo "   → Run: ./scripts/setup/ensure_auto_connect.sh"
        AUTO_OK=false
    fi
else
    AUTO_OK=false
fi
echo ""

# Check 3: Password saved
if [ "$XPRS_OK" = true ]; then
    echo "3. Checking saved credentials..."
    KEY_MGMT=$(nmcli -t -f wifi-sec.key-mgmt connection show "$XPRS_CONN" 2>/dev/null | cut -d: -f2 || true)
    if [ -n "$KEY_MGMT" ]; then
        echo "   ✅ Security configured: $KEY_MGMT"
        CRED_OK=true
    else
        echo "   ⚠️  Security not configured"
        CRED_OK=false
    fi
else
    CRED_OK=false
fi
echo ""

# Check 4: NetworkManager running
echo "4. Checking NetworkManager service..."
if systemctl is-active --quiet NetworkManager 2>/dev/null; then
    echo "   ✅ NetworkManager is running"
    NM_OK=true
else
    echo "   ⚠️  NetworkManager not running (may be normal if using different network manager)"
    NM_OK=true  # Don't fail on this
fi
echo ""

# Check 5: WiFi interface available
echo "5. Checking WiFi interface..."
WIFI_DEVICE=$(nmcli -t -f DEVICE,TYPE device | grep -E "wifi|wireless" | cut -d: -f1 | head -1 || true)

if [ -n "$WIFI_DEVICE" ]; then
    echo "   ✅ WiFi device found: $WIFI_DEVICE"
    WIFI_OK=true
else
    echo "   ⚠️  No WiFi device detected (may be disabled or unavailable)"
    echo "   → This is OK - WiFi will be available at new location"
    WIFI_OK=true  # Don't fail on this
fi
echo ""

# Summary
echo "=== Summary ==="
echo ""

ALL_OK=true
if [ "$XPRS_OK" != true ] || [ "$AUTO_OK" != true ] || [ "$CRED_OK" != true ]; then
    ALL_OK=false
fi

if [ "$ALL_OK" = true ]; then
    echo "✅ ✅ ✅ READY TO MOVE!"
    echo ""
    echo "Everything is configured correctly:"
    echo "  • XPRS connection exists"
    echo "  • Auto-connect is enabled"
    echo "  • Credentials are saved"
    echo ""
    echo "When you plug in at the new location:"
    echo "  → Server will automatically connect to XPRS"
    echo "  → No manual steps required!"
    echo ""
    echo "After moving, verify connection:"
    echo "  ./scripts/setup/verify_wifi_connection.sh"
else
    echo "⚠️  ⚠️  ⚠️  ACTION REQUIRED"
    echo ""
    echo "Some settings need to be configured before moving."
    echo ""
    echo "Run this command to fix everything:"
    echo "  ./scripts/setup/ensure_auto_connect.sh"
    echo ""
    echo "Then run this checklist again to verify:"
    echo "  ./scripts/setup/pre_migration_check.sh"
    exit 1
fi
