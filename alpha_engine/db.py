import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .config import settings
from .models import Market, Opportunity


def connect() -> sqlite3.Connection:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS market_snapshots (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_id TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          yes_price REAL NOT NULL,
          no_price REAL NOT NULL,
          spread REAL NOT NULL,
          liquidity REAL NOT NULL,
          volume REAL NOT NULL,
          raw_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_market_time
          ON market_snapshots(market_id, captured_at);

        CREATE TABLE IF NOT EXISTS analyses (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_id TEXT NOT NULL,
          created_at TEXT NOT NULL,
          side TEXT NOT NULL,
          fair_probability REAL NOT NULL,
          market_probability REAL NOT NULL,
          gross_edge REAL NOT NULL,
          net_edge REAL NOT NULL,
          score REAL NOT NULL,
          stake_usdc REAL NOT NULL,
          decision TEXT NOT NULL,
          payload_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_positions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          market_id TEXT NOT NULL,
          question TEXT NOT NULL,
          side TEXT NOT NULL,
          entry_price REAL NOT NULL,
          shares REAL NOT NULL,
          stake_usdc REAL NOT NULL,
          opened_at TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'OPEN',
          exit_price REAL,
          closed_at TEXT,
          pnl_usdc REAL,
          UNIQUE(market_id, side, status)
        );
        """)


def save_snapshot(m: Market) -> None:
    with connect() as c:
        c.execute("""INSERT INTO market_snapshots
          (market_id,captured_at,yes_price,no_price,spread,liquidity,volume,raw_json)
          VALUES(?,?,?,?,?,?,?,?)""", (
            m.id, datetime.now(timezone.utc).isoformat(), m.yes_price, m.no_price,
            m.spread, m.liquidity, m.volume, m.model_dump_json()
        ))


def save_analysis(o: Opportunity) -> None:
    with connect() as c:
        c.execute("""INSERT INTO analyses
          (market_id,created_at,side,fair_probability,market_probability,gross_edge,
           net_edge,score,stake_usdc,decision,payload_json)
          VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
            o.market.id, datetime.now(timezone.utc).isoformat(), o.side,
            o.fair_probability, o.market_probability, o.gross_edge, o.net_edge,
            o.score, o.stake_usdc, o.decision, o.model_dump_json()
        ))


def open_position(o: Opportunity) -> bool:
    price = o.market.yes_price if o.side == "YES" else o.market.no_price
    shares = o.stake_usdc / price if price > 0 else 0
    try:
        with connect() as c:
            c.execute("""INSERT INTO paper_positions
              (market_id,question,side,entry_price,shares,stake_usdc,opened_at,status)
              VALUES(?,?,?,?,?,?,?,'OPEN')""", (
                o.market.id, o.market.question, o.side, price, shares, o.stake_usdc,
                datetime.now(timezone.utc).isoformat()
            ))
        return True
    except sqlite3.IntegrityError:
        return False


def list_open_positions() -> list[sqlite3.Row]:
    with connect() as c:
        return list(c.execute("SELECT * FROM paper_positions WHERE status='OPEN' ORDER BY opened_at"))


def summary() -> dict:
    with connect() as c:
        open_rows = c.execute("SELECT COUNT(*) n, COALESCE(SUM(stake_usdc),0) stake FROM paper_positions WHERE status='OPEN'").fetchone()
        closed = c.execute("SELECT COUNT(*) n, COALESCE(SUM(pnl_usdc),0) pnl FROM paper_positions WHERE status='CLOSED'").fetchone()
        return {"open_positions": open_rows["n"], "open_stake": open_rows["stake"], "closed_positions": closed["n"], "realized_pnl": closed["pnl"]}
