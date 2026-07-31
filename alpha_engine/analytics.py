import math
from datetime import datetime, timezone
from . import db
from .config import settings


def init_analytics():
    with db.connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS equity_history(
            id INTEGER PRIMARY KEY,
            captured_at TEXT NOT NULL,
            equity REAL NOT NULL,
            total_pnl REAL NOT NULL,
            realized_pnl REAL NOT NULL,
            unrealized_pnl REAL NOT NULL,
            exposure REAL NOT NULL,
            open_positions INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_equity_history_time ON equity_history(captured_at);
        """)


def record_equity():
    init_analytics()
    summary = db.summary()
    with db.connect() as c:
        c.execute(
            "INSERT INTO equity_history(captured_at,equity,total_pnl,realized_pnl,unrealized_pnl,exposure,open_positions) VALUES(?,?,?,?,?,?,?)",
            (
                datetime.now(timezone.utc).isoformat(),
                summary['equity'], summary['total_pnl'], summary['realized_pnl'],
                summary['unrealized_pnl'], summary['open_stake'], summary['open_positions'],
            ),
        )
    return summary


def equity_history(limit=500):
    init_analytics()
    with db.connect() as c:
        rows = c.execute(
            "SELECT * FROM equity_history ORDER BY captured_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def price_history(market_id, limit=250):
    with db.connect() as c:
        rows = c.execute(
            "SELECT captured_at,yes_price,no_price,spread,liquidity,volume_24h FROM snapshots WHERE market_id=? ORDER BY captured_at DESC LIMIT ?",
            (str(market_id), limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def position_detail(position_id):
    with db.connect() as c:
        position = c.execute(
            "SELECT *, (shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl FROM positions WHERE id=?",
            (position_id,),
        ).fetchone()
        if not position:
            return None
        analyses = c.execute(
            "SELECT * FROM analyses WHERE market_id=? ORDER BY created_at DESC LIMIT 25",
            (position['market_id'],),
        ).fetchall()
    return {
        'position': dict(position),
        'analyses': [dict(r) for r in analyses],
        'prices': price_history(position['market_id']),
    }


def advanced_metrics():
    summary = db.summary()
    history = equity_history()
    with db.connect() as c:
        closed = [dict(r) for r in c.execute(
            "SELECT pnl_usdc,stake_usdc,opened_at,closed_at,resolution FROM positions WHERE status='CLOSED' ORDER BY closed_at"
        )]

    peak = -math.inf
    max_drawdown = 0.0
    for point in history:
        equity = float(point['equity'])
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - equity) / peak)

    wins = [float(p['pnl_usdc']) for p in closed if float(p['pnl_usdc'] or 0) > 0]
    losses = [float(p['pnl_usdc']) for p in closed if float(p['pnl_usdc'] or 0) < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    expectancy = sum(float(p['pnl_usdc'] or 0) for p in closed) / len(closed) if closed else 0.0

    returns = []
    for previous, current in zip(history, history[1:]):
        p = float(previous['equity'])
        q = float(current['equity'])
        if p:
            returns.append((q - p) / p)
    volatility = 0.0
    if len(returns) > 1:
        mean = sum(returns) / len(returns)
        volatility = math.sqrt(sum((r - mean) ** 2 for r in returns) / (len(returns) - 1))

    return {
        **summary,
        'max_drawdown_pct': max_drawdown,
        'avg_win_usdc': avg_win,
        'avg_loss_usdc': avg_loss,
        'expectancy_usdc': expectancy,
        'equity_volatility': volatility,
        'equity_points': len(history),
        'closed_trades': len(closed),
    }
