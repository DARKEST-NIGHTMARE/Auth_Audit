"""
Migration: Add pending_action and checkpoint_ns columns to query_jobs.
Run once with: ./venv/bin/python -m app.migrations.add_graph_columns
"""
import asyncio
import logging
from sqlalchemy import text
from app.core.database import engine

logger = logging.getLogger(__name__)


async def run():
    async with engine.begin() as conn:
        # Add AWAITING_APPROVAL to the enum (PostgreSQL-specific)
        try:
            await conn.execute(text(
                "ALTER TYPE queryjobstatus ADD VALUE IF NOT EXISTS 'awaiting_approval'"
            ))
            logger.info("Added 'awaiting_approval' to queryjobstatus enum.")
        except Exception as e:
            logger.warning(f"Enum alter skipped (may already exist): {e}")

        # Add pending_action column
        try:
            await conn.execute(text(
                "ALTER TABLE query_jobs ADD COLUMN IF NOT EXISTS pending_action JSONB"
            ))
            logger.info("Added pending_action column.")
        except Exception as e:
            logger.warning(f"pending_action column: {e}")

        # Add checkpoint_ns column
        try:
            await conn.execute(text(
                "ALTER TABLE query_jobs ADD COLUMN IF NOT EXISTS checkpoint_ns VARCHAR"
            ))
            logger.info("Added checkpoint_ns column.")
        except Exception as e:
            logger.warning(f"checkpoint_ns column: {e}")

    print("Migration complete.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
