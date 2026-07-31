from html import escape
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from . import db

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


def money(value):
    return f"${value:,.2f}"


def pct(value):
    return f"{value * 100:.1f}%"


@app.get('/', response_class=HTMLResponse)
def home():
    summary = db.summary()
    positions = db.list_positions()
    open_positions = [p for p in positions if p['status'] == 'OPEN']
    closed_positions = [p for p in positions if p['status'] == 'CLOSED'][:20]

    latest_analysis = {}
    for analysis in db.recent_analyses(100):
        latest_analysis.setdefault(analysis['market_id'], analysis)

    open_rows = []
    for position in open_positions:
        analysis = latest_analysis.get(position['market_id'], {})
        mark = position['last_price'] or position['entry_price']
        pnl = position['unrealized_pnl']
        pnl_pct = pnl / position['stake_usdc'] if position['stake_usdc'] else 0
        pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else 'neutral'
        open_rows.append(f"""
        <tr>
          <td><strong>{escape(position['question'])}</strong><div class='muted'>Opened {escape(position['opened_at'][:19])} UTC</div></td>
          <td><span class='badge'>{escape(position['side'])}</span></td>
          <td>{position['entry_price']:.3f}</td>
          <td>{mark:.3f}</td>
          <td>{money(position['stake_usdc'])}</td>
          <td class='{pnl_class}'>{money(pnl)}<div class='muted'>{pct(pnl_pct)}</div></td>
          <td>{pct(analysis.get('net_edge', 0))}</td>
          <td>{pct(analysis.get('confidence', 0))}</td>
          <td>{pct(analysis.get('critic_risk', 0))}</td>
          <td>{escape((position.get('last_marked_at') or '-')[:19])}</td>
        </tr>
        """)

    closed_rows = []
    for position in closed_positions:
        pnl = position['pnl_usdc'] or 0
        pnl_class = 'positive' if pnl > 0 else 'negative' if pnl < 0 else 'neutral'
        closed_rows.append(f"""
        <tr>
          <td>{escape(position['question'])}</td>
          <td>{escape(position['side'])}</td>
          <td>{position['entry_price']:.3f}</td>
          <td>{(position['exit_price'] or 0):.3f}</td>
          <td class='{pnl_class}'>{money(pnl)}</td>
          <td>{escape(position.get('resolution') or '-')}</td>
          <td>{escape((position.get('closed_at') or '-')[:19])}</td>
        </tr>
        """)

    return f"""
    <!doctype html>
    <html>
    <head>
      <meta charset='utf-8'>
      <meta http-equiv='refresh' content='30'>
      <meta name='viewport' content='width=device-width, initial-scale=1'>
      <title>Polymarket Alpha Engine</title>
      <style>
        :root {{ color-scheme: dark; }}
        body {{ font-family: Inter, Arial, sans-serif; background:#0b1020; color:#e8ecf3; margin:0; }}
        main {{ max-width:1500px; margin:0 auto; padding:28px; }}
        h1 {{ margin:0 0 6px; font-size:28px; }}
        h2 {{ margin-top:30px; font-size:19px; }}
        .muted {{ color:#8792a8; font-size:12px; margin-top:4px; }}
        .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(190px,1fr)); gap:14px; margin:22px 0; }}
        .card {{ background:#141b2d; border:1px solid #26314d; border-radius:12px; padding:17px; }}
        .label {{ color:#9aa5ba; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
        .value {{ font-size:24px; font-weight:700; margin-top:7px; }}
        .table-wrap {{ overflow-x:auto; border:1px solid #26314d; border-radius:12px; }}
        table {{ border-collapse:collapse; width:100%; min-width:1050px; background:#11182a; }}
        th,td {{ padding:12px; border-bottom:1px solid #222d47; text-align:left; vertical-align:top; }}
        th {{ color:#9aa5ba; font-size:12px; text-transform:uppercase; background:#151d31; position:sticky; top:0; }}
        tr:last-child td {{ border-bottom:0; }}
        .badge {{ padding:4px 8px; border-radius:999px; background:#27385d; font-weight:700; font-size:12px; }}
        .positive {{ color:#54d69b; }} .negative {{ color:#ff7b8b; }} .neutral {{ color:#c8d0df; }}
        .empty {{ padding:25px; color:#8792a8; background:#11182a; border:1px solid #26314d; border-radius:12px; }}
      </style>
    </head>
    <body><main>
      <h1>Polymarket Alpha Engine</h1>
      <div class='muted'>Paper trading · Refresh every 30 seconds</div>
      <section class='cards'>
        <div class='card'><div class='label'>Open positions</div><div class='value'>{summary['open_positions']}</div></div>
        <div class='card'><div class='label'>Exposure</div><div class='value'>{money(summary['open_stake'])}</div></div>
        <div class='card'><div class='label'>Unrealized PnL</div><div class='value'>{money(summary['unrealized_pnl'])}</div></div>
        <div class='card'><div class='label'>Realized PnL</div><div class='value'>{money(summary['realized_pnl'])}</div></div>
      </section>

      <h2>Open positions</h2>
      {"<div class='table-wrap'><table><thead><tr><th>Market</th><th>Side</th><th>Entry</th><th>Mark</th><th>Stake</th><th>uPnL</th><th>Edge</th><th>Confidence</th><th>Critic risk</th><th>Last mark</th></tr></thead><tbody>" + ''.join(open_rows) + "</tbody></table></div>" if open_rows else "<div class='empty'>No open positions.</div>"}

      <h2>Recently closed</h2>
      {"<div class='table-wrap'><table><thead><tr><th>Market</th><th>Side</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Reason</th><th>Closed</th></tr></thead><tbody>" + ''.join(closed_rows) + "</tbody></table></div>" if closed_rows else "<div class='empty'>No closed positions yet.</div>"}
    </main></body></html>
    """
