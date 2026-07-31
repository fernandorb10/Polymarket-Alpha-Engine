from alpha_engine.models import Market, ResearchReport
from alpha_engine.strategy import evaluate


def test_selects_yes_when_yes_has_more_edge():
    m = Market(id="1", question="test", yes_price=.40, no_price=.60, liquidity=100000, volume=100000, spread=.01)
    r = ResearchReport(probability_yes=.60, confidence=.90, thesis="x", counter_thesis="y")
    o = evaluate(m, r)
    assert o.side == "YES"
    assert o.gross_edge > 0


def test_rejects_low_confidence():
    m = Market(id="1", question="test", yes_price=.40, no_price=.60, liquidity=100000, volume=100000, spread=.01)
    r = ResearchReport(probability_yes=.60, confidence=.20, thesis="x", counter_thesis="y")
    assert evaluate(m, r).decision == "SKIP"
