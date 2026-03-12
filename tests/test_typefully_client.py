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
        assert payload["platforms"]["x"]["posts"][0]["media_ids"] == ["uuid-1234"]

    def test_build_draft_payload_per_post_media(self, client):
        payload = client._build_draft_payload(
            posts=["Tweet 1", "Tweet 2"],
            title="Thread",
            per_post_media=[["media-a"], ["media-b"]],
        )
        assert payload["platforms"]["x"]["posts"][0]["media_ids"] == ["media-a"]
        assert payload["platforms"]["x"]["posts"][1]["media_ids"] == ["media-b"]

    def test_build_draft_payload_per_post_media_partial(self, client):
        payload = client._build_draft_payload(
            posts=["Tweet 1", "Tweet 2"],
            title="Thread",
            per_post_media=[["media-a"], []],
        )
        assert payload["platforms"]["x"]["posts"][0]["media_ids"] == ["media-a"]
        assert "media_ids" not in payload["platforms"]["x"]["posts"][1]

    def test_build_draft_payload_no_title(self, client):
        payload = client._build_draft_payload(posts=["Just text"])
        assert "draft_title" not in payload

    def test_build_draft_payload_with_publish_at(self, client):
        payload = client._build_draft_payload(
            posts=["Scheduled post"],
            title="Scheduled",
            publish_at="2026-03-12T15:00:00Z",
        )
        assert payload["publish_at"] == "2026-03-12T15:00:00Z"

    def test_build_draft_payload_without_publish_at(self, client):
        payload = client._build_draft_payload(
            posts=["No schedule"],
            title="Unscheduled",
        )
        assert "publish_at" not in payload

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

    @pytest.mark.asyncio
    async def test_create_draft_passes_publish_at(self, client):
        """create_draft forwards publish_at into the HTTP payload."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "id": 101,
            "status": "draft",
            "private_url": "https://typefully.com/draft/sched",
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await client.create_draft(
                posts=["Scheduled post"],
                title="Sched",
                publish_at="2026-03-12T15:00:00Z",
            )
        assert result["id"] == 101
        # Verify the JSON payload sent to the API contains publish_at
        call_kwargs = mock_post.call_args
        sent_payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert sent_payload["publish_at"] == "2026-03-12T15:00:00Z"

    @pytest.mark.asyncio
    async def test_create_draft_waits_for_media(self, client):
        """create_draft polls media status before submitting."""
        mock_get = AsyncMock()
        # First call: processing, second: ready
        processing_resp = MagicMock()
        processing_resp.json.return_value = {"status": "processing"}
        processing_resp.raise_for_status = MagicMock()
        ready_resp = MagicMock()
        ready_resp.json.return_value = {"status": "ready"}
        ready_resp.raise_for_status = MagicMock()
        mock_get.side_effect = [processing_resp, ready_resp]

        draft_resp = MagicMock()
        draft_resp.status_code = 201
        draft_resp.json.return_value = {"id": 100, "private_url": "https://typefully.com/draft/xyz"}
        draft_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "get", mock_get), \
             patch.object(client._http, "post", new_callable=AsyncMock, return_value=draft_resp), \
             patch("src.typefully_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.create_draft(
                posts=["With media"],
                media_ids=["media-123"],
            )
        assert result["id"] == 100
        assert mock_get.call_count == 2
