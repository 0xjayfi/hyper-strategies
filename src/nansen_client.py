"""Async HTTP client for Nansen API with pagination, rate-limiting, and field mapping."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import structlog

from src.models import RawTrade, TraderPositionSnapshot

log = structlog.get_logger()


class NansenClient:
    """Async client for Nansen API endpoints."""

    BASE_URL = "https://api.nansen.ai/api/v1"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"apiKey": api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    async def _post(self, endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
        """
        Make a POST request with exponential backoff on rate limits.

        Args:
            endpoint: API endpoint path
            body: Request body

        Returns:
            Response JSON as dict

        Raises:
            httpx.HTTPStatusError: After max retries or on non-429 errors
        """
        max_retries = 5
        base_delay = 1.0
        max_delay = 32.0

        for attempt in range(max_retries + 1):
            try:
                response = await self._client.post(endpoint, json=body)
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        log.warning(
                            "rate_limit_hit",
                            endpoint=endpoint,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay_seconds=delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    else:
                        log.error(
                            "rate_limit_max_retries_exceeded",
                            endpoint=endpoint,
                            max_retries=max_retries,
                        )
                        raise
                else:
                    # Non-429 errors are raised immediately
                    log.error(
                        "http_error",
                        endpoint=endpoint,
                        status_code=e.response.status_code,
                        response_text=e.response.text,
                    )
                    raise

        # Should never reach here due to raise in the loop
        raise RuntimeError("Unexpected state in _post method")

    async def _paginated_post(
        self,
        endpoint: str,
        body: dict[str, Any],
        page_key: str = "page",
        per_page: int = 100,
    ) -> list[dict[str, Any]]:
        """
        Make paginated POST requests and accumulate results.

        Args:
            endpoint: API endpoint path
            body: Base request body
            page_key: Key name for page parameter
            per_page: Results per page

        Returns:
            List of all accumulated results from all pages
        """
        all_results = []
        page = 1

        while True:
            paginated_body = {
                **body,
                page_key: page,
                "per_page": per_page,
            }

            log.debug(
                "fetching_page",
                endpoint=endpoint,
                page=page,
                per_page=per_page,
            )

            response = await self._post(endpoint, paginated_body)
            data = response.get("data", [])
            all_results.extend(data)

            log.debug(
                "page_fetched",
                endpoint=endpoint,
                page=page,
                results_count=len(data),
                total_count=len(all_results),
            )

            is_last = response.get("is_last_page", True)
            if is_last or not data:
                break

            page += 1

        log.info(
            "pagination_complete",
            endpoint=endpoint,
            total_pages=page,
            total_results=len(all_results),
        )

        return all_results

    async def get_perp_leaderboard(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """
        Fetch perpetual futures leaderboard.

        Args:
            date_from: Start date (ISO format)
            date_to: End date (ISO format)

        Returns:
            List of leaderboard entries
        """
        body = {"date_from": date_from, "date_to": date_to}
        return await self._paginated_post("/perp-leaderboard", body)

    async def get_address_perp_trades(
        self, address: str, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """
        Fetch perpetual trades for a specific address.

        Args:
            address: Trader wallet address
            date_from: Start date (ISO format)
            date_to: End date (ISO format)

        Returns:
            List of trade records
        """
        body = {"address": address, "date_from": date_from, "date_to": date_to}
        return await self._paginated_post("/profiler/perp-trades", body)

    async def get_address_perp_positions(self, address: str) -> dict[str, Any]:
        """
        Fetch current perpetual positions for a specific address.

        Args:
            address: Trader wallet address

        Returns:
            Position data dict (not paginated)
        """
        body = {"address": address}
        return await self._post("/profiler/perp-positions", body)

    async def get_perp_pnl_leaderboard(
        self, token_symbol: str, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """
        Fetch PnL leaderboard for a specific token.

        Args:
            token_symbol: Token symbol (e.g., "ETH")
            date_from: Start date (ISO format)
            date_to: End date (ISO format)

        Returns:
            List of PnL leaderboard entries
        """
        body = {"token_symbol": token_symbol, "date_from": date_from, "date_to": date_to}
        return await self._paginated_post("/perp-pnl-leaderboard", body)

    async def get_smart_money_perp_trades(
        self, only_new_positions: bool = False
    ) -> list[dict[str, Any]]:
        """
        Fetch smart money perpetual trades.

        Args:
            only_new_positions: If True, only return new position opens

        Returns:
            List of smart money trade records
        """
        body = {"only_new_positions": only_new_positions}
        return await self._paginated_post("/smart-money/perp-trades", body)

    async def get_perp_screener(
        self, date_from: str, date_to: str
    ) -> list[dict[str, Any]]:
        """
        Fetch perpetual screener data.

        Args:
            date_from: Start date (ISO format)
            date_to: End date (ISO format)

        Returns:
            List of screener entries
        """
        body = {"date_from": date_from, "date_to": date_to}
        return await self._paginated_post("/perp-screener", body)


def map_trade(raw: dict[str, Any]) -> RawTrade:
    """
    Map Nansen trade response to internal RawTrade model.

    Args:
        raw: Raw trade dict from Nansen API

    Returns:
        Parsed RawTrade model instance
    """
    return RawTrade(
        action=raw["action"],
        side=raw["side"],
        token_symbol=raw["token_symbol"],
        value_usd=float(raw["value_usd"]),
        price=float(raw["price"]),
        timestamp=raw["timestamp"],
        tx_hash=raw["transaction_hash"],
        start_position=(
            float(raw["start_position"])
            if raw.get("start_position") is not None
            else None
        ),
        size=float(raw["size"]) if raw.get("size") is not None else None,
    )


def map_leaderboard_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Map Nansen leaderboard response to internal trader dict.

    Args:
        raw: Raw leaderboard entry from Nansen API

    Returns:
        Standardized trader dict
    """
    return {
        "address": raw["trader_address"],
        "label": raw.get("trader_address_label"),
        "total_pnl": float(raw.get("total_pnl", 0)),
        "roi": float(raw.get("roi", 0)),
        "account_value": float(raw.get("account_value", 0)),
    }


def map_position(raw: dict[str, Any]) -> TraderPositionSnapshot:
    """
    Map Nansen position response to internal TraderPositionSnapshot.

    Args:
        raw: Raw position dict from Nansen API

    Returns:
        Parsed TraderPositionSnapshot model instance
    """
    pos = raw.get("position", raw)
    return TraderPositionSnapshot(
        token_symbol=pos["token_symbol"],
        position_value_usd=float(pos.get("position_value_usd", 0)),
        entry_price=float(pos.get("entry_price_usd", 0)),
        leverage=pos.get("leverage_value"),
        leverage_type=pos.get("leverage_type"),
        liquidation_price=(
            float(pos["liquidation_price_usd"])
            if pos.get("liquidation_price_usd")
            else None
        ),
        size=float(pos["size"]) if pos.get("size") else None,
        account_value=(
            float(raw["margin_summary_account_value_usd"])
            if raw.get("margin_summary_account_value_usd")
            else None
        ),
    )
