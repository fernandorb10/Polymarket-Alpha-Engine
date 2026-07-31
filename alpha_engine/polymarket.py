import json
import logging
from datetime import datetime

import httpx

from .config import settings
from .models import Market

log = logging.getLogger(__name__)


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _arr(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return []
    return []


def _dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None


class PolymarketClient:
    def __init__(self):
        self.http = httpx.Client(
            timeout=settings.http_timeout,
            headers={'User-Agent': 'polymarket-alpha-engine/1.0'},
        )

    def close(self):
        self.http.close()

    def list_active_markets(self) -> list[Market]:
        """Fetch the active catalogue using Gamma's effective 100-row page size.

        Gamma may return at most 100 rows even when a larger limit is requested.
        Pagination therefore continues until an empty page, the configured scan
        limit, or a page that contributes no new market IDs.
        """
        rows_by_id: dict[str, dict] = {}
        offset = 0
        page_size = min(100, settings.scan_page_size)

        while len(rows_by_id) < settings.scan_limit:
            request_limit = min(page_size, settings.scan_limit - len(rows_by_id))
            response = self.http.get(
                f'{settings.gamma_url}/markets',
                params={
                    'active': 'true',
                    'closed': 'false',
                    'limit': request_limit,
                    'offset': offset,
                },
            )
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break

            before = len(rows_by_id)
            for row in batch:
                market_id = str(row.get('id') or row.get('conditionId') or '')
                if market_id:
                    rows_by_id.setdefault(market_id, row)

            added = len(rows_by_id) - before
            log.debug(
                'Gamma page offset=%s requested=%s received=%s new=%s total=%s',
                offset,
                request_limit,
                len(batch),
                added,
                len(rows_by_id),
            )
            if added == 0:
                log.warning('Gamma pagination stopped because page added no new markets')
                break

            # Advance by the actual response length. This works when Gamma caps
            # the response below the requested limit.
            offset += len(batch)

        markets = [self._parse(row) for row in rows_by_id.values()]
        return [market for market in markets[: settings.scan_limit] if market.yes_token_id]

    def _parse(self, data: dict) -> Market:
        outcomes = [str(outcome).lower() for outcome in _arr(data.get('outcomes'))]
        prices = [_f(price) for price in _arr(data.get('outcomePrices'))]
        tokens = [str(token) for token in _arr(data.get('clobTokenIds'))]
        yes_index = outcomes.index('yes') if 'yes' in outcomes else 0
        no_index = outcomes.index('no') if 'no' in outcomes else 1
        yes_price = prices[yes_index] if yes_index < len(prices) else 0.5
        no_price = prices[no_index] if no_index < len(prices) else 1 - yes_price
        return Market(
            id=str(data.get('id') or data.get('conditionId')),
            condition_id=str(data.get('conditionId') or ''),
            question=data.get('question') or '',
            slug=data.get('slug') or '',
            rules=data.get('description') or '',
            category=data.get('category') or 'unknown',
            end_date=_dt(data.get('endDate')),
            active=bool(data.get('active', True)),
            closed=bool(data.get('closed', False)),
            yes_token_id=tokens[yes_index] if yes_index < len(tokens) else '',
            no_token_id=tokens[no_index] if no_index < len(tokens) else '',
            yes_price=yes_price,
            no_price=no_price,
            spread=_f(data.get('spread')),
            liquidity=_f(data.get('liquidityNum', data.get('liquidity'))),
            volume=_f(data.get('volumeNum', data.get('volume'))),
            volume_24h=_f(data.get('volume24hr')),
            raw=data,
        )

    def enrich_books(self, markets: list[Market]) -> None:
        token_ids = [market.yes_token_id for market in markets if market.yes_token_id]
        for index in range(0, len(token_ids), 500):
            response = self.http.post(
                f'{settings.clob_url}/books',
                json=[{'token_id': token_id} for token_id in token_ids[index : index + 500]],
            )
            if response.status_code >= 400:
                log.warning('books request failed: %s', response.text[:200])
                continue
            by_id = {str(book.get('asset_id')): book for book in response.json()}
            for market in markets:
                book = by_id.get(market.yes_token_id)
                if not book:
                    continue
                bids = sorted(
                    (_f(item.get('price')) for item in book.get('bids', [])),
                    reverse=True,
                )
                asks = sorted(_f(item.get('price')) for item in book.get('asks', []))
                market.best_bid_yes = bids[0] if bids else None
                market.best_ask_yes = asks[0] if asks else None
                if market.best_bid_yes is not None and market.best_ask_yes is not None:
                    market.spread = max(0, market.best_ask_yes - market.best_bid_yes)
                    market.yes_price = (market.best_bid_yes + market.best_ask_yes) / 2
                    market.no_price = 1 - market.yes_price
