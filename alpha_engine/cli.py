import json

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from . import analytics, db, ops
from .config import settings
from .engine import run_cycle
from .logging_setup import configure_logging

app = typer.Typer(no_args_is_help=True)
console = Console()


@app.command()
def init():
    settings.ensure_dirs()
    db.init_db()
    analytics.init_analytics()
    ops.prepare()
    console.print('[green]Database initialized and migrated[/green]')


@app.command()
def cycle(scan_only: bool = typer.Option(False, '--scan-only')):
    configure_logging()
    result = run_cycle(scan_only)
    console.print({k: v for k, v in result.items() if k not in ('top', 'opportunities')})
    table = Table('Score', 'Price', 'Spread', 'Liquidity', 'Question')
    for market in result['top'][:15]:
        table.add_row(
            f'{market.rank_score:.1f}',
            f'{market.yes_price:.3f}',
            f'{market.spread:.3f}',
            f'{market.liquidity:.0f}',
            market.question[:80],
        )
    console.print(table)


@app.command()
def status():
    console.print(analytics.advanced_metrics())


@app.command()
def positions(open_only: bool = False):
    table = Table(
        'ID', 'Status', 'Version', 'Side', 'Entry', 'Mark', 'Stake',
        'PnL', 'MFE', 'MAE', 'Question',
    )
    for position in db.list_positions(open_only):
        pnl = position['unrealized_pnl'] if position['status'] == 'OPEN' else position['pnl_usdc']
        table.add_row(
            str(position['id']),
            position['status'],
            position.get('strategy_version') or 'legacy',
            position['side'],
            f"{position['entry_price']:.4f}",
            f"{(position['last_price'] or position['entry_price']):.4f}",
            f"{position['stake_usdc']:.2f}",
            f"{float(pnl or 0):.2f}",
            f"{float(position.get('mfe_pct') or 0):.1%}",
            f"{float(position.get('mae_pct') or 0):.1%}",
            position['question'][:65],
        )
    console.print(table)


@app.command()
def doctor(no_external: bool = typer.Option(False, '--no-external')):
    """Validate configuration, database integrity, disk and public APIs."""
    db.init_db()
    analytics.init_analytics()
    ops.prepare()
    result = ops.doctor(check_external=not no_external)
    console.print_json(json.dumps(result, default=str))
    if result.get('database') != 'ok':
        raise typer.Exit(code=1)


@app.command('export')
def export_data(output_dir: str | None = typer.Option(None, '--output-dir')):
    """Export positions, analyses, cycles, equity and ledger to CSV."""
    db.init_db()
    analytics.init_analytics()
    ops.prepare()
    files = ops.export_csv(output_dir)
    for file in files:
        console.print(f'[green]{file}[/green]')


@app.command()
def maintenance():
    """Create a verified SQLite backup and enforce data retention."""
    db.init_db()
    analytics.init_analytics()
    ops.prepare()
    result = ops.daily_maintenance()
    console.print(result)


@app.command()
def ledger(limit: int = typer.Option(30, '--limit', min=1, max=500)):
    ops.prepare()
    with ops.connect() as conn:
        rows = conn.execute(
            'SELECT created_at,action,reason,market_id,position_id,strategy_version '
            'FROM decision_ledger ORDER BY id DESC LIMIT ?',
            (limit,),
        ).fetchall()
    table = Table('Time', 'Action', 'Reason', 'Market', 'Position', 'Version')
    for row in rows:
        table.add_row(
            row['created_at'][:19],
            row['action'],
            (row['reason'] or '')[:55],
            row['market_id'] or '-',
            str(row['position_id'] or '-'),
            row['strategy_version'] or '-',
        )
    console.print(table)


@app.command()
def serve(host: str | None = None, port: int | None = None):
    bind_host = host or settings.dashboard_host
    try:
        settings.validate_dashboard_security(bind_host)
    except ValueError as exc:
        console.print(f'[red]{exc}[/red]')
        raise typer.Exit(code=2) from exc
    uvicorn.run(
        'alpha_engine.dashboard:app',
        host=bind_host,
        port=port or settings.dashboard_port,
    )


if __name__ == '__main__':
    app()
