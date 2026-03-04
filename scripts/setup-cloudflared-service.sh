#!/bin/bash
# ============================================================================
# Setup Cloudflared as a Systemd Service
# Purpose: Install cloudflared tunnel as an auto-starting, auto-restarting service
# Usage: sudo ./scripts/setup-cloudflared-service.sh
# ============================================================================

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ Please run with sudo: sudo $0"
    exit 1
fi

SERVICE_NAME="cloudflared-pearlalgo"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
CONFIG_PATH="/home/pearlalgo/.cloudflared/config.yml"
CLOUDFLARED_BIN="/usr/local/bin/cloudflared"

echo "========================================"
echo "  Setting up Cloudflare Tunnel Service"
echo "========================================"
echo ""

# Verify cloudflared exists
if [ ! -f "$CLOUDFLARED_BIN" ]; then
    echo "❌ cloudflared not found at $CLOUDFLARED_BIN"
    exit 1
fi

# Verify config exists
if [ ! -f "$CONFIG_PATH" ]; then
    echo "❌ Config not found at $CONFIG_PATH"
    exit 1
fi

echo "✓ cloudflared binary: $CLOUDFLARED_BIN"
echo "✓ Config file: $CONFIG_PATH"
echo ""

# Stop any existing cloudflared processes
echo "Stopping any running cloudflared processes..."
pkill -f "cloudflared.*tunnel run" 2>/dev/null || true
sleep 1

# Create systemd service file
echo "Creating systemd service at $SERVICE_FILE..."
cat > "$SERVICE_FILE" << 'SERVICEEOF'
[Unit]
Description=Cloudflare Tunnel for pearlalgo.io
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pearl
ExecStart=/usr/local/bin/cloudflared --config /home/pearlalgo/.cloudflared/config.yml tunnel run
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICEEOF

echo "✓ Service file created"

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service (auto-start on boot)
echo "Enabling service for auto-start on boot..."
systemctl enable "$SERVICE_NAME"

# Start service
echo "Starting service..."
systemctl start "$SERVICE_NAME"

# Wait for it to start
sleep 3

# Check status
echo ""
echo "========================================"
echo "  Service Status"
echo "========================================"
systemctl status "$SERVICE_NAME" --no-pager || true

echo ""
echo "========================================"
echo "  ✅ Cloudflare Tunnel Service Installed!"
echo "========================================"
echo ""
echo "Commands:"
echo "  systemctl status $SERVICE_NAME    # Check status"
echo "  systemctl restart $SERVICE_NAME   # Restart"
echo "  systemctl stop $SERVICE_NAME      # Stop"
echo "  journalctl -u $SERVICE_NAME -f    # View logs"
echo ""
echo "The tunnel will now:"
echo "  • Auto-start on boot"
echo "  • Auto-restart if it crashes"
echo "  • Always keep pearlalgo.io accessible"
echo ""
