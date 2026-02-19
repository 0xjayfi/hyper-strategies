"""FastAPI dependency injection helpers."""
from __future__ import annotations

from fastapi import Request

from backend.cache import CacheLayer
from src.datastore import DataStore
from src.nansen_client import NansenClient


def get_nansen_client(request: Request) -> NansenClient:
    """Return the shared NansenClient from app state."""
    return request.app.state.nansen_client


def get_datastore(request: Request) -> DataStore:
    """Return the shared DataStore from app state."""
    return request.app.state.datastore


def get_cache(request: Request) -> CacheLayer:
    """Return the shared CacheLayer from app state."""
    return request.app.state.cache
