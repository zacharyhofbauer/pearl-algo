# WiFi Migration Guide for Beelink Server

This guide helps ensure smooth WiFi connectivity when moving your Beelink server to a new location.

## Pre-Migration Checklist

**⚠️ IMPORTANT: Run this BEFORE moving to ensure auto-connect works!**

### Quick Pre-Migration Check
```bash
# Run the automated pre-migration checklist
cd /path/to/pearlalgo-dev-ai-agents
./scripts/setup/pre_migration_check.sh
```

This will verify:
- ✅ XPRS connection exists
- ✅ Auto-connect is enabled
- ✅ Credentials are saved
- ✅ NetworkManager is running

### Ensure Auto-Connect is Enabled
```bash
# This script will:
# - Create XPRS connection if it doesn't exist
# - Enable auto-connect
# - Save credentials
# - Set high priority for auto-connection
./scripts/setup/ensure_auto_connect.sh
```

### Manual Pre-Migration Steps (Optional)

#### 1. Document Current WiFi Settings
```bash
# Save current WiFi configuration
nmcli connection show --active > ~/wifi_backup_$(date +%Y%m%d).txt
```

#### 2. Check Current Network Configuration
```bash
# View current IP and connection
ip addr show
nmcli device status
```

## Post-Migration Steps

### Step 1: Connect to New WiFi Network

#### Quick Connect (Same Network, New Location)
If you're connecting to the **same network** (e.g., XPRS) at a new location:

```bash
# Use the automated connection script
cd /path/to/pearlalgo-dev-ai-agents
./scripts/setup/connect_xprs.sh
```

This script will:
- Check if already connected
- Use saved connection if available
- Connect with credentials if needed
- Verify connectivity automatically

#### Option A: Using NetworkManager (GUI/CLI)
```bash
# List available networks
nmcli device wifi list

# Connect to new network
nmcli device wifi connect <SSID> password <PASSWORD>

# Or if you need to specify interface
nmcli device wifi connect <SSID> password <PASSWORD> ifname wlan0
```

#### Option B: Using wpa_supplicant (if NetworkManager not available)
```bash
# Edit wpa_supplicant config
sudo nano /etc/wpa_supplicant/wpa_supplicant.conf

# Add network block:
network={
    ssid="YOUR_NEW_SSID"
    psk="YOUR_PASSWORD"
    key_mgmt=WPA2-PSK
}

# Restart wpa_supplicant
sudo systemctl restart wpa_supplicant
```

### Step 2: Verify Connection

Run the verification script:
```bash
cd /path/to/pearlalgo-dev-ai-agents
./scripts/setup/verify_wifi_connection.sh
```

This will check:
- ✅ WiFi interface detection
- ✅ IP address assignment
- ✅ Gateway connectivity
- ✅ DNS resolution
- ✅ Internet connectivity
- ✅ IBKR Gateway status (if running)

### Step 3: Test IBKR Gateway Connection

```bash
# Check Gateway status
./scripts/gateway/gateway.sh status

# If Gateway is running, verify API port
./scripts/gateway/gateway.sh api-ready

# Test API connection
./scripts/gateway/gateway.sh test-api
```

### Step 4: Verify Trading System Services

```bash
# Check NQ Agent service (if running as systemd service)
systemctl status nq-agent.service

# Test IBKR data connection
python3 scripts/testing/smoke_test_ibkr.py
```

## Network Configuration Notes

### Important: No Code Changes Required

The PearlAlgo trading system uses **localhost (127.0.0.1)** for IBKR Gateway connections, which means:
- ✅ **No IP address changes needed** in code
- ✅ **No configuration file updates** required
- ✅ Gateway runs locally on the server

### What Changes with WiFi:

1. **Internet connectivity** - Required for:
   - IBKR Gateway authentication (2FA via mobile app)
   - Telegram bot API (if using Telegram notifications)
   - Market data subscriptions (if using external data providers)

2. **VNC connections** (if using VNC for Gateway):
   - VNC server IP will change with new WiFi
   - Update VNC client connection to new server IP
   - Or use SSH tunnel: `ssh -L 5901:localhost:5901 user@new-server-ip`

### Static vs Dynamic IP

**Recommended: Use Dynamic IP (DHCP)**
- Most WiFi networks use DHCP
- No configuration needed
- Works automatically after connecting

