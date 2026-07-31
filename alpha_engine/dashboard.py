from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from . import db
app=FastAPI(title='Polymarket Alpha Engine')
@app.get('/api/status')
def status(): return db.summary()
@app.get('/api/positions')
def positions(): return db.list_positions()
@app.get('/api/analyses')
def analyses(): return db.recent_analyses()
@app.get('/',response_class=HTMLResponse)
def home():
 s=db.summary(); rows=''.join(f"<tr><td>{p['question']}</td><td>{p['side']}</td><td>{p['entry_price']:.3f}</td><td>{(p['last_price'] or p['entry_price']):.3f}</td><td>{p['unrealized_pnl']:.2f}</td></tr>" for p in db.list_positions(True))
 return f"""<html><head><meta http-equiv="refresh" content="30"><style>body{{font-family:Arial;max-width:1200px;margin:30px auto}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ddd;padding:8px}}</style></head><body><h1>Polymarket Alpha Engine</h1><p>Open: {s['open_positions']} | Exposure: ${s['open_stake']:.2f} | Unrealized PnL: ${s['unrealized_pnl']:.2f} | Realized PnL: ${s['realized_pnl']:.2f}</p><table><tr><th>Market</th><th>Side</th><th>Entry</th><th>Mark</th><th>uPnL</th></tr>{rows}</table></body></html>"""
