import sqlite3

from alpha_engine import db
from alpha_engine.config import settings
from alpha_engine.models import CriticReport, Market, Opportunity, ProbabilityReport


def market(mid="m1", bid=0.40, ask=0.44):
    return Market(
        id=mid,
        question="Will Team win the World Cup?",
        category="sports",
        yes_price=0.42,
        no_price=0.58,
        best_bid_yes=bid,
        best_ask_yes=ask,
        spread=ask - bid,
        liquidity=100000,
        volume=100000,
        yes_token_id="y",
        no_token_id="n",
    )


def opportunity(mid="m1", side="YES", stake=20):
    current_market = market(mid)
    probability = ProbabilityReport(
        probability_yes=0.60,
        confidence=0.8,
        thesis="test",
    )
    critic = CriticReport(
        risk_score=0.1,
        resolution_ambiguity=0.1,
        strongest_objection="none",
        recommendation="ACCEPT",
    )
    price = db.executable_entry_price(current_market, side)
    return Opportunity(
        market=current_market,
        side=side,
        fair_probability=0.6 if side == "YES" else 0.4,
        market_probability=price,
        gross_edge=0.16,
        net_edge=0.15,
        expected_value_per_dollar=0.2,
        confidence=0.8,
        critic_risk=0.1,
        kelly_fraction=0.02,
        stake_usdc=stake,
        score=10,
        decision="OPEN",
        reason="test",
        probability_report=probability,
        critic_report=critic,
    )


def setup_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(settings, "bankroll_usdc", 1000)
    monkeypatch.setattr(settings, "max_total_exposure_pct", 0.05)
    monkeypatch.setattr(settings, "max_category_exposure_pct", 0.10)
    monkeypatch.setattr(settings, "max_event_exposure_pct", 0.05)
    db.init_db()


def test_can_close_reopened_market_twice(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity())
    assert db.close_position(1, 0.50, "TEST")
    assert db.open_position(opportunity())
    assert db.close_position(2, 0.51, "TEST2")
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) n FROM positions WHERE status='CLOSED'"
        ).fetchone()["n"]
    assert count == 2


def test_only_one_open_position_per_market(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity())
    assert not db.open_position(opportunity())


def test_yes_and_no_use_executable_asks():
    current_market = market()
    assert db.executable_entry_price(current_market, "YES") == 0.44
    assert db.executable_entry_price(current_market, "NO") == 0.60
    assert db.executable_exit_price(current_market, "YES") == 0.40
    assert db.executable_exit_price(current_market, "NO") == 0.56


def test_total_exposure_is_hard_limit(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity("m1", stake=30))
    allowed, reason = db.portfolio_allows(
        "Will Player win the Ballon d'Or?",
        25,
        "sports",
    )
    assert not allowed
    assert reason == "TOTAL_EXPOSURE_LIMIT"


def test_open_position_clips_stake_to_remaining_room(monkeypatch, tmp_path):
    setup_tmp(monkeypatch, tmp_path)
    assert db.open_position(opportunity("m1", stake=45))

    second = opportunity("m2", stake=20)
    assert db.open_position(second)
    assert second.stake_usdc == 5.0

    with db.connect() as conn:
        total = conn.execute(
            "SELECT SUM(stake_usdc) total FROM positions WHERE status='OPEN'"
        ).fetchone()["total"]
    assert total == 50.0


def test_recovers_orphaned_legacy_table(monkeypatch, tmp_path):
    database_path = tmp_path / "interrupted.db"
    monkeypatch.setattr(settings, "database_path", str(database_path))

    conn = sqlite3.connect(database_path)
    conn.execute(
        """
        CREATE TABLE positions_legacy_unique(
            id INTEGER PRIMARY KEY,
            market_id TEXT NOT NULL,
            question TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            shares REAL NOT NULL,
            stake_usdc REAL NOT NULL,
            opened_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO positions_legacy_unique(
            id,market_id,question,side,entry_price,shares,stake_usdc,opened_at,status
        ) VALUES(1,'legacy','Legacy position','YES',0.5,20,10,'2026-01-01T00:00:00+00:00','CLOSED')
        """
    )
    conn.commit()
    conn.close()

    db.init_db()

    with db.connect() as recovered:
        count = recovered.execute("SELECT COUNT(*) n FROM positions").fetchone()["n"]
        legacy_exists = recovered.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='positions_legacy_unique'"
        ).fetchone()
    assert count == 1
    assert legacy_exists is None
