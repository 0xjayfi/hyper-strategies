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

import asyncio
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
        per_post_media: Optional[list[list[str]]] = None,
    ) -> dict:
        """Build the JSON payload for creating a draft.

        Media can be attached two ways:
        - ``media_ids``: all media on the first post (legacy)
        - ``per_post_media``: list of media_id lists, one per post
        """
        x_posts = []
        for i, text in enumerate(posts):
            post: dict = {"text": text}
            if per_post_media and i < len(per_post_media) and per_post_media[i]:
                post["media_ids"] = per_post_media[i]
            elif i == 0 and media_ids:
                post["media_ids"] = media_ids
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

        # Typefully signs presigned URLs with empty Content-Type, so we
        # must NOT send a Content-Type header or S3 returns 403.
        async with httpx.AsyncClient(timeout=60.0) as s3_client:
            file_bytes = path.read_bytes()
            s3_resp = await s3_client.put(
                upload_url,
                content=file_bytes,
            )
            if s3_resp.status_code != 200:
                logger.error(
                    "S3 upload failed (%s): %s",
                    s3_resp.status_code,
                    s3_resp.text,
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

    async def wait_for_media_ready(
        self,
        media_id: str,
        timeout: float = 60.0,
        poll_interval: float = 2.0,
    ) -> str:
        """Poll until media is ready. Returns final status."""
        elapsed = 0.0
        while elapsed < timeout:
            status = await self.get_media_status(media_id)
            if status == "ready":
                return status
            if status == "error":
                raise RuntimeError(f"Media {media_id} processing failed")
            logger.debug("Media %s status: %s, waiting...", media_id, status)
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        raise TimeoutError(
            f"Media {media_id} still processing after {timeout}s"
        )

    async def create_draft(
        self,
        posts: list[str],
        title: str = "",
        media_ids: Optional[list[str]] = None,
        per_post_media: Optional[list[list[str]]] = None,
    ) -> dict:
        """Create a Typefully draft. Returns the draft response dict.

        Waits for all referenced media to finish processing before
        submitting the draft.
        """
        # Collect all media IDs that need to be ready
        all_ids: list[str] = []
        if media_ids:
            all_ids.extend(media_ids)
        if per_post_media:
            for ids in per_post_media:
                all_ids.extend(ids)

        # Wait for all media to finish processing
        for mid in all_ids:
            await self.wait_for_media_ready(mid)
            logger.info("Media %s ready", mid)

        payload = self._build_draft_payload(
            posts, title, media_ids, per_post_media
        )
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
