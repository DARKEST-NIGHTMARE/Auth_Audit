"""
Routing logic for the LangGraph summarization agent.
Determines which subgraph/path handles each user request.
"""
from __future__ import annotations
import re
from .state import GraphState


# Keywords that suggest different intents
_ACTION_KEYWORDS = {"save", "create", "upload", "export", "write to drive", "generate report"}
_RESEARCH_KEYWORDS = {"find all", "compare", "across all", "every instance", "correlation",
                      "search for", "look for", "instances of", "occurrences of"}
_SUMMARIZE_KEYWORDS = {"summarize", "summary", "tldr", "overview", "describe", "explain"}
_QUESTION_WORDS = {"what", "how", "why", "when", "who", "which", "where", "tell me"}


def route_query(state: GraphState) -> str:
    """
    Conditional edge function — returns the name of the next node/subgraph.

    Priority order:
    1. Cache hit → skip directly to END
    2. Action intent → tool_executor
    3. Research/cross-file → multi_step_researcher
    4. Summarize folder → hierarchical_folder_summarizer
    5. Summarize file → document_summarizer
    6. Question → question_answerer
    """
    # 1. Cache hit — no processing needed
    if state.get("cache_hit"):
        return "finalize_output"

    query_lower = state.get("query", "").lower()
    resolved = state.get("resolved_items", [])
    intent = state.get("intent", "question")

    # 2. Action detection
    if any(kw in query_lower for kw in _ACTION_KEYWORDS):
        return "action_executor"

    # 3. Research detection: complex cross-file queries or multiple items
    is_complex = any(kw in query_lower for kw in _RESEARCH_KEYWORDS)
    multi_item = len(resolved) > 1
    if is_complex or multi_item:
        return "multi_step_researcher"

    # 4. Folder summarization
    if intent == "summarize" and resolved and resolved[0].get("type") == "folder":
        return "hierarchical_folder_summarizer"

    # 5. File summarization
    if intent == "summarize":
        return "document_summarizer"

    # 6. Default: question answering
    return "question_answerer"


def route_after_validation(state: GraphState) -> str:
    """
    Conditional edge after the validator node.
    Returns next node name based on validation outcome.
    """
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if not errors:
        # Valid output — finalize
        return "finalize_output"
    elif retry_count < max_retries:
        # Still have retries — self-correct
        return "self_correct"
    else:
        # Exhausted retries — use local fallback
        return "local_fallback"


def route_after_cache_check(state: GraphState) -> str:
    """
    Conditional edge after cache check.
    Returns 'finalize_output' on hit, 'route_query' on miss.
    """
    if state.get("cache_hit"):
        return "finalize_output"
    return "route_query"
