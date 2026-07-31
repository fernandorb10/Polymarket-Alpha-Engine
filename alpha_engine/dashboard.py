import json
from datetime import datetime, timezone
from html import escape
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from . import db
from .config import settings

app = FastAPI(title='Polymarket Alpha Engine')


@app.get('/api/status')
def status():
    return db.summary()


@app.get('/api/positions')
def positions():
    return db.list_positions()


@app.get('/api/analyses')
def analyses():
    return db.recent_analyses()


@app.get('/api/cycles')
def cycles():
    return db.recent_cycles()


@app.get('/health')
def health():
    latest = db.latest_cycle()
    return {'status': _engine_status(latest)[0], 'latest_cycle': latest}


def money(value):
    return f"${float(value or 0):,.2f}"


def pct(value):
    return f"{float(value or 0) * 100:.1f}%"


def dt(value):
    if not value:
        return '-'
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.astimezone(timezone.utc).strftime('%d/%m/%Y %H:%M:%S UTC')
    except (TypeError, ValueError):
        return str(value)[:19]


def _engine_status(latest):
    if not latest or not latest.get('finished_at'):
        return 'UNKNOWN', 'No completed cycle'
    try:
        finished = datetime.fromisoformat(latest['finished_at'].replace('Z', '+00:00'))
        age_minutes = (datetime.now(timezone.utc) - finished).total_seconds() / 60
    except (TypeError, ValueError):
        return 'UNKNOWN', 'Invalid cycle timestamp'
    if latest.get('error'):
        return 'ERROR', latest['error']
    if age_minutes > settings.stale_cycle_minutes:
        return 'STALE', f'Last cycle {age_minutes:.0f} minutes ago'
    return 'HEALTHY', f'Last cycle {age_minutes:.0f} minutes ago'


def _analysis_payload(analysis):
    try:
        return json.loads(analysis.get('payload_json') or '{}')
    except (TypeError, json.JSONDecodeError):
        return {}


