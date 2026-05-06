"""
Summarization Router — API endpoints for @file/@folder summarization.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List

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
        )

        # 2. Check Cache / Existing completed jobs for SAME user/query
        cache_key = context_package["cache_key"]
        # (Optimization: We could check the DB for 'completed' jobs with this cache_key)
        
        # 3. Create Job in DB
        import uuid
        job_id = str(uuid.uuid4())
        
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
            "chunks": context_package["chunks"]
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
    """Check if summarization is available and how many files are indexed."""
    from app.core.config import settings

    has_key = bool(settings.gemini_api_key)
    has_drive = bool(current_user.google_drive_access_token)

    indexed_count = 0
    try:
        indexed_ids = summarization_pipeline.vector_store.get_indexed_file_ids()
        indexed_count = len(indexed_ids)
    except Exception:
        pass

    return {
        "available": has_key and has_drive,
        "gemini_configured": has_key,
        "drive_connected": has_drive,
        "indexed_files": indexed_count,
    }
