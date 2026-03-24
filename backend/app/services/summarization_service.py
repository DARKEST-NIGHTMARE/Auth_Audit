"""
Backward-compatible shim for the modularized summarization service.
The core logic has been moved to the `app.services.summarization` package.
"""
from app.services.summarization import SummarizationPipeline, summarization_pipeline

# Re-export key components if they were imported elsewhere individually
from app.services.summarization.document_processor import DocumentType
from app.services.summarization.query_parser import Intent

__all__ = ["SummarizationPipeline", "summarization_pipeline", "DocumentType", "Intent"]
