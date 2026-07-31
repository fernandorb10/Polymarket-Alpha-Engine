import json, logging
from datetime import datetime
import httpx
from .config import settings
from .models import Market

log = logging.getLogger(__name__)

def _f(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default

def _arr(v):
    if isinstance(v, list): return v
    if isinstance(v, str):
        try: return json.loads(v)
        except json.JSONDecodeError: return []
    return []

def _dt(v):
    if not v: return None
    try: return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError: return None

class PolymarketClient:
    def __init__(self):
        self.http = httpx.Client(timeout=settings.http_timeout, headers={"User-Agent":"polymarket-alpha-engine/1.0"})

    def close(self): self.http.close()

    def list_active_markets(self) -> list[Market]:
        rows=[]; offset=0; page=200
        while len(rows) < settings.scan_limit:
            r=self.http.get(f"{settings.gamma_url}/markets", params={"active":"true","closed":"false","limit":page,"offset":offset})
            r.raise_for_status(); batch=r.json()
            if not batch: break
            rows.extend(batch)
            if len(batch)<page: break
            offset += page
        markets=[self._parse(x) for x in rows[:settings.scan_limit]]
        return [m for m in markets if m.yes_token_id]

    def _parse(self, x: dict) -> Market:
        outcomes=[str(o).lower() for o in _arr(x.get("outcomes"))]
        prices=[_f(p) for p in _arr(x.get("outcomePrices"))]
        tokens=[str(t) for t in _arr(x.get("clobTokenIds"))]
        yi=outcomes.index("yes") if "yes" in outcomes else 0
        ni=outcomes.index("no") if "no" in outcomes else 1
        yp=prices[yi] if yi<len(prices) else .5
        np=prices[ni] if ni<len(prices) else 1-yp
        return Market(id=str(x.get("id") or x.get("conditionId")), condition_id=str(x.get("conditionId") or ""),
          question=x.get("question") or "", slug=x.get("slug") or "", rules=x.get("description") or "",
          category=x.get("category") or "unknown", end_date=_dt(x.get("endDate")), active=bool(x.get("active",True)),
          closed=bool(x.get("closed",False)), yes_token_id=tokens[yi] if yi<len(tokens) else "",
          no_token_id=tokens[ni] if ni<len(tokens) else "", yes_price=yp, no_price=np,
          spread=_f(x.get("spread")), liquidity=_f(x.get("liquidityNum",x.get("liquidity"))),
          volume=_f(x.get("volumeNum",x.get("volume"))), volume_24h=_f(x.get("volume24hr")), raw=x)

    def enrich_books(self, markets: list[Market]) -> None:
        ids=[m.yes_token_id for m in markets if m.yes_token_id]
        for i in range(0,len(ids),500):
            r=self.http.post(f"{settings.clob_url}/books", json=[{"token_id":t} for t in ids[i:i+500]])
            if r.status_code>=400:
                log.warning("books request failed: %s", r.text[:200]); continue
            by_id={str(b.get("asset_id")):b for b in r.json()}
            for m in markets:
                b=by_id.get(m.yes_token_id)
                if not b: continue
                bids=sorted((_f(x.get("price")) for x in b.get("bids",[])), reverse=True)
                asks=sorted(_f(x.get("price")) for x in b.get("asks",[]))
                m.best_bid_yes=bids[0] if bids else None; m.best_ask_yes=asks[0] if asks else None
                if m.best_bid_yes is not None and m.best_ask_yes is not None:
                    m.spread=max(0,m.best_ask_yes-m.best_bid_yes)
                    m.yes_price=(m.best_bid_yes+m.best_ask_yes)/2; m.no_price=1-m.yes_price
