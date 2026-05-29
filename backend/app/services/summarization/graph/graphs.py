"""
LangGraph graph assembly — Phase 2 (Fixed wiring + specialized routing).
All 5 paths fully wired: document, folder, research, action, question.
"""
from __future__ import annotations
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _master_router(state) -> str:
    """
    Combined router used as the single conditional edge after cache check.
    If cache hit → finalize_output directly.
    Otherwise → route to the appropriate subgraph entry node.
    """
    if state.get("cache_hit"):
        return "finalize_output"

    from .router import route_query
    route = route_query(state)

    node_map = {
        "document_summarizer":             "classify_document",
        "hierarchical_folder_summarizer":  "hierarchical_folder_summarizer",
        "folder_summarizer":               "hierarchical_folder_summarizer",
        "multi_step_researcher":           "decompose_query",
        "action_executor":                 "parse_action_intent",
        "question_answerer":               "retrieve_context",
    }
    return node_map.get(route, "classify_document")


def _route_after_validation(state) -> str:
    """
    Post-validation conditional edge.
    Valid output → check if a tool action is pending, else finalize.
    Invalid with retries left → self_correct.
    Invalid, retries exhausted → local_fallback.
    """
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if not errors:
        # If this was an action request, execute the tool after summary is ready
        tool_name = state.get("tool_name")
        if tool_name and tool_name != "unknown":
            return "execute_tool"
        return "finalize_output"
    elif retry_count < max_retries:
        return "self_correct"
    else:
        return "local_fallback"


def build_main_graph(checkpointer=None):
    """
    Builds and compiles the main summarization StateGraph.

    Graph topology:
        check_cache
            ↓ (conditional: 6 possible paths)
        [classify_document | hierarchical_folder_summarizer |
         decompose_query | parse_action_intent | retrieve_context]
            ↓
        [retrieve_context → compress_context → generate_summary]
         OR [folder: hierarchical_folder_summarizer → folder_synthesis]
         OR [research: decompose_query → research_step(loop) → synthesize_research]
         OR [action: parse_action_intent → classify_document → ...]
            ↓
        validate_output
            ↓ (conditional: self_correct | execute_tool | local_fallback | finalize)
        finalize_output → END
    """
    try:
        from langgraph.graph import StateGraph, END
    except ImportError:
        raise RuntimeError(
            "langgraph not installed. Run: "
            "pip install 'langgraph>=0.3.0' 'langchain-core>=0.3.0'"
        )

    from .state import GraphState
    from .nodes import (
        check_cache,
        classify_document,
        retrieve_context,
        compress_context,
        generate_summary,
        validate_output,
        self_correct,
        local_fallback,
        hierarchical_folder_summarizer,
        folder_synthesis,
        decompose_query,
        research_step,
        should_continue_research,
        synthesize_research,
        parse_action_intent,
        execute_tool,
        finalize_output,
    )

    workflow = StateGraph(GraphState)

    # ── Register all nodes ──────────────────────────────────────────────
    workflow.add_node("check_cache",                    check_cache)
    workflow.add_node("classify_document",              classify_document)
    workflow.add_node("retrieve_context",               retrieve_context)
    workflow.add_node("compress_context",               compress_context)
    workflow.add_node("generate_summary",               generate_summary)
    workflow.add_node("validate_output",                validate_output)
    workflow.add_node("self_correct",                   self_correct)
    workflow.add_node("local_fallback",                 local_fallback)
    workflow.add_node("hierarchical_folder_summarizer", hierarchical_folder_summarizer)
    workflow.add_node("folder_synthesis",               folder_synthesis)
    workflow.add_node("decompose_query",                decompose_query)
    workflow.add_node("research_step",                  research_step)
    workflow.add_node("synthesize_research",            synthesize_research)
    workflow.add_node("parse_action_intent",            parse_action_intent)
    workflow.add_node("execute_tool",                   execute_tool)
    workflow.add_node("finalize_output",                finalize_output)

    # ── Entry point ─────────────────────────────────────────────────────
    workflow.set_entry_point("check_cache")

    # ── Cache check → 6-way conditional routing ─────────────────────────
    workflow.add_conditional_edges(
        "check_cache",
        _master_router,
        {
            "finalize_output":                 "finalize_output",
            "classify_document":               "classify_document",
            "hierarchical_folder_summarizer":  "hierarchical_folder_summarizer",
            "decompose_query":                 "decompose_query",
            "parse_action_intent":             "parse_action_intent",
            "retrieve_context":                "retrieve_context",
        },
    )

    # ── Document summarizer path ────────────────────────────────────────
    # classify → retrieve → compress → generate → validate
    workflow.add_edge("classify_document",  "retrieve_context")
    workflow.add_edge("retrieve_context",   "compress_context")
    workflow.add_edge("compress_context",   "generate_summary")
    workflow.add_edge("generate_summary",   "validate_output")

    # ── Folder summarizer path ──────────────────────────────────────────
    # hierarchical_folder_summarizer (per-file phase) → folder_synthesis → validate
    workflow.add_edge("hierarchical_folder_summarizer", "folder_synthesis")
    workflow.add_edge("folder_synthesis",               "validate_output")

    # ── Multi-step research path ────────────────────────────────────────
    # decompose_query → research_step (loop) → synthesize_research → validate
    workflow.add_edge("decompose_query", "research_step")
    workflow.add_conditional_edges(
        "research_step",
        should_continue_research,
        {
            "research_step":      "research_step",
            "synthesize_research": "synthesize_research",
        },
    )
    workflow.add_edge("synthesize_research", "validate_output")

    # ── Action path ─────────────────────────────────────────────────────
    # parse_action_intent → classify_document (to generate summary first)
    # After validation succeeds, _route_after_validation sends to execute_tool
    workflow.add_edge("parse_action_intent", "classify_document")

    # ── Tool execution → finalize ───────────────────────────────────────
    workflow.add_edge("execute_tool", "finalize_output")

    # ── Validation conditional routing ──────────────────────────────────
    workflow.add_conditional_edges(
        "validate_output",
        _route_after_validation,
        {
            "finalize_output": "finalize_output",
            "self_correct":    "self_correct",
            "local_fallback":  "local_fallback",
            "execute_tool":    "execute_tool",
        },
    )

    # ── Self-correction validates the corrected draft directly ─────────────
    workflow.add_edge("self_correct",    "validate_output")
    workflow.add_edge("local_fallback",  "finalize_output")

    # ── Final output → END ──────────────────────────────────────────────
    workflow.add_edge("finalize_output", END)

    logger.info("Graph: Main summarization graph compiled successfully.")
    # interrupt_before=["execute_tool"] pauses the graph before any Drive write.
    # The graph state is persisted by the checkpointer.
    # Resume by calling graph.ainvoke(None, config={"thread_id": job_id}) after approval.
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["execute_tool"],
    )


# ── Singleton ───────────────────────────────────────────────────────────────

_main_graph = None


async def get_main_graph():
    """
    Returns the singleton compiled graph (async to init checkpointer).
    Safe to call multiple times — only compiles once.
    """
    global _main_graph
    if _main_graph is None:
        try:
            from .checkpointer import get_checkpointer
            checkpointer = await get_checkpointer()
        except Exception as e:
            logger.warning(f"Checkpointer init failed: {e}. Graph will run without persistence.")
            checkpointer = None
        _main_graph = build_main_graph(checkpointer=checkpointer)
        logger.info("Graph: Singleton initialized.")
    return _main_graph
