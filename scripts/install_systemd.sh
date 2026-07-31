#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cat >/etc/systemd/system/polymarket-alpha.service <<EOF
[Unit]
Description=Polymarket Alpha Engine cycle
After=network-online.target
[Service]
Type=oneshot
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/alpha-engine cycle
EOF
cat >/etc/systemd/system/polymarket-alpha.timer <<EOF
[Unit]
Description=Run Polymarket Alpha Engine every 15 minutes
[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true
[Install]
WantedBy=timers.target
EOF
cat >/etc/systemd/system/polymarket-dashboard.service <<EOF
[Unit]
Description=Polymarket Alpha Dashboard
After=network-online.target
[Service]
WorkingDirectory=$ROOT
ExecStart=$ROOT/.venv/bin/alpha-engine serve
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now polymarket-alpha.timer polymarket-dashboard.service
systemctl status polymarket-alpha.timer --no-pager
