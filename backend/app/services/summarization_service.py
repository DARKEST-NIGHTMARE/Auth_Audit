"""
Summarization Service — @File/@Folder Summarization with Gemini AI + ChromaDB

Core components:
- GeminiClient: LLM (gemini-2.0-flash) + embeddings (text-embedding-004)
- DocumentChunker: Text → chunks (sentence-aware, 512 tokens)
- VectorStoreManager: ChromaDB in-process vector store
- QueryParser: Extracts @mentions and intent from user input
- SummarizationPipeline: Orchestrates parse → resolve → retrieve → summarize
"""

import re
import os
import io
import hashlib
import asyncio
from typing import List, Optional
from enum import Enum
from dataclasses import dataclass, field
from rapidfuzz import fuzz

class DocumentType(str, Enum):
    LEGAL_CASE = "legal_case"
    GENERAL_DOCUMENT = "general_document"
    UNKNOWN = "unknown"

from app.core.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

# ─── Gemini Client ────────────────────────────────────────────────────────────

class GeminiClient:
    """Wraps Google Gemini API for text generation and embeddings."""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from google import genai
            if not settings.gemini_api_key:
                raise RuntimeError("GEMINI_API_KEY not set in .env")
            self._client = genai.Client(api_key=settings.gemini_api_key)
        return self._client

    def generate(self, prompt: str, system_instruction: str = None) -> str:
        """Generate text using Gemini."""
        try:
            config = {}
            if system_instruction:
                from google.genai import types
                config = types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                    max_output_tokens=4096,
                )
            
            response = self.client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=config if config else None,
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini generation error: {e}")
            raise

    def embed(self, text: str) -> List[float]:
        """Generate a single embedding via REST fallback."""
        import requests
        model_name = "models/embedding-001"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:embedContent?key={settings.gemini_api_key}"
        try:
            payload = {
                "model": model_name,
                "content": {"parts": [{"text": text}]}
            }
            res = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
            if res.status_code == 200:
                return res.json()["embedding"]["values"]
            else:
                logger.error(f"Gemini embed HTTP error: {res.text}")
                return [0.0] * 768
        except Exception as e:
            logger.error(f"Gemini embed exception: {e}")
            return [0.0] * 768

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts using batchEmbedContents REST API."""
        import requests
        import time
        if not texts:
            return []

        all_embeddings = []
        model_name = "models/embedding-001"
        url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:batchEmbedContents?key={settings.gemini_api_key}"
        
        # Batch size limit for Gemini is 100
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            payload = {
                "requests": [
                    {
                        "model": model_name,
                        "content": {"parts": [{"text": txt}]}
                    } for txt in batch_texts
                ]
            }
            
            try:
                # Add a tiny 0.5s baseline pause between batches
                if i > 0:
                    time.sleep(0.5)

                # Retry loop for 429s
                max_retries = 3
                for retry in range(max_retries):
                    res = requests.post(url, json=payload, headers={"Content-Type": "application/json"})
                    if res.status_code == 200:
                        batch_res = res.json().get("embeddings", [])
                        all_embeddings.extend([e["values"] for e in batch_res])
                        break
                    elif res.status_code == 429:
                        wait_time = (retry + 1) * 2
                        logger.warning(f"Quota exceeded (429). Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        if retry == max_retries - 1:
                            logger.error("Max retries reached for 429. Filling with zeros.")
                            all_embeddings.extend([[0.0] * 768] * len(batch_texts))
                    else:
                        logger.error(f"Gemini batch embed HTTP error: {res.text}")
                        all_embeddings.extend([[0.0] * 768] * len(batch_texts))
                        break
            except Exception as e:
                logger.error(f"Gemini batch embed exception: {e}")
                all_embeddings.extend([[0.0] * 768] * len(batch_texts))
                
        return all_embeddings


# ─── Document Chunker ─────────────────────────────────────────────────────────

@dataclass
class Chunk:
    text: str
    chunk_index: int
    file_id: str
    file_name: str
    metadata: dict = field(default_factory=dict)


class DocumentChunker:
    """Splits documents into chunks for embedding and retrieval."""

    DEFAULT_CHUNK_SIZE = 1000    # approx tokens (chars / 4) - Increased for legal context
    DEFAULT_OVERLAP = 200        # overlap in approx tokens - Increased for better continuity

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
        """Token-approximate sliding window respecting sentence boundaries."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks = []
        current = []
        current_len = 0
        char_limit = self.DEFAULT_CHUNK_SIZE * 4  # approx chars
        overlap_limit = self.DEFAULT_OVERLAP * 4

        for sent in sentences:
            sent_len = len(sent)
            if current_len + sent_len > char_limit and current:
                chunks.append(" ".join(current))
                # Keep overlap
                overlap_chars = 0
                start = len(current)
                for j in range(len(current) - 1, -1, -1):
                    overlap_chars += len(current[j])
                    if overlap_chars >= overlap_limit:
                        start = j
                        break
                current = current[start:]
                current_len = sum(len(s) for s in current)
            current.append(sent)
            current_len += sent_len

        if current:
            chunks.append(" ".join(current))
        return chunks


