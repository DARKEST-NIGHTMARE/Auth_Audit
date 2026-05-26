"""
Conversation Memory — tracks per-user context across turns.
Enables the graph to resolve follow-up questions like:
  - "What are the key dates?" (after summarizing @Contract.pdf)
  - "Compare those with section 3" (anaphora resolution)

Design:
- In-memory dict keyed by user_id (survives request boundaries within a session)
- Stores last N turns: {query, resolved_items, doc_type, summary_snippet}
- Lightweight: no DB dependency, expires on server restart (acceptable for session memory)
- Thread-safe via asyncio.Lock
"""
from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_TURNS = 5          # How many past turns to remember per user
SESSION_TTL_MINUTES = 30  # Expire memory after inactivity


@dataclass
class Turn:
    query: str
    resolved_items: List[Dict[str, Any]]    # [{id, name, type}]
    doc_type: Optional[str]                  # "legal_case" | "general_document"
    summary_snippet: str                     # First 300 chars of summary
    source_files: List[str]
    timestamp: datetime = field(default_factory=datetime.now)


class ConversationMemory:
    """
    Per-user conversation memory with TTL and turn limit.
    """

    def __init__(self):
        self._store: Dict[str, List[Turn]] = {}   # user_id → [Turn]
        self._lock = asyncio.Lock()

    async def record_turn(
        self,
        user_id: str,
        query: str,
        resolved_items: List[Dict],
        doc_type: Optional[str],
        summary: str,
        source_files: List[str],
    ) -> None:
        """Record a completed turn for a user."""
        turn = Turn(
            query=query,
            resolved_items=resolved_items,
            doc_type=doc_type,
            summary_snippet=summary[:300] if summary else "",
            source_files=source_files,
        )
        async with self._lock:
            history = self._store.get(str(user_id), [])
            history.append(turn)
            # Keep only the last MAX_TURNS
            self._store[str(user_id)] = history[-MAX_TURNS:]

    async def get_history(self, user_id: str) -> List[Turn]:
        """Returns non-expired turns for a user."""
        cutoff = datetime.now() - timedelta(minutes=SESSION_TTL_MINUTES)
        async with self._lock:
            history = self._store.get(str(user_id), [])
            # Filter expired turns
            fresh = [t for t in history if t.timestamp > cutoff]
            self._store[str(user_id)] = fresh
            return fresh

    async def get_last_context(self, user_id: str) -> Optional[Turn]:
        """Returns the most recent turn (for anaphora resolution)."""
        history = await self.get_history(user_id)
        return history[-1] if history else None

    async def resolve_implicit_context(
        self,
        user_id: str,
        query: str,
        current_resolved_items: List[Dict],
    ) -> List[Dict]:
        """
        If the current query has no @mentions and no resolved items,
        try to inherit resolved_items from the previous turn.

        Handles follow-up patterns like:
        - "What are the key dates?" → uses previous document
        - "Summarize this" → uses previous document
        - "Tell me more" → uses previous document
        """
        if current_resolved_items:
            return current_resolved_items  # Already resolved — don't override

        # Check if this looks like a follow-up (short query, no @mentions)
        is_followup = (
            len(query.split()) <= 10
            or any(w in query.lower() for w in [
                "this", "that", "it", "those", "these",
                "the document", "the file", "the case",
                "tell me more", "continue", "elaborate",
                "what else", "anything else",
            ])
        )

        if not is_followup:
            return current_resolved_items

        last = await self.get_last_context(user_id)
        if last and last.resolved_items:
            logger.info(
                f"Memory: Resolved implicit context for user {user_id}. "
                f"Inheriting: {[i['name'] for i in last.resolved_items]}"
            )
            return last.resolved_items

        return current_resolved_items

    def build_history_context(self, turns: List[Turn]) -> str:
        """
        Build a brief conversation history string to prepend to prompts,
        helping the LLM understand the conversational context.
        """
        if not turns:
            return ""

        lines = ["**Previous conversation context:**"]
        for i, turn in enumerate(turns[-3:], 1):  # Last 3 turns only
            files = ", ".join(turn.source_files) if turn.source_files else "unknown"
            lines.append(f"{i}. User asked: \"{turn.query}\" (about: {files})")
            if turn.summary_snippet:
                lines.append(f"   Summary snippet: {turn.summary_snippet[:150]}...")
        return "\n".join(lines)

    async def clear_user(self, user_id: str) -> None:
        """Clear memory for a specific user (e.g., on logout)."""
        async with self._lock:
            self._store.pop(str(user_id), None)


# Module-level singleton
conversation_memory = ConversationMemory()
