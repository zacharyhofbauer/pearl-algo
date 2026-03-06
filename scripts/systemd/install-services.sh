#!/bin/bash
# PearlAlgo Systemd Services Installer
# Run with: sudo ./install-services.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== PearlAlgo Systemd Services Installer ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root: sudo $0"
    exit 1
fi

# Remove stale service if it exists
if [ -f "$SYSTEMD_DIR/pearlalgo-api-mffu.service" ]; then
    echo "Removing stale pearlalgo-api-mffu.service..."
    systemctl disable --now pearlalgo-api-mffu.service 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/pearlalgo-api-mffu.service"
fi

# Copy service files (only those present in SCRIPT_DIR)
echo "Installing service files..."
for f in ibkr-gateway.service pearlalgo-agent.service pearlalgo-api.service pearlalgo-webapp.service pearlalgo-telegram.service; do
    if [ -f "$SCRIPT_DIR/$f" ]; then
        cp "$SCRIPT_DIR/$f" "$SYSTEMD_DIR/"
    else
        echo "  (skip $f - not found)"
    fi
done

# Reload systemd
echo "Reloading systemd..."
systemctl daemon-reload

echo ""
echo "=== Services Installed ==="
echo ""
echo "Available services:"
echo "  - ibkr-gateway       : IBKR Gateway (must start first)"
echo "  - pearlalgo-agent    : Market Agent (use CONFIG_PATH for account)"
echo "  - pearlalgo-api      : API Server (port 8001)"
echo "  - pearlalgo-webapp   : Web App (port 3001)"
echo "  - pearlalgo-telegram : Telegram Handler"
echo ""
echo "Commands:"
echo "  Start all:     sudo systemctl start ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-webapp pearlalgo-telegram"
echo "  Stop all:      sudo systemctl stop pearlalgo-telegram pearlalgo-webapp pearlalgo-api pearlalgo-agent ibkr-gateway"
echo "  Enable boot:   sudo systemctl enable ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-webapp pearlalgo-telegram"
echo "  Disable boot:  sudo systemctl disable ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-webapp pearlalgo-telegram"
echo "  Check status:  sudo systemctl status pearlalgo-*"
echo ""
echo "View logs:"
echo "  journalctl -u pearlalgo-agent -f"
echo ""
