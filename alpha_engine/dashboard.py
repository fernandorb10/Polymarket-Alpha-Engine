import csv
import io
import json
import secrets
from datetime import datetime, timezone
from html import escape

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import analytics, db, ops
from .config import settings

app = FastAPI(title='EL ROJILLA BOT')
security = HTTPBasic(auto_error=False)


def require_auth(credentials: HTTPBasicCredentials | None = Depends(security)):
    if not settings.dashboard_username or not settings.dashboard_password:
        return True
    valid = credentials is not None
    if valid:
        valid = secrets.compare_digest(credentials.username, settings.dashboard_username) and secrets.compare_digest(
            credentials.password, settings.dashboard_password
        )
    if not valid:
        raise HTTPException(status_code=401, detail='Autenticación requerida', headers={'WWW-Authenticate': 'Basic'})
    return True


def money(value):
    return f"${float(value or 0):,.2f}"


def pct(value):
    return f"{float(value or 0) * 100:.1f}%"


def dt(value):
    if not value:
        return '-'
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')
    except (TypeError, ValueError):
        return str(value)[:19]


def payload(row):
    try:
        return json.loads(row.get('payload_json') or '{}')
    except (TypeError, json.JSONDecodeError):
        return {}


def engine_status(latest):
    if not latest or not latest.get('finished_at'):
        return 'DESCONOCIDO', 'No hay ciclos completados'
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest['finished_at'].replace('Z', '+00:00'))).total_seconds() / 60
    except (TypeError, ValueError):
        return 'DESCONOCIDO', 'Fecha del ciclo no válida'
    if latest.get('error'):
        return 'ERROR', latest['error']
    if age > settings.stale_cycle_minutes:
        return 'ATRASADO', f'Último ciclo hace {age:.0f} minutos'
    return 'SALUDABLE', f'Último ciclo hace {age:.0f} minutos'


def svg_line(values, width=1000, height=220, money_labels=False):
    if not values:
        return "<div class='empty'>Aún no hay histórico suficiente.</div>"
    vals = [float(v) for v in values]
    lo, hi = min(vals), max(vals)
    span = hi - lo or 1
    points = []
    for index, value in enumerate(vals):
        x = 12 + index * (width - 24) / max(1, len(vals) - 1)
        y = 12 + (hi - value) * (height - 24) / span
        points.append(f'{x:.1f},{y:.1f}')
    top = money(hi) if money_labels else f'{hi:.2%}'
    bottom = money(lo) if money_labels else f'{lo:.2%}'
    return f"<svg viewBox='0 0 {width} {height}' class='chart'><polyline points='{' '.join(points)}' fill='none' stroke='currentColor' stroke-width='3'/><text x='12' y='20'>{top}</text><text x='12' y='{height-8}'>{bottom}</text></svg>"


