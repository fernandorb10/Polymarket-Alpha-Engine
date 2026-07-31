import csv
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import db
from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now() -> str:
    return utcnow().isoformat()


def connect() -> sqlite3.Connection:
    return db.connect()


def _add_column(conn, table, definition):
    name=definition.split()[0]
    if name not in {r['name'] for r in conn.execute(f'PRAGMA table_info({table})')}:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')


def prepare():
    settings.ensure_dirs(); db.init_db()
    with connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS decision_ledger(id INTEGER PRIMARY KEY,created_at TEXT NOT NULL,cycle_id INTEGER,market_id TEXT,position_id INTEGER,action TEXT NOT NULL,reason TEXT,strategy_version TEXT,campaign_id TEXT,payload_json TEXT);
            CREATE INDEX IF NOT EXISTS ix_ledger_time ON decision_ledger(created_at);
            CREATE INDEX IF NOT EXISTS ix_ledger_market ON decision_ledger(market_id,created_at);
            CREATE TABLE IF NOT EXISTS entry_confirmations(market_id TEXT PRIMARY KEY,side TEXT NOT NULL,confirmations INTEGER NOT NULL DEFAULT 0,first_seen_at TEXT NOT NULL,last_seen_at TEXT NOT NULL,last_edge REAL,last_confidence REAL,payload_json TEXT);
            CREATE TABLE IF NOT EXISTS service_health(component TEXT PRIMARY KEY,consecutive_failures INTEGER NOT NULL DEFAULT 0,last_success_at TEXT,last_failure_at TEXT,last_error TEXT,paused_until TEXT);
            CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,started_at TEXT NOT NULL,ended_at TEXT,strategy_version TEXT,notes TEXT);
            CREATE TABLE IF NOT EXISTS maintenance_runs(name TEXT PRIMARY KEY,last_run_at TEXT NOT NULL,payload_json TEXT);
        """)
        for definition in ('strategy_version TEXT','campaign_id TEXT','mfe_pct REAL DEFAULT 0','mae_pct REAL DEFAULT 0','peak_value_usdc REAL','trough_value_usdc REAL','entry_reason TEXT','close_detail_json TEXT'):
            _add_column(conn,'positions',definition)
        conn.execute('INSERT OR IGNORE INTO campaigns(id,started_at,strategy_version,notes) VALUES(?,?,?,?)',(settings.campaign_id,now(),settings.strategy_version,'Automatic paper-trading campaign'))


def ledger(action, reason='', *, cycle_id=None, market_id=None, position_id=None, payload=None):
    with connect() as conn:
        conn.execute('INSERT INTO decision_ledger(created_at,cycle_id,market_id,position_id,action,reason,strategy_version,campaign_id,payload_json) VALUES(?,?,?,?,?,?,?,?,?)',(now(),cycle_id,market_id,position_id,action,reason,settings.strategy_version,settings.campaign_id,json.dumps(payload or {},ensure_ascii=False,default=str)))


def component_success(component):
    with connect() as conn:
        conn.execute("INSERT INTO service_health(component,consecutive_failures,last_success_at,last_error,paused_until) VALUES(?,0,?,NULL,NULL) ON CONFLICT(component) DO UPDATE SET consecutive_failures=0,last_success_at=excluded.last_success_at,last_error=NULL,paused_until=NULL",(component,now()))


def component_failure(component,error):
    with connect() as conn:
        row=conn.execute('SELECT consecutive_failures FROM service_health WHERE component=?',(component,)).fetchone(); count=int(row['consecutive_failures'])+1 if row else 1
        paused=(utcnow()+timedelta(minutes=settings.circuit_breaker_cooldown_minutes)).isoformat() if count>=settings.circuit_breaker_failures else None
        conn.execute("INSERT INTO service_health(component,consecutive_failures,last_failure_at,last_error,paused_until) VALUES(?,?,?,?,?) ON CONFLICT(component) DO UPDATE SET consecutive_failures=excluded.consecutive_failures,last_failure_at=excluded.last_failure_at,last_error=excluded.last_error,paused_until=excluded.paused_until",(component,count,now(),str(error)[:1000],paused)); return count


def component_available(component):
    with connect() as conn: row=conn.execute('SELECT paused_until FROM service_health WHERE component=?',(component,)).fetchone()
    if not row or not row['paused_until']: return True
    try:return datetime.fromisoformat(row['paused_until'].replace('Z','+00:00'))<=utcnow()
    except ValueError:return True


def drawdown_pause_reason():
    with connect() as conn:
        row=conn.execute('SELECT MAX(equity) peak,(SELECT equity FROM equity_history ORDER BY id DESC LIMIT 1) current FROM equity_history').fetchone()
        day_pnl=conn.execute("SELECT COALESCE(SUM(pnl_usdc),0) pnl FROM positions WHERE status='CLOSED' AND closed_at>=?",(utcnow().replace(hour=0,minute=0,second=0,microsecond=0).isoformat(),)).fetchone()['pnl']
    if row and row['peak'] and row['current'] is not None:
        drawdown=(float(row['peak'])-float(row['current']))/float(row['peak'])
        if drawdown>=settings.pause_drawdown_pct:return f'DRAWDOWN_PAUSE:{drawdown:.2%}'
    if float(day_pnl)<=-(settings.bankroll_usdc*settings.daily_loss_limit_pct):return f'DAILY_LOSS_PAUSE:{float(day_pnl):.2f}'
    return None


def openings_today():
    start=utcnow().replace(hour=0,minute=0,second=0,microsecond=0).isoformat()
    with connect() as conn:return int(conn.execute('SELECT COUNT(*) n FROM positions WHERE opened_at>=? AND campaign_id=?',(start,settings.campaign_id)).fetchone()['n'])


def reopen_block_reason(market_id):
    cutoff=(utcnow()-timedelta(days=settings.reopen_cooldown_days)).isoformat()
    with connect() as conn:row=conn.execute("SELECT closed_at FROM positions WHERE market_id=? AND status='CLOSED' AND closed_at>=? ORDER BY closed_at DESC LIMIT 1",(market_id,cutoff)).fetchone()
    return f"REOPEN_COOLDOWN:{row['closed_at']}" if row else None


def confirm_entry(opportunity):
    market_id=str(opportunity.market.id); side=opportunity.side; stamp=now(); payload=opportunity.model_dump(mode='json'); cutoff=utcnow()-timedelta(minutes=settings.entry_confirmation_expiry_minutes)
    with connect() as conn:
        row=conn.execute('SELECT * FROM entry_confirmations WHERE market_id=?',(market_id,)).fetchone()
        valid=False
        if row and row['side']==side:
            try:valid=datetime.fromisoformat(row['last_seen_at'].replace('Z','+00:00'))>=cutoff
            except ValueError:valid=False
        confirmations=int(row['confirmations'])+1 if valid else 1
        first_seen=row['first_seen_at'] if valid else stamp
        conn.execute('REPLACE INTO entry_confirmations(market_id,side,confirmations,first_seen_at,last_seen_at,last_edge,last_confidence,payload_json) VALUES(?,?,?,?,?,?,?,?)',(market_id,side,confirmations,first_seen,stamp,opportunity.net_edge,opportunity.confidence,json.dumps(payload,ensure_ascii=False)))
    return confirmations>=settings.entry_confirmation_cycles,confirmations


def clear_entry_confirmation(market_id):
    with connect() as conn:conn.execute('DELETE FROM entry_confirmations WHERE market_id=?',(str(market_id),))


def can_open(opportunity):
    if opportunity.decision!='OPEN':return False,f'DECISION_{opportunity.decision}',0
    pause=drawdown_pause_reason()
    if pause:return False,pause,0
    if openings_today()>=settings.max_new_positions_per_day:return False,'DAILY_OPEN_LIMIT',0
    cooldown=reopen_block_reason(str(opportunity.market.id))
    if cooldown:return False,cooldown,0
    confirmed,count=confirm_entry(opportunity)
    if not confirmed:return False,f'ENTRY_CONFIRMATION:{count}/{settings.entry_confirmation_cycles}',count
    return True,'ENTRY_CONFIRMED',count


def tag_open_position(market_id,reason):
    with connect() as conn:
        row=conn.execute("SELECT id FROM positions WHERE market_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",(str(market_id),)).fetchone()
        if not row:return None
        conn.execute('UPDATE positions SET strategy_version=?,campaign_id=?,entry_reason=? WHERE id=?',(settings.strategy_version,settings.campaign_id,reason,row['id'])); return int(row['id'])


def update_excursions():
    with connect() as conn:
        for row in conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall():
            mark=float(row['last_price'] or row['entry_price']); value=float(row['shares'])*mark; pnl_pct=(value-float(row['stake_usdc']))/float(row['stake_usdc']) if row['stake_usdc'] else 0
            conn.execute('UPDATE positions SET mfe_pct=?,mae_pct=?,peak_value_usdc=?,trough_value_usdc=? WHERE id=?',(max(float(row['mfe_pct'] or 0),pnl_pct),min(float(row['mae_pct'] or 0),pnl_pct),max(float(row['peak_value_usdc'] or value),value),min(float(row['trough_value_usdc'] or value),value),row['id']))


def daily_maintenance(force=False):
    result={'skipped':False,'backup':None,'snapshots_deleted':0,'ledger_deleted':0}
    cutoff=utcnow()-timedelta(hours=settings.maintenance_min_interval_hours)
    with connect() as conn:
        last=conn.execute("SELECT last_run_at FROM maintenance_runs WHERE name='daily'").fetchone()
        if not force and last:
            try:
                if datetime.fromisoformat(last['last_run_at'].replace('Z','+00:00'))>cutoff:
                    result['skipped']=True; return result
            except ValueError:pass
    backup_dir=Path(settings.backup_dir); backup_dir.mkdir(parents=True,exist_ok=True); db_path=Path(settings.database_path)
    if db_path.exists():
        target=backup_dir/f"alpha_engine-{utcnow().strftime('%Y%m%d-%H%M%S')}.db"
        with connect() as source,sqlite3.connect(target) as destination:source.backup(destination)
        result['backup']=str(target)
    with connect() as conn:
        result['snapshots_deleted']=conn.execute('DELETE FROM snapshots WHERE captured_at<?',((utcnow()-timedelta(days=settings.snapshot_retention_days)).isoformat(),)).rowcount
        result['ledger_deleted']=conn.execute('DELETE FROM decision_ledger WHERE created_at<?',((utcnow()-timedelta(days=settings.ledger_retention_days)).isoformat(),)).rowcount
        conn.execute("REPLACE INTO maintenance_runs(name,last_run_at,payload_json) VALUES('daily',?,?)",(now(),json.dumps(result)))
    file_cutoff=utcnow()-timedelta(days=settings.backup_retention_days)
    for path in backup_dir.glob('alpha_engine-*.db'):
        if datetime.fromtimestamp(path.stat().st_mtime,timezone.utc)<file_cutoff:path.unlink(missing_ok=True)
    return result


def export_csv(output_dir=None):
    target=Path(output_dir or settings.export_dir);target.mkdir(parents=True,exist_ok=True);exported=[]
    with connect() as conn:
        for table in ('positions','analyses','cycles','equity_history','decision_ledger'):
            rows=conn.execute(f'SELECT * FROM {table}').fetchall();path=target/f'{table}.csv'
            with path.open('w',newline='',encoding='utf-8') as handle:
                writer=csv.writer(handle)
                if rows:writer.writerow(rows[0].keys());writer.writerows([tuple(row) for row in rows])
            exported.append(str(path))
    return exported


def doctor(check_external=True):
    checks={}
    try:
        with connect() as conn:checks['database']=conn.execute('PRAGMA integrity_check').fetchone()[0];checks['tables']=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    except Exception as exc:checks['database']=f'ERROR: {exc}'
    checks['config']={'strategy_version':settings.strategy_version,'campaign_id':settings.campaign_id,'paper_only':True,'ai_provider':settings.ai_provider,'database_path':settings.database_path,'web_research_enabled':settings.web_research_enabled}
    checks['disk_free_mb']=round(shutil.disk_usage(Path(settings.database_path).parent).free/1024/1024,1)
    if check_external:
        for name,url in {'gamma':settings.gamma_url,'clob':settings.clob_url}.items():
            try:
                response=httpx.get(url,timeout=min(settings.http_timeout,10));checks[name]={'status_code':response.status_code,'ok':response.status_code<500}
            except Exception as exc:checks[name]={'ok':False,'error':str(exc)}
    return checks
