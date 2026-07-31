import csv
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def now() -> str:
    return utcnow().isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    return conn


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
    if name not in existing:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {definition}')


def prepare() -> None:
    settings.ensure_dirs()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS decision_ledger(
                id INTEGER PRIMARY KEY,
                created_at TEXT NOT NULL,
                cycle_id INTEGER,
                market_id TEXT,
                position_id INTEGER,
                action TEXT NOT NULL,
                reason TEXT,
                strategy_version TEXT,
                campaign_id TEXT,
                payload_json TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_ledger_time ON decision_ledger(created_at);
            CREATE INDEX IF NOT EXISTS ix_ledger_market ON decision_ledger(market_id,created_at);

            CREATE TABLE IF NOT EXISTS entry_confirmations(
                market_id TEXT PRIMARY KEY,
                side TEXT NOT NULL,
                confirmations INTEGER NOT NULL DEFAULT 0,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_edge REAL,
                last_confidence REAL,
                payload_json TEXT
            );

            CREATE TABLE IF NOT EXISTS service_health(
                component TEXT PRIMARY KEY,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                last_success_at TEXT,
                last_failure_at TEXT,
                last_error TEXT,
                paused_until TEXT
            );

            CREATE TABLE IF NOT EXISTS campaigns(
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                strategy_version TEXT,
                notes TEXT
            );
            """
        )
        _add_column(conn, 'positions', 'strategy_version TEXT')
        _add_column(conn, 'positions', 'campaign_id TEXT')
        _add_column(conn, 'positions', 'mfe_pct REAL DEFAULT 0')
        _add_column(conn, 'positions', 'mae_pct REAL DEFAULT 0')
        _add_column(conn, 'positions', 'peak_value_usdc REAL')
        _add_column(conn, 'positions', 'trough_value_usdc REAL')
        _add_column(conn, 'positions', 'entry_reason TEXT')
        _add_column(conn, 'positions', 'close_detail_json TEXT')
        conn.execute(
            "INSERT OR IGNORE INTO campaigns(id,started_at,strategy_version,notes) VALUES(?,?,?,?)",
            (settings.campaign_id, now(), settings.strategy_version, 'Automatic paper-trading campaign'),
        )


def ledger(action: str, reason: str = '', *, cycle_id: int | None = None,
           market_id: str | None = None, position_id: int | None = None,
           payload: dict[str, Any] | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO decision_ledger(
                created_at,cycle_id,market_id,position_id,action,reason,
                strategy_version,campaign_id,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (now(), cycle_id, market_id, position_id, action, reason,
             settings.strategy_version, settings.campaign_id,
             json.dumps(payload or {}, ensure_ascii=False, default=str)),
        )


def component_success(component: str) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO service_health(component,consecutive_failures,last_success_at,last_error,paused_until)
               VALUES(?,0,?,NULL,NULL)
               ON CONFLICT(component) DO UPDATE SET consecutive_failures=0,last_success_at=excluded.last_success_at,last_error=NULL,paused_until=NULL""",
            (component, now()),
        )


def component_failure(component: str, error: Exception | str) -> int:
    with connect() as conn:
        row = conn.execute('SELECT consecutive_failures FROM service_health WHERE component=?', (component,)).fetchone()
        count = int(row['consecutive_failures']) + 1 if row else 1
        paused_until = None
        if count >= settings.circuit_breaker_failures:
            paused_until = (utcnow() + timedelta(minutes=settings.circuit_breaker_cooldown_minutes)).isoformat()
        conn.execute(
            """INSERT INTO service_health(component,consecutive_failures,last_failure_at,last_error,paused_until)
               VALUES(?,?,?,?,?)
               ON CONFLICT(component) DO UPDATE SET consecutive_failures=excluded.consecutive_failures,
               last_failure_at=excluded.last_failure_at,last_error=excluded.last_error,paused_until=excluded.paused_until""",
            (component, count, now(), str(error)[:1000], paused_until),
        )
        return count


