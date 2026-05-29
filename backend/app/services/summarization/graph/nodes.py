"""
Node functions for the LangGraph summarization agent.
Each node receives GraphState and returns a partial state update dict.

Architectural rule: OCR, ingestion, embedding, and DB storage stay as
services. Nodes only orchestrate reasoning — they call tools, not services.
"""
from __future__ import annotations
import json
import re
import asyncio
import logging
from typing import Dict, Any, List, Optional

from .state import GraphState
from .budget import token_budget, provider_governor
from .cache import query_cache
from .prompts import (
    GENERAL_SYSTEM, LEGAL_SYSTEM, RESEARCH_SYSTEM, COMPRESSION_SYSTEM,
    CLASSIFY_PROMPT, COMPRESS_PROMPT, GENERAL_SUMMARY_PROMPT,
    LEGAL_SUMMARY_PROMPT, FOLDER_SYNTHESIS_PROMPT, QUESTION_PROMPT,
    DECOMPOSE_QUERY_PROMPT, RESEARCH_SYNTHESIS_PROMPT,
    LEGAL_METADATA_PROMPT, ACTION_INTENT_PROMPT,
    SELF_CORRECTION_PROMPT, JSON_FORMAT,
)
from .tools import search_documents, get_file_chunks, save_to_drive

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _parse_llm_json(text: str) -> Optional[Dict]:
    """Robustly extract JSON from LLM output."""
    if not text:
        return None
    try:
        clean = re.sub(r'```(?:json)?\s*', '', text)
        clean = re.sub(r'\s*```', '', clean).strip()
        start, end = clean.find('{'), clean.rfind('}')
        if start != -1 and end != -1:
            data = json.loads(clean[start:end + 1])
            if "summary" in data:
                return {
                    "summary": str(data["summary"]),
                    "suggested_questions": data.get("suggested_questions", []),
                }
    except Exception:
        pass
    return None


def _compute_confidence(state: GraphState) -> float:
    """
    Estimate output quality 0.0–1.0 based on:
    - Whether self-correction was needed
    - Context truncation
    - Provider fallback
    - Summary length
    """
    score = 1.0
    if state.get("retry_count", 0) > 0:
        score -= 0.2 * state["retry_count"]
    if state.get("context_truncated"):
        score -= 0.1
    if state.get("fallback_triggered"):
        score -= 0.15
    parsed = state.get("parsed_result") or {}
    summary_len = len(parsed.get("summary", ""))
    if summary_len < 100:
        score -= 0.2
    return max(0.0, round(score, 2))


# ── Node 1: Cache Check ──────────────────────────────────────────────────────

async def check_cache(state: GraphState) -> Dict:
    """Check if we already have this answer cached."""
    resolved = state.get("resolved_items", [])
    file_ids = [i["id"] for i in resolved if i.get("type") == "file"]
    folder_ids = [i["id"] for i in resolved if i.get("type") == "folder"]
    key = query_cache.make_key(state.get("query", ""), file_ids, folder_ids)

    cached = await query_cache.get_summary(key)
    if cached:
        logger.info(f"Graph: Cache HIT for query: {state.get('query', '')[:50]}")
        return {"cache_hit": True, "cache_key": key, "final_result": cached}

    return {"cache_hit": False, "cache_key": key}


# ── Node 2: Document Classifier ─────────────────────────────────────────────

async def classify_document(state: GraphState) -> Dict:
    """
    Classify document as 'legal_case' or 'general_document'.
    Heuristic-first, LLM as fallback — same logic as original pipeline.
    """
    # Try to get text from already-retrieved chunks
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        # Fetch first few chunks from the primary file
        resolved = state.get("resolved_items", [])
        if resolved:
            file_id = resolved[0]["id"]
            chunks = await get_file_chunks(file_id)

    text = " ".join(c["document"] for c in chunks[:5])[:5000]

    # Heuristic first
    legal_keywords = ["appellant", "respondent", "judgment", "bench", "held",
                      "supreme court", "act", "case no", "petitioner", "plaintiff"]
    text_lower = text.lower()
    points = sum(2 for k in legal_keywords if k in text_lower)
    if points >= 6:
        logger.info("Graph: Document classified as legal_case (heuristic).")
        return {"doc_type": "legal_case"}

    # LLM fallback for ambiguous docs
    try:
        prompt = CLASSIFY_PROMPT.format(text=text[:2000])
        raw, provider, _ = await provider_governor.generate(prompt)
        label = raw.strip().lower()
        doc_type = "legal_case" if "legal_case" in label else "general_document"
        logger.info(f"Graph: Document classified as {doc_type} (LLM/{provider}).")
        return {"doc_type": doc_type}
    except Exception as e:
        logger.warning(f"Graph: Classification failed, defaulting to general. {e}")
        return {"doc_type": "general_document"}


