import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import settings
from .taxonomy import classify_market
from .taxonomy import event_key as build_event_key

POSITIONS_LEGACY_TABLE = "positions_legacy_unique"


def now() -> str:
    return datetime.now(UTC).isoformat()


def connect() -> sqlite3.Connection:
    settings.ensure_dirs()
    conn = sqlite3.connect(Path(settings.database_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    name = definition.split()[0]
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if name not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _create_positions(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS positions(
            id INTEGER PRIMARY KEY,
            market_id TEXT NOT NULL,
            token_id TEXT,
            question TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            shares REAL NOT NULL,
            stake_usdc REAL NOT NULL,
            opened_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'OPEN',
            last_price REAL,
            last_marked_at TEXT,
            exit_price REAL,
            closed_at TEXT,
            pnl_usdc REAL,
            resolution TEXT,
            category TEXT,
            event_key TEXT,
            peak_price REAL,
            edge_gone_count INTEGER DEFAULT 0,
            entry_fee_usdc REAL DEFAULT 0,
            exit_fee_usdc REAL DEFAULT 0,
            strategy_version TEXT,
            campaign_id TEXT,
            mfe_pct REAL DEFAULT 0,
            mae_pct REAL DEFAULT 0,
            peak_value_usdc REAL,
            trough_value_usdc REAL,
            entry_reason TEXT,
            close_detail_json TEXT
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_positions_open_market "
        "ON positions(market_id) WHERE status='OPEN'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_status_event "
        "ON positions(status,event_key)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS ix_positions_status_category "
        "ON positions(status,category)"
    )


def _copy_positions(conn: sqlite3.Connection, source: str) -> None:
    old_cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({source})")}
    new_cols = {row["name"] for row in conn.execute("PRAGMA table_info(positions)")}
    common = sorted(old_cols & new_cols)
    if not common:
        raise RuntimeError(f"Cannot recover positions from {source}: no common columns")
    names = ",".join(common)
    conn.execute(f"INSERT INTO positions({names}) SELECT {names} FROM {source}")


def _positions_has_legacy_unique(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='positions'"
    ).fetchone()
    sql = (row["sql"] or "").replace(" ", "").lower() if row else ""
    return "unique(market_id,status)" in sql


def _recover_or_migrate_positions(conn: sqlite3.Connection) -> None:
    """Atomically recover interrupted migrations or remove the legacy constraint."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        legacy_exists = _table_exists(conn, POSITIONS_LEGACY_TABLE)
        positions_exists = _table_exists(conn, "positions")

        if legacy_exists:
            if not positions_exists:
                _create_positions(conn)
                _copy_positions(conn, POSITIONS_LEGACY_TABLE)
                conn.execute(f"DROP TABLE {POSITIONS_LEGACY_TABLE}")
            else:
                legacy_count = conn.execute(
                    f"SELECT COUNT(*) n FROM {POSITIONS_LEGACY_TABLE}"
                ).fetchone()["n"]
                positions_count = conn.execute(
                    "SELECT COUNT(*) n FROM positions"
                ).fetchone()["n"]
                if positions_count == 0:
                    _copy_positions(conn, POSITIONS_LEGACY_TABLE)
                    conn.execute(f"DROP TABLE {POSITIONS_LEGACY_TABLE}")
                elif legacy_count == 0:
                    conn.execute(f"DROP TABLE {POSITIONS_LEGACY_TABLE}")
                else:
                    raise RuntimeError(
                        "Both positions and positions_legacy_unique contain data; "
                        "manual recovery is required"
                    )

        if not _table_exists(conn, "positions"):
            _create_positions(conn)
        elif _positions_has_legacy_unique(conn):
            conn.execute(
                f"ALTER TABLE positions RENAME TO {POSITIONS_LEGACY_TABLE}"
            )
            _create_positions(conn)
            _copy_positions(conn, POSITIONS_LEGACY_TABLE)
            conn.execute(f"DROP TABLE {POSITIONS_LEGACY_TABLE}")
        else:
            _create_positions(conn)

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots(
                id INTEGER PRIMARY KEY,
                market_id TEXT,
                captured_at TEXT,
                question TEXT,
                yes_price REAL,
                no_price REAL,
                bid REAL,
                ask REAL,
                spread REAL,
                liquidity REAL,
                volume REAL,
                volume_24h REAL,
                rank_score REAL,
                raw_json TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_snap_market_time
                ON snapshots(market_id,captured_at);
            CREATE TABLE IF NOT EXISTS analyses(
                id INTEGER PRIMARY KEY,
                market_id TEXT,
                created_at TEXT,
                side TEXT,
                fair_probability REAL,
                market_probability REAL,
                gross_edge REAL,
                net_edge REAL,
                confidence REAL,
                critic_risk REAL,
                score REAL,
                stake_usdc REAL,
                decision TEXT,
                payload_json TEXT
            );
            CREATE INDEX IF NOT EXISTS ix_analysis_market_time
                ON analyses(market_id,created_at);
            CREATE TABLE IF NOT EXISTS cycles(
                id INTEGER PRIMARY KEY,
                started_at TEXT,
                finished_at TEXT,
                markets_seen INTEGER,
                eligible INTEGER,
                analysed INTEGER,
                opened INTEGER,
                error TEXT
            );
            """
        )

    with connect() as conn:
        _recover_or_migrate_positions(conn)
        definitions = (
            "category TEXT",
            "event_key TEXT",
            "peak_price REAL",
            "edge_gone_count INTEGER DEFAULT 0",
            "entry_fee_usdc REAL DEFAULT 0",
            "exit_fee_usdc REAL DEFAULT 0",
            "strategy_version TEXT",
            "campaign_id TEXT",
            "mfe_pct REAL DEFAULT 0",
            "mae_pct REAL DEFAULT 0",
            "peak_value_usdc REAL",
            "trough_value_usdc REAL",
            "entry_reason TEXT",
            "close_detail_json TEXT",
        )
        for definition in definitions:
            _add_column(conn, "positions", definition)
        _create_positions(conn)


def classify_question(question: str, raw_category: str = "") -> tuple[str, str]:
    return (
        classify_market(question, raw_category),
        build_event_key(question, raw_category),
    )


def reclassify_positions() -> int:
    updated = 0
    with connect() as conn:
        rows = conn.execute("SELECT id,question FROM positions").fetchall()
        for row in rows:
            category, key = classify_question(row["question"])
            conn.execute(
                "UPDATE positions SET category=?,event_key=? WHERE id=?",
                (category, key, row["id"]),
            )
            updated += 1
    return updated


def save_snapshots(markets) -> None:
    stamp = now()
    rows = [
        (
            market.id,
            stamp,
            market.question,
            market.yes_price,
            market.no_price,
            market.best_bid_yes,
            market.best_ask_yes,
            market.spread,
            market.liquidity,
            market.volume,
            market.volume_24h,
            market.rank_score,
            market.model_dump_json(),
        )
        for market in markets
    ]
    with connect() as conn:
        conn.executemany(
            """
            INSERT INTO snapshots(
                market_id,captured_at,question,yes_price,no_price,bid,ask,
                spread,liquidity,volume,volume_24h,rank_score,raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )


def save_snapshot(market) -> None:
    save_snapshots([market])


def save_analysis(opportunity) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO analyses(
                market_id,created_at,side,fair_probability,market_probability,
                gross_edge,net_edge,confidence,critic_risk,score,stake_usdc,
                decision,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                opportunity.market.id,
                now(),
                opportunity.side,
                opportunity.fair_probability,
                opportunity.market_probability,
                opportunity.gross_edge,
                opportunity.net_edge,
                opportunity.confidence,
                opportunity.critic_risk,
                opportunity.score,
                opportunity.stake_usdc,
                opportunity.decision,
                opportunity.model_dump_json(),
            ),
        )


def exposure() -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(stake_usdc),0) v "
            "FROM positions WHERE status='OPEN'"
        ).fetchone()
    return float(row["v"])


def open_market_ids() -> set[str]:
    with connect() as conn:
        return {
            str(row["market_id"])
            for row in conn.execute(
                "SELECT market_id FROM positions WHERE status='OPEN'"
            )
        }


def open_market_ids_by_oldest_analysis() -> list[str]:
    """Rotate management calls so every open position is eventually reanalysed."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.market_id, MAX(a.created_at) AS last_analysis
            FROM positions p
            LEFT JOIN analyses a ON a.market_id=p.market_id
            WHERE p.status='OPEN'
            GROUP BY p.market_id
            ORDER BY last_analysis IS NOT NULL, last_analysis, p.opened_at
            """
        ).fetchall()
    return [str(row["market_id"]) for row in rows]


def recently_analyzed_market_ids(minutes: int) -> set[str]:
    cutoff = (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat()
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT market_id FROM analyses WHERE created_at>=?",
            (cutoff,),
        )
    return {str(row["market_id"]) for row in rows}


def _portfolio_usage(question: str, raw_category: str = "") -> dict[str, float | int | str]:
    category, key = classify_question(question, raw_category)
    with connect() as conn:
        total = float(
            conn.execute(
                "SELECT COALESCE(SUM(stake_usdc),0) v "
                "FROM positions WHERE status='OPEN'"
            ).fetchone()["v"]
        )
        category_stake = float(
            conn.execute(
                "SELECT COALESCE(SUM(stake_usdc),0) v FROM positions "
                "WHERE status='OPEN' AND category=?",
                (category,),
            ).fetchone()["v"]
        )
        event_stake = float(
            conn.execute(
                "SELECT COALESCE(SUM(stake_usdc),0) v FROM positions "
                "WHERE status='OPEN' AND event_key=?",
                (key,),
            ).fetchone()["v"]
        )
        related = int(
            conn.execute(
                "SELECT COUNT(*) n FROM positions "
                "WHERE status='OPEN' AND event_key=?",
                (key,),
            ).fetchone()["n"]
        )
    return {
        "category": category,
        "event_key": key,
        "total": total,
        "category_stake": category_stake,
        "event_stake": event_stake,
        "related": related,
    }


def max_allowed_stake(question: str, raw_category: str = "") -> tuple[float, str | None]:
    usage = _portfolio_usage(question, raw_category)
    if int(usage["related"]) >= settings.max_related_positions:
        return 0.0, "RELATED_LIMIT"

    rooms = {
        "TOTAL_EXPOSURE_LIMIT": (
            settings.bankroll_usdc * settings.max_total_exposure_pct
            - float(usage["total"])
        ),
        "CATEGORY_LIMIT": (
            settings.bankroll_usdc * settings.max_category_exposure_pct
            - float(usage["category_stake"])
        ),
        "EVENT_LIMIT": (
            settings.bankroll_usdc * settings.max_event_exposure_pct
            - float(usage["event_stake"])
        ),
    }
    limiting_reason, room = min(rooms.items(), key=lambda item: item[1])
    return max(0.0, room), limiting_reason if room <= 0 else None


def portfolio_allows(
    question: str,
    stake: float,
    raw_category: str = "",
) -> tuple[bool, str | None]:
    room, reason = max_allowed_stake(question, raw_category)
    if room + 1e-9 < stake:
        return False, reason or "PORTFOLIO_LIMIT"
    return True, None


def _buy_price(price: float) -> float:
    return min(0.999, max(0.001, price * (1 + settings.paper_execution_slippage_pct)))


def _sell_price(price: float) -> float:
    return min(0.999, max(0.001, price * (1 - settings.paper_execution_slippage_pct)))


def executable_entry_price(market, side: str) -> float:
    if side == "YES":
        if market.best_ask_yes is not None:
            return market.best_ask_yes
        return market.yes_price + market.spread / 2
    if market.best_bid_yes is not None:
        return 1 - market.best_bid_yes
    return market.no_price + market.spread / 2


def executable_exit_price(market, side: str) -> float:
    if side == "YES":
        if market.best_bid_yes is not None:
            return market.best_bid_yes
        return market.yes_price - market.spread / 2
    if market.best_ask_yes is not None:
        return 1 - market.best_ask_yes
    return market.no_price - market.spread / 2


def open_position(opportunity) -> bool:
    if opportunity.decision != "OPEN":
        return False

    room, _ = max_allowed_stake(
        opportunity.market.question,
        opportunity.market.category,
    )
    stake = round(min(float(opportunity.stake_usdc), room), 2)
    if stake < 1:
        return False
    opportunity.stake_usdc = stake

    token = (
        opportunity.market.yes_token_id
        if opportunity.side == "YES"
        else opportunity.market.no_token_id
    )
    category, key = classify_question(
        opportunity.market.question,
        opportunity.market.category,
    )
    entry_price = _buy_price(
        executable_entry_price(opportunity.market, opportunity.side)
    )
    fee = stake * settings.paper_fee_pct
    shares = max(0.0, stake - fee) / entry_price if entry_price else 0.0

    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO positions(
                    market_id,token_id,question,side,entry_price,shares,
                    stake_usdc,opened_at,last_price,last_marked_at,category,
                    event_key,peak_price,edge_gone_count,entry_fee_usdc
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    opportunity.market.id,
                    token,
                    opportunity.market.question,
                    opportunity.side,
                    entry_price,
                    shares,
                    stake,
                    now(),
                    entry_price,
                    now(),
                    category,
                    key,
                    entry_price,
                    0,
                    fee,
                ),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def mark_positions(markets) -> int:
    by_id = {str(market.id): market for market in markets}
    marked = 0
    stamp = now()
    with connect() as conn:
        positions = conn.execute(
            "SELECT * FROM positions WHERE status='OPEN'"
        ).fetchall()
        for position in positions:
            market = by_id.get(str(position["market_id"]))
            if not market:
                continue
            price = executable_exit_price(market, position["side"])
            peak = max(float(position["peak_price"] or position["entry_price"]), price)
            conn.execute(
                "UPDATE positions SET last_price=?,last_marked_at=?,peak_price=? "
                "WHERE id=?",
                (price, stamp, peak, position["id"]),
            )
            marked += 1
    return marked


def _close_position_with_conn(
    conn: sqlite3.Connection,
    position: sqlite3.Row | dict,
    market_price: float,
    reason: str,
) -> dict[str, float]:
    exit_price = _sell_price(market_price)
    gross = float(position["shares"]) * exit_price
    exit_fee = gross * settings.paper_fee_pct
    pnl = gross - exit_fee - float(position["stake_usdc"])
    stamp = now()
    conn.execute(
        """
        UPDATE positions
        SET status='CLOSED',exit_price=?,closed_at=?,pnl_usdc=?,resolution=?,
            last_price=?,last_marked_at=?,exit_fee_usdc=?,close_detail_json=?
        WHERE id=? AND status='OPEN'
        """,
        (
            exit_price,
            stamp,
            pnl,
            reason,
            market_price,
            stamp,
            exit_fee,
            json.dumps(
                {
                    "gross_value": gross,
                    "exit_fee": exit_fee,
                    "reason": reason,
                }
            ),
            position["id"],
        ),
    )
    return {"exit_price": exit_price, "pnl_usdc": pnl}


def close_position(position_id: int, market_price: float, reason: str):
    with connect() as conn:
        position = conn.execute(
            "SELECT * FROM positions WHERE id=? AND status='OPEN'",
            (position_id,),
        ).fetchone()
        if not position:
            return False
        return _close_position_with_conn(conn, position, market_price, reason)


def manage_exits(markets, opportunities) -> list[dict]:
    market_by_id = {str(market.id): market for market in markets}
    opportunity_by_id = {
        str(opportunity.market.id): opportunity for opportunity in opportunities
    }
    closed = []
    current = datetime.now(UTC)

    with connect() as conn:
        positions = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM positions WHERE status='OPEN'"
            ).fetchall()
        ]

        for position in positions:
            market = market_by_id.get(str(position["market_id"]))
            if not market:
                continue

            executable = executable_exit_price(market, position["side"])
            estimate = _sell_price(executable)
            exit_fee = (
                float(position["shares"])
                * estimate
                * settings.paper_fee_pct
            )
            pnl = (
                float(position["shares"]) * estimate
                - exit_fee
                - float(position["stake_usdc"])
            )
            stake = float(position["stake_usdc"])
            pnl_pct = pnl / stake if stake else 0.0
            peak = max(
                float(position.get("peak_price") or position["entry_price"]),
                executable,
            )
            trailing = (peak - executable) / peak if peak else 0.0
            reason = None

            if pnl_pct >= settings.take_profit_pct:
                reason = "TAKE_PROFIT"
            elif pnl_pct <= -settings.stop_loss_pct:
                reason = "STOP_LOSS"
            elif (
                peak
                >= float(position["entry_price"])
                * (1 + settings.trailing_activation_pct)
                and trailing >= settings.trailing_stop_pct
            ):
                reason = "TRAILING_STOP"
            else:
                opened_at = datetime.fromisoformat(position["opened_at"])
                if (current - opened_at).days >= settings.max_position_age_days:
                    reason = "MAX_AGE"
                elif market.end_date is not None:
                    end = (
                        market.end_date
                        if market.end_date.tzinfo
                        else market.end_date.replace(tzinfo=UTC)
                    )
                    hours_left = (end - current).total_seconds() / 3600
                    if hours_left <= settings.exit_hours_to_resolution:
                        reason = "NEAR_RESOLUTION"

            opportunity = opportunity_by_id.get(str(position["market_id"]))
            edge_bad = opportunity is not None and (
                opportunity.side != position["side"]
                or opportunity.net_edge < settings.exit_min_edge
                or opportunity.decision == "REJECT"
            )
            count = int(position.get("edge_gone_count") or 0)
            if edge_bad:
                count += 1
            elif opportunity is not None:
                count = 0

            conn.execute(
                "UPDATE positions SET edge_gone_count=? WHERE id=?",
                (count, position["id"]),
            )
            if reason is None and count >= settings.exit_confirmation_cycles:
                reason = "EDGE_GONE_CONFIRMED"

            if reason:
                result = _close_position_with_conn(
                    conn,
                    position,
                    executable,
                    reason,
                )
                closed.append(
                    {
                        "id": position["id"],
                        "question": position["question"],
                        "reason": reason,
                        "pnl_pct": pnl_pct,
                        **result,
                    }
                )
    return closed


def list_positions(open_only: bool = False) -> list[dict]:
    query = (
        "SELECT *, "
        "(shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl "
        "FROM positions"
    )
    if open_only:
        query += " WHERE status='OPEN'"
    query += " ORDER BY opened_at DESC"
    with connect() as conn:
        return [dict(row) for row in conn.execute(query)]


def summary() -> dict:
    with connect() as conn:
        open_row = conn.execute(
            """
            SELECT COUNT(*) n,
                   COALESCE(SUM(stake_usdc),0) stake,
                   COALESCE(SUM(
                       shares*COALESCE(last_price,entry_price)-stake_usdc
                   ),0) upnl
            FROM positions WHERE status='OPEN'
            """
        ).fetchone()
        closed_row = conn.execute(
            """
            SELECT COUNT(*) n,
                   COALESCE(SUM(pnl_usdc),0) pnl,
                   COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END),0) wins,
                   COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN 1 ELSE 0 END),0) losses,
                   COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN pnl_usdc ELSE 0 END),0) gp,
                   ABS(COALESCE(SUM(
                       CASE WHEN pnl_usdc<0 THEN pnl_usdc ELSE 0 END
                   ),0)) gl
            FROM positions WHERE status='CLOSED'
            """
        ).fetchone()

    total = float(open_row["upnl"]) + float(closed_row["pnl"])
    closed_count = int(closed_row["n"])
    gross_loss = float(closed_row["gl"])
    return {
        "open_positions": int(open_row["n"]),
        "open_stake": float(open_row["stake"]),
        "exposure_pct": float(open_row["stake"]) / settings.bankroll_usdc,
        "unrealized_pnl": float(open_row["upnl"]),
        "closed_positions": closed_count,
        "realized_pnl": float(closed_row["pnl"]),
        "total_pnl": total,
        "equity": settings.bankroll_usdc + total,
        "return_pct": total / settings.bankroll_usdc,
        "wins": int(closed_row["wins"]),
        "losses": int(closed_row["losses"]),
        "win_rate": int(closed_row["wins"]) / closed_count if closed_count else 0,
        "profit_factor": (
            float(closed_row["gp"]) / gross_loss if gross_loss else None
        ),
    }


def category_exposure() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(category,'other') category,
                   COUNT(*) positions,
                   SUM(stake_usdc) stake
            FROM positions
            WHERE status='OPEN'
            GROUP BY category
            ORDER BY stake DESC
            """
        )
    return [dict(row) for row in rows]


def recent_analyses(limit: int = 50) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return [dict(row) for row in rows]


def recent_cycles(limit: int = 20) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cycles ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    return [dict(row) for row in rows]


def latest_cycle() -> dict | None:
    rows = recent_cycles(1)
    return rows[0] if rows else None


def start_cycle() -> int:
    with connect() as conn:
        cursor = conn.execute("INSERT INTO cycles(started_at) VALUES(?)", (now(),))
        return int(cursor.lastrowid)


def finish_cycle(
    cycle_id: int,
    seen: int,
    eligible: int,
    analysed: int,
    opened: int,
    error: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE cycles
            SET finished_at=?,markets_seen=?,eligible=?,analysed=?,opened=?,error=?
            WHERE id=?
            """,
            (now(), seen, eligible, analysed, opened, error, cycle_id),
        )
