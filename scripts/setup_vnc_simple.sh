#!/bin/bash
# Set VNC password non-interactively and start VNC

echo "Setting up VNC password..."

# Create VNC directory
mkdir -p ~/.vnc

# Set VNC password (you'll need to run this interactively or provide password)
# For now, we'll create a simple password setup
if [ ! -f ~/.vnc/passwd ]; then
    echo "VNC password file not found."
    echo ""
    echo "To set VNC password, run this command:"
    echo "  vncpasswd"
    echo ""
    echo "Or set it non-interactively (less secure):"
    echo "  echo 'your_password' | vncpasswd -f > ~/.vnc/passwd"
    echo "  chmod 600 ~/.vnc/passwd"
    echo ""
    echo "For now, let's try to start VNC with a default setup..."
fi

# Create xstartup if it doesn't exist
mkdir -p ~/.vnc
if [ ! -f ~/.vnc/xstartup ]; then
    cat > ~/.vnc/xstartup << 'EOF'
#!/bin/bash
startxfce4 &
EOF
    chmod +x ~/.vnc/xstartup
fi

# Kill any existing VNC
vncserver -kill :1 2>/dev/null

# Try to start VNC (will prompt for password if not set)
echo ""
echo "Starting VNC server..."
echo "If prompted, set a password (you'll use this to connect)"
vncserver :1 -geometry 1920x1080 -depth 24

sleep 2

# Check if it's running
if ss -tuln | grep -q ":5901"; then
    echo ""
    echo "✅ VNC server is running on port 5901!"
    echo ""
    echo "Your server IP appears to be: $(hostname -I | awk '{print $1}')"
    echo ""
    echo "To connect:"
    echo "  1. From your local machine:"
    echo "     ssh -L 5901:localhost:5901 pearlalgo@$(hostname -I | awk '{print $1}')"
    echo ""
    echo "  2. Connect VNC client to: localhost:5901"
    echo ""
    echo "  3. In VNC, run IB Gateway:"
    echo "     export DISPLAY=:1"
    echo "     cd ~/ibc"
    echo "     ./gatewaystart.sh"
else
    echo ""
    echo "⚠️  VNC may need password setup first"
    echo "Run: vncpasswd"
    echo "Then run this script again"
fi
