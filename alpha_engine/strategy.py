import math
from .config import settings
from .models import Market, Opportunity, ResearchReport


def evaluate(m: Market, r: ResearchReport) -> Opportunity:
    yes_edge = r.probability_yes - m.yes_price
    no_prob = 1 - r.probability_yes
    no_edge = no_prob - m.no_price
    if yes_edge >= no_edge:
        side, fair, price, gross = "YES", r.probability_yes, m.yes_price, yes_edge
    else:
        side, fair, price, gross = "NO", no_prob, m.no_price, no_edge

    friction = max(m.spread / 2, 0.005) + 0.005  # spread impact + slippage reserve
    net = gross - friction
    liquidity_score = min(1.0, math.log10(max(m.liquidity, 1)) / 6)
    edge_score = min(1.0, max(0.0, net) / 0.20)
    score = 100 * (0.50 * edge_score + 0.30 * r.confidence + 0.20 * liquidity_score)

    # Quarter-Kelly, hard capped by configuration.
    b = (1 / price) - 1 if 0 < price < 1 else 0
    kelly = max(0.0, (b * fair - (1 - fair)) / b) if b > 0 else 0
    fraction = min(settings.max_position_pct, 0.25 * kelly)
    stake = round(settings.bankroll_usdc * fraction, 2)

    valid = (
        m.liquidity >= settings.min_liquidity_usdc
        and m.volume >= settings.min_volume_usdc
        and m.spread <= settings.max_spread
        and net >= settings.min_edge
        and r.confidence >= 0.55
        and stake >= 1
    )
    return Opportunity(
        market=m, report=r, fair_probability=fair, market_probability=price,
        gross_edge=gross, net_edge=net, side=side, score=score,
        stake_usdc=stake if valid else 0.0, decision="PAPER_BUY" if valid else "SKIP"
    )
