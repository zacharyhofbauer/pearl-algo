#!/bin/bash
# PearlAlgo Position Sizing Validation
# Checks ALL config files for MFF compliance (all values must = 1)

set -e

echo "=== PearlAlgo Position Sizing Check ==="
echo ""

CONFIG_DIR=~/PearlAlgoProject/config
ERRORS=0

echo "📋 Checking base.yaml..."
echo ""

# Check base.yaml position sizing settings
BASE_SETTINGS=$(grep -E "position_size|base_contracts|high_conf_contracts|max_conf_contracts" "$CONFIG_DIR/base.yaml" | grep -v "^#" || true)

if [ -z "$BASE_SETTINGS" ]; then
    echo "⚠️  No position sizing settings found in base.yaml"
    ERRORS=$((ERRORS + 1))
else
    echo "$BASE_SETTINGS"
    echo ""
    
    # Check if any value != 1
    if echo "$BASE_SETTINGS" | grep -qv ": 1$"; then
        echo "❌ base.yaml has values != 1"
        ERRORS=$((ERRORS + 1))
    else
        echo "✅ base.yaml: all position sizing = 1"
    fi
fi

echo ""
echo "📋 Checking accounts/tradovate_paper.yaml..."
echo ""

# Check account-specific overrides
ACCOUNT_FILE="$CONFIG_DIR/accounts/tradovate_paper.yaml"

if [ ! -f "$ACCOUNT_FILE" ]; then
    echo "⚠️  Account file not found: $ACCOUNT_FILE"
    ERRORS=$((ERRORS + 1))
else
    ACCOUNT_SETTINGS=$(grep -E "contracts" "$ACCOUNT_FILE" | grep -v "^#" || true)
    
    if [ -z "$ACCOUNT_SETTINGS" ]; then
        echo "ℹ️  No contract settings in tradovate_paper.yaml (uses base.yaml defaults)"
    else
        echo "$ACCOUNT_SETTINGS"
        echo ""
        
        # Check if any value != 1
        if echo "$ACCOUNT_SETTINGS" | grep -qv ": 1$"; then
            echo "❌ tradovate_paper.yaml has values != 1"
            ERRORS=$((ERRORS + 1))
        else
            echo "✅ tradovate_paper.yaml: all contract limits = 1"
        fi
    fi
fi

echo ""
echo "================================="

if [ "$ERRORS" -eq 0 ]; then
    echo "✅ MFF COMPLIANT: All position sizing settings = 1"
    exit 0
else
    echo "❌ VIOLATIONS FOUND: $ERRORS issue(s) detected"
    echo ""
    echo "All values must = 1 for MFF compliance (5 contract TOTAL limit)"
    exit 1
fi
