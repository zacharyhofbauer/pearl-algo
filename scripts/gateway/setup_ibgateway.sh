#!/bin/bash
# Complete IB Gateway setup script
# Merges functionality from setup_ibgateway_readonly.sh, configure_ibgateway_api.sh, and configure_ibc_readonly.sh

set -e

echo "=== IB Gateway Complete Setup ==="
echo ""

# Parse command line arguments
MODE="${1:-readonly}"  # readonly or full
IBC_MODE="${2:-yes}"   # yes to configure IBC, no to skip

echo "Mode: $MODE"
echo "IBC Configuration: $IBC_MODE"
echo ""

# 1. Configure jts.ini for API access
echo "1. Configuring jts.ini for API access..."
mkdir -p ~/pearlalgo-dev-ai-agents/ibkr/Jts

# Check if SocketPort already exists
if ! grep -q "SocketPort" ~/pearlalgo-dev-ai-agents/ibkr/Jts/jts.ini 2>/dev/null; then
    echo "   Adding API port settings..."
    cat >> ~/pearlalgo-dev-ai-agents/ibkr/Jts/jts.ini << 'EOF'

# API Configuration for Read-Only Data Access (added automatically)
SocketPort=4002
ReadOnlyAPI=true
EnableReadOnlyAPI=true
MasterAPIclientId=0
ApiOnly=true
TrustedIPs=127.0.0.1
UseSSL=false
EOF
    echo "   ✅ API settings added"
else
    echo "   ✅ API settings already exist"
fi

# 2. Configure IBC if requested
if [ "$IBC_MODE" = "yes" ]; then
    echo ""
    echo "2. Configuring IBC (IB Controller)..."
    cd ~/pearlalgo-dev-ai-agents/ibkr/ibc || exit 1
    
    # Backup existing config
    if [ -f config-auto.ini ]; then
        cp config-auto.ini "config-auto.ini.backup.$(date +%Y%m%d_%H%M%S)"
    fi
    
    # Create/update config for read-only API
    cat > config-auto.ini << 'EOF'
# IB Controller Configuration - Read-Only Data Access
# This configuration enables API access for data retrieval only (no trading)

# Trading Mode: paper trading account (safer for data access)
TradingMode=paper

# API Settings - READ ONLY
ReadOnlyApi=yes
EnableAPI=yes

# IB Directory (where Gateway settings are stored)
IbDir=/home/pearlalgo/pearlalgo-dev-ai-agents/ibkr/Jts

# Auto-restart settings (optional - keeps Gateway running)
AutoRestart=yes
RestartDaily=yes
RestartTime=03:00

# Logging
LogComponents=yes
LogToFile=yes
EOF
    
    echo "   ✅ IBC configured for read-only API access"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Configuration Summary:"
echo "  - API Only mode: Enabled"
echo "  - Read-Only API: Enabled (no trading)"
echo "  - Socket Port: 4002 (paper trading port)"
echo "  - Trusted IPs: 127.0.0.1 (localhost only)"
if [ "$IBC_MODE" = "yes" ]; then
    echo "  - IBC Configuration: Complete"
fi
echo ""
echo "Next steps:"
echo "  1. Start IB Gateway:"
if [ "$IBC_MODE" = "yes" ]; then
    echo "     cd ~/pearlalgo-dev-ai-agents/ibkr/ibc"
    echo "     ./gatewaystart.sh -inline"
else
    echo "     ./scripts/gateway/start_ibgateway_ibc.sh"
fi
echo "  2. Check status:"
echo "     ./scripts/gateway/check_gateway_status.sh"
echo "  3. Test connection:"
echo "     python3 scripts/testing/smoke_test_ibkr.py"





