from datetime import UTC, datetime, timedelta

from alpha_engine.models import CriticReport, Market, ProbabilityReport
from alpha_engine.strategy import build_opportunity, eligible, kelly_binary


def market(spread: float = 0.02) -> Market:
    return Market(
        id="m1",
        question="Will the event happen this week?",
        yes_price=0.50,
        no_price=0.50,
        best_bid_yes=0.49,
        best_ask_yes=0.51,
        spread=spread,
        liquidity=100000,
        volume=100000,
        volume_24h=10000,
        end_date=datetime.now(UTC) + timedelta(days=5),
    )


def report(probability: float, sources: int = 2) -> ProbabilityReport:
    return ProbabilityReport(
        probability_yes=probability,
        confidence=0.80,
        thesis="test",
        source_urls=[f"https://source-{index}.example" for index in range(sources)],
    )


def critic() -> CriticReport:
    return CriticReport(
        risk_score=0.10,
        resolution_ambiguity=0.10,
        strongest_objection="none",
        recommendation="ACCEPT",
    )


def test_kelly_no_edge():
    assert kelly_binary(0.5, 0.5) == 0


def test_kelly_positive():
    assert kelly_binary(0.7, 0.5) > 0.39


def test_v6_rejects_insufficient_evidence():
    opportunity = build_opportunity(market(), report(0.75, sources=1), critic(), 0)
    assert opportunity.decision == "REJECT"
    assert "evidence" in opportunity.reason


def test_v6_rejects_edge_that_does_not_cover_costs():
    opportunity = build_opportunity(market(spread=0.03), report(0.62), critic(), 0)
    assert opportunity.decision == "REJECT"
    assert "cost-aware" in opportunity.reason


def test_v6_accepts_strong_supported_short_horizon_edge():
    opportunity = build_opportunity(market(spread=0.01), report(0.78), critic(), 0)
    assert opportunity.decision == "OPEN"


def test_v6_rejects_long_horizon_market():
    candidate = market()
    candidate.end_date = datetime.now(UTC) + timedelta(days=30)
    assert not eligible(candidate)
