import re
import io
from enum import Enum
from typing import List, Optional
from dataclasses import dataclass, field
from app.logger import get_logger

logger = get_logger(__name__)

class DocumentType(str, Enum):
    LEGAL_CASE = "legal_case"
    GENERAL_DOCUMENT = "general_document"
    UNKNOWN = "unknown"

@dataclass
class Chunk:
    text: str
    file_id: str
    file_name: str
    chunk_index: int
    metadata: dict = field(default_factory=dict)

class DocumentChunker:
    """Splits documents into chunks for embedding and retrieval."""

    DEFAULT_CHUNK_SIZE = 600     # optimized for legal/name retrieval
    DEFAULT_OVERLAP = 100        # optimized for better context

    def chunk_text(self, text: str, file_id: str, file_name: str) -> List[Chunk]:
        """Smart chunking: split by paragraphs, then sliding window if too large."""
        if not text or not text.strip():
            return []

        # Split by paragraphs / double newlines / headings
        sections = re.split(r'\n\s*\n|\n#{1,6}\s', text)
        sections = [s.strip() for s in sections if s.strip()]

        chunks = []
        for section in sections:
            approx_tokens = len(section) // 4
            if approx_tokens <= self.DEFAULT_CHUNK_SIZE:
                chunks.append(section)
            else:
                chunks.extend(self._sliding_window(section))

        return [
            Chunk(text=c, chunk_index=i, file_id=file_id, file_name=file_name)
            for i, c in enumerate(chunks) if c.strip()
        ]

    def _sliding_window(self, text: str) -> List[str]:
        """Fallback sliding window for very large paragraphs."""
        words = text.split()
        chunks = []
        step = self.DEFAULT_CHUNK_SIZE - self.DEFAULT_OVERLAP
        
        for i in range(0, len(words), step):
            chunk = " ".join(words[i : i + self.DEFAULT_CHUNK_SIZE])
            if chunk.strip():
                chunks.append(chunk)
            if i + self.DEFAULT_CHUNK_SIZE >= len(words):
                break
        return chunks


class DocumentExtractor:
    """Extracts raw text from various file formats (PDF, DOCX, TXT)."""

    async def extract_from_bytes(self, content: bytes, mime_type: str, filename: str) -> str:
        """Entry point for extraction based on mime type."""
        try:
            if content.startswith(b"%PDF"):
                return self._extract_pdf(content)
            
            fn_low = filename.lower().strip()
            if "pdf" in mime_type.lower() or fn_low.endswith(".pdf"):
                return self._extract_pdf(content)
            elif "word" in mime_type.lower() or fn_low.endswith((".docx", ".doc")):
                return self._extract_docx(content)
            else:
                return content.decode("utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Extraction failed for {filename}: {e}")
            return ""

    def _extract_pdf(self, content: bytes) -> str:
        import pdfplumber
        text = ""
        try:
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
            return text
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            return ""

    def _extract_docx(self, content: bytes) -> str:
        from docx import Document
        try:
            doc = Document(io.BytesIO(content))
            return "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
            return ""
