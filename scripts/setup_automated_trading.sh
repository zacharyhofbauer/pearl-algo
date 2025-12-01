#!/bin/bash
# Setup script for automated trading systemd service

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="automated_trading.service"
SERVICE_FILE="$SCRIPT_DIR/$SERVICE_NAME"
SYSTEMD_PATH="/etc/systemd/system/$SERVICE_NAME"

echo "=========================================="
echo "Automated Trading Service Setup"
echo "=========================================="
echo ""

# Check if running as root for systemd operations
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  This script needs sudo for systemd operations."
    echo "   You can also manually copy the service file:"
    echo "   sudo cp $SERVICE_FILE $SYSTEMD_PATH"
    echo ""
    read -p "Continue with sudo? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
    SUDO="sudo"
else
    SUDO=""
fi

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Service file not found: $SERVICE_FILE"
    exit 1
fi

echo "📋 Service file: $SERVICE_FILE"
echo "📦 Target: $SYSTEMD_PATH"
echo ""

# Copy service file
echo "📝 Copying service file..."
$SUDO cp "$SERVICE_FILE" "$SYSTEMD_PATH"
echo "✅ Service file copied"

# Reload systemd
echo "🔄 Reloading systemd daemon..."
$SUDO systemctl daemon-reload
echo "✅ Systemd reloaded"

echo ""
echo "=========================================="
echo "Next Steps:"
echo "=========================================="
echo ""
echo "1. Edit the service file (optional):"
echo "   sudo nano $SYSTEMD_PATH"
echo ""
echo "2. Enable the service (starts on boot):"
echo "   sudo systemctl enable $SERVICE_NAME"
echo ""
echo "3. Start the service:"
echo "   sudo systemctl start $SERVICE_NAME"
echo ""
echo "4. Check status:"
echo "   sudo systemctl status $SERVICE_NAME"
echo ""
echo "5. View logs:"
echo "   sudo journalctl -u $SERVICE_NAME -f"
echo ""
echo "=========================================="

