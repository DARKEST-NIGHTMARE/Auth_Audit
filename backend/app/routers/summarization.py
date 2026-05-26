"""
Summarization Router — API endpoints for @file/@folder summarization.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List
import json

from app.core.database import get_db
from app.models import User, QueryJob, QueryJobStatus
from app.core.dependencies import get_current_db_user
from app.services.summarization.pipeline import summarization_pipeline
from app.core.task_manager import task_manager
from app.services.google_drive_service import drive_service
from app.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/summarize", tags=["summarization"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    text: str  # e.g. "summarize @FolderName"

class QueryJobResponse(BaseModel):
    job_id: str
    status: str
    message: str

class QueryResultResponse(BaseModel):
    job_id: str
    status: str
    answer: Optional[str] = None
    sources: Optional[list] = None
    error: Optional[str] = None

class ChatHistoryItem(BaseModel):
    job_id: str
    query: str
    status: str
    answer: Optional[str] = None
    sources: Optional[list] = None
    created_at: str

class IngestResponse(BaseModel):
    status: str
    message: str = ""
    details: Optional[dict] = None

class AutocompleteItem(BaseModel):
    id: str
    name: str
    type: str  # "file" or "folder"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryJobResponse)
async def handle_query(
    request: QueryRequest,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Async query endpoint.
    Retrieves context, enqueues a job, and returns job_id immediately.
    """
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive not connected.")

    try:
        # 1. Resolve mentions and fetch context chunks (fast part)
        files_and_folders = drive_service.list_all_files(
            current_user.google_drive_access_token,
            current_user.google_drive_refresh_token
        )

        context_package = await summarization_pipeline.get_query_context(
            text=request.text,
            folders=files_and_folders,
            access_token=current_user.google_drive_access_token,
            refresh_token=current_user.google_drive_refresh_token,
            user_id=str(current_user.id),
        )

        # 2. Check Cache / Existing completed jobs for SAME user/query
        cache_key = context_package["cache_key"]

        # 3. Create Job in DB
        import uuid
        job_id = str(uuid.uuid4())

        # Enrich context_package with tokens so streaming endpoint can reconstruct state
        context_package["access_token"] = current_user.google_drive_access_token
        context_package["refresh_token"] = current_user.google_drive_refresh_token
        context_package["resolved_items"] = context_package.get("resolved_items", [])

        new_job = QueryJob(
            id=job_id,
            user_id=current_user.id,
            query=request.text,
            status=QueryJobStatus.PENDING,
            context_data=context_package
        )
        db.add(new_job)
        await db.commit()

        # 4. Enqueue for Worker
        job_payload = {
            "job_id": job_id,
            "user_id": current_user.id,
            "query": context_package["query"],
            "chunks": context_package["chunks"],
            "access_token": current_user.google_drive_access_token,
            "refresh_token": current_user.google_drive_refresh_token,
            "resolved_items": context_package.get("resolved_items", []),
        }
        await task_manager.enqueue_job(job_payload)

        return QueryJobResponse(
            job_id=job_id,
            status="pending",
            message="Your request has been enqueued. Please poll for results."
        )

    except Exception as e:
        logger.error(f"Async query enqueue error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue query: {str(e)}")

@router.get("/result/{job_id}", response_model=QueryResultResponse)
async def get_query_result(
    job_id: str,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db)
):
    """Poll for the result of a specific summarization job."""
    stmt = select(QueryJob).where(QueryJob.id == job_id, QueryJob.user_id == current_user.id)
    res = await db.execute(stmt)
    job = res.scalars().first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    import json
    answer = None
    sources = []
    
    if job.status == QueryJobStatus.COMPLETED and job.result:
        try:
            # result is JSON in DB
            res_data = job.result
            if isinstance(res_data, str):
                res_data = json.loads(res_data)
            
            # The answer might be a stringified JSON (from our previous pipeline implementation)
            answer = res_data.get("answer", "")
            sources = res_data.get("sources", [])
        except Exception as e:
            logger.error(f"Error parsing job result for {job_id}: {e}")
            answer = str(job.result)

    return QueryResultResponse(
        job_id=job_id,
        status=job.status.value,
        answer=answer,
        sources=sources,
        error=job.error
    )


