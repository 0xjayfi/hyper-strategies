"""Health check router."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from backend.config import NANSEN_API_KEY
from backend.dependencies import get_datastore
from backend.schemas import HealthResponse
from src.datastore import DataStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check(
    datastore: DataStore = Depends(get_datastore),
) -> HealthResponse:
    """Return system health status."""
    db_ok = False
    try:
        datastore._conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        logger.warning("Health check: database connection failed", exc_info=True)

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        db_connected=db_ok,
        nansen_key_set=bool(NANSEN_API_KEY),
    )
