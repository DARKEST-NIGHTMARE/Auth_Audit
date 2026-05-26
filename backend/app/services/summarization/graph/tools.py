"""
Tool wrappers for LangGraph nodes.
Exposes services (ChromaDB, Drive) as callable async functions.
Services themselves are NOT modified — this is purely an interface layer.
"""
from __future__ import annotations
import logging
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


# ── ChromaDB Tools ──────────────────────────────────────────────────────────

async def search_documents(
    query: str,
    file_ids: Optional[List[str]] = None,
    folder_ids: Optional[List[str]] = None,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """
    Semantic search in ChromaDB. Returns list of chunk dicts.
    Wraps VectorStoreManager.query() — service unchanged.
    """
    from app.services.summarization.pipeline import summarization_pipeline
    vs = summarization_pipeline.vector_store
    results = vs.query(query, file_ids=file_ids, folder_id=folder_ids, top_k=top_k)
    chunks = []
    if results and results.get("documents") and results["documents"][0]:
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            chunks.append({
                "document": doc,
                "file_name": meta.get("file_name", "unknown"),
                "file_id": meta.get("file_id", "unknown"),
                "chunk_index": meta.get("chunk_index", 0),
                "folder_id": meta.get("folder_id"),
            })
    return chunks


async def get_file_chunks(file_id: str) -> List[Dict[str, Any]]:
    """
    Get all chunks for a specific file, ordered by chunk index.
    Wraps VectorStoreManager.get_all_chunks_for_file().
    """
    from app.services.summarization.pipeline import summarization_pipeline
    vs = summarization_pipeline.vector_store
    results = vs.get_all_chunks_for_file(file_id)
    chunks = []
    if results and results.get("documents"):
        for doc, meta in zip(results["documents"], results.get("metadatas", [])):
            chunks.append({
                "document": doc,
                "file_name": meta.get("file_name", "unknown"),
                "file_id": file_id,
                "chunk_index": meta.get("chunk_index", 0),
            })
    return chunks


async def ingest_file_tool(
    file_id: str,
    file_name: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    folder_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download + index a file from Google Drive into ChromaDB.
    Wraps pipeline.ingest_file() — service unchanged.
    """
    from app.services.summarization.pipeline import summarization_pipeline
    return await summarization_pipeline.ingest_file(
        file_id=file_id,
        file_name=file_name,
        access_token=access_token,
        refresh_token=refresh_token,
        folder_id=folder_id,
    )


# ── Google Drive Tools ──────────────────────────────────────────────────────

async def save_to_drive(
    content: str,
    filename: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new text file in the user's Google Drive.
    Wraps GoogleDriveService.create_file() — service unchanged.
    """
    try:
        from app.services.google_drive_service import drive_service
        result = drive_service.create_file(
            name=filename,
            content=content,
            access_token=access_token,
            refresh_token=refresh_token,
            parent_id=parent_folder_id,
        )
        logger.info(f"Saved to Drive: {filename} (ID: {result.get('id')})")
        return {"status": "success", "file_id": result.get("id"), "file_name": filename}
    except Exception as e:
        logger.error(f"Drive save failed: {e}")
        return {"status": "error", "error": str(e)}


async def upload_report(
    content: bytes,
    filename: str,
    mime_type: str,
    access_token: str,
    refresh_token: Optional[str] = None,
    parent_folder_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Upload a binary file (PDF, DOCX) to the user's Google Drive.
    Wraps GoogleDriveService.upload_file() — service unchanged.
    """
    try:
        from app.services.google_drive_service import drive_service
        result = drive_service.upload_file(
            file_content=content,
            filename=filename,
            mime_type=mime_type,
            access_token=access_token,
            refresh_token=refresh_token,
            parent_id=parent_folder_id,
        )
        logger.info(f"Uploaded report: {filename} (ID: {result.get('id')})")
        return {"status": "success", "file_id": result.get("id"), "file_name": filename}
    except Exception as e:
        logger.error(f"Drive upload failed: {e}")
        return {"status": "error", "error": str(e)}
