import pytest
from datetime import datetime
from src.models import Trade, TradeMetrics
from src.datastore import DataStore

def make_trade(closed_pnl=100.0, value_usd=1000.0, action="Close", **overrides):
    defaults = dict(
        action=action, closed_pnl=closed_pnl, price=50000.0, side="Long",
        size=0.1, timestamp=datetime.utcnow().isoformat(),
        token_symbol="BTC", value_usd=value_usd, fee_usd=1.0, start_position=0.0,
    )
    defaults.update(overrides)
    return Trade(**defaults)

def make_metrics(window_days=30, **overrides):
    defaults = dict(
        window_days=window_days, total_trades=50, winning_trades=30, losing_trades=20,
        win_rate=0.6, gross_profit=15000.0, gross_loss=5000.0, profit_factor=3.0,
        avg_return=0.05, std_return=0.03, pseudo_sharpe=1.67,
        total_pnl=10000.0, roi_proxy=20.0, max_drawdown_proxy=0.05,
    )
    defaults.update(overrides)
    return TradeMetrics(**defaults)

@pytest.fixture
def ds():
    with DataStore(":memory:") as store:
        yield store