@router.get("/history", response_model=List[ChatHistoryItem])
async def get_chat_history(
    limit: int = 50,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db)
):
    """Fetch the user's recent AI chat history."""
    stmt = select(QueryJob).where(
        QueryJob.user_id == current_user.id
    ).order_by(QueryJob.created_at.asc()).limit(limit)
    res = await db.execute(stmt)
    jobs = res.scalars().all()
    
    history = []
    import json
    for job in jobs:
        answer = None
        sources = []
        if job.status == QueryJobStatus.COMPLETED and job.result:
            try:
                res_data = job.result
                if isinstance(res_data, str):
                    res_data = json.loads(res_data)
                answer = res_data.get("answer", "")
                sources = res_data.get("sources", [])
            except Exception as e:
                answer = str(job.result)
        
        history.append(ChatHistoryItem(
            job_id=job.id,
            query=job.query,
            status=job.status.value,
            answer=answer,
            sources=sources,
            created_at=job.created_at.isoformat() if job.created_at else ""
        ))
    return history


@router.get("/autocomplete")
async def autocomplete_mentions(
    q: str = "",
    current_user: User = Depends(get_current_db_user)
):
    """
    Typeahead for @mentions.
    Returns matching file/folder names from user's Drive.
    """
    if not current_user.google_drive_access_token:
        return []

    try:
        items = drive_service.list_all_files(
            current_user.google_drive_access_token,
            current_user.google_drive_refresh_token
        )

        def get_type(item):
            return "folder" if "folder" in item.get("mimeType", "") else "file"

        if not q:
            return [
                AutocompleteItem(id=f["id"], name=f["name"], type=get_type(f))
                for f in items[:15]
            ]

        # Fuzzy filter
        from rapidfuzz import fuzz
        results = []
        for item in items:
            score = max(
                fuzz.ratio(q.lower(), item["name"].lower()),
                fuzz.partial_ratio(q.lower(), item["name"].lower())
            )
            if score >= 40:
                results.append((score, item))

        results.sort(key=lambda x: x[0], reverse=True)
        return [
            AutocompleteItem(id=f["id"], name=f["name"], type=get_type(f))
            for _, f in results[:10]
        ]

    except Exception as e:
        logger.error(f"Autocomplete error: {e}")
        return []


@router.post("/ingest/{file_id}")
async def ingest_file(
    file_id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_db_user)
):
    """Ingest a specific file into the vector store."""
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive not connected.")

    try:
        result = await summarization_pipeline.ingest_file(
            file_id=file_id,
            file_name="",
            access_token=current_user.google_drive_access_token,
            refresh_token=current_user.google_drive_refresh_token,
        )
        return IngestResponse(
            status=result.get("status", "unknown"),
            message=f"File '{result.get('file', '')}': {result.get('status', '')}",
            details=result,
        )
    except Exception as e:
        logger.error(f"Ingest file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest-folder/{folder_id}")
async def ingest_folder(
    folder_id: str,
    current_user: User = Depends(get_current_db_user)
):
    """Ingest all files in a folder into the vector store."""
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive not connected.")

    try:
        result = await summarization_pipeline.ingest_folder(
            folder_id=folder_id,
            access_token=current_user.google_drive_access_token,
            refresh_token=current_user.google_drive_refresh_token,
        )
        return IngestResponse(
            status=result.get("status", "unknown"),
            message=f"Indexed {result.get('indexed', 0)} of {result.get('total_files', 0)} files",
            details=result,
        )
    except Exception as e:
        logger.error(f"Ingest folder error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def summarization_status(
    current_user: User = Depends(get_current_db_user)
):
    """Check if summarization is available, how many files are indexed, and graph health."""
    from app.core.config import settings

    has_key = bool(settings.gemini_api_key)
    has_drive = bool(current_user.google_drive_access_token)

    indexed_count = 0
    try:
        indexed_ids = summarization_pipeline.vector_store.get_indexed_file_ids()
        indexed_count = len(indexed_ids)
    except Exception:
        pass

    # Graph health check
    graph_status = "unavailable"
    try:
        g = summarization_pipeline._get_graph()
        graph_status = "ready" if g is not None else "unavailable"
    except Exception:
        pass

    # Cache stats
    cache_stats = {}
    try:
        from app.services.summarization.graph.cache import query_cache
        cache_stats = query_cache.stats()
    except Exception:
        pass

    return {
        "available": has_key and has_drive,
        "gemini_configured": has_key,
        "drive_connected": has_drive,
        "indexed_files": indexed_count,
        "langgraph_status": graph_status,
        "cache": cache_stats,
    }