# ── Node 3: Context Retrieval ────────────────────────────────────────────────

async def retrieve_context(state: GraphState) -> Dict:
    """
    Retrieves relevant chunks from ChromaDB, applies token budget,
    and assembles the context_text string.
    """
    from app.core.config import settings

    query = state.get("query", "")
    resolved = state.get("resolved_items", [])
    doc_type = state.get("doc_type", "general_document")

    file_ids = [i["id"] for i in resolved if i.get("type") == "file"]
    folder_ids = [i["id"] for i in resolved if i.get("type") == "folder"]

    # Use multi-query for legal docs (better coverage)
    top_k = 8 if doc_type == "legal_case" else 10
    chunks = await search_documents(query, file_ids=file_ids or None,
                                    folder_ids=folder_ids or None, top_k=top_k)

    if not chunks:
        return {"retrieved_chunks": [], "context_text": "", "source_files": []}

    # Sort by chunk_index for narrative coherence
    chunks.sort(key=lambda c: c.get("chunk_index", 0))

    # Deduplicate
    seen, unique_chunks = set(), []
    for c in chunks:
        key = c["document"][:100]
        if key not in seen:
            seen.add(key)
            unique_chunks.append(c)

    # Enforce a hard maximum to prevent OOM on massive folders
    if len(unique_chunks) > 40:
        logger.warning(f"Graph: Hard truncating {len(unique_chunks)} chunks down to 40.")
        unique_chunks = unique_chunks[:40]

    # Apply token budget
    provider = getattr(settings, "generation_provider", "cerebras")
    context_text, truncated = token_budget.fit_context(
        [c["document"] for c in unique_chunks], provider
    )

    source_files = list(dict.fromkeys(c["file_name"] for c in unique_chunks))
    budget_used = len(context_text) // token_budget.CHARS_PER_TOKEN

    logger.info(f"Graph: Retrieved {len(unique_chunks)} chunks, "
                f"{budget_used} tokens, truncated={truncated}.")

    return {
        "retrieved_chunks": unique_chunks,
        "context_text": context_text,
        "source_files": source_files,
        "token_budget_used": budget_used,
        "context_truncated": truncated,
    }


# ── Node 4: Chunk Compression ────────────────────────────────────────────────

async def compress_context(state: GraphState) -> Dict:
    """
    Compresses chunks when context exceeds 65% of the token budget.
    Uses fast Cerebras call to extract key sentences from each chunk.
    """
    from app.core.config import settings
    provider = getattr(settings, "generation_provider", "cerebras")
    context = state.get("context_text", "")

    if not token_budget.needs_compression(context, provider):
        return {}  # No-op

    logger.info("Graph: Context too large — compressing chunks.")
    chunks = state.get("retrieved_chunks", [])
    compressed_chunks = []

    for chunk in chunks:
        try:
            prompt = COMPRESS_PROMPT.format(text=chunk["document"])
            compressed_text, used_provider, _ = await provider_governor.generate(
                prompt, COMPRESSION_SYSTEM
            )
            if used_provider == "local":
                compressed_chunks.append(chunk)
            else:
                compressed_chunks.append({**chunk, "document": compressed_text})
        except Exception:
            compressed_chunks.append(chunk)  # Keep original on failure

    new_context, truncated = token_budget.fit_context(
        [c["document"] for c in compressed_chunks], provider
    )

    logger.info(f"Graph: Compressed context from {len(context)} to {len(new_context)} chars.")
    return {
        "retrieved_chunks": compressed_chunks,
        "context_text": new_context,
        "context_truncated": truncated,
    }


