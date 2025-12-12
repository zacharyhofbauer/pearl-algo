#!/bin/bash
# Quick VNC setup - minimal version

echo "Setting up VNC for IB Gateway access..."

# Install if needed
if ! command -v vncserver >/dev/null 2>&1; then
    echo "Installing VNC server..."
    sudo apt update
    sudo apt install -y tigervnc-standalone-server xfce4
fi

# Kill any existing VNC
vncserver -kill :1 2>/dev/null

# Create startup script
mkdir -p ~/.vnc
cat > ~/.vnc/xstartup << 'EOF'
#!/bin/bash
startxfce4 &
EOF
chmod +x ~/.vnc/xstartup

# Set password if needed
if [ ! -f ~/.vnc/passwd ]; then
    echo "Setting VNC password (you'll be prompted)..."
    vncserver
    vncserver -kill :1 2>/dev/null
fi

# Start VNC
echo "Starting VNC server on display :1..."
vncserver :1 -geometry 1920x1080

echo ""
echo "✅ VNC server started!"
echo ""
echo "To connect:"
echo "  1. From your local machine, create SSH tunnel:"
echo "     ssh -L 5901:localhost:5901 pearlalgo@$(hostname -I | awk '{print $1}')"
echo ""
echo "  2. Connect VNC client to: localhost:5901"
echo ""
echo "  3. In VNC, open terminal and run:"
echo "     export DISPLAY=:1"
echo "     cd ~/pearlalgo-dev-ai-agents/ibkr/ibc"
echo "     ./gatewaystart.sh"
echo ""
echo "VNC password is stored in: ~/.vnc/passwd"
