#!/bin/bash
# Setup VNC Server for IB Gateway GUI Access

echo "=== Setting up VNC Server for GUI Access ==="
echo ""

# Check if running as root (we'll use sudo)
if [ "$EUID" -eq 0 ]; then 
    SUDO=""
else
    SUDO="sudo"
fi

# 1. Install required packages
echo "1. Installing VNC server and lightweight desktop..."
$SUDO apt update
$SUDO apt install -y tigervnc-standalone-server xfce4 xfce4-goodies

# 2. Set VNC password (if not already set)
echo ""
echo "2. Setting up VNC password..."
if [ ! -f ~/.vnc/passwd ]; then
    echo "You'll be prompted to set a VNC password (for remote access)"
    vncserver
    vncserver -kill :1 2>/dev/null
else
    echo "VNC password already configured"
fi

# 3. Configure VNC startup
echo ""
echo "3. Configuring VNC startup script..."
mkdir -p ~/.vnc
cat > ~/.vnc/xstartup << 'EOF'
#!/bin/bash
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
[ -x /etc/vnc/xstartup ] && exec /etc/vnc/xstartup
[ -r $HOME/.Xresources ] && xrdb $HOME/.Xresources
x-window-manager &
startxfce4 &
EOF

chmod +x ~/.vnc/xstartup

# 4. Start VNC server
echo ""
echo "4. Starting VNC server..."
vncserver -kill :1 2>/dev/null
vncserver :1 -geometry 1920x1080 -depth 24

# 5. Display connection info
echo ""
echo "=== VNC Server Setup Complete ==="
echo ""
echo "✅ VNC server is running on display :1"
echo ""
echo "To connect from your local machine:"
echo ""
echo "Option 1: SSH Tunnel (Recommended - Secure)"
echo "  ssh -L 5901:localhost:5901 pearlalgo@$(hostname -I | awk '{print $1}')"
echo "  Then connect VNC client to: localhost:5901"
echo ""
echo "Option 2: Direct Connection (Less Secure)"
echo "  Connect VNC client to: $(hostname -I | awk '{print $1}'):5901"
echo ""
echo "VNC Display: :1"
echo "VNC Port: 5901"
echo ""
echo "To start IB Gateway in VNC:"
echo "  export DISPLAY=:1"
echo "  cd ~/ibc"
echo "  ./gatewaystart.sh"
echo ""
echo "To stop VNC server:"
echo "  vncserver -kill :1"
echo ""
echo "To restart VNC server:"
echo "  vncserver :1 -geometry 1920x1080 -depth 24"
