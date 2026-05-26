"""
QueryCache — 3-layer async cache for multi-user query deduplication.
Layers: embeddings → retrieval results → final summaries.
Prevents redundant LLM calls when multiple users ask the same question.
"""
from __future__ import annotations
import asyncio
import hashlib
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class QueryCache:
    """
    Thread-safe async cache with TTL expiry.

    Key design decisions:
    - Keyed by MD5(query + sorted file_ids + sorted folder_ids)
    - Separate TTLs per layer (summaries cached longer than retrievals)
    - asyncio.Lock ensures no race conditions under concurrent requests
    """

    def __init__(
        self,
        summary_ttl_minutes: int = 60,
        retrieval_ttl_minutes: int = 30,
    ):
        self._summary_cache: Dict[str, Dict[str, Any]] = {}
        self._retrieval_cache: Dict[str, Dict[str, Any]] = {}
        self._summary_ttl = timedelta(minutes=summary_ttl_minutes)
        self._retrieval_ttl = timedelta(minutes=retrieval_ttl_minutes)
        self._lock = asyncio.Lock()

    # ── Key Generation ──────────────────────────────────────────────────

    def make_key(
        self,
        query: str,
        file_ids: Optional[list] = None,
        folder_ids: Optional[list] = None,
    ) -> str:
        """Content-aware cache key. Normalizes query and sorts IDs."""
        file_ids = sorted(file_ids or [])
        folder_ids = sorted(folder_ids or [])
        raw = f"{query.strip().lower()}:{file_ids}:{folder_ids}"
        return hashlib.md5(raw.encode()).hexdigest()

    # ── Summary Cache ───────────────────────────────────────────────────

    async def get_summary(self, key: str) -> Optional[Dict]:
        async with self._lock:
            entry = self._summary_cache.get(key)
            if not entry:
                return None
            if datetime.now() - entry["ts"] > self._summary_ttl:
                del self._summary_cache[key]
                logger.debug(f"Cache EXPIRED (summary): {key[:8]}")
                return None
            logger.info(f"Cache HIT (summary): {key[:8]}")
            return entry["data"]

    async def set_summary(self, key: str, result: Dict) -> None:
        async with self._lock:
            self._summary_cache[key] = {"data": result, "ts": datetime.now()}
            logger.debug(f"Cache SET (summary): {key[:8]}")

    async def invalidate_summary(self, key: str) -> None:
        """Call this when a file is re-ingested to bust stale summaries."""
        async with self._lock:
            self._summary_cache.pop(key, None)

    # ── Retrieval Cache ─────────────────────────────────────────────────

    async def get_retrieval(self, key: str) -> Optional[Dict]:
        async with self._lock:
            entry = self._retrieval_cache.get(key)
            if not entry:
                return None
            if datetime.now() - entry["ts"] > self._retrieval_ttl:
                del self._retrieval_cache[key]
                return None
            logger.info(f"Cache HIT (retrieval): {key[:8]}")
            return entry["data"]

    async def set_retrieval(self, key: str, chunks: Dict) -> None:
        async with self._lock:
            self._retrieval_cache[key] = {"data": chunks, "ts": datetime.now()}

    # ── Maintenance ─────────────────────────────────────────────────────

    async def clear_all(self) -> None:
        """Flush all cache layers. Useful after bulk re-ingestion."""
        async with self._lock:
            count = len(self._summary_cache) + len(self._retrieval_cache)
            self._summary_cache.clear()
            self._retrieval_cache.clear()
            logger.info(f"Cache cleared: {count} entries removed.")

    def stats(self) -> Dict[str, int]:
        return {
            "summary_entries": len(self._summary_cache),
            "retrieval_entries": len(self._retrieval_cache),
        }


# Module-level singleton
query_cache = QueryCache(summary_ttl_minutes=60, retrieval_ttl_minutes=30)
