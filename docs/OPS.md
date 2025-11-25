# Operations (IB Gateway + IBC)

## Service management
```bash
sudo systemctl status ibgateway.service
sudo systemctl restart ibgateway.service
sudo systemctl stop ibgateway.service
```

## Logs
- Service stdout/stderr (appended): `~/ibgateway.out.log`, `~/ibgateway.err.log`
- Tail both: `scripts/ibgateway_logs.sh`
- IBC diagnostics: `tail -f ~/ibc/logs/ibc-3.23.0_GATEWAY-1041_Tuesday.txt`
- Journal: `journalctl -fu ibgateway.service`

If you update `scripts/ibgateway-ibc.service`, recopy and reload:
```bash
sudo cp scripts/ibgateway-ibc.service /etc/systemd/system/ibgateway.service
sudo systemctl daemon-reload
sudo systemctl restart ibgateway.service
```

## Connectivity test
```bash
source .venv/bin/activate
python scripts/ibkr_download_data.py
```

## Safety notes
- IBKR enforces single-session per account; avoid concurrent TWS/Gateway logins.
- Keep credentials in private configs (not in git). Use `/home/pearlalgo/ibc/config-auto.ini` or `/etc/default/ibgateway-ibc`.
- Live trading requires explicit enablement; prefer paper/backtest by default.