def component_available(component: str) -> bool:
    with connect() as conn:
        row = conn.execute('SELECT paused_until FROM service_health WHERE component=?', (component,)).fetchone()
    if not row or not row['paused_until']:
        return True
    try:
        return datetime.fromisoformat(row['paused_until'].replace('Z', '+00:00')) <= utcnow()
    except ValueError:
        return True


def drawdown_pause_reason() -> str | None:
    with connect() as conn:
        rows = conn.execute('SELECT equity,captured_at FROM equity_history ORDER BY id').fetchall()
        day_pnl = conn.execute(
            "SELECT COALESCE(SUM(pnl_usdc),0) pnl FROM positions WHERE status='CLOSED' AND closed_at>=?",
            (utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),),
        ).fetchone()['pnl']
    if rows:
        peak = max(float(row['equity']) for row in rows)
        current = float(rows[-1]['equity'])
        drawdown = (peak - current) / peak if peak else 0
        if drawdown >= settings.pause_drawdown_pct:
            return f'DRAWDOWN_PAUSE:{drawdown:.2%}'
    if float(day_pnl) <= -(settings.bankroll_usdc * settings.daily_loss_limit_pct):
        return f'DAILY_LOSS_PAUSE:{float(day_pnl):.2f}'
    return None


def openings_today() -> int:
    """Count only positions opened by the active paper campaign today.

    Legacy positions created before campaign tagging must not consume the current
    campaign's daily opening allowance.
    """
    start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with connect() as conn:
        return int(conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE opened_at>=? AND campaign_id=?",
            (start, settings.campaign_id),
        ).fetchone()['n'])


def reopen_block_reason(market_id: str) -> str | None:
    cutoff = (utcnow() - timedelta(days=settings.reopen_cooldown_days)).isoformat()
    with connect() as conn:
        row = conn.execute(
            "SELECT closed_at,resolution FROM positions WHERE market_id=? AND status='CLOSED' AND closed_at>=? ORDER BY closed_at DESC LIMIT 1",
            (market_id, cutoff),
        ).fetchone()
    return f"REOPEN_COOLDOWN:{row['closed_at']}" if row else None


def confirm_entry(opportunity) -> tuple[bool, int]:
    market_id = str(opportunity.market.id)
    side = opportunity.side
    stamp = now()
    payload = opportunity.model_dump(mode='json')
    with connect() as conn:
        row = conn.execute('SELECT * FROM entry_confirmations WHERE market_id=?', (market_id,)).fetchone()
        if row and row['side'] == side:
            confirmations = int(row['confirmations']) + 1
            conn.execute(
                "UPDATE entry_confirmations SET confirmations=?,last_seen_at=?,last_edge=?,last_confidence=?,payload_json=? WHERE market_id=?",
                (confirmations, stamp, opportunity.net_edge, opportunity.confidence,
                 json.dumps(payload, ensure_ascii=False), market_id),
            )
        else:
            confirmations = 1
            conn.execute(
                "REPLACE INTO entry_confirmations(market_id,side,confirmations,first_seen_at,last_seen_at,last_edge,last_confidence,payload_json) VALUES(?,?,?,?,?,?,?,?)",
                (market_id, side, confirmations, stamp, stamp, opportunity.net_edge,
                 opportunity.confidence, json.dumps(payload, ensure_ascii=False)),
            )
    return confirmations >= settings.entry_confirmation_cycles, confirmations


def clear_entry_confirmation(market_id: str) -> None:
    with connect() as conn:
        conn.execute('DELETE FROM entry_confirmations WHERE market_id=?', (str(market_id),))


def can_open(opportunity) -> tuple[bool, str, int]:
    if opportunity.decision != 'OPEN':
        return False, f'DECISION_{opportunity.decision}', 0
    pause = drawdown_pause_reason()
    if pause:
        return False, pause, 0
    if openings_today() >= settings.max_new_positions_per_day:
        return False, 'DAILY_OPEN_LIMIT', 0
    cooldown = reopen_block_reason(str(opportunity.market.id))
    if cooldown:
        return False, cooldown, 0
    confirmed, count = confirm_entry(opportunity)
    if not confirmed:
        return False, f'ENTRY_CONFIRMATION:{count}/{settings.entry_confirmation_cycles}', count
    return True, 'ENTRY_CONFIRMED', count


