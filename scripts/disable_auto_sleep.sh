#!/bin/bash
#
# Disable Auto-Sleep for Beelink Mini PC
# This script disables automatic sleep/suspend to keep the system running 24/7
#

set -e

echo "🔧 Disabling auto-sleep on Beelink..."

# Check if running as root for system-level changes
if [ "$EUID" -ne 0 ]; then 
    echo "⚠️  Some commands require sudo. You may be prompted for your password."
    SUDO="sudo"
else
    SUDO=""
fi

# 1. Disable GNOME Power Manager sleep timeouts
echo "📱 Disabling GNOME power manager sleep timeouts..."
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout 0 2>/dev/null || echo "  (GNOME settings not available, skipping)"
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-timeout 0 2>/dev/null || echo "  (GNOME settings not available, skipping)"
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing' 2>/dev/null || echo "  (GNOME settings not available, skipping)"
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing' 2>/dev/null || echo "  (GNOME settings not available, skipping)"

# 2. Configure systemd-logind to ignore suspend/hibernate
echo "⚙️  Configuring systemd-logind..."
LOGIND_CONF="/etc/systemd/logind.conf"
LOGIND_CONF_BAK="/etc/systemd/logind.conf.backup.$(date +%Y%m%d_%H%M%S)"

# Backup original config
if [ -f "$LOGIND_CONF" ]; then
    $SUDO cp "$LOGIND_CONF" "$LOGIND_CONF_BAK"
    echo "  ✓ Backed up original config to $LOGIND_CONF_BAK"
fi

# Create or update logind.conf with settings to prevent sleep
$SUDO tee -a "$LOGIND_CONF" > /dev/null <<EOF

# Disable auto-sleep for NQ Agent (added by disable_auto_sleep.sh)
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
HandleSuspendKey=ignore
IdleAction=ignore
EOF

echo "  ✓ Updated systemd-logind.conf"

# 3. Restart systemd-logind to apply changes
echo "🔄 Restarting systemd-logind..."
$SUDO systemctl restart systemd-logind 2>/dev/null || echo "  ⚠️  Could not restart systemd-logind (may require reboot)"

# 4. Mask sleep targets (prevent them from being activated)
echo "🚫 Masking sleep targets..."
$SUDO systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target 2>/dev/null || echo "  ⚠️  Could not mask sleep targets"

# 5. Set systemd to prevent idle action
echo "⏸️  Setting idle action to ignore..."
$SUDO systemctl set-property --runtime systemd-logind.service IdleAction=ignore 2>/dev/null || echo "  ⚠️  Could not set idle action"

# 6. Check for other power management tools
if command -v xset >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
    echo "🖥️  Disabling X11 DPMS (Display Power Management)..."
    xset s off 2>/dev/null || true
    xset -dpms 2>/dev/null || true
    xset s noblank 2>/dev/null || true
    echo "  ✓ Disabled X11 screen saver and DPMS"
fi

# 7. Check if systemctl-inhibit is available and create a service to keep system awake
if command -v systemd-inhibit >/dev/null 2>&1; then
    echo "🔒 systemd-inhibit available (can be used to prevent sleep)"
fi

echo ""
echo "✅ Auto-sleep disabled!"
echo ""
echo "📝 Summary:"
echo "  • GNOME power manager: Sleep disabled"
echo "  • systemd-logind: Sleep actions ignored"
echo "  • Sleep targets: Masked"
echo ""
echo "⚠️  Note: Some changes may require a reboot to take full effect."
echo "   If the system still sleeps after this script, try rebooting."
echo ""
echo "🔄 To re-enable sleep in the future, run: scripts/enable_auto_sleep.sh"

