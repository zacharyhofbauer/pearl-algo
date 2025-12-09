# Pre-Deployment Checklist

## ✅ Critical Items (Must Complete Before Deployment)

### 1. Dependencies
- ✅ All required packages in `pyproject.toml`
- ✅ `pytz` added for market hours (just added)
- ⚠️ **Action Required:** Run `pip install -e .` to install dependencies

### 2. Environment Variables
- ⚠️ **Action Required:** Create `.env` file with:
  ```bash
  POLYGON_API_KEY=your_key_here
  TELEGRAM_BOT_TOKEN=your_token_here
  TELEGRAM_CHAT_ID=your_chat_id_here
  GROQ_API_KEY=your_key_here  # Optional
  ```

### 3. Configuration
- ✅ Production config created (`config/config.production.yaml`)
- ⚠️ **Optional:** Review and customize settings if needed

### 4. Service Scripts
- ✅ Signal generation service (`scripts/signal_generation_service.py`)
- ✅ Health monitor (`scripts/signal_health_monitor.py`)
- ✅ Deployment script (`scripts/deploy_24_7.sh`)
- ✅ All scripts are executable

### 5. Testing
- ⚠️ **Recommended:** Test manually before deploying as service:
  ```bash
  # Test signal generation
  source .venv/bin/activate
  ./scripts/run_signal_generation.sh ES NQ sr
  
  # Test health monitor
  python scripts/signal_health_monitor.py
  
  # Test market hours
  python -c "from pearlalgo.utils.market_hours import is_market_open; print(is_market_open())"
  ```

## 🚀 Ready to Deploy

The core 24/7 infrastructure is **complete**. You can deploy now with:

```bash
# 1. Install dependencies (if not already done)
source .venv/bin/activate
pip install -e .

# 2. Deploy service
sudo ./scripts/deploy_24_7.sh

# 3. Start service
sudo systemctl start pearlalgo-signal_service.service

# 4. Monitor
sudo systemctl status pearlalgo-signal_service.service
tail -f logs/signal_generation.log
```

## 📋 Optional Enhancements (Can Add Later)

These are **not required** for deployment but can be added incrementally:

### Phase 2: Additional Monitoring
- Signal dashboard (`scripts/signal_dashboard.py`) - Real-time metrics
- Enhanced structured logging - JSON logging for analysis

### Phase 3: Rate Limiting
- Enhanced Polygon rate limiting - Request queuing (basic exists, may need enhancement)

### Phase 4: Notification Control
- Notification batching - Group multiple signals
- Notification frequency control - Rate limit per symbol
- Quiet hours - Reduce notifications during off-hours

### Phase 6: Testing
- Integration tests - Automated service testing
- Load testing - Test rate limits
- Monitoring validation - Test health checks

## ⚠️ Known Limitations

1. **Rate Limiting**: Basic rate limiting exists. If you hit Polygon API limits, you may need to:
   - Increase interval between cycles
   - Reduce number of symbols
   - Upgrade Polygon API tier

2. **Notification Spam**: Signal deduplication prevents duplicates within 15 minutes, but if you have many symbols, you may still get frequent notifications. Consider:
   - Increasing deduplication window
   - Implementing notification batching (future enhancement)

3. **Market Hours**: Currently uses simplified market hours. May need adjustment for:
   - Specific exchange holidays
   - Pre-market/post-market hours
   - Different timezones

## 🔍 Post-Deployment Monitoring

After deployment, monitor:

1. **Service Status**
   ```bash
   sudo systemctl status pearlalgo-signal_service.service
   ```

2. **Logs**
   ```bash
   tail -f logs/signal_generation.log
   sudo journalctl -u pearlalgo-signal_service.service -f
   ```

3. **Health Checks**
   ```bash
   python scripts/signal_health_monitor.py
   ```

4. **Telegram Notifications**
   - Verify signals are being sent
   - Check notification frequency
   - Monitor for any errors

5. **Signal Quality**
   - Review signals in `data/performance/futures_decisions.csv`
   - Check signal frequency
   - Monitor P&L tracking

## 🐛 Troubleshooting

If issues arise:

1. **Service won't start**
   - Check logs: `sudo journalctl -u pearlalgo-signal_service.service -n 50`
   - Verify environment variables: `sudo systemctl show pearlalgo-signal_service.service | grep Environment`
   - Check Python path: Ensure `.venv/bin/python` exists

2. **No signals generated**
   - Check if market is open: `python -c "from pearlalgo.utils.market_hours import is_market_open; print(is_market_open())"`
   - Verify Polygon API key: `echo $POLYGON_API_KEY`
   - Check logs for errors: `tail -100 logs/signal_generation.log`

3. **Telegram not working**
   - Test bot: `python scripts/send_test_message.py`
   - Verify credentials in `.env`
   - Check Telegram API status

4. **High memory/CPU usage**
   - Reduce number of symbols
   - Increase interval between cycles
   - Check for memory leaks in logs

## ✅ Deployment Summary

**Status:** ✅ **READY FOR DEPLOYMENT**

**Critical Actions:**
1. Install dependencies: `pip install -e .`
2. Create `.env` file with API keys
3. (Optional) Test manually first
4. Deploy: `sudo ./scripts/deploy_24_7.sh`
5. Start: `sudo systemctl start pearlalgo-signal_service.service`

**Optional Enhancements:** Can be added incrementally after deployment is stable.

