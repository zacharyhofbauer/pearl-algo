# IB Gateway Configuration for Read-Only Data Access
# This file configures IB Gateway to enable API access for data only (no trading)

# Create jts.ini with API enabled for read-only access
mkdir -p ~/pearlalgo-dev-ai-agents/ibkr/Jts

cat > ~/pearlalgo-dev-ai-agents/ibkr/Jts/jts.ini << 'EOF'
[Logon]
# API Settings
ApiOnly=true
TrustedIPs=127.0.0.1
ReadOnlyAPI=true
SocketPort=4002
MasterAPIclientId=0
EnableReadOnlyAPI=true

# Connection settings
UseSSL=false
EOF

echo "✅ Created ~/pearlalgo-dev-ai-agents/ibkr/Jts/jts.ini with read-only API enabled"
echo ""
echo "Configuration:"
echo "  - API Only mode: Enabled"
echo "  - Read-Only API: Enabled (no trading)"
echo "  - Socket Port: 4002 (paper trading port)"
echo "  - Trusted IPs: 127.0.0.1 (localhost only)"
echo ""
echo "Now start IB Gateway:"
echo "  cd ~/pearlalgo-dev-ai-agents/ibkr/Jts/ibgateway/1041"
echo "  xvfb-run -a ./ibgateway1 &"
