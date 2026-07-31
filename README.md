# Polymarket Alpha Engine

Market discovery, CLOB order-book enrichment, AI-assisted probability estimation, adversarial review, Kelly-based sizing, persistent paper trading, and a lightweight dashboard.

## Safety and scope

This release is **paper trading only**. It does not accept wallet private keys and does not place real orders. Forecasts can be wrong; profitability is not guaranteed.

## Ubuntu installation

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
cd ~/polymarket-alpha-engine
chmod +x scripts/*.sh
./scripts/bootstrap.sh
nano .env
```

Set `OPENAI_API_KEY`. Keep `AI_ENABLED=false` for scanner-only operation.

## Commands

```bash
.venv/bin/alpha-engine init
.venv/bin/alpha-engine cycle --scan-only
.venv/bin/alpha-engine cycle
.venv/bin/alpha-engine status
.venv/bin/alpha-engine positions --open-only
.venv/bin/alpha-engine serve
pytest -q
```

Dashboard: `http://SERVER_IP:8080` (restrict access with a firewall or reverse proxy).

## Scheduled operation

```bash
sudo ./scripts/install_systemd.sh
systemctl list-timers | grep polymarket
journalctl -u polymarket-alpha.service -f
journalctl -u polymarket-dashboard.service -f
```

## Pipeline

1. Gamma API discovers active markets.
2. CLOB `/books` supplies executable bid/ask and spread data.
3. Hard filters remove illiquid, wide-spread, extreme-price and near-expiry markets.
4. Ranking limits expensive AI calls to the strongest candidates.
5. OpenAI web research returns a structured probability report.
6. An independent critic checks ambiguity and failure modes.
7. Net edge includes half-spread and a slippage buffer.
8. Fractional Kelly plus portfolio caps determines paper stake.
9. SQLite stores snapshots, analyses, cycles and positions.
10. Each cycle marks open positions to current prices.

## Important next milestones

- Automated resolution/settlement accounting.
- Brier score and calibration dashboards by category.
- Historical replay dataset and walk-forward testing.
- News-event change detection rather than repeated full research.
- PostgreSQL/Redis only when SQLite becomes a real bottleneck.
