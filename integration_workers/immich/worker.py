"""
Immich worker entrypoint.

This is a placeholder for Iteration 11 Phase 1. The full worker logic
will be implemented in Phase 2.
"""

__version__ = "0.1.0"

import asyncio
import logging
import sys


async def main() -> None:
    """Run a placeholder loop so the container stays alive."""
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("immich_worker")
    logger.info("Starting Immich placeholder worker...")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Worker cancelled, shutting down.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