def tag_open_position(market_id: str, reason: str) -> int | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM positions WHERE market_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
            (str(market_id),),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE positions SET strategy_version=?,campaign_id=?,entry_reason=? WHERE id=?",
            (settings.strategy_version, settings.campaign_id, reason, row['id']),
        )
        return int(row['id'])


def update_excursions() -> None:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM positions WHERE status='OPEN'").fetchall()
        for row in rows:
            mark = float(row['last_price'] or row['entry_price'])
            value = float(row['shares']) * mark
            pnl_pct = (value - float(row['stake_usdc'])) / float(row['stake_usdc']) if row['stake_usdc'] else 0
            mfe = max(float(row['mfe_pct'] or 0), pnl_pct)
            mae = min(float(row['mae_pct'] or 0), pnl_pct)
            peak_value = max(float(row['peak_value_usdc'] or value), value)
            trough_value = min(float(row['trough_value_usdc'] or value), value)
            conn.execute(
                "UPDATE positions SET mfe_pct=?,mae_pct=?,peak_value_usdc=?,trough_value_usdc=? WHERE id=?",
                (mfe, mae, peak_value, trough_value, row['id']),
            )


def daily_maintenance() -> dict[str, Any]:
    result: dict[str, Any] = {'backup': None, 'snapshots_deleted': 0, 'ledger_deleted': 0}
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    db_path = Path(settings.database_path)
    if db_path.exists():
        target = backup_dir / f"alpha_engine-{utcnow().strftime('%Y%m%d')}.db"
        if not target.exists():
            with connect() as source, sqlite3.connect(target) as destination:
                source.backup(destination)
            result['backup'] = str(target)
    snapshot_cutoff = (utcnow() - timedelta(days=settings.snapshot_retention_days)).isoformat()
    ledger_cutoff = (utcnow() - timedelta(days=settings.ledger_retention_days)).isoformat()
    with connect() as conn:
        result['snapshots_deleted'] = conn.execute('DELETE FROM snapshots WHERE captured_at<?', (snapshot_cutoff,)).rowcount
        result['ledger_deleted'] = conn.execute('DELETE FROM decision_ledger WHERE created_at<?', (ledger_cutoff,)).rowcount
    cutoff_files = utcnow() - timedelta(days=settings.backup_retention_days)
    for path in backup_dir.glob('alpha_engine-*.db'):
        if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff_files:
            path.unlink(missing_ok=True)
    return result


def export_csv(output_dir: str | None = None) -> list[str]:
    target = Path(output_dir or settings.export_dir)
    target.mkdir(parents=True, exist_ok=True)
    exported = []
    tables = ('positions', 'analyses', 'cycles', 'equity_history', 'decision_ledger')
    with connect() as conn:
        for table in tables:
            rows = conn.execute(f'SELECT * FROM {table}').fetchall()
            path = target / f'{table}.csv'
            with path.open('w', newline='', encoding='utf-8') as handle:
                writer = csv.writer(handle)
                if rows:
                    writer.writerow(rows[0].keys())
                    writer.writerows([tuple(row) for row in rows])
            exported.append(str(path))
    return exported


def doctor(check_external: bool = True) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    try:
        with connect() as conn:
            checks['database'] = conn.execute('PRAGMA integrity_check').fetchone()[0]
            checks['tables'] = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    except Exception as exc:
        checks['database'] = f'ERROR: {exc}'
    checks['config'] = {
        'strategy_version': settings.strategy_version,
        'campaign_id': settings.campaign_id,
        'paper_only': True,
        'ai_provider': settings.ai_provider,
        'database_path': settings.database_path,
    }
    checks['disk_free_mb'] = round(shutil.disk_usage(Path(settings.database_path).parent).free / 1024 / 1024, 1)
    if check_external:
        for name, url in {'gamma': settings.gamma_url, 'clob': settings.clob_url}.items():
            try:
                response = httpx.get(url, timeout=min(settings.http_timeout, 10))
                checks[name] = {'status_code': response.status_code, 'ok': response.status_code < 500}
            except Exception as exc:
                checks[name] = {'ok': False, 'error': str(exc)}
    return checks
