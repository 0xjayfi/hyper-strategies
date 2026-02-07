"""Shared test fixtures for the consensus trading strategy."""

import pytest

from consensus.config import StrategyConfig


@pytest.fixture
def config() -> StrategyConfig:
    """Default strategy config for tests."""
    return StrategyConfig(
        NANSEN_API_KEY="test-key",
        HL_PRIVATE_KEY="test-key",
        TYPEFULLY_API_KEY="test-key",
    )
