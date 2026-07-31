import re
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


def _add_column(c, table, definition):
    name = definition.split()[0]
    columns = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
    if name not in columns:
        c.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')


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
        _add_column(c, 'positions', 'category TEXT')
        _add_column(c, 'positions', 'event_key TEXT')
        _add_column(c, 'positions', 'peak_price REAL')
        _add_column(c, 'positions', 'edge_gone_count INTEGER DEFAULT 0')
        _add_column(c, 'positions', 'entry_fee_usdc REAL DEFAULT 0')
        _add_column(c, 'positions', 'exit_fee_usdc REAL DEFAULT 0')
        c.execute("CREATE INDEX IF NOT EXISTS ix_positions_status_event ON positions(status,event_key)")
        c.execute("CREATE INDEX IF NOT EXISTS ix_positions_status_category ON positions(status,category)")


def classify_question(question):
    text = question.lower()
    if any(x in text for x in ('election', 'president', 'nomination', 'senate', 'congress', 'prime minister')):
        category = 'politics'
    elif any(x in text for x in ('bitcoin', 'ethereum', 'crypto', 'solana', 'token')):
        category = 'crypto'
    elif any(x in text for x in ('nba', 'nfl', 'mlb', 'nhl', 'championship', 'world cup', 'league')):
        category = 'sports'
    elif any(x in text for x in ('fed', 'inflation', 'gdp', 'recession', 'interest rate')):
        category = 'economy'
    else:
        category = 'other'

    normalized = re.sub(r'\b(will|does|do|is|are|the|a|an|win|be|by|on|in|of|to|as)\b', ' ', text)
    years = re.findall(r'20\d{2}', text)
    words = [w for w in re.findall(r'[a-z0-9]+', normalized) if len(w) > 2 and not w.isdigit()]
    event_words = sorted(set(words))[:8]
    event_key = category + ':' + '-'.join(event_words + years[:1])
    return category, event_key[:180]


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


