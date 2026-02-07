import pytest

from src.risk.slippage import get_slippage_assumption


@pytest.mark.parametrize("token,expected", [
    ("BTC", 0.05),
    ("ETH", 0.10),
    ("SOL", 0.15),
    ("HYPE", 0.30),
    ("DOGE", 0.20),
    ("UNKNOWN", 0.20),
])
def test_slippage_assumptions(token, expected):
    assert get_slippage_assumption(token) == expected
