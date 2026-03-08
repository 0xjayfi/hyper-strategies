"""Tests for the Typefully API client (mocked HTTP)."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.typefully_client import TypefullyClient


@pytest.fixture
def client():
    return TypefullyClient(api_key="test-key", social_set_id=123)


class TestTypefullyClient:

    def test_build_draft_payload_single_tweet(self, client):
        payload = client._build_draft_payload(
            posts=["Hello world"],
            title="Test Draft",
        )
        assert payload["platforms"]["x"]["enabled"] is True
        assert len(payload["platforms"]["x"]["posts"]) == 1
        assert payload["platforms"]["x"]["posts"][0]["text"] == "Hello world"
        assert payload["draft_title"] == "Test Draft"

    def test_build_draft_payload_thread(self, client):
        payload = client._build_draft_payload(
            posts=["Tweet 1", "Tweet 2", "Tweet 3"],
            title="Thread",
        )
        assert len(payload["platforms"]["x"]["posts"]) == 3

    def test_build_draft_payload_with_media(self, client):
        payload = client._build_draft_payload(
            posts=["Check this chart"],
            title="Chart Post",
            media_ids=["uuid-1234"],
        )
        assert payload["platforms"]["x"]["posts"][0]["media"] == ["uuid-1234"]

    def test_build_draft_payload_no_title(self, client):
        payload = client._build_draft_payload(posts=["Just text"])
        assert "draft_title" not in payload

    @pytest.mark.asyncio
    async def test_create_draft_calls_api(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 99,
            "status": "draft",
            "private_url": "https://typefully.com/draft/abc",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response):
            result = await client.create_draft(
                posts=["Test post"],
                title="Test",
            )
        assert result["id"] == 99
        assert result["private_url"] == "https://typefully.com/draft/abc"
