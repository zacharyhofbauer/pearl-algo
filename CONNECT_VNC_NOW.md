# Quick VNC Connection Guide

## ✅ VNC is Ready!

**Your server IP**: 192.168.86.32  
**VNC Port**: 5901

## Connect Now:

### 1. From Your Local Machine, Create SSH Tunnel:

```bash
ssh -L 5901:localhost:5901 pearlalgo@192.168.86.32
```

**Keep this terminal open!**

### 2. Connect VNC Client:

- **Mac**: Open "Screen Sharing" → Connect to `localhost:5901`
- **Windows**: Use TightVNC Viewer → Connect to `localhost:5901`  
- **Linux**: `vncviewer localhost:5901`

**Password**: The one you set with `vncpasswd`

### 3. In VNC Window:

You should see a terminal window. Run:

```bash
export DISPLAY=:1
cd ~/ibc
./gatewaystart.sh
```

### 4. Complete IB Gateway Login

- Enter credentials
- Complete 2FA if needed
- Wait for login to complete

### 5. Verify It Worked:

```bash
ss -tuln | grep 4002
```

If you see port 4002, you're done! Close VNC and run headless:

```bash
cd ~/ibc
./gatewaystart.sh -inline
```

---

**Note**: If VNC shows a blank screen or just a terminal, that's fine - you just need to run the IB Gateway command in that terminal window.