# ─── Text Extractors ──────────────────────────────────────────────────────────

class TextExtractor:
    """Extracts text from various file types."""

    def extract_from_bytes(self, content: bytes, mime_type: str, filename: str = "") -> str:
        """Route to the correct extractor based on MIME type."""
        mime_lower = mime_type.lower() if mime_type else ""
        filename_lower = filename.lower()

        # Skip images and known binaries
        if "image/" in mime_lower or any(ext in filename_lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"]):
            return ""
        if any(ext in filename_lower for ext in [".exe", ".zip", ".tar", ".gz", ".bin", ".iso"]):
            return ""

        if "pdf" in mime_lower:
            return self._extract_pdf(content)
        elif "wordprocessingml" in mime_lower or "docx" in (filename.split('.')[-1:] or [""]):
            return self._extract_docx(content)
        elif "text" in mime_lower or "plain" in mime_lower:
            return content.decode("utf-8", errors="replace")
        elif "spreadsheet" in mime_lower or "csv" in mime_lower:
            return content.decode("utf-8", errors="replace")
        elif "google-apps.document" in mime_lower:
            # Google Docs should be exported as text/plain by the caller
            return content.decode("utf-8", errors="replace")
        else:
            # Attempt text decode for unknown types
            try:
                return content.decode("utf-8", errors="replace")
            except Exception:
                return ""

    def _extract_pdf(self, content: bytes) -> str:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = []
                logger.info(f"PDF Extraction: Found {len(pdf.pages)} pages")
                for i, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        pages.append(f"[Page {i+1}]\n{text}")
                
                result = "\n\n".join(pages).strip()
                if not result and len(pdf.pages) > 0:
                    logger.warning("pdfplumber extracted 0 text from a multi-page PDF. It might be scanned or protected.")
                
                logger.info(f"PDF Extraction: Extracted {len(result)} characters total")
                return result
        except Exception as e:
            logger.error(f"PDF extraction error: {e}")
            # Fallback: attempt raw text extraction for simple PDFs
            try:
                raw_text = content.decode("latin-1", errors="ignore")
                # Very basic filter for readable strings
                readable = "".join([c for c in raw_text if c.isprintable() or c in "\n\r\t"])
                if len(readable) > 100:
                    logger.info("Used latin-1 fallback for PDF text recovery")
                    return readable
            except:
                pass
            return ""

    def _extract_docx(self, content: bytes) -> str:
        try:
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        except Exception as e:
            logger.error(f"DOCX extraction error: {e}")
            return ""


# ─── Vector Store (ChromaDB) ──────────────────────────────────────────────────

class VectorStoreManager:
    """Manages ChromaDB for storing and querying document embeddings."""

    COLLECTION_NAME = "audit_documents"

    def __init__(self, gemini_client: GeminiClient):
        self._client = None
        self._collection = None
        self.gemini = gemini_client
        self._db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "chroma_data"
        )

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            self._client = chromadb.PersistentClient(path=self._db_path)
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def add_chunks(self, chunks: List[Chunk], embeddings: List[List[float]]):
        """Store chunks with their embeddings."""
        if not chunks:
            return

        ids = [f"{c.file_id}_chunk_{c.chunk_index}" for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [
            {"file_id": c.file_id, "file_name": c.file_name, "chunk_index": c.chunk_index}
            for c in chunks
        ]

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        logger.info(f"Stored {len(chunks)} chunks in ChromaDB")

    def query(self, query_text: str, file_ids: List[str] = None, top_k: int = 15) -> dict:
        """Query similar chunks."""
        query_embedding = self.gemini.embed(query_text)
        
        where_filter = None
        if file_ids:
            if len(file_ids) == 1:
                where_filter = {"file_id": file_ids[0]}
            else:
                where_filter = {"file_id": {"$in": file_ids}}

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"]
        )
        return results

    def get_all_chunks_for_file(self, file_id: str) -> dict:
        """Get all chunks for a specific file, ordered by index."""
        results = self.collection.get(
            where={"file_id": file_id},
            include=["documents", "metadatas"]
        )
        
        # Sort by chunk_index
        if results and results["metadatas"]:
            combined = list(zip(
                results["ids"], results["documents"], results["metadatas"]
            ))
            combined.sort(key=lambda x: x[2].get("chunk_index", 0))
            results["ids"] = [c[0] for c in combined]
            results["documents"] = [c[1] for c in combined]
            results["metadatas"] = [c[2] for c in combined]
        
        return results

    def delete_file_chunks(self, file_id: str):
        """Delete all chunks for a specific file."""
        try:
            existing = self.collection.get(where={"file_id": file_id})
            if existing and existing["ids"]:
                self.collection.delete(ids=existing["ids"])
                logger.info(f"Deleted {len(existing['ids'])} chunks for file {file_id}")
        except Exception as e:
            logger.error(f"Error deleting chunks for {file_id}: {e}")

    def get_indexed_file_ids(self) -> set:
        """Get all unique file_ids in the collection."""
        try:
            results = self.collection.get(include=["metadatas"])
            if results and results["metadatas"]:
                return {m["file_id"] for m in results["metadatas"]}
        except Exception:
            pass
        return set()


