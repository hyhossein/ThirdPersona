"""
Extraction worker process — deploy alongside the API as a second service.

    python scripts/worker.py

Connects with the runtime (non-superuser) DSN; executes each job inside
that user's RLS context. Ctrl-C for graceful shutdown.
"""

import asyncio
import logging
import os
import signal
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.services.jobs import worker_loop  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await worker_loop(settings.database_url, stop_event=stop)


if __name__ == "__main__":
    asyncio.run(main())
