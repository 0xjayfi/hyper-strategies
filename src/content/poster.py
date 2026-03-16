"""Content poster — atomic Typefully push + DB recording.

Single code-owned function that ensures cooldown tracking stays
accurate even if the prompt-driven agent skips a step.

Usage from prompt templates::

    from src.content.poster import post_and_record
    result = post_and_record(
        draft=final_draft,
        angle_type="leaderboard_shakeup",
        title="Leaderboard Shakeup — DATE",
        auto_publish=True,
    )
    print(result['private_url'])
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.datastore import DataStore
from src.typefully_client import TypefullyClient

logger = logging.getLogger(__name__)

_SELECTIONS_PATH = "data/content_selections.json"
_CHARTS_DIR = "data/charts"
_AUTO_PUBLISH_DELAY_MINUTES = 90


async def _do_post(
    client: TypefullyClient,
    draft: dict,
    title: str,
    auto_publish: bool,
) -> dict:
    """Async inner function — upload media, create draft, return result."""
    # Upload media
    media_map: dict[str, str] = {}
    for tweet in draft["tweets"]:
        for filename in tweet.get("screenshots", []):
            if filename not in media_map:
                filepath = os.path.join(_CHARTS_DIR, filename)
                media_map[filename] = await client.upload_media(filepath)

    # Build per-post media
    per_post_media: list[list[str]] = []
    for tweet in draft["tweets"]:
        ids = [media_map[f] for f in tweet.get("screenshots", []) if f in media_map]
        per_post_media.append(ids)

    # Determine publish_at
    publish_at: Optional[str] = None
    if auto_publish:
        publish_at = (
            datetime.now(timezone.utc) + timedelta(minutes=_AUTO_PUBLISH_DELAY_MINUTES)
        ).isoformat()

    # Create draft
    result = await client.create_draft(
        posts=[t["text"] for t in draft["tweets"]],
        title=title,
        per_post_media=per_post_media,
        publish_at=publish_at,
    )

    await client.close()
    return result


def post_and_record(
    draft: dict,
    angle_type: str,
    title: str,
    auto_publish: bool = False,
    selections_path: str = _SELECTIONS_PATH,
    db_path: str = "data/pnl_weighted.db",
) -> dict:
    """Push draft to Typefully and record to content_posts. Returns Typefully result dict."""

    api_key = os.environ["TYPEFULLY_API_KEY"]
    social_set_id = int(os.environ["TYPEFULLY_SOCIAL_SET_ID"])

    client = TypefullyClient(api_key=api_key, social_set_id=social_set_id)

    # Single asyncio.run() call for all async operations
    result = asyncio.run(_do_post(client, draft, title, auto_publish))

    # Record to DB (synchronous)
    sel = _load_selection(angle_type, selections_path)
    ds = DataStore(db_path)
    try:
        ds.insert_content_post(
            post_date=datetime.now(timezone.utc).date(),
            angle_type=angle_type,
            raw_score=sel.get("raw_score", 0.0),
            effective_score=sel.get("effective_score", 0.0),
            auto_published=auto_publish,
            typefully_url=result.get("private_url"),
            payload_path=sel.get("payload_path"),
        )
    finally:
        ds.close()

    logger.info(
        "Posted %s -> %s (recorded to DB)", angle_type, result.get("private_url")
    )
    return result


def _load_selection(angle_type: str, selections_path: str) -> dict:
    """Load the selection entry for this angle from content_selections.json."""
    try:
        with open(selections_path) as f:
            selections = json.load(f)
        return next(
            (s for s in selections if s["angle_type"] == angle_type),
            {"raw_score": 0.0, "effective_score": 0.0},
        )
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning("Could not load selections from %s", selections_path)
        return {"raw_score": 0.0, "effective_score": 0.0}
