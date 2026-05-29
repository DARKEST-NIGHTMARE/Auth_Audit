"""
TokenBudgetManager — enforces hard context window limits per LLM provider.
ProviderGovernor — manages provider availability + automatic fallback chain.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TokenBudgetManager:
    """
    Enforces hard context window limits per provider.
    Uses character-count approximation (4 chars ≈ 1 token).
    """
    # Conservative safe limits (actual - 20% buffer)
    BUDGET_MAP = {
        "cerebras": 50_000,   # modern Cerebras hosted models support much larger context windows
        "gemini":   28_000,   # gemini-2.0-flash actual: 32K
        "local":    2_000,    # Local extractive fallback
    }
    CHARS_PER_TOKEN = 4
    COMPRESSION_THRESHOLD = 0.65  # Compress if context > 65% of budget

    def get_budget_chars(self, provider: str, reserved_prompt_tokens: int = 1500) -> int:
        """Returns max characters available for context (after prompt overhead)."""
        token_budget = self.BUDGET_MAP.get(provider, 6_000)
        return (token_budget - reserved_prompt_tokens) * self.CHARS_PER_TOKEN

    def needs_compression(self, context: str, provider: str) -> bool:
        """Returns True if the context exceeds the compression threshold."""
        budget = self.get_budget_chars(provider)
        return len(context) > (budget * self.COMPRESSION_THRESHOLD)

    def fit_context(self, chunks: list[str], provider: str,
                    reserved_prompt_tokens: int = 1500) -> tuple[str, bool]:
        """
        Greedily assembles chunks until the budget is hit.
        Returns (context_text, was_truncated).
        """
        budget_chars = self.get_budget_chars(provider, reserved_prompt_tokens)
        context = ""
        truncated = False
        for chunk in chunks:
            if len(context) + len(chunk) + 2 > budget_chars:
                truncated = True
                break
            context += chunk + "\n\n"
        return context.strip(), truncated

    def compress_chunk(self, chunk: str, target_chars: int) -> str:
        """
        Extractive compression: keeps first 60% + last 40% of a chunk.
        Preserves intro context and conclusion.
        """
        if len(chunk) <= target_chars:
            return chunk
        front = int(target_chars * 0.6)
        back = target_chars - front
        return chunk[:front] + "\n...[compressed]...\n" + chunk[-back:]


class ProviderGovernor:
    """
    Manages LLM provider availability and routes to fallbacks on failure.
    Fallback chain: Cerebras → Gemini → Local Extractive
    """

    def __init__(self, cerebras_concurrency: int = 3, gemini_concurrency: int = 2):
        self.cerebras_sem = asyncio.Semaphore(cerebras_concurrency)
        self.gemini_sem = asyncio.Semaphore(gemini_concurrency)

    async def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        context_for_fallback: str = "",
        file_name: str = "document",
    ) -> tuple[str, str, bool]:
        """
        Attempt generation with fallback chain.
        Returns (generated_text, provider_used, fallback_triggered).
        """
        from app.services.summarization.ai_clients import CerebrasClient, GeminiClient
        from app.core.config import settings

        # 1. Try Cerebras (primary)
        if settings.cerebras_api_key:
            try:
                async with self.cerebras_sem:
                    client = CerebrasClient()
                    result = await client.generate(prompt, system_instruction)
                    return result, "cerebras", False
            except Exception as e:
                logger.warning(f"Cerebras failed ({type(e).__name__}). Trying Gemini.")

        # 2. Try Gemini (secondary)
        if settings.gemini_api_key:
            try:
                async with self.gemini_sem:
                    client = GeminiClient()
                    result = await client.generate(prompt, system_instruction)
                    return result, "gemini", True
            except Exception as e:
                logger.warning(f"Gemini failed ({type(e).__name__}). Using local fallback.")

        # 3. Local extractive fallback (no API)
        logger.error("All LLM providers failed. Returning local extractive summary.")
        snippet = context_for_fallback[:1500].strip() if context_for_fallback else "(No content available)"
        local_result = (
            f'{{"summary": "**Notice: AI Generation Paused.**\\n\\n'
            f'**Document Excerpt ({file_name}):**\\n> {snippet}...\\n\\n'
            f'*Summary generated via local extraction.*", "suggested_questions": []}}'
        )
        return local_result, "local", True


# Module-level singleton instances
token_budget = TokenBudgetManager()
provider_governor = ProviderGovernor()
