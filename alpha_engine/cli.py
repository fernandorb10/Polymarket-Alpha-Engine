import json
from pathlib import Path
import typer
from rich.console import Console
from rich.table import Table
from .db import init_db, summary, list_open_positions
from .engine import scan

app = typer.Typer(help="Polymarket Alpha Engine: scanner IA y paper trading")
console = Console()


@app.command()
def init():
    init_db(); console.print("[green]Base de datos inicializada.[/green]")


@app.command()
def run(limit: int = 250, analyze: int = 10, execute: bool = False, output: str = "reports/latest.json"):
    """Escanea, investiga y opcionalmente abre operaciones simuladas."""
    result = scan(limit=limit, analyze=analyze, execute=execute)
    table = Table(title="Mejores oportunidades")
    for col in ["Score","Decisión","Lado","Mercado","Precio","Justo","Edge neto","Stake"]: table.add_column(col)
    for o in result:
        table.add_row(f"{o.score:.1f}", o.decision, o.side, o.market.question[:55],
                      f"{o.market_probability:.3f}", f"{o.fair_probability:.3f}",
                      f"{o.net_edge:+.1%}", f"${o.stake_usdc:.2f}")
    console.print(table)
    path = Path(output); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([o.model_dump(mode="json") for o in result], ensure_ascii=False, indent=2))
    console.print(f"Informe: {path}")


@app.command()
def status():
    init_db(); s = summary(); console.print(s)
    for p in list_open_positions():
        console.print(f"#{p['id']} {p['side']} ${p['stake_usdc']:.2f} — {p['question']}")


if __name__ == "__main__": app()
