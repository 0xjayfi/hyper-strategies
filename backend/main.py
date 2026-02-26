"""Hyper-Signals FastAPI application."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.cache import CacheLayer
from backend.config import ALLOWED_ORIGINS, NANSEN_API_KEY, NANSEN_BASE_URL
from backend.routers import allocations, assess, health, leaderboard, market, positions, screener, traders
from src.allocation import RiskConfig
from src.datastore import DataStore
from src.nansen_client import NansenAPIError, NansenClient, NansenRateLimitError
from src.scheduler import run_scheduler

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown resources."""
    # --- startup ---
    logger.info("Starting Hyper-Signals API...")

    if not NANSEN_API_KEY:
        logger.warning("NANSEN_API_KEY is not set — Nansen API calls will fail.")

    nansen_client = NansenClient(api_key=NANSEN_API_KEY, base_url=NANSEN_BASE_URL)
    app.state.nansen_client = nansen_client

    datastore = DataStore("data/pnl_weighted.db")
    app.state.datastore = datastore

    cache = CacheLayer()
    app.state.cache = cache

    # Launch scheduler as background task (skip in test mode)
    if os.getenv("TESTING") != "1":
        risk_config = RiskConfig(max_total_open_usd=50_000.0)
        scheduler_task = asyncio.create_task(
            run_scheduler(nansen_client, datastore, risk_config)
        )
        app.state.scheduler_task = scheduler_task

    logger.info("Hyper-Signals API ready.")
    yield

    # --- shutdown ---
    logger.info("Shutting down Hyper-Signals API...")
    if hasattr(app.state, "scheduler_task"):
        app.state.scheduler_task.cancel()
        try:
            await app.state.scheduler_task
        except asyncio.CancelledError:
            pass
    await nansen_client.close()
    datastore.close()
    logger.info("Hyper-Signals API stopped.")


app = FastAPI(
    title="Hyper-Signals API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions.router)
app.include_router(health.router)
app.include_router(market.router)
app.include_router(leaderboard.router)
app.include_router(screener.router)
app.include_router(traders.router)
app.include_router(allocations.router)
app.include_router(assess.router)


@app.exception_handler(NansenRateLimitError)
async def rate_limit_handler(request: Request, exc: NansenRateLimitError):
    return JSONResponse(
        status_code=503,
        content={"detail": "Rate limit exceeded. Please try again later.", "retry_after": 60},
        headers={"Retry-After": "60"},
    )


@app.exception_handler(NansenAPIError)
async def nansen_error_handler(request: Request, exc: NansenAPIError):
    return JSONResponse(
        status_code=502,
        content={"detail": f"Upstream API error: {exc.detail}"},
    )


@app.get("/")
def root() -> dict[str, str]:
    """Root endpoint."""
    return {"name": "Hyper-Signals API", "version": "0.1.0"}
