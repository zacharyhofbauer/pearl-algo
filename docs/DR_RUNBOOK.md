# Pearl-Algo Disaster Recovery Runbook

**Purpose**: if the Beelink (`px-core`) fails, this document gets pearl-algo back to a live-trading state on replacement hardware.

**Last validated**: 2026-04-21 (desk-check, not an actual DR drill)
**Audience**: operator (Zach) + Claude agents assisting recovery

---

## 1. Blast-Radius Assessment (IF BEELINK DIES MID-TRADE)

**Open positions do NOT die with the Beelink.** Orders live at Tradovate and, downstream, MFF. If the Beelink is unreachable:

1. **Stop loss still works** — Tradovate-side brackets and stops remain active.
2. **New signals won't fire** — that's desired during recovery.
3. **To manually close positions NOW**, while recovery proceeds:
   - Tradovate web: https://trader.tradovate.com → paper account → flatten
   - TraderSyncer handles the mirror to MFF automatically (if running). If TraderSyncer is also down, flatten the MFF side manually via the MFF dashboard.
4. **Daily loss limit**: MFF will auto-flatten if thresholds trip. Do not assume positions ride out the recovery.

---

## 2. What Lives Where (Ground Truth)

### In the git repo (recoverable via `git clone`)
- All source code (`src/`, `tests/`, `scripts/`)
- `config/live/tradovate_paper.yaml` — canonical live runtime config
- `pearl.sh` master control script
- CI workflows
- `CLAUDE.md`, `docs/`, this runbook

Repo: `git@github.com:zacharyhofbauer/pearl-algo.git` (public)

### NOT in git — must be restored from backup or re-provisioned

| Path | Contains | Recovery path |
|------|----------|---------------|
| `/home/pearlalgo/.config/pearlalgo/secrets.env` | Tradovate credentials, MFF credentials, TraderSyncer token, any API keys | Restore from operator's password manager / encrypted backup. **Not sharable; never check into git.** |
| `/home/pearlalgo/projects/pearl-algo/.env` | Non-secret env vars (paths, feature flags) | Recreate from template; see section 5.4 |
| `/home/pearlalgo/projects/pearl-algo/apps/pearl-algo-app/.env.local` | Webapp-local overrides | Recreate from template |
| `/home/pearlalgo/.cloudflared/cert.pem` + `config.yml` + tunnel credentials | Cloudflare tunnel for pearlalgo.io | Re-authenticate via `cloudflared tunnel login` and re-bind tunnel, OR restore from encrypted backup |
| `/etc/systemd/system/pearlalgo-agent.service` | Agent service definition | Template is in this runbook (section 6); reinstall |
| `/etc/systemd/system/pearlalgo-api.service` | API service | Template in section 6 |
| `/etc/systemd/system/pearlalgo-webapp.service` | Webapp service | Template in section 6 |
| `/etc/systemd/system/ibkr-gateway.service` | IBKR Gateway + Xvfb wrapper | Template in section 6 |
| `/etc/systemd/system/cloudflared-pearlalgo.service` | Cloudflare tunnel service | Template in section 6 |
| `/home/pearlalgo/var/pearl-algo/state/` | **Runtime state**: agent_state, trades.db, equity curve, session data | **This is the hot state.** If lost, the bot starts fresh — lose equity-curve history, loss-streak counters, any active signal state. Recoverable via periodic backup (recommended: nightly rsync to obsidian-brain or S3). Not currently backed up. |
| IBKR Gateway installation (under `~/Jts/` or similar IBC directory) | IBC config, jts.ini, IB Gateway install | Re-download IBKR Gateway + IBC, re-authenticate |

### External state (not on the Beelink at all)
- Tradovate paper & live accounts (cloud)
- MFF account (cloud)
- TraderSyncer config (their web dashboard)
- Cloudflare DNS + tunnel registration (cloud)
- GitHub repo (cloud)
- Tailscale tailnet membership (cloud)

---

## 3. Hardware Requirements for Replacement

Minimum viable replacement (anything ≥ these specs works):
- **CPU**: 6-core x86_64, AVX2 support (any Ryzen 5+, Intel i5 8th-gen+)
- **RAM**: 16 GB (current uses ~4 GB, headroom for IBKR Java heap + backtests)
- **Disk**: 100 GB SSD (current uses ~30 GB including IBKR Gateway + state history)
- **Network**: wired ethernet preferred; stable WiFi acceptable
- **OS**: Ubuntu 22.04+ or Debian 12+ (systemd-based). Tested on Ubuntu 24.04 on current Beelink.

Current hardware: **Beelink SER8** — Ryzen 7 8845HS / 27 GB / ~500 GB NVMe / Ubuntu 24.04.

---

## 4. Pre-Recovery Checklist (BEFORE touching the replacement box)

- [ ] Confirm positions are flat OR you accept the risk of running without an auto-exit bot for the recovery window
- [ ] Retrieve `secrets.env` from backup / password manager
- [ ] Confirm Tailscale account access (for re-joining the tailnet)
- [ ] Confirm Cloudflare account access (for re-binding the tunnel)
- [ ] Confirm GitHub SSH key is available on the replacement machine (or use HTTPS + PAT)
- [ ] Confirm IBKR account credentials + 2FA method

