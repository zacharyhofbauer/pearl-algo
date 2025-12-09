#!/bin/bash
# Deploy 24/7 Signal Generation Service

set -e

echo "=========================================="
echo "PearlAlgo 24/7 Signal Generation Deployment"
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
SERVICE_NAME="pearlalgo-signal_service.service"

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
    echo "   - POLYGON_API_KEY"
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

# Make scripts executable
echo "🔧 Making scripts executable..."
chmod +x "$PROJECT_ROOT/scripts/signal_generation_service.py"
chmod +x "$PROJECT_ROOT/scripts/signal_health_monitor.py"

# Install systemd service
echo "📦 Installing systemd service..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

# Create service file
cat > "$SERVICE_FILE" << EOF
[Unit]
Description=PearlAlgo 24/7 Signal Generation Service (Polygon)
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
ExecStart=$PROJECT_ROOT/.venv/bin/python \\
    $PROJECT_ROOT/scripts/signal_generation_service.py \\
    --symbols ES NQ MES MNQ \\
    --strategy sr \\
    --interval 300 \\
    --log-file logs/signal_generation.log \\
    --max-retries 3 \\
    --retry-backoff 60.0

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
echo "4. Run health check:"
echo "   cd $PROJECT_ROOT && source .venv/bin/activate"
echo "   python scripts/signal_health_monitor.py"
echo
echo "5. Stop the service:"
echo "   sudo systemctl stop $SERVICE_NAME"
echo