# ── Node 5: Generate Summary ─────────────────────────────────────────────────

async def generate_summary(state: GraphState) -> Dict:
    """
    Generates the summary/answer using the ProviderGovernor.
    Builds the prompt based on doc_type and intent.
    """
    doc_type = state.get("doc_type", "general_document")
    intent = state.get("intent", "summarize")
    context_text = state.get("context_text", "")
    source_files = state.get("source_files", [])
    resolved = state.get("resolved_items", [])
    file_name = resolved[0]["name"] if resolved else "document"
    files_str = ", ".join(source_files) if source_files else file_name
    conversation_history = state.get("conversation_history", "")

    if intent == "question" or intent == "general":
        prompt = QUESTION_PROMPT.format(
            context_text=context_text,
            file_names=files_str,
            question=state.get("query", ""),
            conversation_history=conversation_history,
            json_format=JSON_FORMAT,
        )
        system = GENERAL_SYSTEM
    elif doc_type == "legal_case":
        prompt = LEGAL_SUMMARY_PROMPT.format(
            context_text=context_text,
            json_format=JSON_FORMAT,
        )
        system = LEGAL_SYSTEM
    else:
        prompt = GENERAL_SUMMARY_PROMPT.format(
            file_name=file_name,
            context_text=context_text,
            conversation_history=conversation_history,
            json_format=JSON_FORMAT,
        )
        system = GENERAL_SYSTEM


    raw, provider, fallback = await provider_governor.generate(
        prompt, system,
        context_for_fallback=context_text,
        file_name=file_name,
    )

    logger.info(f"Graph: Generated via {provider} (fallback={fallback}).")
    return {
        "draft_answer": raw,
        "provider_used": provider,
        "fallback_triggered": fallback,
    }


# ── Node 6: Validate Output ──────────────────────────────────────────────────

async def validate_output(state: GraphState) -> Dict:
    """
    Validates the draft_answer:
    1. Must be parseable as JSON with a 'summary' key.
    2. Summary must be > 50 characters.
    3. Summary must not be empty or just an error message.
    """
    draft = state.get("draft_answer", "")
    errors = []

    parsed = _parse_llm_json(draft)
    if not parsed:
        errors.append("Output is not valid JSON with a 'summary' key.")
    else:
        summary = parsed.get("summary", "")
        if len(summary) < 50:
            errors.append(f"Summary too short ({len(summary)} chars). Must be >50.")
        if summary.lower().startswith("notice: ai generation paused") and state.get("provider_used") != "local":
            errors.append("Summary contains local fallback text despite live provider.")

    retry_count = state.get("retry_count", 0)

    if errors:
        logger.warning(f"Graph: Validation FAILED (attempt {retry_count + 1}): {errors}")
        return {
            "validation_errors": errors,
            "retry_count": retry_count + 1,
            "parsed_result": None,
        }

    logger.info("Graph: Validation PASSED.")
    return {
        "validation_errors": [],
        "parsed_result": parsed,
    }


# ── Node 7: Self-Correct ─────────────────────────────────────────────────────

async def self_correct(state: GraphState) -> Dict:
    """
    Re-prompts the LLM with the validation errors and original context,
    asking it to fix the specific issues.
    """
    errors = state.get("validation_errors", [])
    context_text = state.get("context_text", "")
    logger.info(f"Graph: Self-correcting. Errors: {errors}")

    prompt = SELF_CORRECTION_PROMPT.format(
        errors="\n".join(f"- {e}" for e in errors),
        context_text=context_text[:4000],  # Keep correction prompt short
    )

    raw, provider, fallback = await provider_governor.generate(
        prompt, GENERAL_SYSTEM,
        context_for_fallback=context_text,
    )

    return {
        "draft_answer": raw,
        "provider_used": provider,
        "fallback_triggered": fallback,
    }


# ── Node 8: Local Fallback ───────────────────────────────────────────────────

