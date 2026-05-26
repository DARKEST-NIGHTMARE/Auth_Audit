"""
LangGraph checkpoint persistence.
Uses AsyncSqliteSaver (no extra deps) as primary,
with AsyncPostgresSaver as upgrade path for production.

Checkpointing enables:
- Resumable graph runs after server restart
- Human-in-the-loop interrupts (the graph "parks" mid-run)
- Replay and debugging via LangSmith
"""
from __future__ import annotations
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Path for SQLite checkpoint DB (used in dev/single-server deployments)
_CHECKPOINT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "checkpoints.db"
)
_CHECKPOINT_DB_PATH = os.path.normpath(_CHECKPOINT_DB_PATH)

_checkpointer = None
_checkpointer_lock = None


async def get_checkpointer():
    """
    Returns the async checkpointer singleton.

    Priority:
    1. PostgreSQL (if POSTGRES_CHECKPOINT_URL env var is set)
    2. SQLite (default — works with no extra dependencies)
    3. None (in-memory only — graph still works, just not resumable)
    """
    global _checkpointer, _checkpointer_lock

    if _checkpointer is not None:
        return _checkpointer

    import asyncio
    if _checkpointer_lock is None:
        _checkpointer_lock = asyncio.Lock()

    async with _checkpointer_lock:
        if _checkpointer is not None:
            return _checkpointer

        # 1. Try PostgreSQL (production multi-server setup)
        pg_url = os.getenv("POSTGRES_CHECKPOINT_URL")
        if pg_url:
            try:
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
                saver = AsyncPostgresSaver.from_conn_string(pg_url)
                await saver.setup()
                _checkpointer = saver
                logger.info("Checkpointer: Using AsyncPostgresSaver (PostgreSQL).")
                return _checkpointer
            except Exception as e:
                logger.warning(f"Checkpointer: PostgreSQL failed ({e}). Trying SQLite.")

        # 2. Try SQLite (dev / single-server — langgraph-checkpoint-sqlite package)
        try:
            from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
            saver = AsyncSqliteSaver.from_conn_string(_CHECKPOINT_DB_PATH)
            await saver.setup()
            _checkpointer = saver
            logger.info(f"Checkpointer: Using AsyncSqliteSaver at {_CHECKPOINT_DB_PATH}.")
            return _checkpointer
        except ImportError:
            logger.warning(
                "Checkpointer: langgraph-checkpoint-sqlite not installed. "
                "Run: pip install langgraph-checkpoint-sqlite. "
                "Falling back to in-memory (not resumable)."
            )
        except Exception as e:
            logger.warning(f"Checkpointer: SQLite failed ({e}). Falling back to in-memory.")

        # 3. Fallback: MemorySaver (graph works but not resumable)
        try:
            from langgraph.checkpoint.memory import MemorySaver
            _checkpointer = MemorySaver()
            logger.info("Checkpointer: Using MemorySaver (in-memory, not resumable).")
        except Exception as e:
            logger.error(f"Checkpointer: MemorySaver also failed: {e}")
            _checkpointer = None

        return _checkpointer