# ─── Query Parser ─────────────────────────────────────────────────────────────

class Intent(str, Enum):
    SUMMARIZE = "summarize"
    QUESTION = "question"
    GENERAL = "general"


@dataclass
class ParsedQuery:
    original_text: str
    intent: Intent
    mentions: List[str]
    remaining_text: str


class QueryParser:
    """Parses user queries to extract intent and @mentions."""

    MENTION_PATTERNS = [
        r'@"([^"]+)"',      # @"multi word name"
        r"@'([^']+)'",      # @'multi word name'
        r'@(\S+)',           # @singleword
    ]

    def parse(self, text: str) -> ParsedQuery:
        mentions = self._extract_mentions(text)
        intent = self._classify_intent(text)
        remaining = self._strip_mentions(text)
        return ParsedQuery(
            original_text=text,
            intent=intent,
            mentions=mentions,
            remaining_text=remaining.strip()
        )

    def _extract_mentions(self, text: str) -> List[str]:
        mentions = []
        for pattern in self.MENTION_PATTERNS:
            for match in re.finditer(pattern, text):
                mentions.append(match.group(1))
        return mentions

    def _classify_intent(self, text: str) -> Intent:
        lower = text.lower()
        if any(w in lower for w in ["summarize", "summary", "tldr", "overview", "describe"]):
            return Intent.SUMMARIZE
        elif "?" in text or any(w in lower for w in ["what", "how", "why", "when", "who", "which"]):
            return Intent.QUESTION
        return Intent.GENERAL

    def _strip_mentions(self, text: str) -> str:
        result = text
        for pattern in self.MENTION_PATTERNS:
            result = re.sub(pattern, "", result)
        return result.strip()


# ─── Prompt Builder ───────────────────────────────────────────────────────────

