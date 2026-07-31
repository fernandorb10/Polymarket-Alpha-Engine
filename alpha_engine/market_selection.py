from collections import Counter, defaultdict

from . import db
from .config import settings


CATEGORY_ALIASES = {
    'sport': 'sports',
    'sports': 'sports',
    'crypto': 'crypto',
    'cryptocurrency': 'crypto',
    'economics': 'economy',
    'economy': 'economy',
    'finance': 'economy',
    'politics': 'politics',
    'political': 'politics',
    'technology': 'technology',
    'tech': 'technology',
    'entertainment': 'entertainment',
    'culture': 'entertainment',
}


def market_category(market) -> str:
    raw = str(getattr(market, 'category', '') or '').strip().lower()
    if raw in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[raw]

    text = f"{getattr(market, 'question', '')} {getattr(market, 'slug', '')}".lower()
    if any(word in text for word in (
        'nba', 'nfl', 'nhl', 'mlb', 'uefa', 'champions league', 'world cup',
        'premier league', 'la liga', 'serie a', 'bundesliga', 'tennis', 'ufc',
        'formula 1', 'f1 ', 'super bowl', 'playoffs', 'match', 'game ', 'wins the',
    )):
        return 'sports'
    if any(word in text for word in (
        'bitcoin', 'btc', 'ethereum', 'eth ', 'solana', 'crypto', 'token',
        'dogecoin', 'xrp', 'blockchain', 'market cap',
    )):
        return 'crypto'
    if any(word in text for word in (
        'fed ', 'federal reserve', 'interest rate', 'inflation', 'gdp', 'recession',
        'unemployment', 'cpi', 'stock market', 's&p', 'nasdaq', 'dow jones',
    )):
        return 'economy'
    if any(word in text for word in (
        'election', 'president', 'prime minister', 'senate', 'congress',
        'nomination', 'governor', 'parliament', 'mayor',
    )):
        return 'politics'
    if any(word in text for word in (
        'ai ', 'artificial intelligence', 'openai', 'apple', 'google', 'microsoft',
        'tesla', 'spacex', 'launch', 'iphone', 'android',
    )):
        return 'technology'
    if any(word in text for word in (
        'oscar', 'grammy', 'emmy', 'movie', 'film', 'album', 'box office',
        'celebrity', 'tv show', 'streaming',
    )):
        return 'entertainment'

    fallback, _ = db.classify_question(getattr(market, 'question', ''))
    return fallback if fallback != 'other' else 'other'


def category_counts(markets) -> dict[str, int]:
    return dict(sorted(Counter(market_category(market) for market in markets).items()))


def select_balanced(ranked, limit: int, open_ids: set[str], recent_ids: set[str]):
    """Select open positions first, then reserve category diversity, then fill globally."""
    selected = []
    selected_ids: set[str] = set()
    selected_category_counts: Counter[str] = Counter()

    def add(market) -> bool:
        market_id = str(market.id)
        if market_id in selected_ids:
            return False
        selected.append(market)
        selected_ids.add(market_id)
        selected_category_counts[market_category(market)] += 1
        return True

    for market in ranked:
        if str(market.id) in open_ids:
            add(market)
            if len(selected) >= limit:
                return selected

    available = [
        market for market in ranked
        if str(market.id) not in selected_ids and str(market.id) not in recent_ids
    ]

    if settings.diversify_analysis:
        buckets = defaultdict(list)
        for market in available:
            buckets[market_category(market)].append(market)

        for category in settings.analysis_category_list:
            if len(selected) >= limit:
                break
            if selected_category_counts[category] >= settings.max_analysis_per_category:
                continue
            for market in buckets.get(category, []):
                if add(market):
                    break

    for market in available:
        if len(selected) >= limit:
            break
        category = market_category(market)
        if settings.diversify_analysis and selected_category_counts[category] >= settings.max_analysis_per_category:
            continue
        add(market)

    # If strict per-category caps leave capacity unused, fill with the best global markets.
    for market in available:
        if len(selected) >= limit:
            break
        add(market)

    return selected
