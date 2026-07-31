import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone
from .config import settings


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    settings.ensure_dirs()
    c = sqlite3.connect(Path(settings.database_path))
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with connect() as c:
        c.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, market_id TEXT,captured_at TEXT,question TEXT,yes_price REAL,no_price REAL,bid REAL,ask REAL,spread REAL,liquidity REAL,volume REAL,volume_24h REAL,rank_score REAL,raw_json TEXT);
        CREATE INDEX IF NOT EXISTS ix_snap_market_time ON snapshots(market_id,captured_at);
        CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY,market_id TEXT,created_at TEXT,side TEXT,fair_probability REAL,market_probability REAL,gross_edge REAL,net_edge REAL,confidence REAL,critic_risk REAL,score REAL,stake_usdc REAL,decision TEXT,payload_json TEXT);
        CREATE INDEX IF NOT EXISTS ix_analysis_market_time ON analyses(market_id,created_at);
        CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY,market_id TEXT,token_id TEXT,question TEXT,side TEXT,entry_price REAL,shares REAL,stake_usdc REAL,opened_at TEXT,status TEXT DEFAULT 'OPEN',last_price REAL,last_marked_at TEXT,exit_price REAL,closed_at TEXT,pnl_usdc REAL,resolution TEXT,UNIQUE(market_id,status));
        CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,markets_seen INTEGER,eligible INTEGER,analysed INTEGER,opened INTEGER,error TEXT);
        """)


def save_snapshot(m):
    with connect() as c:
        c.execute(
            'INSERT INTO snapshots(market_id,captured_at,question,yes_price,no_price,bid,ask,spread,liquidity,volume,volume_24h,rank_score,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (m.id, now(), m.question, m.yes_price, m.no_price, m.best_bid_yes, m.best_ask_yes, m.spread, m.liquidity, m.volume, m.volume_24h, m.rank_score, m.model_dump_json()),
        )


def save_analysis(o):
    with connect() as c:
        c.execute(
            'INSERT INTO analyses(market_id,created_at,side,fair_probability,market_probability,gross_edge,net_edge,confidence,critic_risk,score,stake_usdc,decision,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (o.market.id, now(), o.side, o.fair_probability, o.market_probability, o.gross_edge, o.net_edge, o.confidence, o.critic_risk, o.score, o.stake_usdc, o.decision, o.model_dump_json()),
        )


def exposure():
    with connect() as c:
        return float(c.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN'").fetchone()['v'])


def open_market_ids():
    with connect() as c:
        return {str(r['market_id']) for r in c.execute("SELECT market_id FROM positions WHERE status='OPEN'")}


def recently_analyzed_market_ids(minutes):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with connect() as c:
        return {str(r['market_id']) for r in c.execute("SELECT DISTINCT market_id FROM analyses WHERE created_at>=?", (cutoff,))}


def open_position(o):
    if o.decision != 'OPEN':
        return False
    token = o.market.yes_token_id if o.side == 'YES' else o.market.no_token_id
    try:
        with connect() as c:
            c.execute(
                "INSERT INTO positions(market_id,token_id,question,side,entry_price,shares,stake_usdc,opened_at,last_price,last_marked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (o.market.id, token, o.market.question, o.side, o.market_probability, o.stake_usdc / o.market_probability, o.stake_usdc, now(), o.market_probability, now()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def mark_positions(markets):
    by = {m.id: m for m in markets}
    n = 0
    with connect() as c:
        for p in c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall():
            m = by.get(p['market_id'])
            if not m:
                continue
            price = m.yes_price if p['side'] == 'YES' else m.no_price
            c.execute('UPDATE positions SET last_price=?,last_marked_at=? WHERE id=?', (price, now(), p['id']))
            n += 1
    return n


def close_position(position_id, exit_price, reason):
    with connect() as c:
        p = c.execute("SELECT * FROM positions WHERE id=? AND status='OPEN'", (position_id,)).fetchone()
        if not p:
            return False
        pnl = p['shares'] * exit_price - p['stake_usdc']
        c.execute(
            "UPDATE positions SET status='CLOSED',exit_price=?,closed_at=?,pnl_usdc=?,resolution=?,last_price=?,last_marked_at=? WHERE id=?",
            (exit_price, now(), pnl, reason, exit_price, now(), position_id),
        )
        return True


def manage_exits(markets, opportunities):
    market_by_id = {m.id: m for m in markets}
    opportunity_by_id = {o.market.id: o for o in opportunities}
    closed = []
    current = datetime.now(timezone.utc)

    with connect() as c:
        positions = [dict(r) for r in c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()]

    for p in positions:
        market = market_by_id.get(p['market_id'])
        if not market:
            continue
        price = market.yes_price if p['side'] == 'YES' else market.no_price
        pnl_pct = (p['shares'] * price - p['stake_usdc']) / p['stake_usdc'] if p['stake_usdc'] else 0
        reason = None

        if pnl_pct >= settings.take_profit_pct:
            reason = 'TAKE_PROFIT'
        elif pnl_pct <= -settings.stop_loss_pct:
            reason = 'STOP_LOSS'
        elif market.end_date is not None:
            end = market.end_date
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            hours_left = (end - current).total_seconds() / 3600
            if hours_left <= settings.exit_hours_to_resolution:
                reason = 'NEAR_RESOLUTION'

        opportunity = opportunity_by_id.get(p['market_id'])
        if reason is None and opportunity is not None:
            if opportunity.side != p['side'] or opportunity.net_edge < settings.exit_min_edge or opportunity.decision == 'REJECT':
                reason = 'EDGE_GONE'

        if reason and close_position(p['id'], price, reason):
            closed.append({'id': p['id'], 'reason': reason, 'pnl_pct': pnl_pct, 'exit_price': price})

    return closed


def list_positions(open_only=False):
    q = "SELECT *, (shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl FROM positions"
    if open_only:
        q += " WHERE status='OPEN'"
    q += " ORDER BY opened_at DESC"
    with connect() as c:
        return [dict(r) for r in c.execute(q)]


def summary():
    with connect() as c:
        r = c.execute("SELECT COUNT(*) n,COALESCE(SUM(stake_usdc),0) stake,COALESCE(SUM(shares*COALESCE(last_price,entry_price)-stake_usdc),0) upnl FROM positions WHERE status='OPEN'").fetchone()
        x = c.execute("SELECT COUNT(*) n,COALESCE(SUM(pnl_usdc),0) pnl,COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END),0) wins,COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN 1 ELSE 0 END),0) losses FROM positions WHERE status='CLOSED'").fetchone()
        total_pnl = float(r['upnl']) + float(x['pnl'])
        equity = settings.bankroll_usdc + total_pnl
        closed_count = int(x['n'])
        return {
            'open_positions': int(r['n']),
            'open_stake': float(r['stake']),
            'exposure_pct': float(r['stake']) / settings.bankroll_usdc if settings.bankroll_usdc else 0,
            'unrealized_pnl': float(r['upnl']),
            'closed_positions': closed_count,
            'realized_pnl': float(x['pnl']),
            'total_pnl': total_pnl,
            'equity': equity,
            'return_pct': total_pnl / settings.bankroll_usdc if settings.bankroll_usdc else 0,
            'wins': int(x['wins']),
            'losses': int(x['losses']),
            'win_rate': int(x['wins']) / closed_count if closed_count else 0,
        }


def recent_analyses(limit=50):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?', (limit,))]


def recent_cycles(limit=20):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT ?', (limit,))]


def latest_cycle():
    cycles = recent_cycles(1)
    return cycles[0] if cycles else None


def start_cycle():
    with connect() as c:
        cur = c.execute('INSERT INTO cycles(started_at) VALUES(?)', (now(),))
        return cur.lastrowid


def finish_cycle(cid, seen, eligible, analysed, opened, error=None):
    with connect() as c:
        c.execute('UPDATE cycles SET finished_at=?,markets_seen=?,eligible=?,analysed=?,opened=?,error=? WHERE id=?', (now(), seen, eligible, analysed, opened, error, cid))