def page(title, body, refresh=False):
    refresh_tag = f"<meta http-equiv='refresh' content='{settings.dashboard_refresh_seconds}'>" if refresh else ''
    return f"""<!doctype html><html lang='es'><head><meta charset='utf-8'>{refresh_tag}<meta name='viewport' content='width=device-width,initial-scale=1'><title>{escape(title)}</title>
<style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{font-family:Inter,Arial,sans-serif;background:#0b1020;color:#e8ecf3;margin:0}}main{{max-width:1700px;margin:auto;padding:28px}}a{{color:#7fb3ff;text-decoration:none}}h1{{margin:0 0 6px}}h2{{margin-top:30px}}h3{{margin-bottom:8px}}.topbar{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;align-items:flex-start}}.muted{{color:#8792a8;font-size:12px;line-height:1.45;margin-top:4px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:22px 0}}.card,.panel,.status{{background:#141b2d;border:1px solid #26314d;border-radius:12px;padding:17px}}.label{{color:#9aa5ba;font-size:12px;text-transform:uppercase;letter-spacing:.08em}}.value{{font-size:24px;font-weight:700;margin-top:7px}}.table-wrap{{overflow-x:auto;border:1px solid #26314d;border-radius:12px}}table{{border-collapse:collapse;width:100%;min-width:1000px;background:#11182a}}th,td{{padding:12px;border-bottom:1px solid #222d47;text-align:left;vertical-align:top}}th{{color:#9aa5ba;font-size:12px;text-transform:uppercase;background:#151d31;position:sticky;top:0}}.badge{{padding:4px 8px;border-radius:999px;background:#27385d;font-weight:700;font-size:12px}}.positive{{color:#54d69b}}.negative{{color:#ff7b8b}}.warning{{color:#f4c96b}}.neutral{{color:#c8d0df}}.empty{{padding:25px;color:#8792a8;background:#11182a;border:1px solid #26314d;border-radius:12px}}.chart{{width:100%;height:220px;color:#54d69b;background:#11182a;border-radius:12px}}.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}}.button{{display:inline-block;background:#27385d;color:#e8ecf3;padding:9px 13px;border-radius:8px}}.nowrap{{white-space:nowrap}}ul{{line-height:1.6}}@media(max-width:720px){{main{{padding:16px}}.value{{font-size:20px}}table{{min-width:850px}}}}
</style></head><body><main>{body}</main></body></html>"""


