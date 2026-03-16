"""Tests for the content poster module."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.datastore import DataStore


@pytest.fixture
def ds(tmp_path):
    db_path = str(tmp_path / "test.db")
    store = DataStore(db_path)
    yield store
    store.close()


@pytest.fixture
def selections_file(tmp_path):
    """Write a fake content_selections.json and return its path."""
    sel = [
        {
            "angle_type": "leaderboard_shakeup",
            "raw_score": 0.75,
            "effective_score": 0.85,
            "auto_publish": True,
            "payload_path": "data/content_payload_leaderboard_shakeup.json",
        }
    ]
    path = tmp_path / "content_selections.json"
    path.write_text(json.dumps(sel))
    return str(path)


class TestPostAndRecord:
    """post_and_record pushes to Typefully AND records to DB atomically."""

    @patch("src.content.poster.TypefullyClient")
    def test_records_to_db_after_typefully_push(
        self, MockClient, selections_file, tmp_path
    ):
        from src.content.poster import post_and_record

        mock_instance = MockClient.return_value
        mock_instance.upload_media = AsyncMock(return_value="media-id-123")
        mock_instance.create_draft = AsyncMock(
            return_value={"id": "draft-1", "private_url": "https://typefully.com/d/123"}
        )
        mock_instance.close = AsyncMock()

        draft = {"tweets": [{"text": "Hello world", "screenshots": []}]}

        result = post_and_record(
            draft=draft,
            angle_type="leaderboard_shakeup",
            title="Leaderboard Shakeup — 2026-03-16",
            selections_path=selections_file,
            db_path=str(tmp_path / "test.db"),
        )

        assert result["private_url"] == "https://typefully.com/d/123"

        # Verify DB was populated
        ds2 = DataStore(str(tmp_path / "test.db"))
        last = ds2.get_last_post_date("leaderboard_shakeup")
        ds2.close()
        assert last is not None

    @patch("src.content.poster.TypefullyClient")
    def test_auto_publish_sets_publish_at(self, MockClient, selections_file, tmp_path):
        from src.content.poster import post_and_record

        mock_instance = MockClient.return_value
        mock_instance.upload_media = AsyncMock(return_value="media-id")
        mock_instance.create_draft = AsyncMock(
            return_value={"id": "1", "private_url": "https://typefully.com/d/1"}
        )
        mock_instance.close = AsyncMock()

        draft = {"tweets": [{"text": "Test", "screenshots": []}]}

        post_and_record(
            draft=draft,
            angle_type="leaderboard_shakeup",
            title="Test",
            selections_path=selections_file,
            db_path=str(tmp_path / "test.db"),
            auto_publish=True,
        )

        # Verify create_draft was called with publish_at
        call_kwargs = mock_instance.create_draft.call_args[1]
        assert call_kwargs.get("publish_at") is not None

    @patch("src.content.poster.TypefullyClient")
    def test_no_publish_at_when_not_auto(self, MockClient, selections_file, tmp_path):
        from src.content.poster import post_and_record

        mock_instance = MockClient.return_value
        mock_instance.upload_media = AsyncMock(return_value="media-id")
        mock_instance.create_draft = AsyncMock(
            return_value={"id": "1", "private_url": "https://typefully.com/d/1"}
        )
        mock_instance.close = AsyncMock()

        draft = {"tweets": [{"text": "Test", "screenshots": []}]}

        post_and_record(
            draft=draft,
            angle_type="leaderboard_shakeup",
            title="Test",
            selections_path=selections_file,
            db_path=str(tmp_path / "test.db"),
            auto_publish=False,
        )

        call_kwargs = mock_instance.create_draft.call_args[1]
        assert call_kwargs.get("publish_at") is None
