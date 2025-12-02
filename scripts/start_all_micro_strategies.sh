#!/bin/bash
# Start all micro strategies - Scalping, Intraday Swing, and SR on different micro contracts

cd "$(dirname "$0")/.."
source .venv/bin/activate

echo "🚀 Starting All Micro Strategies..."
echo ""
echo "This will start multiple trading strategies in the background:"
echo "  - Scalping on MES, MNQ (fast trading)"
echo "  - Intraday Swing on MGC, MYM (longer holds)"
echo "  - SR on MCL (support/resistance)"
echo ""

# Create logs directory if it doesn't exist
mkdir -p logs

# Check if IB Gateway is running
if ! pgrep -f "ibgateway" > /dev/null && ! pgrep -f "IB Gateway" > /dev/null; then
    echo "⚠️  Warning: IB Gateway doesn't appear to be running"
    echo "   Start it with: pearlalgo gateway start --wait"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Strategy 1: Scalping on MES, MNQ (fast micro contracts)
echo "📈 Starting Scalping Strategy (MES, MNQ)..."
nohup pearlalgo --verbosity VERBOSE trade auto \
  MES MNQ \
  --strategy scalping \
  --interval 60 \
  --tiny-size 2 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 20 \
  --log-file logs/micro_scalping_trading.log \
  --log-level INFO > logs/micro_scalping_console.log 2>&1 &

SCALPING_PID=$!
echo "   ✅ Scalping started (PID: $SCALPING_PID)"
echo "   📊 Logs: logs/micro_scalping_trading.log"
echo "   🔌 Client ID: 20"
echo ""

# Strategy 2: Intraday Swing on MGC, MYM (longer holds)
echo "📈 Starting Intraday Swing Strategy (MGC, MYM)..."
nohup pearlalgo --verbosity VERBOSE trade auto \
  MGC MYM \
  --strategy intraday_swing \
  --interval 900 \
  --tiny-size 3 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 21 \
  --log-file logs/micro_swing_trading.log \
  --log-level INFO > logs/micro_swing_console.log 2>&1 &

SWING_PID=$!
echo "   ✅ Intraday Swing started (PID: $SWING_PID)"
echo "   📊 Logs: logs/micro_swing_trading.log"
echo "   🔌 Client ID: 21"
echo ""

# Strategy 3: SR on MCL (support/resistance)
echo "📈 Starting SR Strategy (MCL)..."
nohup pearlalgo --verbosity VERBOSE trade auto \
  MCL \
  --strategy sr \
  --interval 300 \
  --tiny-size 2 \
  --profile-config config/micro_strategy_config.yaml \
  --ib-client-id 22 \
  --log-file logs/micro_sr_trading.log \
  --log-level INFO > logs/micro_sr_console.log 2>&1 &

SR_PID=$!
echo "   ✅ SR Strategy started (PID: $SR_PID)"
echo "   📊 Logs: logs/micro_sr_trading.log"
echo ""

# Save PIDs to file for easy stopping
echo "$SCALPING_PID" > logs/micro_strategies_pids.txt
echo "$SWING_PID" >> logs/micro_strategies_pids.txt
echo "$SR_PID" >> logs/micro_strategies_pids.txt

echo "✅ All micro strategies started!"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 MONITORING OPTIONS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Terminal 1 - Professional Terminal Dashboard:"
echo "    pearlalgo terminal"
echo ""
echo "  Terminal 2 - Status Dashboard:"
echo "    python scripts/status_dashboard.py --live"
echo ""
echo "  Terminal 3 - Live Trading Feed:"
echo "    pearlalgo monitor --live-feed"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 VIEW LOGS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Scalping Strategy:"
echo "    tail -f logs/micro_scalping_trading.log    # Trading decisions"
echo "    tail -f logs/micro_scalping_console.log    # Console output"
echo ""
echo "  Intraday Swing Strategy:"
echo "    tail -f logs/micro_swing_trading.log        # Trading decisions"
echo "    tail -f logs/micro_swing_console.log        # Console output"
echo ""
echo "  SR Strategy:"
echo "    tail -f logs/micro_sr_trading.log           # Trading decisions"
echo "    tail -f logs/micro_sr_console.log           # Console output"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🛑 STOP ALL STRATEGIES:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  bash scripts/stop_all_micro_strategies.sh"
echo ""
echo "  Or manually:"
echo "    kill $SCALPING_PID $SWING_PID $SR_PID"
echo "    # or"
echo "    pkill -f 'pearlalgo trade auto'"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 TIP: Use 'pearlalgo terminal' to see all positions and P&L in real-time!"
echo ""

