import math
from datetime import datetime, timezone

from .config import settings
from .db import executable_entry_price
from .models import CriticReport, Market, Opportunity, ProbabilityReport


def hours_left(m: Market) -> float:
    if not m.end_date:
        return 999999
    end = m.end_date if m.end_date.tzinfo else m.end_date.replace(tzinfo=timezone.utc)
    return (end - datetime.now(timezone.utc)).total_seconds() / 3600


def eligible(m: Market) -> bool:
    return (
        m.active and not m.closed and m.liquidity >= settings.min_liquidity
        and m.volume >= settings.min_volume and m.spread <= settings.max_spread
        and settings.min_price <= m.yes_price <= settings.max_price
        and hours_left(m) >= settings.min_hours_to_close
    )


def rank_market(m: Market) -> float:
    liq = min(1, math.log10(max(m.liquidity, 1)) / 6)
    vol = min(1, math.log10(max(m.volume, 1)) / 7)
    activity = min(1, math.log10(max(m.volume_24h, 1)) / 5)
    spread = max(0, 1 - m.spread / max(settings.max_spread, .001))
    uncertainty = 1 - abs(m.yes_price - .5) * 2
    m.rank_score = 100 * (.25 * liq + .25 * vol + .20 * activity + .20 * spread + .10 * uncertainty)
    return m.rank_score


def kelly_binary(p: float, price: float) -> float:
    if price <= 0 or price >= 1:
        return 0
    b = (1 - price) / price
    return max(0, (b * p - (1 - p)) / b)


def build_opportunity(m: Market, p: ProbabilityReport, c: CriticReport, current_exposure: float) -> Opportunity:
    side = 'YES' if p.probability_yes >= m.yes_price else 'NO'
    fair = p.probability_yes if side == 'YES' else 1 - p.probability_yes
    market = executable_entry_price(m, side)
    gross = fair - market
    # The executable ask already contains the spread. Only explicit slippage/uncertainty buffer remains.
    net = gross - settings.slippage_buffer
    kelly = kelly_binary(fair, market) * settings.kelly_fraction
    max_stake = settings.bankroll_usdc * settings.max_position_pct
    exposure_room = max(0, settings.bankroll_usdc * settings.max_total_exposure_pct - current_exposure)
    stake = min(settings.bankroll_usdc * kelly, max_stake, exposure_room)
    ev = (fair * (1 - market) - (1 - fair) * market) / market if market > 0 else -1

    decision, reason = 'OPEN', 'edge and risk thresholds passed'
    if (
        net < settings.min_net_edge or p.confidence < settings.min_confidence
        or c.risk_score > settings.max_critic_risk or c.recommendation == 'REJECT'
        or stake < 1
    ):
        decision, reason = 'REJECT', 'threshold or portfolio constraint failed'
    elif c.recommendation == 'REDUCE':
        stake *= .5
        decision, reason = 'WATCH', 'critic requested reduced conviction'

    score = 100 * max(0, net) * p.confidence * (1 - c.risk_score)
    return Opportunity(
        market=m, side=side, fair_probability=fair, market_probability=market,
        gross_edge=gross, net_edge=net, expected_value_per_dollar=ev,
        confidence=p.confidence, critic_risk=c.risk_score, kelly_fraction=kelly,
        stake_usdc=round(stake, 2), score=score, decision=decision, reason=reason,
        probability_report=p, critic_report=c,
    )
