"""Typefully API v2 client for creating X drafts with media.

Usage::

    client = TypefullyClient(api_key="...", social_set_id=123)
    result = await client.create_draft(
        posts=["Tweet 1", "Tweet 2"],
        title="My Thread",
        media_ids=["uuid-1234"],
    )
    print(result["private_url"])
    await client.close()
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.typefully.com/v2"


class TypefullyClient:
    """Async client for Typefully API v2."""

    def __init__(self, api_key: str, social_set_id: int) -> None:
        self._api_key = api_key
        self._social_set_id = social_set_id
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._http.aclose()

    def _build_draft_payload(
        self,
        posts: list[str],
        title: str = "",
        media_ids: Optional[list[str]] = None,
    ) -> dict:
        """Build the JSON payload for creating a draft."""
        x_posts = []
        for i, text in enumerate(posts):
            post = {"text": text}
            if i == 0 and media_ids:
                post["media"] = media_ids
            x_posts.append(post)

        payload = {
            "platforms": {
                "x": {
                    "enabled": True,
                    "posts": x_posts,
                }
            },
        }
        if title:
            payload["draft_title"] = title

        return payload

    async def upload_media(self, file_path: str) -> str:
        """Upload a media file and return its media_id."""
        path = Path(file_path)
        resp = await self._http.post(
            f"/social-sets/{self._social_set_id}/media/upload",
            json={"file_name": path.name},
        )
        resp.raise_for_status()
        data = resp.json()
        media_id = data["media_id"]
        upload_url = data["upload_url"]

        mime_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
        }
        content_type = mime_types.get(path.suffix.lower(), "application/octet-stream")

        async with httpx.AsyncClient(timeout=60.0) as s3_client:
            with open(file_path, "rb") as f:
                s3_resp = await s3_client.put(
                    upload_url,
                    content=f.read(),
                    headers={"Content-Type": content_type},
                )
                s3_resp.raise_for_status()

        logger.info("Uploaded media %s -> %s", path.name, media_id)
        return media_id

    async def get_media_status(self, media_id: str) -> str:
        """Check media processing status. Returns 'ready', 'processing', or 'error'."""
        resp = await self._http.get(
            f"/social-sets/{self._social_set_id}/media/{media_id}"
        )
        resp.raise_for_status()
        return resp.json()["status"]

    async def create_draft(
        self,
        posts: list[str],
        title: str = "",
        media_ids: Optional[list[str]] = None,
    ) -> dict:
        """Create a Typefully draft. Returns the draft response dict."""
        payload = self._build_draft_payload(posts, title, media_ids)
        resp = await self._http.post(
            f"/social-sets/{self._social_set_id}/drafts",
            json=payload,
        )
        resp.raise_for_status()
        result = resp.json()
        logger.info(
            "Created Typefully draft #%s: %s",
            result.get("id"),
            result.get("private_url"),
        )
        return result
