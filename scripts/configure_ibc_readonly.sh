# IB Controller Configuration for Read-Only Data Access
# This configures IBC to run IB Gateway in read-only mode (data only, no trading)

cd ~/ibc

# Backup existing config
cp config-auto.ini config-auto.ini.backup.$(date +%Y%m%d_%H%M%S) 2>/dev/null

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
IbDir=~/Jts

# Auto-restart settings (optional - keeps Gateway running)
AutoRestart=yes
RestartDaily=yes
RestartTime=03:00

# Logging
LogComponents=yes
LogToFile=yes
EOF

echo "✅ Configured IBC for read-only API access"
echo ""
echo "Configuration:"
echo "  - Trading Mode: paper (safe for data access)"
echo "  - Read-Only API: enabled"
echo "  - API Enabled: yes"
echo ""
echo "To start IB Gateway with IBC:"
echo "  cd ~/ibc"
echo "  ./gatewaystart.sh -inline"
echo ""
echo "Or run in background:"
echo "  nohup ~/ibc/gatewaystart.sh -inline > ~/ibc/logs/gateway.log 2>&1 &"