async def local_fallback(state: GraphState) -> Dict:
    """
    Final safety net after max retries exceeded.
    Returns an extractive summary from the raw context.
    """
    logger.warning("Graph: Max retries exceeded. Using local extractive fallback.")
    context = state.get("context_text", "")
    resolved = state.get("resolved_items", [])
    file_name = resolved[0]["name"] if resolved else "document"

    snippet = context[:1500].strip() if context else "(No content available)"
    fallback_summary = (
        f"**Notice: AI Self-Correction Exhausted.**\n\n"
        f"**Document Excerpt ({file_name}):**\n> {snippet}...\n\n"
        f"*The AI was unable to generate a structured summary after 3 attempts. "
        f"The raw excerpt is shown above.*"
    )

    parsed = {"summary": fallback_summary, "suggested_questions": []}
    return {
        "parsed_result": parsed,
        "validation_errors": [],
        "provider_used": "local",
        "fallback_triggered": True,
    }


# ── Node 9: Hierarchical Folder Summarizer ───────────────────────────────────

async def hierarchical_folder_summarizer(state: GraphState) -> Dict:
    """
    Phase 1: Summarize each file independently (uses cache).
    Phase 2: Synthesize a folder-level executive summary.
    """
    from app.core.config import settings
    resolved = state.get("resolved_items", [])
    folder_id = resolved[0]["id"] if resolved else None
    folder_name = resolved[0]["name"] if resolved else "Folder"

    if not folder_id:
        return {"context_text": "", "source_files": [], "doc_type": "general_document"}

    # Get all files in the folder from ChromaDB
    from app.services.summarization.pipeline import summarization_pipeline
    vs = summarization_pipeline.vector_store
    try:
        raw = vs.collection.get(where={"folder_id": folder_id},
                                include=["metadatas"], limit=500)
        file_map: Dict[str, str] = {}
        for meta in (raw.get("metadatas") or []):
            fid = meta.get("file_id")
            fname = meta.get("file_name")
            if fid and fname:
                file_map[fid] = fname
    except Exception as e:
        logger.error(f"Graph: Folder file listing failed: {e}")
        file_map = {}

    if not file_map:
        return {"context_text": "No indexed content found for this folder.",
                "source_files": [], "doc_type": "general_document"}

    # Phase 1: Per-file summaries (concurrency limited to 3)
    sem = asyncio.Semaphore(3)
    file_summaries: Dict[str, str] = {}

    async def _summarize_one(fid: str, fname: str):
        async with sem:
            chunks = await get_file_chunks(fid)
            if not chunks:
                return
            provider = getattr(settings, "generation_provider", "cerebras")
            ctx, _ = token_budget.fit_context(
                [c["document"] for c in chunks], provider,
                reserved_prompt_tokens=800
            )
            prompt = GENERAL_SUMMARY_PROMPT.format(
                file_name=fname, context_text=ctx, json_format=JSON_FORMAT
            )
            raw, _, _ = await provider_governor.generate(prompt, GENERAL_SYSTEM,
                                                          context_for_fallback=ctx,
                                                          file_name=fname)
            parsed = _parse_llm_json(raw)
            if parsed:
                file_summaries[fname] = parsed["summary"]

    await asyncio.gather(*[_summarize_one(fid, fname) for fid, fname in file_map.items()])

    if not file_summaries:
        return {"context_text": "Could not summarize files in folder.",
                "source_files": list(file_map.values()), "doc_type": "general_document"}

    # Phase 2: Build synthesis context
    summaries_text = "\n\n---\n\n".join(
        f"**{name}**:\n{summary}" for name, summary in file_summaries.items()
    )

    logger.info(f"Graph: Folder summarizer Phase 1 complete. "
                f"{len(file_summaries)}/{len(file_map)} files summarized.")

    # Store for synthesis in generate_summary node
    return {
        "folder_files": file_map,
        "file_summaries": file_summaries,
        "context_text": summaries_text[:16000],  # Generous limit for synthesis
        "source_files": list(file_summaries.keys()),
        "doc_type": "general_document",
        "intent": "summarize",  # Ensure generate_summary uses folder prompt
    }