class PromptBuilder:
    """Consolidates prompts for legal and general RAG flows."""

    # Specialized System Instructions
    LEGAL_SYSTEM_INSTRUCTION = """You are a senior legal analyst preparing concise, accurate notes for Indian judiciary exams.
Your task is to analyze judicial excerpts and produce a structured, professional legal summary.

STRICT RULES:
1. ONLY use information from the provided excerpts.
2. If a section (e.g. "Arguments") is missing from the excerpts, say: "Not explicitly mentioned in the provided text."
3. TONE: Formal, authoritative, and precise.
4. LANGUAGE: Use professional legal terminology (e.g. "Ratio Decidendi", "Inter alia").
5. ACCURACY: Do not hallucinate or extrapolate beyond the text.
"""

    GENERAL_SYSTEM_INSTRUCTION = """You are a professional analysis assistant with a lucid and highly readable writing style.
ONLY use information from the PROVIDED CONTEXT. If the answer is not in the context, say so clearly.
TONE: Professional, concise, and structured. Use clear headers and bullet points."""

    # Legal Extraction Prompts
    LEGAL_SECTION_PROMPT = """TASK: Extract ONLY the {section_name} from the provided case excerpts.

SECTION TO EXTRACT: {section_name}
{section_description}

EXCERPTS:
---
{chunks_text}
---

INSTRUCTIONS:
1. Be extremely precise.
2. If this section is not discussed in the excerpts, return: "SECTION_NOT_FOUND".
3. Use professional legal language.
"""

    LEGAL_SYNTHESIS_PROMPT = """TASK: Synthesize the following extracted sections into a final, polished case summary.

SECTIONS:
{sections_text}

INSTRUCTIONS:
1. Format as a clean, structured legal note.
2. Ensure logical flow between sections.
3. Use bold headers for each section.
"""

    SUGGESTED_QUESTIONS_PROMPT = """TASK: Based ON THE SUMMARY ABOVE, generate 3-4 concise follow-up questions that a user might want to ask to explore the case further.
 
FORMAT:
- Return only the questions, one per line.
- Each line MUST start with a bullet point '-' or a number '1.'
- Do not include categories, labels, or extra text.
- Keep each question relevant and exploratory.
 
SUMMARY:
---
{summary_text}
---
### Suggested Questions
"""

    # General Prompts
    GENERAL_SUMMARY_PROMPT = """TASK: Provide a lucid and professional summary of the document "{file_name}".

CONTEXT:
---
{chunks_text}
---

INSTRUCTIONS:
1. Start with a high-level overview.
2. Use bullet points for "Key Insights".
3. Conclude with 2-3 comprehension questions."""

    def build_legal_section_prompt(self, section_name: str, section_description: str, chunks_text: str) -> str:
        return self.LEGAL_SECTION_PROMPT.format(
            section_name=section_name, 
            section_description=section_description, 
            chunks_text=chunks_text
        )

    def build_legal_synthesis_prompt(self, sections_text: str) -> str:
        return self.LEGAL_SYNTHESIS_PROMPT.format(sections_text=sections_text)

    def build_judicial_question_prompt(self, summary_text: str) -> str:
        return self.SUGGESTED_QUESTIONS_PROMPT.format(summary_text=summary_text)

    def build_general_summary_prompt(self, file_name: str, chunks_text: str) -> str:
        return self.GENERAL_SUMMARY_PROMPT.format(file_name=file_name, chunks_text=chunks_text)


# ─── Summarization Pipeline ──────────────────────────────────────────────────

