from alpha_engine import db
from alpha_engine.config import settings
from alpha_engine.models import CriticReport, Market, Opportunity, ProbabilityReport


def market(mid='m1', bid=.40, ask=.44):
    return Market(id=mid, question='Will Team win the World Cup?', category='sports', yes_price=.42, no_price=.58,
                  best_bid_yes=bid, best_ask_yes=ask, spread=ask-bid, liquidity=100000, volume=100000,
                  yes_token_id='y', no_token_id='n')


def opportunity(mid='m1', side='YES', stake=20):
    m = market(mid)
    p = ProbabilityReport(probability_yes=.60, confidence=.8, thesis='test')
    c = CriticReport(risk_score=.1, resolution_ambiguity=.1, strongest_objection='none', recommendation='ACCEPT')
    price = db.executable_entry_price(m, side)
    return Opportunity(market=m, side=side, fair_probability=.6 if side=='YES' else .4,
                       market_probability=price, gross_edge=.16, net_edge=.15,
                       expected_value_per_dollar=.2, confidence=.8, critic_risk=.1,
                       kelly_fraction=.02, stake_usdc=stake, score=10, decision='OPEN',
                       reason='test', probability_report=p, critic_report=c)


def setup_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'database_path', str(tmp_path / 'test.db'))
    monkeypatch.setattr(settings, 'bankroll_usdc', 1000)
    monkeypatch.setattr(settings, 'max_total_exposure_pct', .05)
    monkeypatch.setattr(settings, 'max_category_exposure_pct', .10)
    monkeypatch.setattr(settings, 'max_event_exposure_pct', .05)
    db.init_db()


def test_can_close_reopened_market_twice(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity())
    first = db.close_position(1, .50, 'TEST')
    assert first
    assert db.open_position(opportunity())
    second = db.close_position(2, .51, 'TEST2')
    assert second
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) n FROM positions WHERE status='CLOSED'").fetchone()['n'] == 2


def test_only_one_open_position_per_market(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity())
    assert not db.open_position(opportunity())


def test_yes_and_no_use_executable_asks():
    m = market()
    assert db.executable_entry_price(m, 'YES') == .44
    assert db.executable_entry_price(m, 'NO') == .60
    assert db.executable_exit_price(m, 'YES') == .40
    assert db.executable_exit_price(m, 'NO') == .56


def test_total_exposure_is_hard_limit(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity('m1', stake=30))
    allowed, reason = db.portfolio_allows('Will Player win the Ballon d Or?', 25, 'sports')
    assert not allowed
    assert reason == 'TOTAL_EXPOSURE_LIMIT'