async def folder_synthesis(state: GraphState) -> Dict:
    """Phase 2 of folder summarization: final executive synthesis."""
    file_summaries = state.get("file_summaries", {})
    folder_name = (state.get("resolved_items") or [{}])[0].get("name", "Folder")
    summaries_text = "\n\n---\n\n".join(
        f"**{name}**:\n{summary}" for name, summary in file_summaries.items()
    )

    prompt = FOLDER_SYNTHESIS_PROMPT.format(
        folder_name=folder_name,
        num_files=len(file_summaries),
        file_summaries_text=summaries_text,
        json_format=JSON_FORMAT,
    )
    raw, provider, fallback = await provider_governor.generate(
        prompt, GENERAL_SYSTEM,
        context_for_fallback=summaries_text[:1000],
        file_name=folder_name,
    )

    logger.info(f"Graph: Folder synthesis complete via {provider}.")
    return {
        "draft_answer": raw,
        "provider_used": provider,
        "fallback_triggered": fallback,
    }


# ── Node 10: Multi-Step Researcher ───────────────────────────────────────────

async def decompose_query(state: GraphState) -> Dict:
    """Breaks a complex research query into 2-4 specific sub-questions."""
    query = state.get("query", "")
    prompt = DECOMPOSE_QUERY_PROMPT.format(query=query)

    try:
        raw, _, _ = await provider_governor.generate(prompt)
        raw = raw.strip()
        # Extract JSON array
        start, end = raw.find('['), raw.rfind(']')
        if start != -1 and end != -1:
            sub_queries = json.loads(raw[start:end + 1])
            if isinstance(sub_queries, list):
                sub_queries = [str(q) for q in sub_queries[:4]]
                logger.info(f"Graph: Decomposed into {len(sub_queries)} sub-queries.")
                return {"search_queries": sub_queries, "research_steps": [], "research_iteration": 0}
    except Exception as e:
        logger.warning(f"Graph: Query decomposition failed: {e}. Using original query.")

    return {"search_queries": [query], "research_steps": [], "research_iteration": 0}


async def research_step(state: GraphState) -> Dict:
    """
    Executes one research step: takes the next sub-query,
    searches ChromaDB, and logs the findings.
    """
    sub_queries = state.get("search_queries", [])
    steps = state.get("research_steps", [])
    iteration = state.get("research_iteration", 0)

    if iteration >= len(sub_queries):
        return {"research_iteration": iteration}

    current_query = sub_queries[iteration]
    resolved = state.get("resolved_items", [])
    file_ids = [i["id"] for i in resolved if i.get("type") == "file"]
    folder_ids = [i["id"] for i in resolved if i.get("type") == "folder"]

    chunks = await search_documents(current_query, file_ids=file_ids or None,
                                    folder_ids=folder_ids or None, top_k=5)

    step_log = {
        "query": current_query,
        "chunks_found": len(chunks),
        "source_files": list({c["file_name"] for c in chunks}),
        "top_excerpt": chunks[0]["document"][:300] if chunks else "",
        "chunks": chunks,
    }
    steps = steps + [step_log]
    logger.info(f"Graph: Research step {iteration + 1}: '{current_query}' → {len(chunks)} chunks.")

    return {
        "research_steps": steps,
        "research_iteration": iteration + 1,
    }


def should_continue_research(state: GraphState) -> str:
    """Conditional edge: continue research loop or synthesize."""
    iteration = state.get("research_iteration", 0)
    sub_queries = state.get("search_queries", [])
    max_steps = 4  # Hard cap

    if iteration < len(sub_queries) and iteration < max_steps:
        return "research_step"
    return "synthesize_research"