class SummarizationPipeline:
    """Main orchestrator: parse → resolve → ingest → retrieve → summarize."""

    def __init__(self):
        self.gemini = GeminiClient()
        self.chunker = DocumentChunker()
        self.extractor = TextExtractor()
        self.vector_store = VectorStoreManager(self.gemini)
        self.parser = QueryParser()
        self.prompt_builder = PromptBuilder()
        self._summary_cache = {}  # Simple in-memory cache

    async def _classify_document_type(self, text: str) -> DocumentType:
        """Heuristic-first classification, then LLM for confidence."""
        # 1. Heuristic Keywords
        legal_keywords = [
            "appellant", "respondent", "judgment", "bench", "held", "supreme court", 
            "high court", "section", "act", "case no", "petition", "counsel"
        ]
        text_lower = text[:5000].lower() # Check first 5k chars
        points = sum(2 for k in legal_keywords if k in text_lower)
        
        if points >= 6: # Strong heuristic signal
            return DocumentType.LEGAL_CASE
            
        # 2. Lightweight LLM check if uncertain
        try:
            prompt = f"Categorize the following text as 'legal_case' or 'general_document'. Only return the label.\n\nTEXT EXCERPT:\n{text[:2000]}"
            label = self.gemini.generate(prompt).strip().lower()
            if "legal_case" in label:
                return DocumentType.LEGAL_CASE
            return DocumentType.GENERAL_DOCUMENT
        except Exception:
            return DocumentType.GENERAL_DOCUMENT

    def _generate_subqueries(self, doc_type: DocumentType, original_name: str) -> List[str]:
        """Generate targeted sub-queries based on document type."""
        if doc_type == DocumentType.LEGAL_CASE:
            return [
                f"facts and background of the case {original_name}",
                f"legal issues and questions of law involved in {original_name}",
                f"arguments by appellant and respondent in {original_name}",
                f"court reasoning and detailed analysis in {original_name}",
                f"held ratio decidendi and final judgment in {original_name}"
            ]
        return [f"main summary and key overview of {original_name}", f"important details and findings in {original_name}"]

    async def _multi_query_retrieve(self, subqueries: List[str], file_id: str, top_k_per_query: int = 4) -> str:
        """Retrieve chunks for multiple queries and deduplicate."""
        all_docs = []
        seen_ids = set()
        
        for query in subqueries:
            results = self.vector_store.query(query, file_ids=[file_id], top_k=top_k_per_query)
            if results and results["documents"]:
                for doc, metadata, id in zip(results["documents"][0], results["metadatas"][0], results["ids"][0]):
                    if id not in seen_ids:
                        seen_ids.add(id)
                        all_docs.append((metadata.get("chunk_index", 0), doc))
            
            # Tiny sleep to avoid slamming the embedding API if not batched
            await asyncio.sleep(0.1)

        # Sort by chunk_index to maintain document flow
        all_docs.sort(key=lambda x: x[0])
        
        combined_text = "\n\n".join([d[1] for d in all_docs])
        return combined_text

    async def ingest_file(self, file_id: str, file_name: str, access_token: str, refresh_token: str = None) -> dict:
        """Download a file from Drive, chunk it, embed it, store in ChromaDB."""
        from app.services.google_drive_service import drive_service

        try:
            # Get the Drive service client
            service = drive_service.get_client(access_token, refresh_token)
            
            # Get file metadata
            file_meta = service.files().get(
                fileId=file_id, fields="id, name, mimeType, size"
            ).execute()

            mime_type = file_meta.get("mimeType", "")
            name = file_meta.get("name", file_name)

            # Skip folders
            if "folder" in mime_type:
                return {"status": "skipped", "reason": "is_folder", "file": name}

            # Download content
            if "google-apps" in mime_type:
                export_mime = "text/plain"
                if "spreadsheet" in mime_type:
                    export_mime = "text/csv"
                request = service.files().export_media(fileId=file_id, mimeType=export_mime)
                content_bytes = request.execute()
            else:
                from googleapiclient.http import MediaIoBaseDownload
                import io
                request = service.files().get_media(fileId=file_id)
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                content_bytes = fh.getvalue()
            
            logger.info(f"Downloaded '{name}': {len(content_bytes)} bytes")
            if not content_bytes:
                return {"status": "skipped", "reason": "empty", "file": name}

            # Extract text
            text = self.extractor.extract_from_bytes(content_bytes, mime_type, name)
            if not text or len(text.strip()) < 5:
                logger.warning(f"File '{name}' (ID: {file_id}) has insufficient text for indexing")
                return {"status": "skipped", "reason": "no_extractable_text", "file": name}

            # Classify document type (NEW)
            doc_type = await self._classify_document_type(text)

            # Delete old chunks for this file
            self.vector_store.delete_file_chunks(file_id)

            # Chunk the text
            chunks = self.chunker.chunk_text(text, file_id, name)
            if not chunks:
                return {"status": "skipped", "reason": "no_chunks", "file": name}

            # Embed all chunks
            texts = [c.text for c in chunks]
            embeddings = self.gemini.embed_batch(texts)

            # Store in ChromaDB
            self.vector_store.add_chunks(chunks, embeddings)
            
            # Store doc_type in metadata of first chunk or separate store if needed
            # For now, we'll re-classify on summarize if not cached, or store in cache
            self._summary_cache[f"{file_id}_type"] = doc_type

            # Invalidate cache
            self._summary_cache.pop(file_id, None)

            logger.info(f"Ingested '{name}': {len(chunks)} chunks")
            return {"status": "indexed", "file": name, "chunks": len(chunks)}

        except Exception as e:
            logger.error(f"Ingest error for {file_id}: {e}")
            return {"status": "error", "file": file_name, "error": str(e)}

    async def ingest_folder(self, folder_id: str, access_token: str, refresh_token: str = None) -> dict:
        """Ingest all files in a folder."""
        from app.services.google_drive_service import drive_service

        try:
            service = drive_service.get_client(access_token, refresh_token)
            
            # List files in folder
            query = f"'{folder_id}' in parents and trashed=false"
            results = service.files().list(
                q=query,
                fields="files(id, name, mimeType)",
                pageSize=200
            ).execute()

            files = results.get("files", [])
            if not files:
                return {"status": "empty", "message": "No files in folder"}

            # Ingest each file
            ingestion_results = []
            for f in files:
                if "folder" in f.get("mimeType", ""):
                    # Recursively ingest sub-folders
                    sub_result = await self.ingest_folder(f["id"], access_token, refresh_token)
                    ingestion_results.append({"file": f["name"], "type": "folder", "result": sub_result})
                else:
                    result = await self.ingest_file(f["id"], f["name"], access_token, refresh_token)
                    ingestion_results.append(result)

            indexed = sum(1 for r in ingestion_results if isinstance(r, dict) and r.get("status") == "indexed")
            return {
                "status": "complete",
                "total_files": len(files),
                "indexed": indexed,
                "details": ingestion_results
            }

        except Exception as e:
            logger.error(f"Folder ingest error for {folder_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def query(self, text: str, folders: list, access_token: str, refresh_token: str = None) -> dict:
        """
        Main query handler. 
        - text: user's query (e.g. "summarize @FolderName")
        - folders: list of user's Drive folders (for @mention resolution)
        """
        parsed = self.parser.parse(text)

        # Resolve @mentions to file/folder IDs
        resolved_items = []  # List of dicts: {id, name, type}
        seen_ids = set()

        if parsed.mentions:
            for mention in parsed.mentions:
                match = self._resolve_mention(mention, folders)
                if match and match["id"] not in seen_ids:
                    seen_ids.add(match["id"])
                    resolved_items.append({
                        "id": match["id"],
                        "name": match["name"],
                        "type": "folder" if match.get("is_folder") else "file"
                    })
        
        if not resolved_items:
            # No @mentions or couldn't resolve — use all indexed files
            return {
                "answer": "I couldn't find the referenced file or folder. Please use @mention with an existing file/folder name.\n\nAvailable folders: " + ", ".join([f['name'] for f in folders[:10]]),
                "sources": [],
                "intent": parsed.intent.value,
            }

        # Auto-ingest if not yet indexed
        indexed_ids = self.vector_store.get_indexed_file_ids()
        skip_reports = []
        for item in resolved_items:
            if item["type"] == "folder":
                # For folders, we check if they are already indexed (implicitly by their files)
                # But to be safe, always trigger ingest_folder (it handles existing chunks internally)
                await self.ingest_folder(item["id"], access_token, refresh_token)
            elif item["id"] not in indexed_ids:
                res = await self.ingest_file(item["id"], item["name"], access_token, refresh_token)
                if res.get("status") == "skipped":
                    reason = res.get("reason", "unknown")
                    if reason == "no_extractable_text":
                        skip_reports.append(f"'{item['name']}' appears to be a scanned image or empty PDF (no text found).")
                    else:
                        skip_reports.append(f"'{item['name']}' was skipped: {reason}")
        
        # After auto-ingest attempt, re-check indexed files for FILE queries only
        indexed_ids = self.vector_store.get_indexed_file_ids()
        missing_files = [item["name"] for item in resolved_items if item["type"] == "file" and item["id"] not in indexed_ids]
        
        if missing_files:
            error_msg = f"I couldn't analyze: {', '.join(missing_files)}.\n"
            if skip_reports:
                error_msg += "\n".join(skip_reports)
            else:
                error_msg += "Please ensure the files contain readable text and are not password-protected."
            
            return {
                "answer": error_msg,
                "sources": [],
                "intent": parsed.intent.value,
            }

        # Generate response based on intent
        main_item = resolved_items[0]
        if parsed.intent == Intent.SUMMARIZE:
            if main_item["type"] == "folder":
                return await self._summarize_folder(main_item["id"], main_item["name"], access_token, refresh_token)
            else:
                return await self._summarize_file(main_item["id"], main_item["name"])
        elif parsed.intent == Intent.QUESTION:
            # For questions, we use all resolved IDs as context
            all_ids = [it["id"] for it in resolved_items]
            all_names = [it["name"] for it in resolved_items]
            return await self._answer_question(parsed.remaining_text, all_ids, all_names)
        else:
            # General — try summarize
            if main_item["type"] == "folder":
                return await self._summarize_folder(main_item["id"], main_item["name"], access_token, refresh_token)
            return await self._summarize_file(main_item["id"], main_item["name"])

    def _resolve_mention(self, mention: str, items: list) -> Optional[dict]:
        """Fuzzy-match an @mention against available folders/files."""
        best_match = None
        best_score = 0

        for item in items:
            score = fuzz.ratio(mention.lower(), item["name"].lower())
            partial = fuzz.partial_ratio(mention.lower(), item["name"].lower())
            combined = max(score, partial)
            
            is_folder = "folder" in item.get("mimeType", "")
            
            if combined > best_score and combined >= 60:
                best_score = combined
                best_match = {
                    "id": item["id"],
                    "name": item["name"],
                    "is_folder": is_folder,
                    "score": combined,
                }

        return best_match

    async def _summarize_file(self, file_id: str, file_name: str) -> dict:
        """Generate file-level summary using adaptive RAG flows."""
        if file_id in self._summary_cache:
            return self._summary_cache[file_id]

        # 1. Determine Document Type
        doc_type = self._summary_cache.get(f"{file_id}_type")
        if not doc_type:
            # Fallback if ingestion happened earlier or type wasn't cached
            chunks_data = self.vector_store.get_all_chunks_for_file(file_id)
            if not chunks_data or not chunks_data.get("documents"):
                return {"answer": f"No content found for '{file_name}'.", "sources": []}
            sample_text = "\n".join(chunks_data["documents"][:5])
            doc_type = await self._classify_document_type(sample_text)

        # 2. Route to appropriate flow
        try:
            if doc_type == DocumentType.LEGAL_CASE:
                result = await self._legal_synthesis_flow(file_id, file_name)
            else:
                result = await self._general_summarization_flow(file_id, file_name)
            
            self._summary_cache[file_id] = result
            return result
        except Exception as e:
            logger.error(f"Summarization flow error: {e}")
            return await self._fallback_summarization(file_id, file_name, str(e))

    async def _legal_synthesis_flow(self, file_id: str, file_name: str) -> dict:
        """Deep legal analysis flow with multi-query and section-wise extraction."""
        subqueries = self._generate_subqueries(DocumentType.LEGAL_CASE, file_name)
        
        sections = {
            "Facts": "Background, parties, and events leading to the case.",
            "Issues": "Core legal questions and points of law to be decided.",
            "Arguments": "Summary of contentions from both Appellant and Respondent.",
            "Reasoning": "The court's analysis and interpretation of law.",
            "Held": "The final decision and Ratio Decidendi (the legal principle established)."
        }

        extracted_sections = {}
        for section, desc in sections.items():
            # Retrieve relevant chunks for this specific section
            query = f"{section} and {desc} in the case of {file_name}"
            chunks_text = await self._multi_query_retrieve([query], file_id, top_k_per_query=6)
            
            # Extract section
            prompt = self.prompt_builder.build_legal_section_prompt(section, desc, chunks_text)
            content = self.gemini.generate(prompt, system_instruction=PromptBuilder.LEGAL_SYSTEM_INSTRUCTION)
            
            if "SECTION_NOT_FOUND" in content or len(content.strip()) < 10:
                extracted_sections[section] = "Not explicitly detailed in the provided excerpts."
            else:
                extracted_sections[section] = content
            
            # Rate limit safety (15 RPM limit)
            await asyncio.sleep(2.0)

        # Synthesis
        sections_text = "\n\n".join([f"### {k}\n{v}" for k, v in extracted_sections.items()])
        synth_prompt = self.prompt_builder.build_legal_synthesis_prompt(sections_text)
        final_summary = self.gemini.generate(synth_prompt, system_instruction=PromptBuilder.LEGAL_SYSTEM_INSTRUCTION)
        
        # Questions
        q_prompt = self.prompt_builder.build_judicial_question_prompt(final_summary)
        questions = self.gemini.generate(q_prompt)

        return {
            "type": "legal_case",
            "answer": f"{final_summary}\n\n### Judicial Practice Questions\n{questions}",
            "sources": [{"file": file_name, "type": "legal"}],
            "intent": "summarize"
        }

    async def _general_summarization_flow(self, file_id: str, file_name: str) -> dict:
        """Standard RAG flow for general documents."""
        subqueries = self._generate_subqueries(DocumentType.GENERAL_DOCUMENT, file_name)
        chunks_text = await self._multi_query_retrieve(subqueries, file_id, top_k_per_query=8)
        
        prompt = self.prompt_builder.build_general_summary_prompt(file_name, chunks_text)
        answer = self.gemini.generate(prompt, system_instruction=PromptBuilder.GENERAL_SYSTEM_INSTRUCTION)
        
        return {
            "type": "general_document",
            "answer": answer,
            "sources": [{"file": file_name, "type": "general"}],
            "intent": "summarize"
        }

    async def _fallback_summarization(self, file_id: str, file_name: str, error: str) -> dict:
        """Single-pass fallback if deep flow fails."""
        logger.warning(f"Falling back to single-pass summary for {file_name} due to: {error}")
        chunks_data = self.vector_store.get_all_chunks_for_file(file_id)
        text = "\n\n".join(chunks_data["documents"][:10]) # Limit to first 10 chunks
        
        prompt = f"Provide a brief summary of {file_name} based on these excerpts:\n\n{text}"
        answer = self.gemini.generate(prompt)
        
        return {
            "type": "fallback",
            "answer": f"**Note: Using basic summary due to system constraints.**\n\n{answer}",
            "sources": [{"file": file_name, "type": "fallback"}]
        }

    async def _summarize_folder(self, folder_id: str, folder_name: str, access_token: str, refresh_token: str = None) -> dict:
        """Generate folder-level summary (summary of file summaries)."""
        from app.services.google_drive_service import drive_service

        service = drive_service.get_client(access_token, refresh_token)
        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, mimeType)",
            pageSize=200
        ).execute()
        files = results.get("files", [])

        if not files:
            return {"answer": f"Folder '{folder_name}' is empty.", "sources": []}

        # Summarize each non-folder file
        file_summaries = []
        for f in files:
            if "folder" in f.get("mimeType", ""):
                continue
            summary = await self._summarize_file(f["id"], f["name"])
            if summary.get("answer"):
                file_summaries.append(f"### {f['name']}\n{summary['answer']}")

        if not file_summaries:
            return {"answer": f"No summarizable content found in '{folder_name}'.", "sources": []}

        combined = "\n\n---\n\n".join(file_summaries)
        
        # If just 1 file, return its summary directly
        if len(file_summaries) == 1:
            return {
                "answer": file_summaries[0],
                "sources": [{"file": f["name"]} for f in files if "folder" not in f.get("mimeType", "")],
                "intent": "summarize"
            }

        prompt = self.prompt_builder.build_folder_summary_prompt(folder_name, combined, len(file_summaries))
        answer = self.gemini.generate(prompt, system_instruction=PromptBuilder.SYSTEM_INSTRUCTION)

        return {
            "answer": answer,
            "sources": [{"file": f["name"]} for f in files if "folder" not in f.get("mimeType", "")],
            "intent": "summarize"
        }

    async def _answer_question(self, question: str, file_ids: List[str], file_names: List[str]) -> dict:
        """Answer a question using relevant chunks from specified files."""
        results = self.vector_store.query(question, file_ids=file_ids, top_k=15)

        if not results or not results.get("documents") or not results["documents"][0]:
            return {"answer": "No relevant content found to answer your question.", "sources": []}

        docs = results["documents"][0]
        metas = results["metadatas"][0]

        chunks_text = "\n\n".join([
            f"[Chunk from '{m.get('file_name', 'unknown')}']:\n{doc}"
            for doc, m in zip(docs, metas)
        ])

        prompt = self.prompt_builder.build_question_prompt(
            question, chunks_text, ", ".join(file_names)
        )
        answer = self.gemini.generate(prompt, system_instruction=PromptBuilder.SYSTEM_INSTRUCTION)

        seen_files = list({m.get("file_name", "unknown") for m in metas})
        return {
            "answer": answer,
            "sources": [{"file": f} for f in seen_files],
            "intent": "question"
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

summarization_pipeline = SummarizationPipeline()
