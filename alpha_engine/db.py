import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import settings
from .taxonomy import classify_market, event_key as build_event_key


def now():
    return datetime.now(timezone.utc).isoformat()


def connect():
    settings.ensure_dirs()
    conn = sqlite3.connect(Path(settings.database_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _add_column(conn, table, definition):
    name = definition.split()[0]
    columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    if name not in columns:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')


def _create_positions(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions(
            id INTEGER PRIMARY KEY, market_id TEXT NOT NULL, token_id TEXT,
            question TEXT NOT NULL, side TEXT NOT NULL, entry_price REAL NOT NULL,
            shares REAL NOT NULL, stake_usdc REAL NOT NULL, opened_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN', last_price REAL, last_marked_at TEXT,
            exit_price REAL, closed_at TEXT, pnl_usdc REAL, resolution TEXT,
            category TEXT, event_key TEXT, peak_price REAL,
            edge_gone_count INTEGER DEFAULT 0, entry_fee_usdc REAL DEFAULT 0,
            exit_fee_usdc REAL DEFAULT 0, strategy_version TEXT, campaign_id TEXT,
            mfe_pct REAL DEFAULT 0, mae_pct REAL DEFAULT 0, peak_value_usdc REAL,
            trough_value_usdc REAL, entry_reason TEXT, close_detail_json TEXT
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_open_market ON positions(market_id) WHERE status='OPEN'")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_positions_status_event ON positions(status,event_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_positions_status_category ON positions(status,category)")


def _migrate_positions_unique_constraint(conn):
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='positions'").fetchone()
    sql = (row['sql'] or '').replace(' ', '').lower() if row else ''
    if 'unique(market_id,status)' not in sql:
        _create_positions(conn)
        return
    conn.execute('ALTER TABLE positions RENAME TO positions_legacy_unique')
    _create_positions(conn)
    old_cols = {r['name'] for r in conn.execute('PRAGMA table_info(positions_legacy_unique)')}
    new_cols = {r['name'] for r in conn.execute('PRAGMA table_info(positions)')}
    common = sorted(old_cols & new_cols)
    names = ','.join(common)
    conn.execute(f'INSERT INTO positions({names}) SELECT {names} FROM positions_legacy_unique')
    conn.execute('DROP TABLE positions_legacy_unique')


def init_db():
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY,market_id TEXT,captured_at TEXT,question TEXT,yes_price REAL,no_price REAL,bid REAL,ask REAL,spread REAL,liquidity REAL,volume REAL,volume_24h REAL,rank_score REAL,raw_json TEXT);
            CREATE INDEX IF NOT EXISTS ix_snap_market_time ON snapshots(market_id,captured_at);
            CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY,market_id TEXT,created_at TEXT,side TEXT,fair_probability REAL,market_probability REAL,gross_edge REAL,net_edge REAL,confidence REAL,critic_risk REAL,score REAL,stake_usdc REAL,decision TEXT,payload_json TEXT);
            CREATE INDEX IF NOT EXISTS ix_analysis_market_time ON analyses(market_id,created_at);
            CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,markets_seen INTEGER,eligible INTEGER,analysed INTEGER,opened INTEGER,error TEXT);
        """)
        _migrate_positions_unique_constraint(conn)
        for definition in ('category TEXT','event_key TEXT','peak_price REAL','edge_gone_count INTEGER DEFAULT 0','entry_fee_usdc REAL DEFAULT 0','exit_fee_usdc REAL DEFAULT 0','strategy_version TEXT','campaign_id TEXT','mfe_pct REAL DEFAULT 0','mae_pct REAL DEFAULT 0','peak_value_usdc REAL','trough_value_usdc REAL','entry_reason TEXT','close_detail_json TEXT'):
            _add_column(conn, 'positions', definition)
        _create_positions(conn)


def classify_question(question, raw_category=''):
    return classify_market(question, raw_category), build_event_key(question, raw_category)


def reclassify_positions():
    updated = 0
    with connect() as conn:
        for row in conn.execute('SELECT id,question FROM positions').fetchall():
            category, key = classify_question(row['question'])
            conn.execute('UPDATE positions SET category=?,event_key=? WHERE id=?', (category, key, row['id']))
            updated += 1
    return updated


def save_snapshots(markets):
    stamp = now()
    rows = [(m.id,stamp,m.question,m.yes_price,m.no_price,m.best_bid_yes,m.best_ask_yes,m.spread,m.liquidity,m.volume,m.volume_24h,m.rank_score,m.model_dump_json()) for m in markets]
    with connect() as conn:
        conn.executemany('INSERT INTO snapshots(market_id,captured_at,question,yes_price,no_price,bid,ask,spread,liquidity,volume,volume_24h,rank_score,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)


def save_snapshot(m):
    save_snapshots([m])


def save_analysis(o):
    with connect() as conn:
        conn.execute('INSERT INTO analyses(market_id,created_at,side,fair_probability,market_probability,gross_edge,net_edge,confidence,critic_risk,score,stake_usdc,decision,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(o.market.id,now(),o.side,o.fair_probability,o.market_probability,o.gross_edge,o.net_edge,o.confidence,o.critic_risk,o.score,o.stake_usdc,o.decision,o.model_dump_json()))


def exposure():
    with connect() as conn:
        return float(conn.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN'").fetchone()['v'])


def open_market_ids():
    with connect() as conn:
        return {str(r['market_id']) for r in conn.execute("SELECT market_id FROM positions WHERE status='OPEN'")}


def recently_analyzed_market_ids(minutes):
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    with connect() as conn:
        return {str(r['market_id']) for r in conn.execute('SELECT DISTINCT market_id FROM analyses WHERE created_at>=?', (cutoff,))}


def portfolio_allows(question, stake, raw_category=''):
    category, key = classify_question(question, raw_category)
    with connect() as conn:
        total = float(conn.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN'").fetchone()['v'])
        category_stake = float(conn.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN' AND category=?", (category,)).fetchone()['v'])
        event_stake = float(conn.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN' AND event_key=?", (key,)).fetchone()['v'])
        related = int(conn.execute("SELECT COUNT(*) n FROM positions WHERE status='OPEN' AND event_key=?", (key,)).fetchone()['n'])
    if total + stake > settings.bankroll_usdc * settings.max_total_exposure_pct + 1e-9:
        return False, 'TOTAL_EXPOSURE_LIMIT'
    if category_stake + stake > settings.bankroll_usdc * settings.max_category_exposure_pct + 1e-9:
        return False, 'CATEGORY_LIMIT'
    if event_stake + stake > settings.bankroll_usdc * settings.max_event_exposure_pct + 1e-9:
        return False, 'EVENT_LIMIT'
    if related >= settings.max_related_positions:
        return False, 'RELATED_LIMIT'
    return True, None


def _buy_price(price):
    return min(.999, max(.001, price * (1 + settings.paper_execution_slippage_pct)))


def _sell_price(price):
    return min(.999, max(.001, price * (1 - settings.paper_execution_slippage_pct)))


def executable_entry_price(market, side):
    if side == 'YES':
        return market.best_ask_yes if market.best_ask_yes is not None else market.yes_price + market.spread / 2
    return 1 - market.best_bid_yes if market.best_bid_yes is not None else market.no_price + market.spread / 2


def executable_exit_price(market, side):
    if side == 'YES':
        return market.best_bid_yes if market.best_bid_yes is not None else market.yes_price - market.spread / 2
    return 1 - market.best_ask_yes if market.best_ask_yes is not None else market.no_price - market.spread / 2


def open_position(o):
    if o.decision != 'OPEN': return False
    allowed, _ = portfolio_allows(o.market.question, o.stake_usdc, o.market.category)
    if not allowed: return False
    token = o.market.yes_token_id if o.side == 'YES' else o.market.no_token_id
    category, key = classify_question(o.market.question, o.market.category)
    entry_price = _buy_price(executable_entry_price(o.market, o.side))
    fee = o.stake_usdc * settings.paper_fee_pct
    shares = max(0, o.stake_usdc - fee) / entry_price if entry_price else 0
    try:
        with connect() as conn:
            conn.execute("INSERT INTO positions(market_id,token_id,question,side,entry_price,shares,stake_usdc,opened_at,last_price,last_marked_at,category,event_key,peak_price,edge_gone_count,entry_fee_usdc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(o.market.id,token,o.market.question,o.side,entry_price,shares,o.stake_usdc,now(),entry_price,now(),category,key,entry_price,0,fee))
        return True
    except sqlite3.IntegrityError:
        return False


def mark_positions(markets):
    by_id = {str(m.id): m for m in markets}; marked = 0
    with connect() as conn:
        for p in conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall():
            m = by_id.get(str(p['market_id']))
            if not m: continue
            price = executable_exit_price(m, p['side'])
            peak = max(float(p['peak_price'] or p['entry_price']), price)
            conn.execute('UPDATE positions SET last_price=?,last_marked_at=?,peak_price=? WHERE id=?',(price,now(),peak,p['id']))
            marked += 1
    return marked


def close_position(position_id, market_price, reason):
    with connect() as conn:
        p = conn.execute("SELECT * FROM positions WHERE id=? AND status='OPEN'",(position_id,)).fetchone()
        if not p: return False
        exit_price = _sell_price(market_price)
        gross = p['shares'] * exit_price
        exit_fee = gross * settings.paper_fee_pct
        pnl = gross - exit_fee - p['stake_usdc']
        conn.execute("UPDATE positions SET status='CLOSED',exit_price=?,closed_at=?,pnl_usdc=?,resolution=?,last_price=?,last_marked_at=?,exit_fee_usdc=?,close_detail_json=? WHERE id=?",(exit_price,now(),pnl,reason,market_price,now(),exit_fee,json.dumps({'gross_value':gross,'exit_fee':exit_fee,'reason':reason}),position_id))
        return {'exit_price':exit_price,'pnl_usdc':pnl}


def manage_exits(markets, opportunities):
    market_by_id = {str(m.id):m for m in markets}; opp_by_id = {str(o.market.id):o for o in opportunities}; closed=[]; current=datetime.now(timezone.utc)
    with connect() as conn: positions=[dict(r) for r in conn.execute("SELECT * FROM positions WHERE status='OPEN'")]
    for p in positions:
        m=market_by_id.get(str(p['market_id']))
        if not m: continue
        executable=executable_exit_price(m,p['side']); estimate=_sell_price(executable); exit_fee=p['shares']*estimate*settings.paper_fee_pct
        pnl=p['shares']*estimate-exit_fee-p['stake_usdc']; pnl_pct=pnl/p['stake_usdc'] if p['stake_usdc'] else 0
        peak=max(float(p.get('peak_price') or p['entry_price']),executable); trailing=(peak-executable)/peak if peak else 0; reason=None
        if pnl_pct>=settings.take_profit_pct: reason='TAKE_PROFIT'
        elif pnl_pct<=-settings.stop_loss_pct: reason='STOP_LOSS'
        elif peak>=p['entry_price']*(1+settings.trailing_activation_pct) and trailing>=settings.trailing_stop_pct: reason='TRAILING_STOP'
        elif (current-datetime.fromisoformat(p['opened_at'].replace('Z','+00:00'))).days>=settings.max_position_age_days: reason='MAX_AGE'
        elif m.end_date is not None:
            end=m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
            if (end-current).total_seconds()/3600<=settings.exit_hours_to_resolution: reason='NEAR_RESOLUTION'
        opp=opp_by_id.get(str(p['market_id'])); edge_bad=opp is not None and (opp.side!=p['side'] or opp.net_edge<settings.exit_min_edge or opp.decision=='REJECT')
        count=int(p.get('edge_gone_count') or 0); count=count+1 if edge_bad else (0 if opp is not None else count)
        with connect() as conn: conn.execute('UPDATE positions SET edge_gone_count=? WHERE id=?',(count,p['id']))
        if reason is None and count>=settings.exit_confirmation_cycles: reason='EDGE_GONE_CONFIRMED'
        if reason:
            result=close_position(p['id'],executable,reason)
            if result: closed.append({'id':p['id'],'question':p['question'],'reason':reason,'pnl_pct':pnl_pct,**result})
    return closed


def list_positions(open_only=False):
    q="SELECT *, (shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl FROM positions"+(" WHERE status='OPEN'" if open_only else '')+' ORDER BY opened_at DESC'
    with connect() as conn: return [dict(r) for r in conn.execute(q)]


def summary():
    with connect() as conn:
        o=conn.execute("SELECT COUNT(*) n,COALESCE(SUM(stake_usdc),0) stake,COALESCE(SUM(shares*COALESCE(last_price,entry_price)-stake_usdc),0) upnl FROM positions WHERE status='OPEN'").fetchone()
        c=conn.execute("SELECT COUNT(*) n,COALESCE(SUM(pnl_usdc),0) pnl,COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END),0) wins,COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN 1 ELSE 0 END),0) losses,COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN pnl_usdc ELSE 0 END),0) gp,ABS(COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN pnl_usdc ELSE 0 END),0)) gl FROM positions WHERE status='CLOSED'").fetchone()
    total=float(o['upnl'])+float(c['pnl']); closed=int(c['n']); gl=float(c['gl'])
    return {'open_positions':int(o['n']),'open_stake':float(o['stake']),'exposure_pct':float(o['stake'])/settings.bankroll_usdc,'unrealized_pnl':float(o['upnl']),'closed_positions':closed,'realized_pnl':float(c['pnl']),'total_pnl':total,'equity':settings.bankroll_usdc+total,'return_pct':total/settings.bankroll_usdc,'wins':int(c['wins']),'losses':int(c['losses']),'win_rate':int(c['wins'])/closed if closed else 0,'profit_factor':float(c['gp'])/gl if gl else None}


def category_exposure():
    with connect() as conn: return [dict(r) for r in conn.execute("SELECT COALESCE(category,'other') category,COUNT(*) positions,SUM(stake_usdc) stake FROM positions WHERE status='OPEN' GROUP BY category ORDER BY stake DESC")]

def recent_analyses(limit=50):
    with connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?',(limit,))]

def recent_cycles(limit=20):
    with connect() as conn: return [dict(r) for r in conn.execute('SELECT * FROM cycles ORDER BY id DESC LIMIT ?',(limit,))]

def latest_cycle():
    rows=recent_cycles(1); return rows[0] if rows else None

def start_cycle():
    with connect() as conn: return conn.execute('INSERT INTO cycles(started_at) VALUES(?)',(now(),)).lastrowid

def finish_cycle(cid,seen,eligible,analysed,opened,error=None):
    with connect() as conn: conn.execute('UPDATE cycles SET finished_at=?,markets_seen=?,eligible=?,analysed=?,opened=?,error=? WHERE id=?',(now(),seen,eligible,analysed,opened,error,cid))