async def synthesize_research(state: GraphState) -> Dict:
    """Synthesizes all research step findings into a final report."""
    steps = state.get("research_steps", [])
    query = state.get("query", "")

    findings_text = ""
    for i, step in enumerate(steps, 1):
        findings_text += f"### Search {i}: {step['query']}\n"
        findings_text += f"**Sources**: {', '.join(step['source_files'])}\n"
        for chunk in step.get("chunks", [])[:3]:
            findings_text += f"\n[{chunk['file_name']}]: {chunk['document'][:400]}\n"
        findings_text += "\n"

    from app.core.config import settings
    provider = getattr(settings, "generation_provider", "cerebras")
    ctx, _ = token_budget.fit_context([findings_text], provider)

    prompt = RESEARCH_SYNTHESIS_PROMPT.format(
        query=query, research_findings=ctx, json_format=JSON_FORMAT
    )
    raw, prov, fallback = await provider_governor.generate(
        prompt, RESEARCH_SYSTEM,
        context_for_fallback=findings_text[:1000],
    )

    all_sources = list({f for step in steps for f in step.get("source_files", [])})
    logger.info(f"Graph: Research synthesis complete. Sources: {all_sources}")

    return {
        "draft_answer": raw,
        "provider_used": prov,
        "fallback_triggered": fallback,
        "source_files": all_sources,
        "context_text": ctx,
    }


# ── Node 11: Action Executor ─────────────────────────────────────────────────

async def parse_action_intent(state: GraphState) -> Dict:
    """Determines what Drive action to perform."""
    prompt = ACTION_INTENT_PROMPT.format(query=state.get("query", ""))
    try:
        raw, _, _ = await provider_governor.generate(prompt)
        start, end = raw.find('{'), raw.rfind('}')
        if start != -1:
            data = json.loads(raw[start:end + 1])
            return {
                "tool_name": data.get("action", "unknown"),
                "tool_args": {
                    "filename": data.get("filename") or "AI_Summary.txt",
                    "parent_folder": data.get("parent_folder"),
                },
            }
    except Exception as e:
        logger.warning(f"Graph: Action intent parsing failed: {e}")
    return {"tool_name": "unknown", "tool_args": {}}


async def execute_tool(state: GraphState) -> Dict:
    """
    Executes the parsed Drive action — only runs after human approval.
    When the graph is interrupted by interrupt_before=["execute_tool"],
    it resumes here after approve_action endpoint sets human_approved=True.
    """
    # Gate: must be explicitly approved
    if not state.get("human_approved"):
        logger.warning("Graph: execute_tool reached without human_approved=True. Skipping.")
        return {
            "tool_results": [{"status": "skipped", "reason": "Awaiting human approval."}]
        }

    tool_name = state.get("tool_name", "unknown")
    tool_args = state.get("tool_args", {})
    parsed = state.get("parsed_result", {})
    access_token = state.get("access_token", "")
    refresh_token = state.get("refresh_token")

    if tool_name == "unknown":
        return {"tool_results": [{"status": "error", "error": "Unknown action"}]}

    content = parsed.get("summary", "") if parsed else ""
    if not content:
        return {"tool_results": [{"status": "error", "error": "No summary to save"}]}

    filename = tool_args.get("filename", "AI_Summary.txt")
    result = await save_to_drive(
        content=content,
        filename=filename,
        access_token=access_token,
        refresh_token=refresh_token,
    )

    logger.info(f"Graph: Tool execution complete: {result}")
    return {"tool_results": [result]}



# ── Node 12: Finalize Output ──────────────────────────────────────────────────

async def finalize_output(state: GraphState) -> Dict:
    """
    Packages the final result dict and writes to cache.
    """
    # If cache hit, final_result is already set — nothing to do
    if state.get("cache_hit") and state.get("final_result"):
        return {}

    parsed = state.get("parsed_result", {})
    source_files = state.get("source_files", [])
    doc_type = state.get("doc_type", "general_document")
    intent = state.get("intent", "summarize")
    tool_results = state.get("tool_results", [])
    confidence = _compute_confidence(state)

    result = {
        "type": doc_type,
        "answer": json.dumps(parsed),
        "sources": [{"file": f} for f in source_files],
        "intent": intent,
        "confidence_score": confidence,
        "provider_used": state.get("provider_used", "unknown"),
        "context_truncated": state.get("context_truncated", False),
        "fallback_triggered": state.get("fallback_triggered", False),
        "tool_results": tool_results,
    }

    # Write to cache (skip for actions)
    cache_key = state.get("cache_key", "")
    if cache_key and not tool_results:
        await query_cache.set_summary(cache_key, result)

    logger.info(f"Graph: Finalized. confidence={confidence}, provider={result['provider_used']}")
    return {"final_result": result, "confidence_score": confidence}
