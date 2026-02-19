"""Backend-specific configuration."""
import os
from dotenv import load_dotenv

load_dotenv()

NANSEN_API_KEY = os.getenv("NANSEN_API_KEY", "")
NANSEN_BASE_URL = os.getenv("NANSEN_BASE_URL", "https://api.nansen.ai")
MOCK_STRATEGY_DATA = os.getenv("MOCK_STRATEGY_DATA", "false").lower() == "true"
CACHE_TTL_POSITIONS = int(os.getenv("CACHE_TTL_POSITIONS", "300"))  # 5 min
CACHE_TTL_LEADERBOARD = int(os.getenv("CACHE_TTL_LEADERBOARD", "3600"))  # 1 hour
CACHE_TTL_TRADER = int(os.getenv("CACHE_TTL_TRADER", "600"))  # 10 min
CACHE_TTL_ALLOCATIONS = int(os.getenv("CACHE_TTL_ALLOCATIONS", "3600"))  # 1 hour
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://localhost:5173")
