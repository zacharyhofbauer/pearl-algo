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

# Copy service files
echo "Installing service files..."
cp "$SCRIPT_DIR/ibkr-gateway.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-agent.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-api.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-api-mffu.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-webapp.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-telegram.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-monitor.service" "$SYSTEMD_DIR/"
cp "$SCRIPT_DIR/pearlalgo-monitor.timer" "$SYSTEMD_DIR/"

# Reload systemd
echo "Reloading systemd..."
systemctl daemon-reload

echo ""
echo "=== Services Installed ==="
echo ""
echo "Available services:"
echo "  - ibkr-gateway        : IBKR Gateway (must start first)"
echo "  - pearlalgo-agent     : Market Agent (NQ)"
echo "  - pearlalgo-api       : API Server - NQ/Inception (port 8000)"
echo "  - pearlalgo-api-mffu  : API Server - MFFU Eval (port 8001)"
echo "  - pearlalgo-webapp    : Web App (port 3001)"
echo "  - pearlalgo-telegram  : Telegram Handler"
echo "  - pearlalgo-monitor   : Health monitor (runs every 5 min)"
echo ""
echo "Commands:"
echo "  Start all:     sudo systemctl start ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-api-mffu pearlalgo-webapp pearlalgo-telegram"
echo "  Stop all:      sudo systemctl stop pearlalgo-telegram pearlalgo-webapp pearlalgo-api-mffu pearlalgo-api pearlalgo-agent ibkr-gateway"
echo "  Enable boot:   sudo systemctl enable ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-api-mffu pearlalgo-webapp pearlalgo-telegram"
echo "  Disable boot:  sudo systemctl disable ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-api-mffu pearlalgo-webapp pearlalgo-telegram"
echo "  Check status:  sudo systemctl status pearlalgo-*"
echo ""
echo "Enable monitoring:"
echo "  sudo systemctl enable --now pearlalgo-monitor.timer"
echo ""
echo "View logs:"
echo "  journalctl -u pearlalgo-agent -f"
echo "  journalctl -u pearlalgo-monitor --since '1 hour ago'"
echo ""
