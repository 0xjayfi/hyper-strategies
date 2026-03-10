"""Run the Hyper-Signals backend server."""
import os
import uvicorn
from backend.config import BACKEND_PORT

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=BACKEND_PORT,
        reload=os.getenv("DEV", "").lower() in ("1", "true"),
    )
