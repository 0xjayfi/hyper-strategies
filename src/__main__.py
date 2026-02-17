"""Entry point: python -m src"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from .nansen_client import NansenClient
from .datastore import DataStore
from .allocation import RiskConfig
from .scheduler import run_scheduler

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "scheduler.log")),
        logging.StreamHandler(sys.stdout),
    ],
)


async def main() -> None:
    client = NansenClient()
    datastore = DataStore(db_path="data/pnl_weighted.db")
    risk_config = RiskConfig(max_total_open_usd=50_000.0)

    logging.info("Scheduler starting — press Ctrl+C to stop")
    try:
        await run_scheduler(client, datastore, risk_config)
    except KeyboardInterrupt:
        logging.info("Scheduler stopped by user")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
