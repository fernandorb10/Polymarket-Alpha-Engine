import math
from datetime import UTC, datetime

from .config import settings
from .db import executable_entry_price
from .models import CriticReport, Market, Opportunity, ProbabilityReport


def hours_left(market: Market) -> float:
    if not market.end_date:
        return math.inf
    end = (
        market.end_date
        if market.end_date.tzinfo
        else market.end_date.replace(tzinfo=UTC)
    )
    return (end - datetime.now(UTC)).total_seconds() / 3600


def eligible(market: Market) -> bool:
    remaining = hours_left(market)
    return (
        market.active
        and not market.closed
        and market.liquidity >= settings.min_liquidity
        and market.volume >= settings.min_volume
        and market.spread <= settings.max_spread
        and settings.min_price <= market.yes_price <= settings.max_price
        and settings.min_hours_to_close <= remaining <= settings.max_hours_to_close
    )


def rank_market(market: Market) -> float:
    liquidity = min(1, math.log10(max(market.liquidity, 1)) / 6)
    volume = min(1, math.log10(max(market.volume, 1)) / 7)
    activity = min(1, math.log10(max(market.volume_24h, 1)) / 5)
    spread = max(0, 1 - market.spread / max(settings.max_spread, 0.001))

    remaining = hours_left(market)
    if math.isinf(remaining):
        horizon = 0.0
    else:
        horizon = max(
            0.0,
            1 - remaining / max(settings.max_hours_to_close, 1.0),
        )

    market.rank_score = 100 * (
        0.30 * liquidity
        + 0.25 * volume
        + 0.20 * activity
        + 0.15 * spread
        + 0.10 * horizon
    )
    return market.rank_score


def kelly_binary(probability: float, price: float) -> float:
    if price <= 0 or price >= 1:
        return 0
    odds = (1 - price) / price
    return max(0, (odds * probability - (1 - probability)) / odds)


def build_opportunity(
    market: Market,
    probability: ProbabilityReport,
    critic: CriticReport,
    current_exposure: float,
) -> Opportunity:
    side = "YES" if probability.probability_yes >= market.yes_price else "NO"
    fair = (
        probability.probability_yes
        if side == "YES"
        else 1 - probability.probability_yes
    )
    executable_price = executable_entry_price(market, side)
    gross_edge = fair - executable_price
    net_edge = gross_edge - settings.slippage_buffer
    kelly = kelly_binary(fair, executable_price) * settings.kelly_fraction
    max_stake = settings.bankroll_usdc * settings.max_position_pct
    exposure_room = max(
        0,
        settings.bankroll_usdc * settings.max_total_exposure_pct
        - current_exposure,
    )
    stake = min(settings.bankroll_usdc * kelly, max_stake, exposure_room)
    expected_value = (
        (
            fair * (1 - executable_price)
            - (1 - fair) * executable_price
        )
        / executable_price
        if executable_price > 0
        else -1
    )

    decision = "OPEN"
    reason = "edge and risk thresholds passed"
    if (
        net_edge < settings.min_net_edge
        or probability.confidence < settings.min_confidence
        or critic.risk_score > settings.max_critic_risk
        or critic.recommendation == "REJECT"
        or stake < 1
    ):
        decision = "REJECT"
        reason = "threshold or portfolio constraint failed"
    elif critic.recommendation == "REDUCE":
        stake *= 0.5
        decision = "WATCH"
        reason = "critic requested reduced conviction"

    score = (
        100
        * max(0, net_edge)
        * probability.confidence
        * (1 - critic.risk_score)
    )
    return Opportunity(
        market=market,
        side=side,
        fair_probability=fair,
        market_probability=executable_price,
        gross_edge=gross_edge,
        net_edge=net_edge,
        expected_value_per_dollar=expected_value,
        confidence=probability.confidence,
        critic_risk=critic.risk_score,
        kelly_fraction=kelly,
        stake_usdc=round(stake, 2),
        score=score,
        decision=decision,
        reason=reason,
        probability_report=probability,
        critic_report=critic,
    )
