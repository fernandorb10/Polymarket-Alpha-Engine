import json
import httpx
from .config import settings
from .models import Market


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _prices(raw) -> tuple[float, float]:
    values = raw.get("outcomePrices") or raw.get("outcome_prices") or []
    if isinstance(values, str):
        try: values = json.loads(values)
        except json.JSONDecodeError: values = []
    yes = _f(values[0], 0.5) if values else 0.5
    no = _f(values[1], 1 - yes) if len(values) > 1 else 1 - yes
    return yes, no


class PolymarketClient:
    def __init__(self):
        self.client = httpx.Client(timeout=30, headers={"User-Agent": "polymarket-alpha-engine/0.1"})

    def fetch_markets(self, limit: int = 250) -> list[Market]:
        r = self.client.get(f"{settings.gamma_url}/markets", params={
            "active": "true", "closed": "false", "limit": limit,
            "order": "volume24hr", "ascending": "false"
        })
        r.raise_for_status()
        result = []
        for x in r.json():
            yes, no = _prices(x)
            spread = _f(x.get("spread"), abs((yes + no) - 1.0))
            result.append(Market(
                id=str(x.get("id") or x.get("conditionId")),
                condition_id=str(x.get("conditionId") or ""),
                question=x.get("question") or x.get("title") or "",
                slug=x.get("slug") or "",
                end_date=x.get("endDate") or None,
                liquidity=_f(x.get("liquidityNum") or x.get("liquidity")),
                volume=_f(x.get("volumeNum") or x.get("volume")),
                yes_price=yes, no_price=no, spread=spread,
                active=bool(x.get("active", True)), closed=bool(x.get("closed", False)),
                rules=x.get("description") or ""
            ))
        return result
