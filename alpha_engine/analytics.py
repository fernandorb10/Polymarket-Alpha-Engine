import math
from datetime import datetime, timezone

from . import db


def init_analytics():
    with db.connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS equity_history(
                id INTEGER PRIMARY KEY,captured_at TEXT NOT NULL,equity REAL NOT NULL,
                total_pnl REAL NOT NULL,realized_pnl REAL NOT NULL,unrealized_pnl REAL NOT NULL,
                exposure REAL NOT NULL,open_positions INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_equity_history_time ON equity_history(captured_at);
        """)


def record_equity():
    init_analytics(); summary = db.summary()
    with db.connect() as conn:
        conn.execute('INSERT INTO equity_history(captured_at,equity,total_pnl,realized_pnl,unrealized_pnl,exposure,open_positions) VALUES(?,?,?,?,?,?,?)',(datetime.now(timezone.utc).isoformat(),summary['equity'],summary['total_pnl'],summary['realized_pnl'],summary['unrealized_pnl'],summary['open_stake'],summary['open_positions']))
    return summary


def equity_history(limit=None):
    init_analytics()
    query='SELECT * FROM equity_history ORDER BY captured_at DESC'; params=()
    if limit is not None:
        query+=' LIMIT ?'; params=(limit,)
    with db.connect() as conn: rows=conn.execute(query,params).fetchall()
    return [dict(r) for r in reversed(rows)]


def price_history(market_id,limit=250):
    with db.connect() as conn:
        rows=conn.execute('SELECT captured_at,yes_price,no_price,spread,liquidity,volume_24h FROM snapshots WHERE market_id=? ORDER BY captured_at DESC LIMIT ?',(str(market_id),limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def position_detail(position_id):
    with db.connect() as conn:
        position=conn.execute('SELECT *, (shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl FROM positions WHERE id=?',(position_id,)).fetchone()
        if not position:return None
        analyses=conn.execute('SELECT * FROM analyses WHERE market_id=? ORDER BY created_at DESC LIMIT 25',(position['market_id'],)).fetchall()
        ledger=conn.execute('SELECT * FROM decision_ledger WHERE market_id=? OR position_id=? ORDER BY created_at DESC LIMIT 100',(position['market_id'],position_id)).fetchall()
    return {'position':dict(position),'analyses':[dict(r) for r in analyses],'prices':price_history(position['market_id']),'ledger':[dict(r) for r in ledger]}


def _risk_ratios(returns,timestamps):
    if len(returns)<2:return 0.,0.,0.
    mean=sum(returns)/len(returns); variance=sum((r-mean)**2 for r in returns)/(len(returns)-1); volatility=math.sqrt(variance)
    downside=[min(0.,r) for r in returns]; downside_deviation=math.sqrt(sum(r*r for r in downside)/len(downside))
    gaps=[]
    for a,b in zip(timestamps,timestamps[1:]):
        gaps.append(max(1.,(b-a).total_seconds()))
    median_gap=sorted(gaps)[len(gaps)//2] if gaps else 86400.
    periods_per_year=(365.25*24*3600)/median_gap; scale=math.sqrt(periods_per_year)
    return volatility,(mean/volatility)*scale if volatility else 0.,(mean/downside_deviation)*scale if downside_deviation else 0.


def advanced_metrics():
    summary=db.summary(); history=equity_history()
    with db.connect() as conn:
        closed=[dict(r) for r in conn.execute("SELECT pnl_usdc,stake_usdc,opened_at,closed_at,resolution,mfe_pct,mae_pct,strategy_version,campaign_id,category FROM positions WHERE status='CLOSED' ORDER BY closed_at")]
        versions=[dict(r) for r in conn.execute("SELECT COALESCE(strategy_version,'legacy') strategy_version,COUNT(*) trades,COALESCE(SUM(pnl_usdc),0) pnl,COALESCE(AVG(pnl_usdc),0) expectancy FROM positions WHERE status='CLOSED' GROUP BY COALESCE(strategy_version,'legacy') ORDER BY strategy_version")]
        categories=[dict(r) for r in conn.execute("SELECT COALESCE(category,'other') category,COUNT(*) trades,COALESCE(SUM(pnl_usdc),0) pnl,COALESCE(AVG(pnl_usdc),0) expectancy FROM positions WHERE status='CLOSED' GROUP BY COALESCE(category,'other') ORDER BY pnl DESC")]
    peak=-math.inf; max_drawdown=current_drawdown=0.
    for point in history:
        equity=float(point['equity']); peak=max(peak,equity); drawdown=(peak-equity)/peak if peak>0 else 0.; max_drawdown=max(max_drawdown,drawdown); current_drawdown=drawdown
    wins=[float(p['pnl_usdc']) for p in closed if float(p['pnl_usdc'] or 0)>0]; losses=[float(p['pnl_usdc']) for p in closed if float(p['pnl_usdc'] or 0)<0]
    returns=[]; timestamps=[datetime.fromisoformat(p['captured_at'].replace('Z','+00:00')) for p in history]
    for previous,current in zip(history,history[1:]):
        p=float(previous['equity']); q=float(current['equity']);
        if p:returns.append((q-p)/p)
    volatility,sharpe,sortino=_risk_ratios(returns,timestamps)
    return {**summary,'max_drawdown_pct':max_drawdown,'current_drawdown_pct':current_drawdown,'avg_win_usdc':sum(wins)/len(wins) if wins else 0.,'avg_loss_usdc':sum(losses)/len(losses) if losses else 0.,'expectancy_usdc':sum(float(p['pnl_usdc'] or 0) for p in closed)/len(closed) if closed else 0.,'avg_mfe_pct':sum(float(p.get('mfe_pct') or 0) for p in closed)/len(closed) if closed else 0.,'avg_mae_pct':sum(float(p.get('mae_pct') or 0) for p in closed)/len(closed) if closed else 0.,'equity_volatility':volatility,'sharpe_estimate':sharpe,'sortino_estimate':sortino,'equity_points':len(history),'closed_trades':len(closed),'by_strategy_version':versions,'by_category':categories}