@app.get('/', response_class=HTMLResponse)
def home():
    summary = db.summary()
    positions = db.list_positions()
    open_positions = [p for p in positions if p['status'] == 'OPEN']
    closed_positions = [p for p in positions if p['status'] == 'CLOSED'][:20]
    recent_cycles = db.recent_cycles(10)
    latest_cycle = recent_cycles[0] if recent_cycles else None
    engine_status, engine_detail = _engine_status(latest_cycle)
    status_class = 'positive' if engine_status == 'HEALTHY' else 'negative' if engine_status == 'ERROR' else 'warning'

    latest_analysis = {}
    for analysis in db.recent_analyses(100):
        latest_analysis.setdefault(analysis['market_id'], analysis)

    open_rows = []
    for position in open_positions:
        analysis = latest_analysis.get(position['market_id'], {})
        payload = _analysis_payload(analysis)
        probability = payload.get('probability_report', {})
        mark = position['last_price'] or position['entry_price']
        pnl = position['unrealized_pnl']
        pnl_pct = pnl / position['stake_usdc'] if position['stake_usdc'] else 0
        pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else 'neutral'
        thesis = probability.get('thesis') or 'No thesis stored'
        open_rows.append(f"""
        <tr>
          <td><strong>{escape(position['question'])}</strong><div class='muted'>{escape(thesis[:180])}</div><div class='muted'>Opened {dt(position['opened_at'])}</div></td>
          <td><span class='badge'>{escape(position['side'])}</span></td>
          <td>{position['entry_price']:.4f}</td>
          <td>{mark:.4f}</td>
          <td>{money(position['stake_usdc'])}</td>
          <td class='{pnl_class}'>{money(pnl)}<div class='muted'>{pct(pnl_pct)}</div></td>
          <td>{pct(analysis.get('net_edge', 0))}</td>
          <td>{pct(analysis.get('confidence', 0))}</td>
          <td>{pct(analysis.get('critic_risk', 0))}</td>
          <td>{dt(position.get('last_marked_at'))}</td>
        </tr>
        """)

    closed_rows = []
    for position in closed_positions:
        pnl = position['pnl_usdc'] or 0
        pnl_pct = pnl / position['stake_usdc'] if position['stake_usdc'] else 0
        pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else 'neutral'
        closed_rows.append(f"""
        <tr>
          <td>{escape(position['question'])}</td>
          <td>{escape(position['side'])}</td>
          <td>{position['entry_price']:.4f}</td>
          <td>{(position['exit_price'] or 0):.4f}</td>
          <td class='{pnl_class}'>{money(pnl)}<div class='muted'>{pct(pnl_pct)}</div></td>
          <td>{escape(position.get('resolution') or '-')}</td>
          <td>{dt(position.get('closed_at'))}</td>
        </tr>
        """)

    cycle_rows = []
    for cycle in recent_cycles:
        duration = '-'
        try:
            start = datetime.fromisoformat(cycle['started_at'].replace('Z', '+00:00'))
            finish = datetime.fromisoformat(cycle['finished_at'].replace('Z', '+00:00')) if cycle.get('finished_at') else None
            if finish:
                duration = f"{(finish - start).total_seconds():.1f}s"
        except (TypeError, ValueError):
            pass
        result = 'ERROR' if cycle.get('error') else 'OK'
        result_class = 'negative' if cycle.get('error') else 'positive'
        cycle_rows.append(f"""
        <tr>
          <td>{cycle['id']}</td><td>{dt(cycle.get('started_at'))}</td><td>{duration}</td>
          <td>{cycle.get('markets_seen') or 0}</td><td>{cycle.get('eligible') or 0}</td>
          <td>{cycle.get('analysed') or 0}</td><td>{cycle.get('opened') or 0}</td>
          <td class='{result_class}'>{result}</td>
        </tr>
        """)

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset='utf-8'>
      <meta http-equiv='refresh' content='{settings.dashboard_refresh_seconds}'>
      <meta name='viewport' content='width=device-width, initial-scale=1'>
      <title>Polymarket Alpha Engine</title>
      <style>
        :root {{ color-scheme: dark; }}
        body {{ font-family: Inter,Arial,sans-serif;background:#0b1020;color:#e8ecf3;margin:0; }}
        main {{ max-width:1600px;margin:0 auto;padding:28px; }}
        h1 {{ margin:0 0 6px;font-size:28px; }} h2 {{ margin-top:30px;font-size:19px; }}
        .topbar {{ display:flex;justify-content:space-between;gap:18px;align-items:flex-start;flex-wrap:wrap; }}
        .muted {{ color:#8792a8;font-size:12px;margin-top:4px;line-height:1.4; }}
        .status {{ background:#141b2d;border:1px solid #26314d;border-radius:10px;padding:10px 14px; }}
        .cards {{ display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:22px 0; }}
        .card {{ background:#141b2d;border:1px solid #26314d;border-radius:12px;padding:17px; }}
        .label {{ color:#9aa5ba;font-size:12px;text-transform:uppercase;letter-spacing:.08em; }}
        .value {{ font-size:24px;font-weight:700;margin-top:7px; }}
        .table-wrap {{ overflow-x:auto;border:1px solid #26314d;border-radius:12px; }}
        table {{ border-collapse:collapse;width:100%;min-width:1000px;background:#11182a; }}
        th,td {{ padding:12px;border-bottom:1px solid #222d47;text-align:left;vertical-align:top; }}
        th {{ color:#9aa5ba;font-size:12px;text-transform:uppercase;background:#151d31;position:sticky;top:0; }}
        tr:last-child td {{ border-bottom:0; }}
        .badge {{ padding:4px 8px;border-radius:999px;background:#27385d;font-weight:700;font-size:12px; }}
        .positive {{ color:#54d69b; }} .negative {{ color:#ff7b8b; }} .warning {{ color:#f4c96b; }} .neutral {{ color:#c8d0df; }}
        .empty {{ padding:25px;color:#8792a8;background:#11182a;border:1px solid #26314d;border-radius:12px; }}
      </style>
    </head>
    <body><main>
      <div class='topbar'><div><h1>Polymarket Alpha Engine</h1><div class='muted'>Paper trading · Gemini · Refresh every {settings.dashboard_refresh_seconds} seconds</div></div>
      <div class='status'><strong class='{status_class}'>{engine_status}</strong><div class='muted'>{escape(engine_detail)}</div></div></div>

      <section class='cards'>
        <div class='card'><div class='label'>Equity</div><div class='value'>{money(summary['equity'])}</div></div>
        <div class='card'><div class='label'>Total return</div><div class='value'>{pct(summary['return_pct'])}</div></div>
        <div class='card'><div class='label'>Open positions</div><div class='value'>{summary['open_positions']}</div></div>
        <div class='card'><div class='label'>Exposure</div><div class='value'>{money(summary['open_stake'])}</div><div class='muted'>{pct(summary['exposure_pct'])} of bankroll</div></div>
        <div class='card'><div class='label'>Unrealized PnL</div><div class='value'>{money(summary['unrealized_pnl'])}</div></div>
        <div class='card'><div class='label'>Realized PnL</div><div class='value'>{money(summary['realized_pnl'])}</div></div>
        <div class='card'><div class='label'>Win rate</div><div class='value'>{pct(summary['win_rate'])}</div><div class='muted'>{summary['wins']}W / {summary['losses']}L</div></div>
      </section>

      <h2>Open positions</h2>
      {"<div class='table-wrap'><table><thead><tr><th>Market & thesis</th><th>Side</th><th>Entry</th><th>Mark</th><th>Stake</th><th>uPnL</th><th>Edge</th><th>Confidence</th><th>Critic risk</th><th>Last mark</th></tr></thead><tbody>" + ''.join(open_rows) + "</tbody></table></div>" if open_rows else "<div class='empty'>No open positions.</div>"}

      <h2>Recently closed</h2>
      {"<div class='table-wrap'><table><thead><tr><th>Market</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th><th>Closed</th></tr></thead><tbody>" + ''.join(closed_rows) + "</tbody></table></div>" if closed_rows else "<div class='empty'>No closed positions yet.</div>"}

      <h2>Recent cycles</h2>
      {"<div class='table-wrap'><table><thead><tr><th>ID</th><th>Started</th><th>Duration</th><th>Seen</th><th>Eligible</th><th>Analysed</th><th>Opened</th><th>Result</th></tr></thead><tbody>" + ''.join(cycle_rows) + "</tbody></table></div>" if cycle_rows else "<div class='empty'>No cycles recorded.</div>"}
    </main></body></html>
    """