@router.get("/cache/stats")
async def cache_stats(
    current_user: User = Depends(get_current_db_user)
):
    """Inspect the QueryCache health (summary + retrieval entries, TTL settings)."""
    try:
        from app.services.summarization.graph.cache import query_cache
        return {
            "status": "ok",
            "stats": query_cache.stats(),
            "summary_ttl_minutes": 60,
            "retrieval_ttl_minutes": 30,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}


@router.post("/cache/clear")
async def clear_cache(
    current_user: User = Depends(get_current_db_user)
):
    """
    Flush all QueryCache entries.
    Use after bulk re-ingestion or when stale results are suspected.
    """
    try:
        from app.services.summarization.graph.cache import query_cache
        await query_cache.clear_all()
        return {"status": "ok", "message": "Cache cleared successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Conversation Memory Endpoints ──────────────────────────────────────────

@router.get("/memory/history")
async def get_memory_history(
    current_user: User = Depends(get_current_db_user),
):
    """
    Returns the conversation history stored in memory for the current user.
    Shows what documents and queries the AI remembers for follow-up resolution.
    """
    try:
        from app.services.summarization.graph.memory import conversation_memory
        turns = await conversation_memory.get_history(str(current_user.id))
        return {
            "user_id": current_user.id,
            "turn_count": len(turns),
            "turns": [
                {
                    "query": t.query,
                    "resolved_files": [i.get("name") for i in t.resolved_items],
                    "doc_type": t.doc_type,
                    "summary_snippet": t.summary_snippet,
                    "timestamp": t.timestamp.isoformat(),
                }
                for t in turns
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/memory/clear")
async def clear_memory(
    current_user: User = Depends(get_current_db_user),
):
    """
    Clear the conversation memory for the current user.
    Use this to start a fresh session without context from previous documents.
    """
    try:
        from app.services.summarization.graph.memory import conversation_memory
        await conversation_memory.clear_user(str(current_user.id))
        return {"status": "ok", "message": "Conversation memory cleared."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 4: Human-in-the-Loop Approval ────────────────────────────────

@router.post("/approve-action/{job_id}")
async def approve_action(
    job_id: str,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Resume a graph that paused before a Drive write action.
    After calling this, the graph executes execute_tool and finishes.
    """
    from sqlalchemy import update
    from datetime import datetime, timezone

    stmt = select(QueryJob).where(
        QueryJob.id == job_id,
        QueryJob.user_id == current_user.id
    )
    res = await db.execute(stmt)
    job = res.scalars().first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if job.status != QueryJobStatus.AWAITING_APPROVAL:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not awaiting approval (status: {job.status.value})."
        )

    try:
        graph = await summarization_pipeline._get_graph()
        if graph is None:
            raise HTTPException(status_code=503, detail="Graph unavailable.")

        config = {"configurable": {"thread_id": job_id}}

        # Resume graph from the execute_tool interrupt with human_approved=True
        result_state = await graph.ainvoke(
            {"human_approved": True},
            config=config,
        )
        final = result_state.get("final_result", {})

        await db.execute(
            update(QueryJob)
            .where(QueryJob.id == job_id)
            .values(
                status=QueryJobStatus.COMPLETED,
                result=final,
                pending_action=None,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        return {
            "status": "completed",
            "message": "Action approved and executed.",
            "tool_results": final.get("tool_results", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Approve action error for job {job_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reject-action/{job_id}")
async def reject_action(
    job_id: str,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db)
):
    """Cancel a pending Drive action without executing it."""
    from sqlalchemy import update
    from datetime import datetime, timezone

    stmt = select(QueryJob).where(
        QueryJob.id == job_id,
        QueryJob.user_id == current_user.id,
        QueryJob.status == QueryJobStatus.AWAITING_APPROVAL
    )
    res = await db.execute(stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or not awaiting approval.")

    await db.execute(
        update(QueryJob)
        .where(QueryJob.id == job_id)
        .values(
            status=QueryJobStatus.FAILED,
            error="Action rejected by user.",
            pending_action=None,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return {"status": "rejected", "message": "Drive action cancelled."}


# ── Phase 5: Streaming Node Progress (SSE) ──────────────────────────

# Human-readable labels for each graph node
_NODE_LABELS = {
    "check_cache":                    "Checking cache...",
    "classify_document":              "Classifying document type...",
    "retrieve_context":               "Retrieving relevant context...",
    "compress_context":               "Compressing context to fit budget...",
    "generate_summary":               "Generating summary...",
    "validate_output":                "Validating output...",
    "self_correct":                   "Self-correcting (retry)...",
    "local_fallback":                 "Using local fallback...",
    "hierarchical_folder_summarizer": "Summarizing files in folder...",
    "folder_synthesis":               "Synthesizing folder summary...",
    "decompose_query":                "Decomposing research question...",
    "research_step":                  "Running research step...",
    "synthesize_research":            "Synthesizing research findings...",
    "parse_action_intent":            "Parsing action intent...",
    "execute_tool":                   "Executing Drive action...",
    "finalize_output":                "Finalizing output...",
}


@router.get("/stream/{job_id}")
async def stream_job_progress(
    job_id: str,
    current_user: User = Depends(get_current_db_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Server-Sent Events (SSE) endpoint for real-time graph node progress.

    Client usage (JavaScript):
        const evtSource = new EventSource('/api/summarize/stream/{job_id}');
        evtSource.onmessage = (e) => console.log(JSON.parse(e.data));

    Each event is a JSON object:
        {"node": "retrieve_context", "label": "Retrieving relevant context...", "done": false}
        {"node": "finalize_output",  "label": "Finalizing output...",           "done": true,
         "result": {...}}
    """
    stmt = select(QueryJob).where(
        QueryJob.id == job_id,
        QueryJob.user_id == current_user.id
    )
    res = await db.execute(stmt)
    job = res.scalars().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    context_data = job.context_data or {}
    access_token = context_data.get("access_token", current_user.google_drive_access_token or "")
    refresh_token = context_data.get("refresh_token", current_user.google_drive_refresh_token)

    async def event_generator():
        try:
            graph = await summarization_pipeline._get_graph()
            if graph is None:
                yield f"data: {json.dumps({'error': 'Graph unavailable', 'done': True})}\n\n"
                return

            # Rebuild state from stored context
            from app.services.summarization.query_parser import QueryParser
            parser = QueryParser()
            parsed = parser.parse(job.query)
            intent_map = {"summarize": "summarize", "question": "question", "general": "question"}
            intent = intent_map.get(parsed.intent.value, "question")

            chunks = context_data.get("chunks", [])
            resolved_items = context_data.get("resolved_items", [])

            state = {
                "query": job.query,
                "intent": intent,
                "resolved_items": resolved_items,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "retrieved_chunks": chunks,
                "retry_count": 0,
                "max_retries": 3,
                "research_steps": [],
                "search_queries": [],
                "research_iteration": 0,
                "tool_results": [],
                "validation_errors": [],
                "token_budget_used": 0,
                "context_truncated": False,
                "fallback_triggered": False,
                "cache_hit": False,
                "messages": [],
            }

            config = {"configurable": {"thread_id": job_id}}

            # Stream node-by-node events
            async for event in graph.astream_events(state, config=config, version="v2"):
                kind = event.get("event", "")
                if kind == "on_chain_start":
                    node = event.get("name", "")
                    if node in _NODE_LABELS:
                        payload = {
                            "node": node,
                            "label": _NODE_LABELS[node],
                            "done": False,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"

                elif kind == "on_chain_end":
                    node = event.get("name", "")
                    output = event.get("data", {}).get("output", {})

                    if node == "finalize_output":
                        final = output.get("final_result") if isinstance(output, dict) else None
                        payload = {
                            "node": node,
                            "label": _NODE_LABELS.get(node, "Done."),
                            "done": True,
                            "result": final,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                        return

                    elif node == "execute_tool" and isinstance(output, dict):
                        if output.get("__awaiting_approval__"):
                            payload = {
                                "node": "awaiting_approval",
                                "label": "Waiting for your approval to save to Drive...",
                                "done": True,
                                "awaiting_approval": True,
                                "pending_action": output.get("pending_action"),
                            }
                            yield f"data: {json.dumps(payload)}\n\n"
                            return

        except Exception as e:
            logger.error(f"SSE stream error for job {job_id}: {e}")
            yield f"data: {json.dumps({'error': str(e), 'done': True})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