def portfolio_allows(question, stake):
    category, event_key = classify_question(question)
    with connect() as c:
        category_stake = float(c.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN' AND category=?", (category,)).fetchone()['v'])
        event_stake = float(c.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN' AND event_key=?", (event_key,)).fetchone()['v'])
        related = int(c.execute("SELECT COUNT(*) n FROM positions WHERE status='OPEN' AND event_key=?", (event_key,)).fetchone()['n'])
    if category_stake + stake > settings.bankroll_usdc * settings.max_category_exposure_pct:
        return False, 'CATEGORY_LIMIT'
    if event_stake + stake > settings.bankroll_usdc * settings.max_event_exposure_pct:
        return False, 'EVENT_LIMIT'
    if related >= settings.max_related_positions:
        return False, 'RELATED_LIMIT'
    return True, None


def _buy_price(price):
    return min(0.999, max(0.001, price * (1 + settings.paper_execution_slippage_pct)))


def _sell_price(price):
    return min(0.999, max(0.001, price * (1 - settings.paper_execution_slippage_pct)))


def open_position(o):
    if o.decision != 'OPEN':
        return False
    allowed, _ = portfolio_allows(o.market.question, o.stake_usdc)
    if not allowed:
        return False
    token = o.market.yes_token_id if o.side == 'YES' else o.market.no_token_id
    category, event_key = classify_question(o.market.question)
    entry_price = _buy_price(o.market_probability)
    fee = o.stake_usdc * settings.paper_fee_pct
    investable = max(0, o.stake_usdc - fee)
    shares = investable / entry_price if entry_price else 0
    try:
        with connect() as c:
            c.execute(
                "INSERT INTO positions(market_id,token_id,question,side,entry_price,shares,stake_usdc,opened_at,last_price,last_marked_at,category,event_key,peak_price,edge_gone_count,entry_fee_usdc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (o.market.id, token, o.market.question, o.side, entry_price, shares, o.stake_usdc, now(), o.market_probability, now(), category, event_key, o.market_probability, 0, fee),
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
            peak = max(float(p['peak_price'] or p['entry_price']), price)
            c.execute('UPDATE positions SET last_price=?,last_marked_at=?,peak_price=? WHERE id=?', (price, now(), peak, p['id']))
            n += 1
    return n


def close_position(position_id, market_price, reason):
    with connect() as c:
        p = c.execute("SELECT * FROM positions WHERE id=? AND status='OPEN'", (position_id,)).fetchone()
        if not p:
            return False
        exit_price = _sell_price(market_price)
        gross_value = p['shares'] * exit_price
        exit_fee = gross_value * settings.paper_fee_pct
        pnl = gross_value - exit_fee - p['stake_usdc']
        c.execute(
            "UPDATE positions SET status='CLOSED',exit_price=?,closed_at=?,pnl_usdc=?,resolution=?,last_price=?,last_marked_at=?,exit_fee_usdc=? WHERE id=?",
            (exit_price, now(), pnl, reason, market_price, now(), exit_fee, position_id),
        )
        return {'exit_price': exit_price, 'pnl_usdc': pnl}


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
        exit_estimate = _sell_price(price)
        exit_fee = p['shares'] * exit_estimate * settings.paper_fee_pct
        pnl = p['shares'] * exit_estimate - exit_fee - p['stake_usdc']
        pnl_pct = pnl / p['stake_usdc'] if p['stake_usdc'] else 0
        peak = max(float(p.get('peak_price') or p['entry_price']), price)
        trailing_drawdown = (peak - price) / peak if peak else 0
        reason = None

        if pnl_pct >= settings.take_profit_pct:
            reason = 'TAKE_PROFIT'
        elif pnl_pct <= -settings.stop_loss_pct:
            reason = 'STOP_LOSS'
        elif peak >= p['entry_price'] * (1 + settings.trailing_activation_pct) and trailing_drawdown >= settings.trailing_stop_pct:
            reason = 'TRAILING_STOP'
        elif (current - datetime.fromisoformat(p['opened_at'].replace('Z', '+00:00'))).days >= settings.max_position_age_days:
            reason = 'MAX_AGE'
        elif market.end_date is not None:
            end = market.end_date if market.end_date.tzinfo else market.end_date.replace(tzinfo=timezone.utc)
            if (end - current).total_seconds() / 3600 <= settings.exit_hours_to_resolution:
                reason = 'NEAR_RESOLUTION'

        opportunity = opportunity_by_id.get(p['market_id'])
        edge_bad = opportunity is not None and (opportunity.side != p['side'] or opportunity.net_edge < settings.exit_min_edge or opportunity.decision == 'REJECT')
        edge_count = int(p.get('edge_gone_count') or 0)
        if edge_bad:
            edge_count += 1
        elif opportunity is not None:
            edge_count = 0
        with connect() as c:
            c.execute('UPDATE positions SET edge_gone_count=? WHERE id=?', (edge_count, p['id']))
        if reason is None and edge_count >= settings.exit_confirmation_cycles:
            reason = 'EDGE_GONE_CONFIRMED'

        if reason:
            result = close_position(p['id'], price, reason)
            if result:
                closed.append({'id': p['id'], 'question': p['question'], 'reason': reason, 'pnl_pct': pnl_pct, **result})
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
        x = c.execute("SELECT COUNT(*) n,COALESCE(SUM(pnl_usdc),0) pnl,COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END),0) wins,COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN 1 ELSE 0 END),0) losses,COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN pnl_usdc ELSE 0 END),0) gross_profit,ABS(COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN pnl_usdc ELSE 0 END),0)) gross_loss FROM positions WHERE status='CLOSED'").fetchone()
        total_pnl = float(r['upnl']) + float(x['pnl'])
        closed_count = int(x['n'])
        gross_loss = float(x['gross_loss'])
        return {
            'open_positions': int(r['n']), 'open_stake': float(r['stake']),
            'exposure_pct': float(r['stake']) / settings.bankroll_usdc if settings.bankroll_usdc else 0,
            'unrealized_pnl': float(r['upnl']), 'closed_positions': closed_count,
            'realized_pnl': float(x['pnl']), 'total_pnl': total_pnl,
            'equity': settings.bankroll_usdc + total_pnl,
            'return_pct': total_pnl / settings.bankroll_usdc if settings.bankroll_usdc else 0,
            'wins': int(x['wins']), 'losses': int(x['losses']),
            'win_rate': int(x['wins']) / closed_count if closed_count else 0,
            'profit_factor': float(x['gross_profit']) / gross_loss if gross_loss else (float('inf') if float(x['gross_profit']) > 0 else 0),
        }


def category_exposure():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT COALESCE(category,'other') category,COUNT(*) positions,SUM(stake_usdc) stake FROM positions WHERE status='OPEN' GROUP BY category ORDER BY stake DESC")]


def recent_analyses(limit=50):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?', (limit,))]


def recent_cycles(limit=20):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT ?', (limit,))]


def latest_cycle():
    rows = recent_cycles(1)
    return rows[0] if rows else None


def start_cycle():
    with connect() as c:
        cur = c.execute('INSERT INTO cycles(started_at) VALUES(?)', (now(),))
        return cur.lastrowid


def finish_cycle(cid, seen, eligible, analysed, opened, error=None):
    with connect() as c:
        c.execute('UPDATE cycles SET finished_at=?,markets_seen=?,eligible=?,analysed=?,opened=?,error=? WHERE id=?', (now(), seen, eligible, analysed, opened, error, cid))
