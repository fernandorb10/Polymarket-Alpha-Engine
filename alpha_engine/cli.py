import typer, uvicorn
from rich.console import Console
from rich.table import Table
from .config import settings
from .logging_setup import configure_logging
from .engine import run_cycle
from . import db
app=typer.Typer(no_args_is_help=True); console=Console()
@app.command()
def init():
 settings.ensure_dirs(); db.init_db(); console.print('[green]Database initialized[/green]')
@app.command()
def cycle(scan_only:bool=typer.Option(False,'--scan-only')):
 configure_logging(); r=run_cycle(scan_only); console.print({k:v for k,v in r.items() if k not in ('top','opportunities')})
 t=Table('Score','Price','Spread','Liquidity','Question')
 for m in r['top'][:15]:t.add_row(f'{m.rank_score:.1f}',f'{m.yes_price:.3f}',f'{m.spread:.3f}',f'{m.liquidity:.0f}',m.question[:80])
 console.print(t)
@app.command()
def status(): console.print(db.summary())
@app.command()
def positions(open_only:bool=False):
 t=Table('ID','Side','Entry','Mark','Stake','uPnL','Question')
 for p in db.list_positions(open_only):t.add_row(str(p['id']),p['side'],f"{p['entry_price']:.3f}",f"{(p['last_price'] or p['entry_price']):.3f}",f"{p['stake_usdc']:.2f}",f"{p['unrealized_pnl']:.2f}",p['question'][:70])
 console.print(t)
@app.command()
def serve(host:str|None=None,port:int|None=None):
 uvicorn.run('alpha_engine.dashboard:app',host=host or settings.dashboard_host,port=port or settings.dashboard_port)
if __name__=='__main__': app()