---

## 5. Recovery Procedure (step-by-step on a fresh Ubuntu box)

### 5.1 OS baseline
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    build-essential python3.12 python3.12-venv python3-pip \
    nodejs npm git curl wget \
    xvfb openbox unzip default-jre \
    sqlite3 jq
```

### 5.2 Create pearlalgo user
```bash
sudo useradd -m -s /bin/bash pearlalgo
sudo usermod -aG sudo pearlalgo
# If you want passwordless sudo for ops:
# echo "pearlalgo ALL=(ALL) NOPASSWD: ALL" | sudo tee /etc/sudoers.d/pearlalgo
```

### 5.3 Clone the repo
```bash
sudo -iu pearlalgo
mkdir -p ~/projects
cd ~/projects
# Set up SSH key or use HTTPS
git clone git@github.com:zacharyhofbauer/pearl-algo.git
cd pearl-algo
```

### 5.4 Recreate env files
```bash
# .env (non-secret — from memory/README or previous backup)
cat > .env <<'EOF'
PEARL_MARKET=MNQ
# (add other non-secret env vars here)
EOF

# Restore secrets.env from backup
mkdir -p ~/.config/pearlalgo
# Put your secrets.env here, chmod 600
chmod 600 ~/.config/pearlalgo/secrets.env

# Webapp local env (if applicable)
# cat > apps/pearl-algo-app/.env.local <<'EOF'
# NEXT_PUBLIC_API_URL=http://localhost:8001
# EOF
```

### 5.5 Python venv + deps
```bash
cd ~/projects/pearl-algo
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### 5.6 Webapp deps
```bash
cd ~/projects/pearl-algo/apps/pearl-algo-app
npm ci
npm run build
```

### 5.7 IBKR Gateway + IBC
- Download IBKR Gateway from interactivebrokers.com
- Install IBC (github.com/IbcAlpha/IBC) for headless automation
- Place under `~/Jts/` (or wherever matches the paths in `scripts/gateway/gateway.sh`)
- Configure jts.ini for your IBKR account
- Verify `scripts/gateway/gateway.sh start` can launch it under Xvfb :99

### 5.8 State directory
```bash
mkdir -p /home/pearlalgo/var/pearl-algo/state/data/agent_state/MNQ
# Restore from backup if available:
# rsync -avz old-backup:/path/to/state/ /home/pearlalgo/var/pearl-algo/state/
# If no backup: the bot will initialize fresh (lose equity curve history)
```

