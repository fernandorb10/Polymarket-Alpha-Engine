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
    """Classify from semantics first; use Gamma's broad category only as fallback."""
    text = f"{getattr(market, 'question', '')} {getattr(market, 'slug', '')}".lower()

    if any(word in text for word in (
        'nba', 'nfl', 'nhl', 'mlb', 'uefa', 'champions league', 'world cup',
        'premier league', 'la liga', 'serie a', 'bundesliga', 'tennis', 'ufc',
        'formula 1', 'f1 ', 'super bowl', 'playoffs', 'match', 'ballon d',
        'football', 'soccer', 'basketball', 'baseball', 'hockey', 'grand slam',
    )):
        return 'sports'
    if any(word in text for word in (
        'bitcoin', ' btc', 'btc ', 'ethereum', ' eth', 'eth ', 'solana',
        'cryptocurrency', 'crypto ', 'dogecoin', 'xrp', 'blockchain', 'stablecoin',
    )):
        return 'crypto'
    if any(word in text for word in (
        'fed ', 'federal reserve', 'interest rate', 'inflation', 'gdp', 'recession',
        'unemployment', 'cpi', 'stock market', 's&p', 'nasdaq', 'dow jones',
        'market cap', 'largest company', 'treasury yield',
    )):
        return 'economy'
    if any(word in text for word in (
        'election', 'president', 'prime minister', 'senate', 'congress',
        'nomination', 'governor', 'parliament', 'mayor', 'regime', 'invade',
    )):
        return 'politics'
    if any(word in text for word in (
        'ai ', 'artificial intelligence', 'openai', 'apple', 'google', 'alphabet',
        'microsoft', 'tesla', 'spacex', 'launch', 'iphone', 'android', 'ipo',
    )):
        return 'technology'
    if any(word in text for word in (
        'oscar', 'grammy', 'emmy', 'movie', 'film', 'album', 'box office',
        'celebrity', 'tv show', 'streaming', 'top grossing',
    )):
        return 'entertainment'

    raw = str(getattr(market, 'category', '') or '').strip().lower()
    if raw in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[raw]

    fallback, _ = db.classify_question(getattr(market, 'question', ''))
    return fallback if fallback != 'other' else 'other'


def category_counts(markets) -> dict[str, int]:
    return dict(sorted(Counter(market_category(market) for market in markets).items()))


def select_balanced(
    ranked,
    limit: int,
    open_ids: set[str],
    recent_ids: set[str],
    diversity_recent_ids: set[str] | None = None,
    pending_confirmation_ids: set[str] | None = None,
):
    """Select open positions, pending confirmations, category coverage, then global rank."""
    selected = []
    selected_ids: set[str] = set()
    selected_category_counts: Counter[str] = Counter()
    diversity_recent_ids = diversity_recent_ids or set()
    pending_confirmation_ids = pending_confirmation_ids or set()

    def add(market) -> bool:
        market_id = str(market.id)
        if market_id in selected_ids:
            return False
        selected.append(market)
        selected_ids.add(market_id)
        selected_category_counts[market_category(market)] += 1
        return True

    # Open positions must always be re-evaluated for exit management.
    for market in ranked:
        if str(market.id) in open_ids:
            add(market)
            if len(selected) >= limit:
                return selected

    # A 2-cycle confirmation is only useful if pending candidates are revisited promptly.
    # Pending confirmations bypass ordinary analysis cooldown, but remain limited by the
    # overall per-cycle AI budget and current eligibility/ranking.
    for market in ranked:
        if str(market.id) in pending_confirmation_ids:
            add(market)
            if len(selected) >= limit:
                return selected

    globally_available = [
        market for market in ranked
        if str(market.id) not in selected_ids and str(market.id) not in recent_ids
    ]
    diversity_available = [
        market for market in ranked
        if str(market.id) not in selected_ids and str(market.id) not in diversity_recent_ids
    ]

    if settings.diversify_analysis:
        buckets = defaultdict(list)
        for market in diversity_available:
            buckets[market_category(market)].append(market)

        for category in settings.analysis_category_list:
            if len(selected) >= limit:
                break
            if selected_category_counts[category] >= settings.max_analysis_per_category:
                continue
            for market in buckets.get(category, []):
                if add(market):
                    break

    for market in globally_available:
        if len(selected) >= limit:
            break
        category = market_category(market)
        if settings.diversify_analysis and selected_category_counts[category] >= settings.max_analysis_per_category:
            continue
        add(market)

    for market in globally_available:
        if len(selected) >= limit:
            break
        add(market)

    return selected
