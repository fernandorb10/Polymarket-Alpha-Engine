from collections import Counter, defaultdict

from .config import settings
from .taxonomy import classify_market


def market_category(market) -> str:
    return classify_market(
        getattr(market, "question", ""),
        getattr(market, "category", ""),
    )


def category_counts(markets) -> dict[str, int]:
    counts = Counter(market_category(market) for market in markets)
    return dict(sorted(counts.items()))


def select_balanced(
    ranked,
    limit: int,
    open_ids,
    recent_ids: set[str],
    diversity_recent_ids: set[str] | None = None,
    pending_confirmation_ids: set[str] | None = None,
):
    """Rotate management candidates and reserve capacity for discovery."""
    selected = []
    selected_ids: set[str] = set()
    counts: Counter[str] = Counter()
    diversity_recent_ids = diversity_recent_ids or set()
    pending_confirmation_ids = pending_confirmation_ids or set()

    ranked_by_id = {str(market.id): market for market in ranked}
    ordered_open_ids = [str(market_id) for market_id in open_ids]

    def add(market) -> bool:
        market_id = str(market.id)
        if market_id in selected_ids:
            return False
        selected.append(market)
        selected_ids.add(market_id)
        counts[market_category(market)] += 1
        return True

    discovery_slots = max(1, round(limit * settings.discovery_budget_fraction))
    management_slots = max(0, limit - discovery_slots)

    # open_ids is ordered from least recently analysed to most recently analysed.
    for market_id in ordered_open_ids:
        if len(selected) >= management_slots:
            break
        market = ranked_by_id.get(market_id)
        if market is not None:
            add(market)

    for market in ranked:
        if len(selected) >= management_slots:
            break
        if str(market.id) in pending_confirmation_ids:
            add(market)

    globally_available = [
        market
        for market in ranked
        if str(market.id) not in selected_ids
        and str(market.id) not in recent_ids
    ]
    diversity_available = [
        market
        for market in ranked
        if str(market.id) not in selected_ids
        and str(market.id) not in diversity_recent_ids
    ]

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
        if (
            settings.diversify_analysis
            and counts[category] >= settings.max_analysis_per_category
        ):
            continue
        add(market)

    for market in globally_available:
        if len(selected) >= limit:
            break
        add(market)

    return selected
