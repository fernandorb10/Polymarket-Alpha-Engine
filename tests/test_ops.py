from types import SimpleNamespace

from alpha_engine import analytics, db, ops
from alpha_engine.config import settings


class FakeOpportunity:
    def __init__(self, market_id='m1', side='YES', decision='OPEN', edge=0.10, confidence=0.80):
        self.market = SimpleNamespace(id=market_id, question='Will Example win the 2028 election?')
        self.side = side
        self.decision = decision
        self.net_edge = edge
        self.confidence = confidence
        self.critic_risk = 0.10
        self.stake_usdc = 10.0

    def model_dump(self, mode='json'):
        return {
            'market': {'id': self.market.id, 'question': self.market.question},
            'side': self.side,
            'decision': self.decision,
            'net_edge': self.net_edge,
            'confidence': self.confidence,
        }


def prepare_database(tmp_path, monkeypatch):
    database = tmp_path / 'test.db'
    monkeypatch.setattr(settings, 'database_path', str(database))
    monkeypatch.setattr(settings, 'backup_dir', str(tmp_path / 'backups'))
    monkeypatch.setattr(settings, 'export_dir', str(tmp_path / 'exports'))
    db.init_db()
    analytics.init_analytics()
    ops.prepare()
    return database


def test_entry_requires_consecutive_confirmations(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, 'entry_confirmation_cycles', 2)
    opportunity = FakeOpportunity()

    confirmed, count = ops.confirm_entry(opportunity)
    assert confirmed is False
    assert count == 1

    confirmed, count = ops.confirm_entry(opportunity)
    assert confirmed is True
    assert count == 2


def test_side_change_resets_confirmation(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, 'entry_confirmation_cycles', 2)

    ops.confirm_entry(FakeOpportunity(side='YES'))
    confirmed, count = ops.confirm_entry(FakeOpportunity(side='NO'))

    assert confirmed is False
    assert count == 1


def test_prepare_adds_strategy_columns(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    with ops.connect() as conn:
        columns = {row['name'] for row in conn.execute('PRAGMA table_info(positions)')}
        tables = {row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    assert {'strategy_version', 'campaign_id', 'mfe_pct', 'mae_pct', 'entry_reason'} <= columns
    assert {'decision_ledger', 'entry_confirmations', 'service_health', 'campaigns'} <= tables


def test_doctor_database_integrity(tmp_path, monkeypatch):
    prepare_database(tmp_path, monkeypatch)
    result = ops.doctor(check_external=False)
    assert result['database'] == 'ok'
    assert result['config']['paper_only'] is True
