import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from .config import settings

def now(): return datetime.now(timezone.utc).isoformat()
def connect():
    settings.ensure_dirs(); c=sqlite3.connect(Path(settings.database_path)); c.row_factory=sqlite3.Row; return c

def init_db():
    with connect() as c: c.executescript("""
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, market_id TEXT,captured_at TEXT,question TEXT,yes_price REAL,no_price REAL,bid REAL,ask REAL,spread REAL,liquidity REAL,volume REAL,volume_24h REAL,rank_score REAL,raw_json TEXT);
    CREATE INDEX IF NOT EXISTS ix_snap_market_time ON snapshots(market_id,captured_at);
    CREATE TABLE IF NOT EXISTS analyses(id INTEGER PRIMARY KEY,market_id TEXT,created_at TEXT,side TEXT,fair_probability REAL,market_probability REAL,gross_edge REAL,net_edge REAL,confidence REAL,critic_risk REAL,score REAL,stake_usdc REAL,decision TEXT,payload_json TEXT);
    CREATE TABLE IF NOT EXISTS positions(id INTEGER PRIMARY KEY,market_id TEXT,token_id TEXT,question TEXT,side TEXT,entry_price REAL,shares REAL,stake_usdc REAL,opened_at TEXT,status TEXT DEFAULT 'OPEN',last_price REAL,last_marked_at TEXT,exit_price REAL,closed_at TEXT,pnl_usdc REAL,resolution TEXT,UNIQUE(market_id,status));
    CREATE TABLE IF NOT EXISTS cycles(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,markets_seen INTEGER,eligible INTEGER,analysed INTEGER,opened INTEGER,error TEXT);
    """)

def save_snapshot(m):
    with connect() as c:c.execute('INSERT INTO snapshots(market_id,captured_at,question,yes_price,no_price,bid,ask,spread,liquidity,volume,volume_24h,rank_score,raw_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(m.id,now(),m.question,m.yes_price,m.no_price,m.best_bid_yes,m.best_ask_yes,m.spread,m.liquidity,m.volume,m.volume_24h,m.rank_score,m.model_dump_json()))
def save_analysis(o):
    with connect() as c:c.execute('INSERT INTO analyses(market_id,created_at,side,fair_probability,market_probability,gross_edge,net_edge,confidence,critic_risk,score,stake_usdc,decision,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(o.market.id,now(),o.side,o.fair_probability,o.market_probability,o.gross_edge,o.net_edge,o.confidence,o.critic_risk,o.score,o.stake_usdc,o.decision,o.model_dump_json()))
def exposure():
    with connect() as c:return float(c.execute("SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN'").fetchone()['v'])
def open_position(o):
    if o.decision!='OPEN': return False
    token=o.market.yes_token_id if o.side=='YES' else o.market.no_token_id
    try:
      with connect() as c:c.execute("INSERT INTO positions(market_id,token_id,question,side,entry_price,shares,stake_usdc,opened_at,last_price,last_marked_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(o.market.id,token,o.market.question,o.side,o.market_probability,o.stake_usdc/o.market_probability,o.stake_usdc,now(),o.market_probability,now()))
      return True
    except sqlite3.IntegrityError:return False
def mark_positions(markets):
    by={m.id:m for m in markets}; n=0
    with connect() as c:
      for p in c.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall():
        m=by.get(p['market_id'])
        if not m: continue
        price=m.yes_price if p['side']=='YES' else m.no_price
        c.execute('UPDATE positions SET last_price=?,last_marked_at=? WHERE id=?',(price,now(),p['id'])); n+=1
    return n
def list_positions(open_only=False):
    q="SELECT *, (shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl FROM positions"+(" WHERE status='OPEN'" if open_only else "")+" ORDER BY opened_at DESC"
    with connect() as c:return [dict(r) for r in c.execute(q)]
def summary():
    with connect() as c:
      r=c.execute("SELECT COUNT(*) n,COALESCE(SUM(stake_usdc),0) stake,COALESCE(SUM(shares*COALESCE(last_price,entry_price)-stake_usdc),0) upnl FROM positions WHERE status='OPEN'").fetchone()
      x=c.execute("SELECT COUNT(*) n,COALESCE(SUM(pnl_usdc),0) pnl FROM positions WHERE status='CLOSED'").fetchone()
      return {'open_positions':r['n'],'open_stake':r['stake'],'unrealized_pnl':r['upnl'],'closed_positions':x['n'],'realized_pnl':x['pnl']}
def recent_analyses(limit=50):
    with connect() as c:return [dict(r) for r in c.execute('SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?',(limit,))]
def start_cycle():
    with connect() as c:cur=c.execute('INSERT INTO cycles(started_at) VALUES(?)',(now(),)); return cur.lastrowid
def finish_cycle(cid,seen,eligible,analysed,opened,error=None):
    with connect() as c:c.execute('UPDATE cycles SET finished_at=?,markets_seen=?,eligible=?,analysed=?,opened=?,error=? WHERE id=?',(now(),seen,eligible,analysed,opened,error,cid))
