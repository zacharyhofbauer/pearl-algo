#!/bin/bash
# Deploy 24/7 Continuous Service

set -e

echo "=========================================="
echo "PearlAlgo 24/7 Continuous Service Deployment"
echo "=========================================="
echo

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  This script needs sudo privileges to install systemd service"
    echo "   Please run: sudo $0"
    exit 1
fi

# Get project directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="pearlalgo-continuous-service.service"

echo "Project root: $PROJECT_ROOT"
echo "Service name: $SERVICE_NAME"
echo

# Check if virtual environment exists
if [ ! -d "$PROJECT_ROOT/.venv" ]; then
    echo "❌ Virtual environment not found at $PROJECT_ROOT/.venv"
    echo "   Please create it first: python3 -m venv .venv"
    exit 1
fi

# Check if .env file exists
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "⚠️  .env file not found"
    echo "   Please create .env file with:"
    echo "   - MASSIVE_API_KEY"
    echo "   - TELEGRAM_BOT_TOKEN"
    echo "   - TELEGRAM_CHAT_ID"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Create log directory
echo "📁 Creating log directory..."
mkdir -p "$PROJECT_ROOT/logs"
chown -R pearlalgo:pearlalgo "$PROJECT_ROOT/logs" 2>/dev/null || true

# Create data/buffers directory for persistence
echo "📁 Creating data directories..."
mkdir -p "$PROJECT_ROOT/data/buffers"
mkdir -p "$PROJECT_ROOT/logs"
chown -R pearlalgo:pearlalgo "$PROJECT_ROOT/data" 2>/dev/null || true
chown -R pearlalgo:pearlalgo "$PROJECT_ROOT/logs" 2>/dev/null || true

# Install systemd service
echo "📦 Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

# Create service file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=PearlAlgo 24/7 Continuous Trading Service
After=network.target
Wants=network.target

[Service]
Type=simple
User=pearlalgo
Group=pearlalgo
WorkingDirectory=$PROJECT_ROOT
Environment="PATH=$PROJECT_ROOT/.venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"

# Load environment variables from .env
$(grep -v '^#' "$PROJECT_ROOT/.env" | grep -v '^$' | sed 's/^/Environment="/;s/$/"/')

# Main service command
ExecStart=$PROJECT_ROOT/.venv/bin/python -m pearlalgo.monitoring.continuous_service \\
    --config $PROJECT_ROOT/config/config.yaml \\
    --log-file $PROJECT_ROOT/logs/continuous_service.log \\
    --health-port 8080

# Restart policy
Restart=always
RestartSec=30
StartLimitInterval=300
StartLimitBurst=5

# Resource limits
MemoryMax=2G
CPUQuota=50%

# Security
NoNewPrivileges=true
PrivateTmp=true

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=pearlalgo-signals

[Install]
WantedBy=multi-user.target
EOF

echo "✅ Service file created: $SERVICE_FILE"

# Reload systemd
echo "🔄 Reloading systemd..."
systemctl daemon-reload

# Enable service
echo "🔌 Enabling service..."
systemctl enable "$SERVICE_NAME"

echo
echo "=========================================="
echo "✅ Deployment Complete!"
echo "=========================================="
echo
echo "Next steps:"
echo "1. Start the service:"
echo "   sudo systemctl start $SERVICE_NAME"
echo
echo "2. Check service status:"
echo "   sudo systemctl status $SERVICE_NAME"
echo
echo "3. View logs:"
echo "   sudo journalctl -u $SERVICE_NAME -f"
echo "   or"
echo "   tail -f $PROJECT_ROOT/logs/signal_generation.log"
echo
echo "4. Check health endpoint:"
echo "   curl http://localhost:8080/healthz"
echo
echo "5. Run health check:"
echo "   cd $PROJECT_ROOT && source .venv/bin/activate"
echo "   python scripts/signal_health_monitor.py"
echo
echo "6. Stop the service:"
echo "   sudo systemctl stop $SERVICE_NAME"
echo
echo "For more information, see:"
echo "   - docs/24_7_OPERATIONS_GUIDE.md"
echo "   - docs/OPTIONS_SCANNING_GUIDE.md"
echo

