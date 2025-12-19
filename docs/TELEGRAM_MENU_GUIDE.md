# Telegram Menu & UI Navigation Guide

## Overview

The NQ Agent Telegram bot now features a **fully UI-driven interface** with inline keyboard buttons. No need to type commands - everything is accessible through intuitive button navigation!

## Quick Start

1. **Start the Command Handler**:
   ```bash
   ./scripts/telegram/start_command_handler.sh --background
   ```

2. **Open Telegram** and send `/start` to your bot

3. **Navigate using buttons** - All actions are available via UI buttons!

## Menu System

### Main Menu (Status View)

The main menu appears when you:
- Send `/start`
- Tap "🏠 Main Menu" button
- Send `/status`

**Button Layout**:
```
[Stop Agent] [Restart]          (if agent running)
[Start Agent]                    (if agent stopped)
[Gateway ✅/❌] [Refresh]
[Status] [Signals] [Performance]
[Config] [Health]
[Help]
```

**Features**:
- **Status Indicators**: Gateway button shows ✅ (running) or ❌ (stopped)
- **Contextual Actions**: Buttons adapt based on current state
- **Quick Refresh**: Update status without navigating away

### Signals View

Access via: `/signals` or "🔔 Signals" button

**Button Layout**:
```
[📊 Chart 1] [📊 Chart 2] ... (one per signal)
[Refresh] [Last Signal]
[Performance] [Main Menu]
```

**Features**:
- View chart for any signal
- Quick access to last signal
- Easy navigation to related views

### Gateway View

Access via: "🔌 Gateway Status" button

**Button Layout**:
```
[Stop Gateway] [Refresh]  (if running)
[Start Gateway] [Refresh]  (if stopped)
[Main Menu] [Agent Status]
```

**Features**:
- One-tap gateway control
- Quick status refresh
- Easy navigation

### Performance View

Access via: "📈 Performance" button

**Button Layout**:
```
[Refresh] [Main Menu]
```

### Config & Health Views

Access via: "⚙️ Config" or "💚 Health" buttons

**Button Layout**:
```
[Main Menu]
```

## Navigation Patterns

### Common Flows

1. **Check Status**:
   - Tap "📊 Status" → See current state
   - Tap "🔄 Refresh" → Update status

2. **View Signals**:
   - Tap "🔔 Signals" → See signal list
   - Tap "📊 Chart" → View chart for specific signal
   - Tap "📊 Last Signal" → Quick access to most recent

3. **Control Services**:
   - Tap "▶️ Start Agent" → Start agent
   - Tap "⏹️ Stop Agent" → Stop agent
   - Tap "🔄 Restart" → Restart agent

4. **Monitor Gateway**:
   - Tap "🔌 Gateway Status" → Check gateway
   - Tap "▶️ Start Gateway" → Start if stopped
   - Tap "🔄 Refresh" → Update status

## Button Features

### Status Indicators

- **Gateway Button**: Shows ✅ when running, ❌ when stopped
- **Agent Buttons**: Change based on state (Start/Stop/Restart)

### Contextual Actions

Buttons automatically show relevant actions:
- If agent stopped → Shows "Start Agent"
- If agent running → Shows "Stop Agent" and "Restart"
- If no signals → Shows helpful message with navigation

### Quick Actions

- **Refresh**: Update current view without navigation
- **Last Signal**: Quick access to most recent signal
- **Main Menu**: Return to status view from anywhere

## Best Practices

1. **Use Buttons First**: Try buttons before typing commands
2. **Check Status**: Use "📊 Status" as your home base
3. **Refresh Often**: Use "🔄 Refresh" to get latest data
4. **Navigate Contextually**: Buttons show what's relevant
5. **Use Main Menu**: Easy way to return to status

## Tips & Tricks

- **Quick Status**: Tap "📊 Status" anytime to see current state
- **Chart Viewing**: All signals have chart buttons - tap to view
- **Error Recovery**: Error messages include helpful buttons
- **State Awareness**: Buttons reflect current system state
- **Navigation**: Always a way back to main menu

## Troubleshooting

### Buttons Not Appearing

**Issue**: Messages don't have buttons

**Solutions**:
1. Restart command handler:
   ```bash
   pkill -f telegram_command_handler
   ./scripts/telegram/start_command_handler.sh --background
   ```

2. Check handler is running:
   ```bash
   ./scripts/telegram/check_command_handler.sh
   ```

3. Verify you're using the correct bot (check chat ID)

### Buttons Not Working

**Issue**: Tapping buttons does nothing

**Solutions**:
1. Check handler logs:
   ```bash
   tail -f logs/telegram_handler.log
   ```

2. Verify authorization (check chat ID matches)

3. Restart handler to reload callbacks

### Old Messages Without Buttons

**Issue**: Old messages don't have buttons

**Solution**: Send a new command (like `/status`) to get buttons

## Advanced Features

### Keyboard Shortcuts

While buttons are preferred, commands still work:
- `/status` - Main status view
- `/signals` - Signals list
- `/last_signal` - Most recent signal
- `/active_trades` - Open positions
- `/quick_status` - Compact status

### Menu Button

The persistent "Menu" button at the bottom of Telegram shows all available commands. This is set via BotFather or the `set_bot_commands.py` script.

## Integration with Charts

Charts are fully integrated with the menu system:

1. **Automatic Charts**: Sent with signals automatically
2. **Chart Buttons**: Available in signals view
3. **Chart Viewing**: Tap "📊 Chart" to view any signal's chart

See [CHART_VISUALIZATION.md](CHART_VISUALIZATION.md) for chart details.

## Summary

The menu system provides:
- ✅ **100% UI-driven navigation**
- ✅ **Contextual buttons** that adapt to state
- ✅ **Status indicators** for quick visual feedback
- ✅ **Easy navigation** with always-available main menu
- ✅ **Quick actions** like refresh and shortcuts
- ✅ **Error recovery** with helpful buttons

**No typing required** - everything is accessible through intuitive button navigation!
