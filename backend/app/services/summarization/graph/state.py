"""
GraphState — the single shared state object flowing through every node.
All fields are optional at construction; nodes populate them progressively.
"""
from __future__ import annotations
from typing import TypedDict, List, Optional, Dict, Any, Annotated

try:
    from langgraph.graph.message import add_messages
except ImportError:
    def add_messages(left, right):
        return (left or []) + (right or [])


class GraphState(TypedDict, total=False):
    # ── Input ──────────────────────────────────────────────────────────
    query: str                               # Original user query text
    intent: str                              # "summarize" | "question" | "research" | "action"
    resolved_items: List[Dict[str, Any]]     # [{id, name, type: "file"|"folder"}]
    access_token: str
    refresh_token: Optional[str]

    # ── Cache ───────────────────────────────────────────────────────────
    cache_hit: bool                          # True if served from QueryCache
    cache_key: str                           # MD5 of query + file/folder IDs

    # ── Context ─────────────────────────────────────────────────────────
    doc_type: Optional[str]                  # "legal_case" | "general_document"
    retrieved_chunks: List[Dict[str, Any]]   # [{document, file_name, file_id, chunk_index}]
    context_text: str                        # Assembled, budget-fitted context string
    source_files: List[str]                  # Unique file names involved
    structured_metadata: Optional[Dict]      # {court, year, case_name, parties} for legal

    # ── Token Budget ────────────────────────────────────────────────────
    token_budget_used: int                   # Estimated tokens consumed
    context_truncated: bool                  # True if context was cut by budget

    # ── Research State (multi-hop) ──────────────────────────────────────
    research_steps: List[Dict[str, Any]]     # Log of each research step + results
    search_queries: List[str]                # Sub-queries generated for multi-hop
    research_iteration: int                  # Current research loop count

    # ── Folder Summarization ────────────────────────────────────────────
    folder_files: Optional[Dict[str, str]]   # {file_id: file_name}
    file_summaries: Optional[Dict[str, str]] # {file_name: summary_text}

    # ── Generation ──────────────────────────────────────────────────────
    draft_answer: str                        # Raw LLM output text
    parsed_result: Optional[Dict]            # Parsed {summary, suggested_questions}
    provider_used: str                       # "cerebras" | "gemini" | "local"
    fallback_triggered: bool                 # True if primary provider failed

    # ── Validation & Self-Correction ────────────────────────────────────
    validation_errors: List[str]             # Issues found by validator node
    retry_count: int                         # Self-correction attempt count
    max_retries: int                         # Hard cap (default 3)
    confidence_score: float                  # 0.0-1.0 quality estimate

    # ── Tool Execution ──────────────────────────────────────────────────
    tool_name: Optional[str]                 # Which tool to call
    tool_args: Optional[Dict]               # Arguments for the tool
    tool_results: List[Dict[str, Any]]      # Results from tool calls
    human_approved: Optional[bool]          # For human-in-the-loop actions



    # ── Output ──────────────────────────────────────────────────────────
    final_result: Optional[Dict[str, Any]]  # Final packaged response
    messages: Annotated[list, add_messages] # LangSmith-compatible message log

    # ── Conversation Memory ──────────────────────────────────────────────
    user_id: Optional[str]                  # User identifier for memory lookup
    conversation_history: Optional[str]     # Pre-built history context string for prompt
