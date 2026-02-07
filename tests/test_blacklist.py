import pytest
from datetime import datetime, timedelta
from src.filters import is_trader_eligible, blacklist_trader
from src.datastore import DataStore

@pytest.fixture
def ds():
    with DataStore(":memory:") as store:
        store.upsert_trader("0xABC")
        yield store

def test_blacklist_blocks_trader(ds):
    blacklist_trader("0xABC", "liquidation", ds)
    ok, reason = is_trader_eligible("0xABC", ds)
    assert ok is False
    assert "liquidation" in reason

def test_blacklist_expires(ds):
    expired = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    ds.add_to_blacklist("0xABC", "liquidation", expires_at=expired)
    ok, _ = is_trader_eligible("0xABC", ds)
    assert ok is True

def test_cooldown_14_days(ds):
    blacklist_trader("0xABC", "liquidation", ds)
    entry = ds.get_blacklist_entry("0xABC")
    assert entry is not None
    expected = datetime.utcnow() + timedelta(days=14)
    actual = datetime.fromisoformat(entry["expires_at"])
    assert abs((actual - expected).total_seconds()) < 60

def test_not_blacklisted_is_eligible(ds):
    ok, reason = is_trader_eligible("0xABC", ds)
    assert ok is True
    assert reason == "eligible"
