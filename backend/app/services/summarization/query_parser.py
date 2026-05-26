import re
from enum import Enum
from typing import List
from dataclasses import dataclass

class Intent(str, Enum):
    SUMMARIZE = "summarize"
    QUESTION = "question"
    GENERAL = "general"

@dataclass
class ParsedQuery:
    original_text: str
    intent: Intent
    mentions: List[str]
    remaining_text: str

class QueryParser:
    """Parses user queries to extract intent and @mentions."""

    MENTION_PATTERNS = [
        r'@"([^"]+)"',      # @"multi word name"
        r"@'([^']+)'",      # @'multi word name'
        r'@(\S+)',           # @singleword
    ]

    def parse(self, text: str) -> ParsedQuery:
        mentions = self._extract_mentions(text)
        intent = self._classify_intent(text)
        remaining = self._strip_mentions(text)
        return ParsedQuery(
            original_text=text,
            intent=intent,
            mentions=mentions,
            remaining_text=remaining.strip()
        )

    def _extract_mentions(self, text: str) -> List[str]:
        mentions = []
        for pattern in self.MENTION_PATTERNS:
            for match in re.finditer(pattern, text):
                mentions.append(match.group(1))
        return mentions

    def _classify_intent(self, text: str) -> Intent:
        lower = text.lower()
        if any(w in lower for w in ["summarize", "summary", "tldr", "overview", "describe"]):
            return Intent.SUMMARIZE
        elif "?" in text or any(w in lower for w in ["what", "how", "why", "when", "who", "which"]):
            return Intent.QUESTION
        return Intent.GENERAL

    def _strip_mentions(self, text: str) -> str:
        result = text
        for pattern in self.MENTION_PATTERNS:
            result = re.sub(pattern, "", result)
        return result.strip()
