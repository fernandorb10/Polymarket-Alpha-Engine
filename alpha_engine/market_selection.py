from collections import Counter, defaultdict

from .config import settings
from .taxonomy import classify_market


def market_category(market) -> str:
    return classify_market(getattr(market, 'question', ''), getattr(market, 'category', ''))


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
    """Reserve capacity for discovery even when many positions are already open."""
    selected = []
    selected_ids: set[str] = set()
    counts: Counter[str] = Counter()
    diversity_recent_ids = diversity_recent_ids or set()
    pending_confirmation_ids = pending_confirmation_ids or set()

    def add(market):
        market_id = str(market.id)
        if market_id in selected_ids:
            return False
        selected.append(market)
        selected_ids.add(market_id)
        counts[market_category(market)] += 1
        return True

    discovery_slots = max(1, round(limit * settings.discovery_budget_fraction))
    management_slots = max(0, limit - discovery_slots)

    for market in ranked:
        if len(selected) >= management_slots:
            break
        if str(market.id) in open_ids:
            add(market)

    for market in ranked:
        if len(selected) >= management_slots:
            break
        if str(market.id) in pending_confirmation_ids:
            add(market)

    globally_available = [m for m in ranked if str(m.id) not in selected_ids and str(m.id) not in recent_ids]
    diversity_available = [m for m in ranked if str(m.id) not in selected_ids and str(m.id) not in diversity_recent_ids]

    if settings.diversify_analysis:
        buckets = defaultdict(list)
        for market in diversity_available:
            buckets[market_category(market)].append(market)
        for category in settings.analysis_category_list:
            if len(selected) >= limit:
                break
            if counts[category] >= settings.max_analysis_per_category:
                continue
            for market in buckets.get(category, []):
                if add(market):
                    break

    for market in globally_available:
        if len(selected) >= limit:
            break
        category = market_category(market)
        if settings.diversify_analysis and counts[category] >= settings.max_analysis_per_category:
            continue
        add(market)

    for market in globally_available:
        if len(selected) >= limit:
            break
        add(market)
    return selected
