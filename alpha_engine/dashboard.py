import json
import secrets
from datetime import datetime, timezone
from html import escape
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from . import analytics, db
from .config import settings

app = FastAPI(title='EL ROJILLA BOT')
security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not settings.dashboard_username or not settings.dashboard_password:
        return True
    valid = credentials is not None
    if valid:
        valid = secrets.compare_digest(credentials.username, settings.dashboard_username) and secrets.compare_digest(credentials.password, settings.dashboard_password)
    if not valid:
        raise HTTPException(status_code=401, detail='Authentication required', headers={'WWW-Authenticate': 'Basic'})
    return True


def money(value): return f"${float(value or 0):,.2f}"
def pct(value): return f"{float(value or 0) * 100:.1f}%"

def dt(value):
    if not value: return '-'
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')
    except (TypeError, ValueError):
        return str(value)[:19]


def payload(analysis):
    try: return json.loads(analysis.get('payload_json') or '{}')
    except (TypeError, json.JSONDecodeError): return {}


def engine_status(latest):
    if not latest or not latest.get('finished_at'): return 'UNKNOWN', 'No completed cycle'
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest['finished_at'].replace('Z', '+00:00'))).total_seconds() / 60
    except (TypeError, ValueError): return 'UNKNOWN', 'Invalid cycle timestamp'
    if latest.get('error'): return 'ERROR', latest['error']
    if age > settings.stale_cycle_minutes: return 'STALE', f'Last cycle {age:.0f} minutes ago'
    return 'HEALTHY', f'Last cycle {age:.0f} minutes ago'


def svg_line(values, width=900, height=220):
    if not values: return "<div class='empty'>No equity history yet.</div>"
    vals = [float(v) for v in values]
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    points = []
    for i, value in enumerate(vals):
        x = 12 + i * (width - 24) / max(1, len(vals) - 1)
        y = 12 + (hi - value) * (height - 24) / span
        points.append(f'{x:.1f},{y:.1f}')
    return f"<svg viewBox='0 0 {width} {height}' class='chart'><polyline points='{' '.join(points)}' fill='none' stroke='currentColor' stroke-width='3'/><text x='12' y='20'>{money(hi)}</text><text x='12' y='{height-8}'>{money(lo)}</text></svg>"


def page(title, body, refresh=False):
    refresh_tag = f"<meta http-equiv='refresh' content='{settings.dashboard_refresh_seconds}'>" if refresh else ''
    return f"""<!doctype html><html><head><meta charset='utf-8'>{refresh_tag}<meta name='viewport' content='width=device-width,initial-scale=1'><title>{escape(title)}</title>
<style>:root{{color-scheme:dark}}body{{font-family:Inter,Arial,sans-serif;background:#0b1020;color:#e8ecf3;margin:0}}main{{max-width:1600px;margin:auto;padding:28px}}a{{color:#7fb3ff;text-decoration:none}}h1{{margin:0 0 6px}}h2{{margin-top:30px}}.topbar{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}}.muted{{color:#8792a8;font-size:12px;line-height:1.45;margin-top:4px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:14px;margin:22px 0}}.card,.panel,.status{{background:#141b2d;border:1px solid #26314d;border-radius:12px;padding:17px}}.label{{color:#9aa5ba;font-size:12px;text-transform:uppercase;letter-spacing:.08em}}.value{{font-size:24px;font-weight:700;margin-top:7px}}.table-wrap{{overflow-x:auto;border:1px solid #26314d;border-radius:12px}}table{{border-collapse:collapse;width:100%;min-width:1000px;background:#11182a}}th,td{{padding:12px;border-bottom:1px solid #222d47;text-align:left;vertical-align:top}}th{{color:#9aa5ba;font-size:12px;text-transform:uppercase;background:#151d31}}.badge{{padding:4px 8px;border-radius:999px;background:#27385d;font-weight:700;font-size:12px}}.positive{{color:#54d69b}}.negative{{color:#ff7b8b}}.warning{{color:#f4c96b}}.neutral{{color:#c8d0df}}.empty{{padding:25px;color:#8792a8;background:#11182a;border:1px solid #26314d;border-radius:12px}}.chart{{width:100%;height:220px;color:#54d69b;background:#11182a;border-radius:12px}}.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}ul{{line-height:1.6}}</style></head><body><main>{body}</main></body></html>"""


@app.get('/health', dependencies=[Depends(require_auth)])
def health():
    latest = db.latest_cycle()
    return {'status': engine_status(latest)[0], 'latest_cycle': latest}

@app.get('/api/status', dependencies=[Depends(require_auth)])
def status(): return analytics.advanced_metrics()

@app.get('/api/positions', dependencies=[Depends(require_auth)])
def positions(): return db.list_positions()

@app.get('/api/analyses', dependencies=[Depends(require_auth)])
def analyses(): return db.recent_analyses()