def _csv_response(table):
    allowed = {'positions', 'analyses', 'cycles', 'equity_history', 'decision_ledger'}
    if table not in allowed:
        raise HTTPException(status_code=404, detail='Exportación no válida')
    with ops.connect() as conn:
        rows = conn.execute(f'SELECT * FROM {table}').fetchall()
    output = io.StringIO()
    writer = csv.writer(output)
    if rows:
        writer.writerow(rows[0].keys())
        writer.writerows([tuple(row) for row in rows])
    return StreamingResponse(iter([output.getvalue()]), media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={table}.csv'})


@app.get('/health', dependencies=[Depends(require_auth)])
def health():
    latest = db.latest_cycle()
    return {'status': engine_status(latest)[0], 'latest_cycle': latest, 'doctor': ops.doctor(check_external=False)}


@app.get('/api/status', dependencies=[Depends(require_auth)])
def status():
    return analytics.advanced_metrics()


@app.get('/api/positions', dependencies=[Depends(require_auth)])
def positions():
    return db.list_positions()


@app.get('/api/analyses', dependencies=[Depends(require_auth)])
def analyses():
    return db.recent_analyses()


@app.get('/api/cycles', dependencies=[Depends(require_auth)])
def cycles():
    return db.recent_cycles()


@app.get('/api/equity', dependencies=[Depends(require_auth)])
def equity():
    return analytics.equity_history()


@app.get('/api/ledger', dependencies=[Depends(require_auth)])
def ledger_api(limit: int = 100):
    ops.prepare()
    with ops.connect() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM decision_ledger ORDER BY id DESC LIMIT ?', (min(limit, 500),))]


@app.get('/api/rejections', dependencies=[Depends(require_auth)])
def rejections_api(limit: int = 100):
    ops.prepare()
    with ops.connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM decision_ledger WHERE action='REJECT' ORDER BY id DESC LIMIT ?", (min(limit, 500),))]


@app.get('/api/positions/{position_id}', dependencies=[Depends(require_auth)])
def position_api(position_id: int):
    item = analytics.position_detail(position_id)
    if not item:
        raise HTTPException(status_code=404, detail='Posición no encontrada')
    return item


@app.get('/export/{table}.csv', dependencies=[Depends(require_auth)])
def export_table(table: str):
    return _csv_response(table)


@app.get('/positions/{position_id}', response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def position_page(position_id: int):
    ops.prepare()
    item = analytics.position_detail(position_id)
    if not item:
        raise HTTPException(status_code=404, detail='Posición no encontrada')
    position = item['position']
    analyses_rows = item['analyses']
    prices = item['prices']
    ledger_rows = item.get('ledger', [])
    latest = analyses_rows[0] if analyses_rows else {}
    data = payload(latest)
    probability = data.get('probability_report', {})
    critic = data.get('critic_report', {})
    side_prices = [row['yes_price'] if position['side'] == 'YES' else row['no_price'] for row in prices]
    evidence = ''.join(f'<li>{escape(str(item))}</li>' for item in probability.get('evidence', [])) or '<li>Sin evidencias guardadas</li>'
    objections = ''.join(f'<li>{escape(str(item))}</li>' for item in probability.get('counterarguments', [])) or '<li>Sin contraargumentos guardados</li>'
    analysis_table = ''.join(
        f"<tr><td>{dt(row['created_at'])}</td><td>{escape(row['side'])}</td><td>{pct(row['net_edge'])}</td><td>{pct(row['confidence'])}</td><td>{pct(row['critic_risk'])}</td><td>{escape(row['decision'])}</td></tr>"
        for row in analyses_rows
    )
    ledger_table = ''.join(
        f"<tr><td>{dt(row['created_at'])}</td><td>{escape(row['action'])}</td><td>{escape(row.get('reason') or '-')}</td><td>{escape(row.get('strategy_version') or '-')}</td></tr>"
        for row in ledger_rows
    )
    pnl = position['pnl_usdc'] if position['status'] == 'CLOSED' else position['unrealized_pnl']
    body = f"""<a href='/'>← Volver al panel</a><h1>{escape(position['question'])}</h1><div class='muted'>Posición #{position['id']} · {escape(position['status'])} · {escape(position.get('category') or 'other')} · {escape(position.get('strategy_version') or 'legacy')}</div>
<section class='cards'><div class='card'><div class='label'>Lado</div><div class='value'>{escape(position['side'])}</div></div><div class='card'><div class='label'>Entrada</div><div class='value'>{position['entry_price']:.4f}</div></div><div class='card'><div class='label'>Marca</div><div class='value'>{float(position['last_price'] or position['entry_price']):.4f}</div></div><div class='card'><div class='label'>Stake</div><div class='value'>{money(position['stake_usdc'])}</div></div><div class='card'><div class='label'>PnL</div><div class='value'>{money(pnl)}</div></div><div class='card'><div class='label'>MFE</div><div class='value'>{pct(position.get('mfe_pct'))}</div></div><div class='card'><div class='label'>MAE</div><div class='value'>{pct(position.get('mae_pct'))}</div></div><div class='card'><div class='label'>Confirmación salida</div><div class='value'>{position.get('edge_gone_count') or 0}/{settings.exit_confirmation_cycles}</div></div></section>
<h2>Histórico de precio</h2>{svg_line(side_prices)}<div class='grid2'><div class='panel'><h2>Tesis actual</h2><p>{escape(probability.get('thesis') or 'Sin tesis guardada')}</p><h3>Evidencias</h3><ul>{evidence}</ul></div><div class='panel'><h2>Revisión de riesgo</h2><p>{escape(critic.get('strongest_objection') or 'Sin revisión crítica guardada')}</p><h3>Contraargumentos</h3><ul>{objections}</ul></div></div>
<h2>Historial de análisis</h2><div class='table-wrap'><table><tr><th>Fecha</th><th>Lado</th><th>Edge</th><th>Confianza</th><th>Riesgo</th><th>Decisión</th></tr>{analysis_table}</table></div>
<h2>Registro de decisiones</h2><div class='table-wrap'><table><tr><th>Fecha</th><th>Acción</th><th>Motivo</th><th>Versión</th></tr>{ledger_table}</table></div>"""
    return page(f"EL ROJILLA BOT · Posición {position_id}", body)


@app.get('/', response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def home():
    ops.prepare()
    metrics = analytics.advanced_metrics()
    all_positions = db.list_positions()
    history = analytics.equity_history(200)
    open_positions = [position for position in all_positions if position['status'] == 'OPEN']
    closed_positions = [position for position in all_positions if position['status'] == 'CLOSED'][:20]
    recent_cycles = db.recent_cycles(10)
    latest_cycle = recent_cycles[0] if recent_cycles else None
    state, detail = engine_status(latest_cycle)
    state_class = 'positive' if state == 'SALUDABLE' else 'negative' if state == 'ERROR' else 'warning'
    latest_analysis = {}
    for analysis in db.recent_analyses(200):
        latest_analysis.setdefault(analysis['market_id'], analysis)
    with ops.connect() as conn:
        rejected = [dict(row) for row in conn.execute("SELECT * FROM decision_ledger WHERE action='REJECT' ORDER BY id DESC LIMIT 15")]
        decisions = [dict(row) for row in conn.execute('SELECT * FROM decision_ledger ORDER BY id DESC LIMIT 15')]
        entry_confirmations = [dict(row) for row in conn.execute('SELECT * FROM entry_confirmations ORDER BY last_seen_at DESC LIMIT 20')]
        health_rows = [dict(row) for row in conn.execute('SELECT * FROM service_health ORDER BY component')]

    open_rows = []
    for position in open_positions:
        analysis = latest_analysis.get(position['market_id'], {})
        thesis = payload(analysis).get('probability_report', {}).get('thesis', 'Sin tesis guardada')
        mark = float(position['last_price'] or position['entry_price'])
        pnl = float(position['unrealized_pnl'])
        pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else 'neutral'
        open_rows.append(
            f"<tr><td><a href='/positions/{position['id']}'><strong>{escape(position['question'])}</strong></a><div class='muted'>{escape(thesis[:180])}</div><div class='muted'>{escape(position.get('category') or 'other')} · {escape(position.get('strategy_version') or 'legacy')} · Abierta {dt(position['opened_at'])}</div></td><td><span class='badge'>{escape(position['side'])}</span></td><td>{position['entry_price']:.4f}</td><td>{mark:.4f}</td><td>{money(position['stake_usdc'])}</td><td class='{pnl_class}'>{money(pnl)}</td><td>{pct(analysis.get('net_edge', 0))}</td><td>{pct(analysis.get('confidence', 0))}</td><td>{pct(position.get('mfe_pct'))}</td><td>{pct(position.get('mae_pct'))}</td><td>{position.get('edge_gone_count') or 0}/{settings.exit_confirmation_cycles}</td></tr>"
        )
    closed_rows = ''.join(
        f"<tr><td><a href='/positions/{position['id']}'>{escape(position['question'])}</a><div class='muted'>{escape(position.get('strategy_version') or 'legacy')}</div></td><td>{escape(position['side'])}</td><td>{position['entry_price']:.4f}</td><td>{float(position['exit_price'] or 0):.4f}</td><td>{money(position['pnl_usdc'])}</td><td>{escape(position.get('resolution') or '-')}</td><td>{pct(position.get('mfe_pct'))}</td><td>{pct(position.get('mae_pct'))}</td><td>{dt(position.get('closed_at'))}</td></tr>"
        for position in closed_positions
    )
    cycle_rows = ''.join(
        f"<tr><td>{cycle['id']}</td><td>{dt(cycle.get('started_at'))}</td><td>{cycle.get('markets_seen') or 0}</td><td>{cycle.get('eligible') or 0}</td><td>{cycle.get('analysed') or 0}</td><td>{cycle.get('opened') or 0}</td><td class='{'negative' if cycle.get('error') else 'positive'}'>{'ERROR' if cycle.get('error') else 'OK'}</td></tr>"
        for cycle in recent_cycles
    )
    exposure_rows = ''.join(
        f"<tr><td>{escape(row['category'])}</td><td>{row['positions']}</td><td>{money(row['stake'])}</td><td>{pct(float(row['stake']) / settings.bankroll_usdc if settings.bankroll_usdc else 0)}</td></tr>"
        for row in db.category_exposure()
    )
    rejected_rows = ''.join(
        f"<tr><td>{dt(row['created_at'])}</td><td>{escape(row.get('market_id') or '-')}</td><td>{escape(row.get('reason') or '-')}</td><td>{escape(row.get('strategy_version') or '-')}</td></tr>"
        for row in rejected
    )
    decision_rows = ''.join(
        f"<tr><td>{dt(row['created_at'])}</td><td>{escape(row['action'])}</td><td>{escape(row.get('reason') or '-')}</td><td>{escape(row.get('market_id') or '-')}</td></tr>"
        for row in decisions
    )
    confirmation_rows = ''.join(
        f"<tr><td>{escape(row['market_id'])}</td><td>{escape(row['side'])}</td><td>{row['confirmations']}/{settings.entry_confirmation_cycles}</td><td>{pct(row.get('last_edge'))}</td><td>{pct(row.get('last_confidence'))}</td><td>{dt(row['last_seen_at'])}</td></tr>"
        for row in entry_confirmations
    )
    health_table = ''.join(
        f"<tr><td>{escape(row['component'])}</td><td>{row['consecutive_failures']}</td><td>{dt(row.get('last_success_at'))}</td><td>{escape(row.get('last_error') or '-')}</td><td>{dt(row.get('paused_until'))}</td></tr>"
        for row in health_rows
    )
    drawdowns = []
    peak = None
    for row in history:
        value = float(row['equity'])
        peak = value if peak is None else max(peak, value)
        drawdowns.append((peak - value) / peak if peak else 0)

    body = f"""<div class='topbar'><div><h1>EL ROJILLA BOT</h1><div class='muted'>Paper trading · Gemini · Estrategia {escape(settings.strategy_version)} · Campaña {escape(settings.campaign_id)} · Refresco cada {settings.dashboard_refresh_seconds}s</div></div><div class='status'><strong class='{state_class}'>{state}</strong><div class='muted'>{escape(detail)}</div><div class='muted'>Próximo ciclo estimado en <span id='countdown'>15:00</span></div></div></div>
<div class='toolbar'><a class='button' href='/export/positions.csv'>Exportar posiciones</a><a class='button' href='/export/analyses.csv'>Exportar análisis</a><a class='button' href='/export/equity_history.csv'>Exportar equity</a><a class='button' href='/export/decision_ledger.csv'>Exportar decisiones</a></div>
<section class='cards'><div class='card'><div class='label'>Equity</div><div class='value'>{money(metrics['equity'])}</div></div><div class='card'><div class='label'>Rentabilidad</div><div class='value'>{pct(metrics['return_pct'])}</div></div><div class='card'><div class='label'>Drawdown actual</div><div class='value'>{pct(metrics['current_drawdown_pct'])}</div></div><div class='card'><div class='label'>Drawdown máximo</div><div class='value'>{pct(metrics['max_drawdown_pct'])}</div></div><div class='card'><div class='label'>Exposición</div><div class='value'>{money(metrics['open_stake'])}</div><div class='muted'>{pct(metrics['exposure_pct'])}</div></div><div class='card'><div class='label'>Win rate</div><div class='value'>{pct(metrics['win_rate'])}</div></div><div class='card'><div class='label'>Profit factor</div><div class='value'>{metrics['profit_factor']:.2f}</div></div><div class='card'><div class='label'>Expectancy</div><div class='value'>{money(metrics['expectancy_usdc'])}</div></div><div class='card'><div class='label'>Sharpe estimado</div><div class='value'>{metrics['sharpe_estimate']:.2f}</div></div><div class='card'><div class='label'>Sortino estimado</div><div class='value'>{metrics['sortino_estimate']:.2f}</div></div><div class='card'><div class='label'>MFE medio</div><div class='value'>{pct(metrics['avg_mfe_pct'])}</div></div><div class='card'><div class='label'>MAE medio</div><div class='value'>{pct(metrics['avg_mae_pct'])}</div></div></section>
<div class='grid2'><div><h2>Curva de equity</h2>{svg_line([row['equity'] for row in history], money_labels=True)}</div><div><h2>Drawdown</h2>{svg_line(drawdowns)}</div></div>
<div class='grid2'><div><h2>Exposición por categoría</h2>{"<div class='table-wrap'><table><tr><th>Categoría</th><th>Posiciones</th><th>Stake</th><th>Bankroll</th></tr>" + exposure_rows + "</table></div>" if exposure_rows else "<div class='empty'>Sin exposición.</div>"}</div><div class='panel'><h2>Controles activos</h2><div class='muted'>Entrada {settings.entry_confirmation_cycles} ciclos · Reentrada {settings.reopen_cooldown_days} días · Máximo diario {settings.max_new_positions_per_day} · Pausa drawdown {pct(settings.pause_drawdown_pct)} · Pérdida diaria {pct(settings.daily_loss_limit_pct)} · TP {pct(settings.take_profit_pct)} · SL {pct(settings.stop_loss_pct)} · Trailing {pct(settings.trailing_stop_pct)} tras {pct(settings.trailing_activation_pct)}</div></div></div>
<h2>Posiciones abiertas</h2>{"<div class='table-wrap'><table><tr><th>Mercado y tesis</th><th>Lado</th><th>Entrada</th><th>Marca</th><th>Stake</th><th>uPnL</th><th>Edge</th><th>Confianza</th><th>MFE</th><th>MAE</th><th>Conf. salida</th></tr>" + ''.join(open_rows) + "</table></div>" if open_rows else "<div class='empty'>No hay posiciones abiertas.</div>"}
<h2>Confirmaciones de entrada pendientes</h2>{"<div class='table-wrap'><table><tr><th>Mercado</th><th>Lado</th><th>Confirmaciones</th><th>Edge</th><th>Confianza</th><th>Última señal</th></tr>" + confirmation_rows + "</table></div>" if confirmation_rows else "<div class='empty'>No hay entradas pendientes.</div>"}
<h2>Cerradas recientemente</h2>{"<div class='table-wrap'><table><tr><th>Mercado</th><th>Lado</th><th>Entrada</th><th>Salida</th><th>PnL</th><th>Motivo</th><th>MFE</th><th>MAE</th><th>Cierre</th></tr>" + closed_rows + "</table></div>" if closed_rows else "<div class='empty'>No hay posiciones cerradas.</div>"}
<div class='grid2'><div><h2>Mercados rechazados</h2>{"<div class='table-wrap'><table><tr><th>Fecha</th><th>Mercado</th><th>Motivo</th><th>Versión</th></tr>" + rejected_rows + "</table></div>" if rejected_rows else "<div class='empty'>No hay rechazos registrados.</div>"}</div><div><h2>Últimas decisiones</h2>{"<div class='table-wrap'><table><tr><th>Fecha</th><th>Acción</th><th>Motivo</th><th>Mercado</th></tr>" + decision_rows + "</table></div>" if decision_rows else "<div class='empty'>No hay decisiones registradas.</div>"}</div></div>
<h2>Salud de componentes</h2>{"<div class='table-wrap'><table><tr><th>Componente</th><th>Fallos consecutivos</th><th>Último éxito</th><th>Último error</th><th>Pausa hasta</th></tr>" + health_table + "</table></div>" if health_table else "<div class='empty'>Sin datos de salud.</div>"}
<h2>Ciclos recientes</h2><div class='table-wrap'><table><tr><th>ID</th><th>Inicio</th><th>Vistos</th><th>Elegibles</th><th>Analizados</th><th>Abiertos</th><th>Resultado</th></tr>{cycle_rows}</table></div>
<script>let seconds=900;setInterval(()=>{{seconds=Math.max(0,seconds-1);const m=String(Math.floor(seconds/60)).padStart(2,'0');const s=String(seconds%60).padStart(2,'0');document.getElementById('countdown').textContent=`${{m}}:${{s}}`;if(seconds===0)seconds=900;}},1000);</script>"""
    return page('EL ROJILLA BOT', body, refresh=True)
