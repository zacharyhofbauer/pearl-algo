# IBKR integration (Gateway + ib_insync)

This repo is IB-first but safe-by-default. Backtest/paper are defaults; live trading requires an explicit flag and profile switch.

## Prereqs
- IBKR account with paper login.
- IB Gateway installed at `/home/pearlalgo/Jts/ibgateway/1041` and configured to auto-login + enable API:
  - Start Gateway GUI once, log in to paper.
  - Enable API: *Configure > API > Settings* → check **Enable ActiveX and Socket Clients**, uncheck read-only, set trusted IPs if desired.
  - Save settings, then exit (settings persist under `~/Jts`).
- `xvfb` installed for headless run: `sudo apt-get install -y xvfb`.

## Environment
Set in `.env` (already loaded via pydantic + dotenv):
```
PEARLALGO_IB_HOST=127.0.0.1
PEARLALGO_IB_PORT=4002         # Gateway paper port
PEARLALGO_IB_CLIENT_ID=1
PEARLALGO_PROFILE=backtest     # backtest | paper | live
PEARLALGO_ALLOW_LIVE_TRADING=false
```
- Keep `PEARLALGO_PROFILE` as `backtest` or `paper` unless intentionally trading live.
- Live trading requires both `PEARLALGO_PROFILE=live` **and** `PEARLALGO_ALLOW_LIVE_TRADING=true`; otherwise the IB broker logs what it would do and skips sending orders.

## systemd (headless Gateway)
### Recommended: IBC-based unit (auto-login)
1) Create a private IBC config (do not commit):
```bash
cp scripts/ibc_config.sample.ini ~/ibc/config-auto.ini
# edit ~/ibc/config-auto.ini and fill IbLoginId / IbPassword / TradingMode
```
2) (Optional) create `/etc/default/ibgateway-ibc` to override paths/mode:
```
IBC_INI=/home/pearlalgo/ibc/config-auto.ini
TRADING_MODE=paper   # or live
```
3) Install the IBC unit:
```bash
sudo cp scripts/ibgateway-ibc.service.example /etc/systemd/system/ibgateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now ibgateway.service
```

### Legacy: direct Gateway unit
If you prefer to start the gateway directly (no IBC auto-login), use:
 ```bash
 sudo cp scripts/ibgateway.service.example /etc/systemd/system/ibgateway.service
 sudo systemctl daemon-reload
 sudo systemctl enable ibgateway.service
 sudo systemctl start ibgateway.service
```
2) Check status/logs:
```bash
scripts/ibgateway_status.sh
```

The unit runs `xvfb-run -a /home/pearlalgo/Jts/ibgateway/1041/ibgateway` as user `pearlalgo` and restarts on failure.

## Data download
Fetch SPY and ES samples via ib_insync:
```bash
source .venv/bin/activate
python scripts/ibkr_download_data.py
```
Outputs:
- `data/equities/SPY_ib_5m.csv`
- `data/futures/ES_ib_15m.csv`

## Python integration
- Data provider: `pearlalgo.data_providers.ibkr_data_provider.IBKRDataProvider`
- Broker: `pearlalgo.brokers.ibkr_broker.IBKRBroker`
- Both read host/port/clientId and live-safety flags from settings/.env.

## Profile switching
- Backtest (default): safest, no external connections.
- Paper: connect to Gateway on port 4002; orders still require `PEARLALGO_ALLOW_LIVE_TRADING=true` **and** `PEARLALGO_PROFILE=live` to actually route.
- Live: set `PEARLALGO_PROFILE=live` and `PEARLALGO_ALLOW_LIVE_TRADING=true` only when ready; review risk controls first.