@app.get('/api/cycles', dependencies=[Depends(require_auth)])
def cycles(): return db.recent_cycles()

@app.get('/api/equity', dependencies=[Depends(require_auth)])
def equity(): return analytics.equity_history()

@app.get('/api/category-exposure', dependencies=[Depends(require_auth)])
def category_exposure(): return db.category_exposure()

@app.get('/api/positions/{position_id}', dependencies=[Depends(require_auth)])
def position_api(position_id: int):
    item = analytics.position_detail(position_id)
    if not item: raise HTTPException(status_code=404, detail='Position not found')
    return item


@app.get('/positions/{position_id}', response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def position_page(position_id: int):
    item = analytics.position_detail(position_id)
    if not item: raise HTTPException(status_code=404, detail='Position not found')
    p = item['position']; analyses = item['analyses']; prices = item['prices']
    latest = analyses[0] if analyses else {}; data = payload(latest)
    prob = data.get('probability_report', {}); critic = data.get('critic_report', {})
    side_prices = [x['yes_price'] if p['side'] == 'YES' else x['no_price'] for x in prices]
    evidence = ''.join(f'<li>{escape(str(x))}</li>' for x in prob.get('evidence', [])) or '<li>No evidence stored</li>'
    objections = ''.join(f'<li>{escape(str(x))}</li>' for x in prob.get('counterarguments', [])) or '<li>No counterarguments stored</li>'
    rows = ''.join(f"<tr><td>{dt(a['created_at'])}</td><td>{escape(a['side'])}</td><td>{pct(a['net_edge'])}</td><td>{pct(a['confidence'])}</td><td>{pct(a['critic_risk'])}</td><td>{escape(a['decision'])}</td></tr>" for a in analyses)
    body = f"""<a href='/'>← Dashboard</a><h1>{escape(p['question'])}</h1><div class='muted'>Position #{p['id']} · {escape(p['status'])} · {escape(p['category'] or 'other')}</div>
<section class='cards'><div class='card'><div class='label'>Side</div><div class='value'>{escape(p['side'])}</div></div><div class='card'><div class='label'>Entry</div><div class='value'>{p['entry_price']:.4f}</div></div><div class='card'><div class='label'>Mark</div><div class='value'>{float(p['last_price'] or p['entry_price']):.4f}</div></div><div class='card'><div class='label'>Stake</div><div class='value'>{money(p['stake_usdc'])}</div></div><div class='card'><div class='label'>PnL</div><div class='value'>{money(p['pnl_usdc'] if p['status']=='CLOSED' else p['unrealized_pnl'])}</div></div><div class='card'><div class='label'>Exit confirm</div><div class='value'>{p.get('edge_gone_count') or 0}/{settings.exit_confirmation_cycles}</div></div></section>
<h2>Price history</h2>{svg_line(side_prices)}<div class='grid2'><div class='panel'><h2>Current thesis</h2><p>{escape(prob.get('thesis') or 'No thesis stored')}</p><h3>Evidence</h3><ul>{evidence}</ul></div><div class='panel'><h2>Risk review</h2><p>{escape(critic.get('strongest_objection') or 'No critic review stored')}</p><h3>Counterarguments</h3><ul>{objections}</ul></div></div>
<h2>Analysis history</h2><div class='table-wrap'><table><tr><th>Time</th><th>Side</th><th>Edge</th><th>Confidence</th><th>Risk</th><th>Decision</th></tr>{rows}</table></div>"""
    return page(f"EL ROJILLA BOT · Position {position_id}", body)


@app.get('/', response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def home():
    metrics = analytics.advanced_metrics(); positions = db.list_positions(); history = analytics.equity_history(150)
    open_positions = [p for p in positions if p['status']=='OPEN']; closed_positions = [p for p in positions if p['status']=='CLOSED'][:20]
    cycles = db.recent_cycles(10); latest_cycle = cycles[0] if cycles else None
    state, detail = engine_status(latest_cycle); state_class = 'positive' if state=='HEALTHY' else 'negative' if state=='ERROR' else 'warning'
    latest_analysis = {}
    for a in db.recent_analyses(200): latest_analysis.setdefault(a['market_id'], a)
    open_rows = []
    for p in open_positions:
        a = latest_analysis.get(p['market_id'], {}); thesis = payload(a).get('probability_report', {}).get('thesis', 'No thesis stored')
        mark=float(p['last_price'] or p['entry_price']); pnl=float(p['unrealized_pnl']); cls='positive' if pnl>0 else 'negative' if pnl<0 else 'neutral'
        open_rows.append(f"<tr><td><a href='/positions/{p['id']}'><strong>{escape(p['question'])}</strong></a><div class='muted'>{escape(thesis[:180])}</div><div class='muted'>{escape(p.get('category') or 'other')} · Opened {dt(p['opened_at'])}</div></td><td><span class='badge'>{escape(p['side'])}</span></td><td>{p['entry_price']:.4f}</td><td>{mark:.4f}</td><td>{money(p['stake_usdc'])}</td><td class='{cls}'>{money(pnl)}</td><td>{pct(a.get('net_edge',0))}</td><td>{pct(a.get('confidence',0))}</td><td>{pct(a.get('critic_risk',0))}</td><td>{p.get('edge_gone_count') or 0}/{settings.exit_confirmation_cycles}</td></tr>")
    closed_rows = ''.join(f"<tr><td><a href='/positions/{p['id']}'>{escape(p['question'])}</a></td><td>{escape(p['side'])}</td><td>{p['entry_price']:.4f}</td><td>{float(p['exit_price'] or 0):.4f}</td><td>{money(p['pnl_usdc'])}</td><td>{escape(p.get('resolution') or '-')}</td><td>{dt(p.get('closed_at'))}</td></tr>" for p in closed_positions)
    cycle_rows = ''.join(f"<tr><td>{c['id']}</td><td>{dt(c.get('started_at'))}</td><td>{c.get('markets_seen') or 0}</td><td>{c.get('eligible') or 0}</td><td>{c.get('analysed') or 0}</td><td>{c.get('opened') or 0}</td><td class='{'negative' if c.get('error') else 'positive'}'>{'ERROR' if c.get('error') else 'OK'}</td></tr>" for c in cycles)
    exposure = ''.join(f"<tr><td>{escape(x['category'])}</td><td>{x['positions']}</td><td>{money(x['stake'])}</td><td>{pct(float(x['stake'])/settings.bankroll_usdc if settings.bankroll_usdc else 0)}</td></tr>" for x in db.category_exposure())
    body=f"""<div class='topbar'><div><h1>EL ROJILLA BOT</h1><div class='muted'>Paper trading · Gemini · Realistic slippage/fees · Refresh every {settings.dashboard_refresh_seconds}s</div></div><div class='status'><strong class='{state_class}'>{state}</strong><div class='muted'>{escape(detail)}</div></div></div>
<section class='cards'><div class='card'><div class='label'>Equity</div><div class='value'>{money(metrics['equity'])}</div></div><div class='card'><div class='label'>Return</div><div class='value'>{pct(metrics['return_pct'])}</div></div><div class='card'><div class='label'>Max drawdown</div><div class='value'>{pct(metrics['max_drawdown_pct'])}</div></div><div class='card'><div class='label'>Exposure</div><div class='value'>{money(metrics['open_stake'])}</div><div class='muted'>{pct(metrics['exposure_pct'])}</div></div><div class='card'><div class='label'>Win rate</div><div class='value'>{pct(metrics['win_rate'])}</div></div><div class='card'><div class='label'>Profit factor</div><div class='value'>{metrics['profit_factor']:.2f}</div></div><div class='card'><div class='label'>Expectancy</div><div class='value'>{money(metrics['expectancy_usdc'])}</div></div><div class='card'><div class='label'>Open positions</div><div class='value'>{metrics['open_positions']}</div></div></section>
<h2>Equity curve</h2>{svg_line([x['equity'] for x in history])}<div class='grid2'><div><h2>Category exposure</h2>{"<div class='table-wrap'><table><tr><th>Category</th><th>Positions</th><th>Stake</th><th>Bankroll</th></tr>"+exposure+"</table></div>" if exposure else "<div class='empty'>No exposure.</div>"}</div><div class='panel'><h2>Risk controls</h2><div class='muted'>TP {pct(settings.take_profit_pct)} · SL {pct(settings.stop_loss_pct)} · Trailing {pct(settings.trailing_stop_pct)} after {pct(settings.trailing_activation_pct)} · Event max {pct(settings.max_event_exposure_pct)} · Category max {pct(settings.max_category_exposure_pct)}</div></div></div>
<h2>Open positions</h2>{"<div class='table-wrap'><table><tr><th>Market & thesis</th><th>Side</th><th>Entry</th><th>Mark</th><th>Stake</th><th>uPnL</th><th>Edge</th><th>Confidence</th><th>Risk</th><th>Exit confirm</th></tr>"+''.join(open_rows)+"</table></div>" if open_rows else "<div class='empty'>No open positions.</div>"}
<h2>Recently closed</h2>{"<div class='table-wrap'><table><tr><th>Market</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th><th>Closed</th></tr>"+closed_rows+"</table></div>" if closed_rows else "<div class='empty'>No closed positions yet.</div>"}
<h2>Recent cycles</h2><div class='table-wrap'><table><tr><th>ID</th><th>Started</th><th>Seen</th><th>Eligible</th><th>Analysed</th><th>Opened</th><th>Result</th></tr>{cycle_rows}</table></div>"""
    return page('EL ROJILLA BOT', body, refresh=True)
