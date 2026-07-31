import json
import secrets
from datetime import datetime, timezone
from html import escape
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from . import db
from .config import settings

app = FastAPI(title='EL ROJILLA BOT')
security = HTTPBasic(auto_error=False)


def auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not settings.dashboard_username or not settings.dashboard_password:
        return True
    valid = credentials and secrets.compare_digest(credentials.username, settings.dashboard_username) and secrets.compare_digest(credentials.password, settings.dashboard_password)
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Authentication required', headers={'WWW-Authenticate': 'Basic'})
    return True


def money(v): return f"${float(v or 0):,.2f}"
def pct(v): return f"{float(v or 0)*100:.1f}%"
def dt(v):
    if not v: return '-'
    try: return datetime.fromisoformat(v.replace('Z','+00:00')).astimezone(timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')
    except Exception: return str(v)[:19]


def engine_status():
    latest = db.latest_cycle()
    if not latest or not latest.get('finished_at'): return 'UNKNOWN','No completed cycle'
    try: age=(datetime.now(timezone.utc)-datetime.fromisoformat(latest['finished_at'].replace('Z','+00:00'))).total_seconds()/60
    except Exception: return 'UNKNOWN','Invalid cycle timestamp'
    if latest.get('error'): return 'ERROR',latest['error']
    if age>settings.stale_cycle_minutes: return 'STALE',f'Last cycle {age:.0f} minutes ago'
    return 'HEALTHY',f'Last cycle {age:.0f} minutes ago'


@app.get('/health')
def health(_=Depends(auth)):
    s,d=engine_status(); return {'status':s,'detail':d,'summary':db.summary()}

@app.get('/api/status')
def api_status(_=Depends(auth)): return db.summary()
@app.get('/api/positions')
def api_positions(_=Depends(auth)): return db.list_positions()
@app.get('/api/analyses')
def api_analyses(_=Depends(auth)): return db.recent_analyses()
@app.get('/api/cycles')
def api_cycles(_=Depends(auth)): return db.recent_cycles()
@app.get('/api/category-exposure')
def api_category_exposure(_=Depends(auth)): return db.category_exposure()


@app.get('/', response_class=HTMLResponse)
def home(_=Depends(auth)):
    summary=db.summary(); positions=db.list_positions(); cycles=db.recent_cycles(10); analyses={}
    for a in db.recent_analyses(100): analyses.setdefault(a['market_id'],a)
    open_rows=[]; closed_rows=[]
    for p in positions:
        if p['status']=='OPEN':
            a=analyses.get(p['market_id'],{}); thesis='No thesis stored'
            try: thesis=json.loads(a.get('payload_json') or '{}').get('probability_report',{}).get('thesis') or thesis
            except Exception: pass
            mark=p['last_price'] or p['entry_price']; pnl=p['unrealized_pnl']; cls='positive' if pnl>0 else 'negative' if pnl<0 else 'neutral'
            open_rows.append(f"<tr><td><strong>{escape(p['question'])}</strong><div class='muted'>{escape(thesis[:220])}</div><div class='muted'>{escape(p.get('category') or 'other')} · Opened {dt(p['opened_at'])}</div></td><td><b>{p['side']}</b></td><td>{p['entry_price']:.4f}</td><td>{mark:.4f}</td><td>{money(p['stake_usdc'])}</td><td class='{cls}'>{money(pnl)}<div class='muted'>{pct(pnl/p['stake_usdc'] if p['stake_usdc'] else 0)}</div></td><td>{pct(a.get('net_edge',0))}</td><td>{pct(a.get('confidence',0))}</td><td>{pct(a.get('critic_risk',0))}</td><td>{p.get('edge_gone_count') or 0}/{settings.exit_confirmation_cycles}</td><td>{dt(p.get('last_marked_at'))}</td></tr>")
        else:
            pnl=p['pnl_usdc'] or 0; cls='positive' if pnl>0 else 'negative' if pnl<0 else 'neutral'
            closed_rows.append(f"<tr><td>{escape(p['question'])}</td><td>{p['side']}</td><td>{p['entry_price']:.4f}</td><td>{(p['exit_price'] or 0):.4f}</td><td class='{cls}'>{money(pnl)}</td><td>{escape(p.get('resolution') or '-')}</td><td>{dt(p.get('closed_at'))}</td></tr>")
    cycle_rows=[]
    for c in cycles:
        result='ERROR' if c.get('error') else 'OK'; cls='negative' if c.get('error') else 'positive'
        cycle_rows.append(f"<tr><td>{c['id']}</td><td>{dt(c.get('started_at'))}</td><td>{c.get('markets_seen') or 0}</td><td>{c.get('eligible') or 0}</td><td>{c.get('analysed') or 0}</td><td>{c.get('opened') or 0}</td><td class='{cls}'>{result}</td></tr>")
    exposure_rows=''.join(f"<tr><td>{escape(x['category'])}</td><td>{x['positions']}</td><td>{money(x['stake'])}</td><td>{pct(x['stake']/settings.bankroll_usdc if settings.bankroll_usdc else 0)}</td></tr>" for x in db.category_exposure())
    state,detail=engine_status(); state_cls='positive' if state=='HEALTHY' else 'negative' if state=='ERROR' else 'warning'
    pf='∞' if summary['profit_factor']==float('inf') else f"{summary['profit_factor']:.2f}"
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta http-equiv='refresh' content='{settings.dashboard_refresh_seconds}'><meta name='viewport' content='width=device-width,initial-scale=1'><title>EL ROJILLA BOT</title><style>
    :root{{color-scheme:dark}}body{{font-family:Inter,Arial;background:#0b1020;color:#e8ecf3;margin:0}}main{{max-width:1650px;margin:auto;padding:28px}}h1{{margin:0}}h2{{margin-top:30px}}.top{{display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:14px;margin:22px 0}}.card,.status{{background:#141b2d;border:1px solid #26314d;border-radius:12px;padding:16px}}.label,.muted{{color:#8792a8;font-size:12px}}.value{{font-size:24px;font-weight:700;margin-top:7px}}.wrap{{overflow-x:auto;border:1px solid #26314d;border-radius:12px}}table{{border-collapse:collapse;width:100%;min-width:900px;background:#11182a}}th,td{{padding:12px;border-bottom:1px solid #222d47;text-align:left;vertical-align:top}}th{{color:#9aa5ba;font-size:12px;text-transform:uppercase;background:#151d31}}.positive{{color:#54d69b}}.negative{{color:#ff7b8b}}.warning{{color:#f4c96b}}.neutral{{color:#c8d0df}}.empty{{padding:24px;background:#11182a;border:1px solid #26314d;border-radius:12px;color:#8792a8}}
    </style></head><body><main><div class='top'><div><h1>EL ROJILLA BOT</h1><div class='muted'>Paper trading · Gemini · realistic slippage & fees · refresh every {settings.dashboard_refresh_seconds}s</div></div><div class='status'><strong class='{state_cls}'>{state}</strong><div class='muted'>{escape(detail)}</div></div></div>
    <section class='cards'><div class='card'><div class='label'>Equity</div><div class='value'>{money(summary['equity'])}</div></div><div class='card'><div class='label'>Total return</div><div class='value'>{pct(summary['return_pct'])}</div></div><div class='card'><div class='label'>Exposure</div><div class='value'>{money(summary['open_stake'])}</div><div class='muted'>{pct(summary['exposure_pct'])}</div></div><div class='card'><div class='label'>Unrealized PnL</div><div class='value'>{money(summary['unrealized_pnl'])}</div></div><div class='card'><div class='label'>Realized PnL</div><div class='value'>{money(summary['realized_pnl'])}</div></div><div class='card'><div class='label'>Win rate</div><div class='value'>{pct(summary['win_rate'])}</div></div><div class='card'><div class='label'>Profit factor</div><div class='value'>{pf}</div></div></section>
    <h2>Open positions</h2>{"<div class='wrap'><table><tr><th>Market & thesis</th><th>Side</th><th>Entry</th><th>Mark</th><th>Stake</th><th>uPnL</th><th>Edge</th><th>Confidence</th><th>Risk</th><th>Exit confirm</th><th>Last mark</th></tr>"+''.join(open_rows)+"</table></div>" if open_rows else "<div class='empty'>No open positions.</div>"}
    <h2>Exposure by category</h2>{"<div class='wrap'><table><tr><th>Category</th><th>Positions</th><th>Stake</th><th>Bankroll</th></tr>"+exposure_rows+"</table></div>" if exposure_rows else "<div class='empty'>No category exposure.</div>"}
    <h2>Recently closed</h2>{"<div class='wrap'><table><tr><th>Market</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th><th>Closed</th></tr>"+''.join(closed_rows[:20])+"</table></div>" if closed_rows else "<div class='empty'>No closed positions yet.</div>"}
    <h2>Recent cycles</h2><div class='wrap'><table><tr><th>ID</th><th>Started</th><th>Seen</th><th>Eligible</th><th>Analysed</th><th>Opened</th><th>Result</th></tr>{''.join(cycle_rows)}</table></div></main></body></html>"""
