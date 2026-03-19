"""
Summarization Router — API endpoints for @file/@folder summarization.
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional, List

from app.core.database import get_db
from app.models import User
from app.core.dependencies import get_current_db_user
from app.services.summarization_service import summarization_pipeline
from app.services.google_drive_service import drive_service
from app.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/summarize", tags=["summarization"])


# ─── Request/Response Models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    text: str  # e.g. "summarize @FolderName"

class QueryResponse(BaseModel):
    answer: str
    sources: list
    intent: str = "summarize"

class IngestResponse(BaseModel):
    status: str
    message: str = ""
    details: Optional[dict] = None

class AutocompleteItem(BaseModel):
    id: str
    name: str
    type: str  # "file" or "folder"


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def handle_query(
    request: QueryRequest,
    current_user: User = Depends(get_current_db_user)
):
    """
    Main query endpoint.
    Accepts natural language with @mentions.
    Example: "summarize @AuthAuditWorkspace"
    """
    if not current_user.google_drive_access_token:
        raise HTTPException(status_code=400, detail="Google Drive not connected. Please connect first.")

    try:
        # Get user's files/folders for @mention resolution
        files_and_folders = drive_service.list_all_files(
            current_user.google_drive_access_token,
            current_user.google_drive_refresh_token
        )

        # Run the pipeline
        result = await summarization_pipeline.query(
            text=request.text,
            folders=files_and_folders,
            access_token=current_user.google_drive_access_token,
            refresh_token=current_user.google_drive_refresh_token,
        )

        return QueryResponse(
            answer=result.get("answer", "No response generated."),
            sources=result.get("sources", []),
            intent=result.get("intent", "summarize"),
        )

    except Exception as e:
        logger.error(f"Summarization query error: {e}")
        raise HTTPException(status_code=500, detail=f"Summarization failed: {str(e)}")


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