### 5.9 systemd units — see section 6 for templates
```bash
sudo cp docs/systemd-templates/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ibkr-gateway pearlalgo-agent pearlalgo-api pearlalgo-webapp
```
*(The templates directory doesn't exist yet — this runbook embeds them inline in section 6 until a future task extracts them.)*

### 5.10 Cloudflare tunnel
```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb

# Re-authenticate:
cloudflared tunnel login
# Either re-create the tunnel or restore ~/.cloudflared/ from backup
# Then install the service:
sudo cp docs/systemd-templates/cloudflared-pearlalgo.service /etc/systemd/system/
sudo systemctl enable --now cloudflared-pearlalgo
```

### 5.11 Tailscale
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --hostname=px-core
# Approve the new device in the Tailscale admin console
# Copy the new IP and update the Mac's ~/.ssh/config `pearlalgo` Host block
```

### 5.12 Verify
```bash
cd ~/projects/pearl-algo
./pearl.sh quick              # should show all ✅
./pearl.sh status             # detailed
# From the Mac:
ssh pearlalgo 'cd ~/projects/pearl-algo && ./pearl.sh status'
./scripts/ops/health-from-mac.sh
```

### 5.13 Arm trading (LAST step)
Edit `config/live/tradovate_paper.yaml`:
```yaml
execution:
  armed: true
  enabled: true
```
Restart: `./pearl.sh tv-paper restart`

Monitor closely for the first session. Do not leave unattended for 24 hours post-recovery.

---

## 6. systemd Unit Templates (copy-paste into `/etc/systemd/system/`)

### `pearlalgo-agent.service`
```ini
[Unit]
Description=PearlAlgo Market Agent - Tradovate Paper
After=network.target ibkr-gateway.service

[Service]
Type=simple
User=pearlalgo
Group=pearlalgo
WorkingDirectory=/home/pearlalgo/projects/pearl-algo
Environment="PATH=/home/pearlalgo/projects/pearl-algo/.venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=/home/pearlalgo/projects/pearl-algo/src"
EnvironmentFile=/home/pearlalgo/projects/pearl-algo/.env
EnvironmentFile=-/home/pearlalgo/.config/pearlalgo/secrets.env
ExecStart=/home/pearlalgo/projects/pearl-algo/.venv/bin/python -m pearlalgo.market_agent.main --config config/live/tradovate_paper.yaml --data-dir data/agent_state/MNQ
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### `pearlalgo-api.service`
```ini
[Unit]
Description=PearlAlgo API Server - Tradovate Paper (port 8001)
After=network.target pearlalgo-agent.service
Wants=pearlalgo-agent.service

[Service]
Type=simple
User=pearlalgo
Group=pearlalgo
WorkingDirectory=/home/pearlalgo/projects/pearl-algo
Environment="PATH=/home/pearlalgo/projects/pearl-algo/.venv/bin:/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONPATH=/home/pearlalgo/projects/pearl-algo/src"
EnvironmentFile=/home/pearlalgo/projects/pearl-algo/.env
EnvironmentFile=-/home/pearlalgo/.config/pearlalgo/secrets.env
ExecStart=/home/pearlalgo/projects/pearl-algo/.venv/bin/python scripts/pearlalgo_web_app/api_server.py --data-dir data/agent_state/MNQ --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `pearlalgo-webapp.service`
```ini
[Unit]
Description=PearlAlgo Web App (Next.js)
After=network.target pearlalgo-api.service
Wants=pearlalgo-api.service

[Service]
Type=simple
User=pearlalgo
Group=pearlalgo
WorkingDirectory=/home/pearlalgo/projects/pearl-algo/apps/pearl-algo-app
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="NODE_ENV=production"
Environment="PORT=3001"
Environment="HOSTNAME=0.0.0.0"
EnvironmentFile=/home/pearlalgo/projects/pearl-algo/.env
EnvironmentFile=-/home/pearlalgo/.config/pearlalgo/secrets.env
EnvironmentFile=-/home/pearlalgo/projects/pearl-algo/apps/pearl-algo-app/.env.local
ExecStart=/usr/bin/node .next/standalone/server.js
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### `ibkr-gateway.service`
```ini
[Unit]
Description=IBKR Gateway (IBC)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
User=pearlalgo
Group=pearlalgo
WorkingDirectory=/home/pearlalgo/projects/pearl-algo
Environment="DISPLAY=:99"
Environment="PATH=/home/pearlalgo/projects/pearl-algo/.venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStartPre=/bin/sh -c '/usr/bin/Xvfb :99 -screen 0 1024x768x24 & sleep 2'
ExecStart=/home/pearlalgo/projects/pearl-algo/scripts/gateway/gateway.sh start
ExecStop=/home/pearlalgo/projects/pearl-algo/scripts/gateway/gateway.sh stop
TimeoutStartSec=300
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

### `cloudflared-pearlalgo.service`
```ini
[Unit]
Description=Cloudflare Tunnel for pearlalgo.io
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pearlalgo
ExecStart=/usr/local/bin/cloudflared --config /home/pearlalgo/.cloudflared/config.yml tunnel run
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## 7. Known Gaps in This Runbook (2026-04-21)

1. **State dir is not backed up.** `/home/pearlalgo/var/pearl-algo/state/` holds trades.db, agent_state, equity curve. If the Beelink dies, that history is gone. **Recommendation**: add a nightly cron on the Beelink that rsyncs state/ to an off-host location (obsidian-brain, S3, or the Mac via Tailscale). This is the single most valuable DR improvement to make.
2. **secrets.env is not documented schema-wise.** The file exists at `~/.config/pearlalgo/secrets.env` but this runbook doesn't enumerate which keys live there. On next edit of that file: capture the (key, purpose) table into this doc with values redacted.
3. **IBKR Gateway version pinning.** IBC + IBKR Gateway versions are not pinned in the repo. If IBKR pushes a breaking change, recovery is harder. Document current versions: `java -jar ~/Jts/ibgateway.jar --version`, `cat ~/IBC/version.txt`.
4. **Cloudflare tunnel credentials.** The tunnel cert/credentials file lives at `~/.cloudflared/<UUID>.json`. Back it up encrypted; without it the tunnel must be fully re-registered (downtime on pearlalgo.io).
5. **No DR drill has been done.** This runbook is desk-checked, not exercised. Recommendation: once the trading system is stable, do a cold-boot recovery test on a spare VM to validate every step.
6. **CI is currently failing** on mypy type checks in `order_manager.py`. If you restore from scratch and CI is still red, the git hooks / branch rulesets you might add post-recovery will block merges. Fix CI before adding rulesets.

---

## 8. Post-Recovery Verification

After section 5.13, before declaring the system recovered:

- [ ] `./pearl.sh quick` all green
- [ ] `./scripts/ops/health-from-mac.sh` (from Mac) exits 0
- [ ] `pearlalgo.io` loads in browser
- [ ] `python -m pytest tests/ -x -q` passes (optional but reassuring)
- [ ] Watch 15 minutes of live session; confirm signals fire, trades execute, PnL updates
- [ ] Reconcile Tradovate open positions against agent's internal state
- [ ] Confirm TraderSyncer is mirroring to MFF (if applicable)
- [ ] Verify Cloudflare tunnel is green in Cloudflare dashboard
- [ ] Verify Tailscale shows px-core online from the Mac's side

## 9. Related Documentation

- `CLAUDE.md` — daily operational guidance
- `docs/architecture/` — system design
- `docs/GATEWAY.md` — IBKR Gateway specifics
- `docs/START_HERE.md` — developer onboarding
