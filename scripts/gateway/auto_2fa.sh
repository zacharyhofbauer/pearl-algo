#!/bin/bash
# Auto-enter 2FA code for IBKR Gateway
# This script monitors for 2FA codes and automatically enters them

echo "=== Auto 2FA Entry for IBKR Gateway ==="
echo ""

# Check if Gateway is running
if ! pgrep -f "java.*IBC.jar" > /dev/null; then
    echo "❌ IB Gateway is not running!"
    exit 1
fi

echo "✅ Gateway is running"
echo ""

# Method 1: Read from file (if you can write 2FA code to a file)
TWOFA_FILE="$HOME/.ibkr_2fa_code"
TWOFA_TIMEOUT=300  # 5 minutes

echo "Waiting for 2FA code..."
echo ""
echo "Option 1: Write 2FA code to file:"
echo "   echo 'YOUR_2FA_CODE' > $TWOFA_FILE"
echo ""
echo "Option 2: Set environment variable:"
echo "   export IBKR_2FA_CODE='YOUR_2FA_CODE'"
echo "   $0"
echo ""
echo "Option 3: Pass as argument:"
echo "   $0 YOUR_2FA_CODE"
echo ""

# Check if 2FA code provided as argument
if [ -n "$1" ]; then
    TWOFA_CODE="$1"
    echo "✅ 2FA code provided as argument"
elif [ -n "$IBKR_2FA_CODE" ]; then
    TWOFA_CODE="$IBKR_2FA_CODE"
    echo "✅ 2FA code found in environment variable"
elif [ -f "$TWOFA_FILE" ]; then
    # Check file age (must be recent, within 60 seconds)
    FILE_AGE=$(($(date +%s) - $(stat -c %Y "$TWOFA_FILE" 2>/dev/null || echo 0)))
    if [ $FILE_AGE -lt 60 ]; then
        TWOFA_CODE=$(cat "$TWOFA_FILE" | tr -d '\n\r ' | head -c 10)
        echo "✅ 2FA code read from file (age: ${FILE_AGE}s)"
        # Clear file after reading
        rm -f "$TWOFA_FILE"
    else
        echo "⚠️  2FA file too old (${FILE_AGE}s), waiting for new code..."
        TWOFA_CODE=""
    fi
else
    TWOFA_CODE=""
fi

if [ -z "$TWOFA_CODE" ]; then
    echo ""
    echo "⏳ Waiting for 2FA code (timeout: ${TWOFA_TIMEOUT}s)..."
    echo "   Write code to: $TWOFA_FILE"
    echo ""
    
    # Wait for file to appear with recent timestamp
    START_TIME=$(date +%s)
    while [ $(($(date +%s) - $START_TIME)) -lt $TWOFA_TIMEOUT ]; do
        if [ -f "$TWOFA_FILE" ]; then
            FILE_AGE=$(($(date +%s) - $(stat -c %Y "$TWOFA_FILE" 2>/dev/null || echo 0)))
            if [ $FILE_AGE -lt 60 ]; then
                TWOFA_CODE=$(cat "$TWOFA_FILE" | tr -d '\n\r ' | head -c 10)
                echo "✅ Got 2FA code from file!"
                rm -f "$TWOFA_FILE"
                break
            fi
        fi
        sleep 1
    done
fi

if [ -z "$TWOFA_CODE" ]; then
    echo "❌ No 2FA code received within timeout"
    exit 1
fi

echo ""
echo "🔑 2FA Code: ${TWOFA_CODE:0:2}****"
echo ""

# Check if xdotool is available for GUI automation
if command -v xdotool >/dev/null 2>&1; then
    echo "✅ Using xdotool for GUI automation"
    
    # Find the 2FA dialog window
    echo "   Searching for 2FA dialog..."
    
    # Try to find the dialog on display :99 (Xvfb) or :1 (VNC)
    for DISPLAY_NUM in ":99" ":1" ""; do
        if [ -n "$DISPLAY_NUM" ]; then
            export DISPLAY="$DISPLAY_NUM"
        fi
        
        # Wait for dialog to appear
        DIALOG_FOUND=false
        for i in {1..30}; do
            DIALOG_WIN=$(xdotool search --name "Second Factor Authentication" 2>/dev/null | head -1)
            if [ -n "$DIALOG_WIN" ]; then
                echo "   ✅ Found 2FA dialog (window: $DIALOG_WIN)"
                DIALOG_FOUND=true
                break
            fi
            sleep 1
        done
        
        if [ "$DIALOG_FOUND" = true ]; then
            # Activate the window
            xdotool windowactivate "$DIALOG_WIN" 2>/dev/null
            sleep 0.5
            
            # Find the input field and enter the code
            echo "   Entering 2FA code..."
            
            # Try different methods to enter the code
            # Method 1: Type directly
            xdotool type --clearmodifiers "$TWOFA_CODE" 2>/dev/null
            sleep 0.5
            
            # Method 2: Click in the field first, then type
            xdotool click 1 2>/dev/null  # Click to focus
            sleep 0.2
            xdotool type --clearmodifiers "$TWOFA_CODE" 2>/dev/null
            sleep 0.5
            
            # Press Enter or click OK button
            echo "   Submitting..."
            xdotool key Return 2>/dev/null
            sleep 0.5
            
            # Also try clicking OK button if it exists
            xdotool search --name "OK" --class "Button" 2>/dev/null | head -1 | xargs -I {} xdotool click {} 2>/dev/null
            
            echo "   ✅ 2FA code entered and submitted!"
            echo ""
            echo "   Waiting 30 seconds for Gateway to authenticate..."
            sleep 30
            
            # Check if API port is ready
            if ss -tuln 2>/dev/null | grep -q ":4002"; then
                echo "   ✅ API port 4002 is listening - Gateway authenticated!"
                exit 0
            else
                echo "   ⚠️  API port not yet ready, but code was entered"
                echo "   Check status: ss -tuln | grep 4002"
            fi
            
            exit 0
        fi
    done
    
    echo "   ⚠️  Could not find 2FA dialog window"
    echo "   Make sure Gateway window is visible or try VNC"
else
    echo "⚠️  xdotool not installed - cannot automate GUI"
    echo ""
    echo "To install xdotool:"
    echo "   sudo apt-get install xdotool"
    echo ""
    echo "Or manually enter the code in the Gateway window:"
    echo "   2FA Code: $TWOFA_CODE"
    exit 1
fi