**If you need Static IP:**
```bash
# Edit NetworkManager connection
sudo nmcli connection modify <CONNECTION_NAME> ipv4.method manual
sudo nmcli connection modify <CONNECTION_NAME> ipv4.addresses 192.168.1.100/24
sudo nmcli connection modify <CONNECTION_NAME> ipv4.gateway 192.168.1.1
sudo nmcli connection modify <CONNECTION_NAME> ipv4.dns "8.8.8.8 8.8.4.4"
sudo nmcli connection up <CONNECTION_NAME>
```

## Troubleshooting

### WiFi Not Connecting

1. **Check WiFi interface:**
   ```bash
   ip link show
   sudo ip link set wlan0 up  # Replace wlan0 with your interface
   ```

2. **Check NetworkManager:**
   ```bash
   sudo systemctl status NetworkManager
   sudo systemctl restart NetworkManager
   ```

3. **Check WiFi driver:**
   ```bash
   lspci | grep -i network
   lsmod | grep -i wifi
   ```

### Connection Drops Frequently

1. **Check signal strength:**
   ```bash
   nmcli device wifi list
   iwconfig  # Shows signal quality
   ```

2. **Disable power management:**
   ```bash
   sudo iwconfig wlan0 power off
   ```

3. **Check for interference:**
   - Use 5GHz band if available (less interference)
   - Move server closer to router
   - Check for other 2.4GHz devices

### IBKR Gateway Can't Connect

1. **Verify internet connectivity:**
   ```bash
   ping -c 3 8.8.8.8
   ```

2. **Check Gateway logs:**
   ```bash
   tail -f ibkr/ibc/logs/ibc-*.txt
   ```

3. **Restart Gateway:**
   ```bash
   ./scripts/gateway/gateway.sh stop
   ./scripts/gateway/gateway.sh start
   ```

### Telegram Bot Not Working

1. **Check internet connectivity** (Telegram needs internet)
2. **Verify Telegram bot token** in `.env` file
3. **Test Telegram API:**
   ```bash
   curl https://api.telegram.org/bot<TOKEN>/getMe
   ```

## Before Moving: Ensure Auto-Connect

**Run this NOW (before moving) to ensure it auto-connects:**

```bash
# 1. Run pre-migration checklist
./scripts/setup/pre_migration_check.sh

# 2. If anything fails, fix it:
./scripts/setup/ensure_auto_connect.sh

# 3. Verify again
./scripts/setup/pre_migration_check.sh
```

This ensures that when you plug in at the new location, the server will **automatically connect to XPRS** without any manual steps.

## Quick Verification Commands

After connecting to new WiFi, run these in order:

```bash
# 1. Connect to XPRS (if same network at new location)
./scripts/setup/connect_xprs.sh

# OR manually connect:
nmcli device wifi connect "XPRS" password "Express1"

# 2. Verify WiFi connection
./scripts/setup/verify_wifi_connection.sh

# 3. Check Gateway status
./scripts/gateway/gateway.sh status

# 4. Test IBKR API
./scripts/gateway/gateway.sh test-api

# 5. Test data connection
python3 scripts/testing/smoke_test_ibkr.py
```

## Network Requirements Summary

| Component | Network Requirement | Notes |
|-----------|---------------------|-------|
| IBKR Gateway | Internet (for auth) | Uses localhost (127.0.0.1) for API |
| NQ Agent | Internet (optional) | Only if using Telegram |
| Telegram Bot | Internet | Required for notifications |
| VNC Server | Local network | Only if using VNC |
| Market Data | Internet | Via IBKR Gateway |

## Best Practices

1. **Use 5GHz WiFi** if available (more stable, less interference)
2. **Keep server close to router** for strong signal
3. **Use wired Ethernet** if possible (most reliable)
4. **Monitor connection stability** after migration:
   ```bash
   watch -n 5 'nmcli device status && echo "" && ping -c 1 8.8.8.8'
   ```
5. **Set up auto-reconnect** (NetworkManager does this by default)

## Emergency: No WiFi Available

If WiFi is not available at new location:

1. **Use Ethernet cable** (most reliable)
2. **Use mobile hotspot** temporarily:
   ```bash
   nmcli device wifi connect "Hotspot-Name" password "password"
   ```
3. **Use USB WiFi adapter** if built-in WiFi fails

---

**Last Updated:** 2025-01-XX  
**Tested On:** Beelink Mini PC, Ubuntu 22.04
