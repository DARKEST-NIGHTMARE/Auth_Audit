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
import json
import hashlib
import asyncio
from typing import List, Optional, Dict, Any
from enum import Enum
from dataclasses import dataclass, field
from rapidfuzz import fuzz
import httpx

class DocumentType(str, Enum):
    LEGAL_CASE = "legal_case"
    GENERAL_DOCUMENT = "general_document"
    UNKNOWN = "unknown"

from app.core.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

# ─── Local Embedding Client ───────────────────────────────────────────────────

class LocalEmbeddingClient:
    """Provides local sentence embeddings to bypass API rate limits."""
    
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None
        
    @property
    def model(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                logger.info(f"Initializing Local Embedding Model: {self.model_name}")
                self._model = TextEmbedding(model_name=self.model_name)
            except ImportError:
                logger.warning("fastembed not installed. Falling back to API embeddings.")
                return None
        return self._model

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings locally."""
        model = self.model
        if model:
            # fastembed returns an iterator of arrays
            return [list(e) for e in model.embed(texts)]
        return []

        return []

class CerebrasClient:
    """Wraps Cerebras Cloud API for high-speed text generation via direct REST calls."""
    
    def __init__(self):
        self.api_key = settings.cerebras_api_key
        self.api_url = "https://api.cerebras.ai/v1/chat/completions"

    async def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Generate text using direct HTTP POST to Cerebras."""
        if not self.api_key:
            raise RuntimeError("CEREBRAS_API_KEY missing.")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.cerebras_model, # Dynamic model selection
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(self.api_url, headers=headers, json=payload)
                
                if response.status_code == 401:
                    logger.error("Cerebras Authentication Failed: Invalid API Key")
                    raise RuntimeError("Cerebras Authentication Error")
                
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                logger.info("Cerebras request successful.")
                return content
            except httpx.HTTPStatusError as e:
                logger.error(f"Cerebras API Error ({e.response.status_code}): {e.response.text}")
                raise
            except Exception as e:
                logger.error(f"Cerebras Connection Error: {e}")
                raise

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

    def _is_hard_quota_error(self, error: Exception) -> bool:
        """Detect if the error is a hard quota exhaustion (not just a temporary rate limit)."""
        err_str = str(error).lower()
        hard_signals = [
            "quota exceeded for metric",
            "daily limit",
            "requests per day",
            "limit: 0",
            "billing details",
        ]
        return any(signal in err_str for signal in hard_signals)

    def generate(self, prompt: str, system_instruction: Optional[str] = None) -> str:
        """Disabled for text generation to prevent quota exhaustion - use Cerebras."""
        logger.error("DISABLED ACTION: Gemini generation called. Redirecting to exception.")
        raise RuntimeError("Gemini generation disabled - use Cerebras")

    def embed(self, text: str) -> List[float]:
        """Generate a single embedding via SDK using gemini-embedding-001 (768 dims)."""
        try:
            # Reverted to gemini-embedding-001 per user request
            response = self.client.models.embed_content(
                model="models/gemini-embedding-001",
                contents=text
            )
            return response.embeddings[0].values
        except Exception as e:
            logger.error(f"Gemini embed exception: {e}")
            return [0.0] * 768

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for multiple texts by looping manually."""
        import time
        if not texts:
            return []

        all_embeddings = []
        logger.info(f"Starting manual embedding loop for {len(texts)} chunks...")
        
        for i, text in enumerate(texts):
            try:
                if i > 0:
                    time.sleep(4.0) # 15 RPM safety
                emb = self.embed(text)
                all_embeddings.append(emb)
            except Exception as e:
                logger.error(f"Manual embed error at chunk {i}: {e}")
                all_embeddings.append([0.0] * 768)
        return all_embeddings

# ─── Centralized Generation Engine ────────────────────────────────────────────

async def generate_text(prompt: str, system_instruction: Optional[str] = None) -> str:
    """Routes ALL text generation tasks exclusively to Cerebras via REST."""
    if not settings.cerebras_api_key:
        logger.error("CEREBRAS_API_KEY missing - generation aborted.")
        raise RuntimeError("CEREBRAS_API_KEY not configured")

    logger.info("Using Cerebras for generation...")
    cerebras = CerebrasClient()
    
    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            return await cerebras.generate(prompt, system_instruction=system_instruction)
        except (RuntimeError, ValueError) as e:
            # Config/Auth errors: FAIL FAST
            logger.error(f"Cerebras Config/Auth Error: {e}. No retry.")
            raise
        except Exception as e:
            # Network/Server errors: RETRY
            if attempt < max_retries:
                wait = 2.0 * (attempt + 1)
                logger.warning(f"Cerebras transient failure (attempt {attempt+1}). Retrying in {wait}s... Error: {e}")
                await asyncio.sleep(wait)
                continue
            logger.error(f"Cerebras exhausted all {max_retries+1} attempts. Failing over to local summary.")
            raise RuntimeError(f"Cerebras exhausted retries: {e}")

    # Safety fallback if loop somehow exits without return/raise
    raise RuntimeError("Cerebras generation failed - unknown error state")


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
                current = current[int(start):]
                current_len = sum(len(s) for s in current)
            current.append(sent)
            current_len += sent_len

        if current:
            chunks.append(" ".join(current))
        return chunks


# ─── Text Extractors ──────────────────────────────────────────────────────────

class TextExtractor:
    """Extracts text from various file types."""

    async def extract_from_bytes(self, content: bytes, mime_type: str, filename: str = "") -> str:
        """Route to the correct extractor based on MIME type."""
        mime_lower = mime_type.lower() if mime_type else ""
        filename_lower = filename.lower()

        # Skip images and known binaries
        if "image/" in mime_lower or any(ext in filename_lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico"]):
            return ""
        if any(ext in filename_lower for ext in [".exe", ".zip", ".tar", ".gz", ".bin", ".iso"]):
            return ""

        if "pdf" in mime_lower:
            return await self._extract_pdf(content)
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

    async def _extract_pdf(self, content: bytes) -> str:
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
        self.local_embedder = LocalEmbeddingClient()
        self._db_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "chroma_data"
        )

    @property
    def collection(self):
        if self._collection is None:
            import chromadb
            try:
                self._client = chromadb.PersistentClient(path=self._db_path)
                self._collection = self._client.get_or_create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"}
                )
                logger.info(f"ChromaDB initialized. Total chunks in collection: {self.collection.count()}")
            except Exception as e:
                logger.error(f"ChromaDB initialization error: {e}")
                raise
        return self._collection

    def add_chunks(self, chunks: List[Chunk], folder_id: Optional[str] = None):
        """Store chunks with their embeddings + folder context."""
        if not chunks:
            return

        texts = [c.text for c in chunks]
        # Prioritize Gemini as per user request, fallback to local if API fails
        embeddings = self.gemini.embed_batch(texts)
        if not embeddings:
            logger.warning("Gemini embedding failed; attempting local fallback.")
            embeddings = self.local_embedder.embed_texts(texts)

        if not embeddings:
            logger.error("Failed to generate embeddings.")
            return

        # Fix 1: Calculate content hash for the entire file (combined chunks)
        content_for_hash = "".join(texts)
        content_hash = hashlib.md5(content_for_hash.encode()).hexdigest()

        ids = [f"{c.file_id}_chunk_{c.chunk_index}" for c in chunks]
        documents = [c.text for c in chunks]
        metadatas: List[Dict[str, Any]] = []
        for c in chunks:
            m: Dict[str, Any] = {
                "file_id": c.file_id, 
                "file_name": c.file_name, 
                "chunk_index": c.chunk_index,
                "content_hash": content_hash # Fix 1: Store hash
            }
            if folder_id:
                m["folder_id"] = folder_id
            metadatas.append(m)

        try:
            self.collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"Stored {len(chunks)} chunks in ChromaDB (Folder: {folder_id})")
        except Exception as e:
            if "dimension" in str(e).lower():
                logger.warning(f"Dimension mismatch detected: {e}. Recreating collection...")
                self._client.delete_collection(self.COLLECTION_NAME)
                self._collection = self._client.create_collection(
                    name=self.COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"}
                )
                # Retry once after recreate
                self._collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )
                logger.info(f"Successfully recreated collection and stored {len(chunks)} chunks.")
            else:
                raise

    def query(self, query_text: str, file_ids: List[str] = None, folder_id: Optional[str] = None, top_k: int = 15) -> dict:
        """Query similar chunks with optional file/folder filtering."""
        query_embedding = self.gemini.embed(query_text)
        
        where_filter = None
        if folder_id:
            where_filter = {"folder_id": folder_id}
        elif file_ids:
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

        # Fix 4: Hybrid Search Fallback (Keyword Match)
        # If no results or very low similarity (distances in cosine space: 0=identical, 2=opposite)
        # Cosine distance > 0.6 is often weak for specific name matches
        if not results["documents"] or not results["documents"][0] or (results["distances"] and results["distances"][0][0] > 0.6):
            logger.info(f"Weak vector match for '{query_text}'. Triggering keyword fallback...")
            keyword_results = self._keyword_search_fallback(query_text, where_filter, top_k=top_k)
            if keyword_results["documents"] and keyword_results["documents"][0]:
                logger.info(f"Keyword search found {len(keyword_results['documents'][0])} supplemental results.")
                # Merge: Keep top vector match if any, then append keyword results
                return keyword_results

        return results

    def _keyword_search_fallback(self, query_text: str, where_filter: Optional[dict] = None, top_k: int = 10) -> dict:
        """Fix 4: Basic keyword fallback via ChromaDB where_document contains."""
        # Clean query for simple tokens
        keywords = [w for w in re.findall(r'\w+', query_text) if len(w) > 3]
        if not keywords:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        # We take the longest keywords as they are usually specific names
        keywords.sort(key=len, reverse=True)
        primary_keyword = keywords[0]

        try:
            # ChromaDB supports $contains in where_document
            results = self.collection.query(
                query_texts=[query_text], # Using text query lets Chroma handle basic tokenization
                n_results=top_k,
                where=where_filter,
                where_document={"$contains": primary_keyword},
                include=["documents", "metadatas", "distances"]
            )
            return results
        except Exception as e:
            logger.warning(f"Keyword search failed: {e}")
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

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
                return {m["file_id"] for m in results["metadatas"] if "file_id" in m}
        except Exception:
            pass
        return set()

    def is_file_indexed(self, file_id: str, content_hash: Optional[str] = None) -> bool:
        """Fix 1: Check if file exists AND hash matches if provided."""
        try:
            where = {"file_id": file_id}
            if content_hash:
                where["content_hash"] = content_hash
            
            res = self.collection.get(where=where, limit=1)
            return len(res.get("ids", [])) > 0
        except Exception:
            return False


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

    # General Prompts
    SYSTEM_INSTRUCTION = """You are a professional analysis assistant with a lucid and highly readable writing style.
ONLY use information from the PROVIDED CONTEXT. If the answer is not in the context, say so clearly.
TONE: Professional, concise, and structured. Use clear headers and bullet points."""

    GENERAL_SYSTEM_INSTRUCTION = SYSTEM_INSTRUCTION

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

    JSON_FORMAT_INSTRUCTION = """
IMPORTANT: Return your output strictly as a JSON object with these keys:
- "summary": The structured text response in markdown format. (MUST NOT BE EMPTY)
- "suggested_questions": A clean array of 3-5 strings (no bullet points or numbers).
Do NOT include any text before or after the JSON block. The "summary" field must contain the full analysis."""


    FOLDER_SUMMARY_PROMPT = """TASK: Provide a high-level summary of the folder "{folder_name}" based on the summaries of its contents.

FILE SUMMARIES:
---
{combined_text}
---

INSTRUCTIONS:
1. Synthesize the overall purpose of these {num_files} files.
2. Highlight cross-document themes or relationships.
3. Keep it professional and concise.

{json_instruction}
"""

    QUESTION_PROMPT = """TASK: Answer the following question based ONLY on the provided document contexts.

CONTEXTS:
---
{chunks_text}
---

FILES INVOLVED: {file_names}

QUESTION: {question}

INSTRUCTIONS:
1. Be precise and cite the relevant files in your narrative.
2. If the answer isn't in the contexts, say: "I couldn't find information regarding this in the provided documents."

{json_instruction}
"""

    # Legal Extraction & Synthesis (All-in-One)
    LEGAL_ALL_IN_ONE_PROMPT = """TASK: Provide a comprehensive, structured legal analysis and follow-up questions for the provided case based ONLY on the excerpts provided.

SUMMARY STRUCTURE:
1. **Facts**: Background, parties, and events leading to the case.
2. **Issues**: Core legal questions and points of law to be decided.
3. **Arguments**: Contentions from both petitioner/appellant and respondent.
4. **Reasoning**: The court's analysis, interpretation of law, and precedents cited.
5. **Held**: The final decision and Ratio Decidendi (the legal principle established).

EXCERPTS:
---
{chunks_text}
---

INSTRUCTIONS:
1. Use professional legal terminology.
2. Adhere STRICTLY to the provided excerpts.
3. TONE: Formal, authoritative, and precise.

{json_instruction}
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

{json_instruction}

CONTEXT:
---
{chunks_text}
---

INSTRUCTIONS:
1. Start with a high-level overview.
2. Use bullet points for "Key Insights" in the summary content."""

    def build_judicial_question_prompt(self, summary_text: str) -> str:
        return self.SUGGESTED_QUESTIONS_PROMPT.format(summary_text=summary_text)

    def build_general_summary_prompt(self, file_name: str, chunks_text: str) -> str:
        return self.GENERAL_SUMMARY_PROMPT.format(
            file_name=file_name, 
            chunks_text=chunks_text,
            json_instruction=self.JSON_FORMAT_INSTRUCTION
        )

    def build_folder_summary_prompt(self, folder_name: str, combined_text: str, num_files: int) -> str:
        return self.FOLDER_SUMMARY_PROMPT.format(
            folder_name=folder_name, 
            combined_text=combined_text, 
            num_files=num_files,
            json_instruction=self.JSON_FORMAT_INSTRUCTION
        )

    def build_question_prompt(self, question: str, chunks_text: str, file_names: str) -> str:
        return self.QUESTION_PROMPT.format(
            question=question, 
            chunks_text=chunks_text, 
            file_names=file_names,
            json_instruction=self.JSON_FORMAT_INSTRUCTION
        )


# ─── Summarization Pipeline ──────────────────────────────────────────────────

class SummarizationPipeline:
    """Main orchestrator: parse → resolve → ingest → retrieve → summarize."""

    def __init__(self):
        self.embedding_service = GeminiClient() # Always Gemini for embeddings
        self.chunker = DocumentChunker()
        self.extractor = TextExtractor()
        self.vector_store = VectorStoreManager(self.embedding_service)
        self.parser = QueryParser()
        self.prompt_builder = PromptBuilder()
        self._summary_cache: Dict[str, dict] = {}
        self._doc_types: Dict[str, DocumentType] = {}

    def _parse_llm_json(self, response_text: str) -> dict:
        """Force-clean and extract JSON from LLM output (Critical Sanitizer)."""
        if not response_text:
            return {"summary": "No content generated.", "suggested_questions": []}
            
        text = str(response_text).strip()
        
        # 1. Clean common markdown wrappers
        text = re.sub(r"^```json\s*", "", text, flags=re.MULTILINE | re.IGNORECASE)
        text = re.sub(r"```$", "", text, flags=re.MULTILINE)
        text = text.strip()

        # 2. Strategy A: Direct JSON parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # 3. Strategy B: Extract the LARGEST balanced { } block
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                candidate = text[start : end + 1]
                return json.loads(candidate)
        except Exception:
            pass

        # 4. Strategy C: Boundary-based field extraction (Best for legal text)
        res = {"summary": "", "suggested_questions": []}
        
        # Look for "summary" value starting after the key
        summary_start = re.search(r'"summary":\s*"', text, re.I)
        if summary_start:
            start_pos = summary_start.end()
            # Find the end of summary by looking for the transition to "suggested_questions"
            # or the end of the JSON object
            marker = re.search(r'",\s*"suggested_questions"', text[start_pos:], re.I)
            if marker:
                res["summary"] = text[start_pos : start_pos + marker.start()].strip()
                # Continue to extract questions from the marker onwards
                questions_text = text[start_pos + marker.end():]
                res["suggested_questions"] = re.findall(r'"([^"]{10,}\?)"', questions_text)
            else:
                # No marker? Just take until the last }
                last_brace = text.rfind("}")
                if last_brace > start_pos:
                    res["summary"] = text[start_pos : last_brace].strip()
        
        # 5. Final Fallback: If summary is still empty, treat whole text as summary
        if not res["summary"] or len(res["summary"]) < 50:
            res["summary"] = text
            # Try once more for questions anywhere in the text
            res["suggested_questions"] = re.findall(r'"([^"]{10,}\?)"', text)

        # Cleanup: Fix double escaped quotes and newlines if they came through as literal characters
        summary_val = res.get("summary", "")
        if isinstance(summary_val, str):
            res["summary"] = summary_val.replace('\\"', '"').replace('\\n', '\n')
        else:
            res["summary"] = str(summary_val)
            
        return res

    async def _generate_with_fallback(self, prompt: str, system_instruction: str, file_name: str, fallback_text: str) -> str:
        """Unified generator with zero-API local fallback."""
        try:
            return await generate_text(prompt, system_instruction=system_instruction)
        except Exception as e:
            logger.warning(f"Cerebras generation failed for {file_name}. Using local extraction. Error: {e}")
            return self._local_extractive_summary(fallback_text, file_name)

    def _local_extractive_summary(self, text: str, file_name: str) -> str:
        """Generates a text-based extractive summary without any API calls."""
        snippet = text[:1500].strip()
        if not snippet:
            snippet = "(No readable text found in document)"
            
        return (
            f"**Notice: AI Generation Paused (Quota Stability).**\n\n"
            f"**Preliminary Document Excerpt ({file_name}):**\n"
            f"> {snippet}...\n\n"
            f"*Summary generated via local extraction to prevent system throttling.*"
        )

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
            label = (await generate_text(prompt)).strip().lower()
            if "legal_case" in label:
                return DocumentType.LEGAL_CASE
            return DocumentType.GENERAL_DOCUMENT
        except Exception:
            return DocumentType.GENERAL_DOCUMENT

    def _generate_subqueries(self, doc_type: DocumentType, original_name: str) -> List[str]:
        """Generate targeted sub-queries based on document type. Consolidate for 429 resilience."""
        if doc_type == DocumentType.LEGAL_CASE:
            # Consolidate to exactly 1 query to minimize embedding calls (15 RPM limit)
            return [f"comprehensive facts, issues, arguments, reasoning, and judgment in {original_name}"]
        # General documents also consolidated to 1 query
        return [f"main summary, key insights, and important findings in {original_name}"]

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
            
            # Sleep to avoid slamming the embedding API
            await asyncio.sleep(0.5)

        # Sort by chunk_index to maintain document flow
        all_docs.sort(key=lambda x: x[0])
        
        combined_text = "\n\n".join([d[1] for d in all_docs])
        return combined_text


    async def ingest_file(self, file_id: str, file_name: str, access_token: str, refresh_token: str = None, folder_id: Optional[str] = None) -> dict:
        """Ingest a single file with adaptive deduplication (Fix 1: Content Hash)."""
        try:
            name = file_name or "unknown_file"
            from app.services.google_drive_service import drive_service
            
            # Fetch metadata first to get mimeType
            meta = drive_service.get_file_metadata(file_id, access_token, refresh_token)
            mime_type = meta.get('mimeType', '')
            
            # 1. STOP FAKE "already indexed": Download and check hash
            content = drive_service.download_file_bytes(file_id, access_token, refresh_token)
            if not content:
                return {"status": "error", "reason": "download_failed", "file": name}
            
            content_hash = hashlib.md5(content).hexdigest()
            if self.vector_store.is_file_indexed(file_id, content_hash=content_hash):
                logger.info(f"Skipping ingestion for '{name}'; already indexed with matching hash.")
                return {"status": "indexed", "file": name, "reason": "already_exists_same_hash"}

            # Extract text
            text = await self.extractor.extract_from_bytes(content, mime_type, name)
            
            if not text or len(text.strip()) < 10:
                return {"status": "skipped", "reason": "no_extractable_text", "file": name}

            # 2. Classify document type
            doc_type = await self._classify_document_type(text)

            # 3. Chunk and Store
            chunks = self.chunker.chunk_text(text, file_id, name)
            if not chunks:
                return {"status": "skipped", "reason": "no_chunks", "file": name}

            # In-process embedding and storage (Now include content_hash)
            self.vector_store.add_chunks(chunks, folder_id=folder_id)
            
            # 4. Update cache
            self._summary_cache[f"{file_id}_type"] = doc_type
            self._summary_cache.pop(file_id, None)

            logger.info(f"Ingested '{name}': {len(chunks)} chunks (Total: {self.vector_store.collection.count()})")
            return {"status": "indexed", "file": name, "chunks": len(chunks)}

        except Exception as e:
            logger.error(f"Ingest failure for {file_id}: {e}")
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
                    result = await self.ingest_file(f["id"], f["name"], access_token, refresh_token, folder_id=folder_id)
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
        """Main query handler with intelligent context resolution."""
        parsed = self.parser.parse(text)

        # 1. Resolve Explicit context (@mention) - Highest Priority
        resolved_items = []
        if parsed.mentions:
            for m in parsed.mentions:
                matched = self._resolve_mention(m, folders)
                if matched:
                    resolved_items.append({
                        "id": matched["id"],
                        "name": matched["name"],
                        "type": "folder" if matched["is_folder"] else "file"
                    })

        # 2. Resolve Implicit context (Fuzzy name match) - Medium Priority
        if not resolved_items:
            implicit_match = self._fuzzy_match_text_to_items(parsed.remaining_text, folders)
            if implicit_match:
                logger.info(f"Implicit match found: {implicit_match['name']}")
                resolved_items.append({
                    "id": implicit_match["id"],
                    "name": implicit_match["name"],
                    "type": "folder" if implicit_match["is_folder"] else "file"
                })

        # 3. Handle No Context
        if not resolved_items:
            if parsed.intent == Intent.QUESTION:
                # Global Search Fallback - Lowest Priority
                logger.info("No context identified; falling back to global semantic search.")
                return await self._answer_question(parsed.remaining_text, [], [], folder_id=None)
            else:
                # Summarize requires a specific target
                return {
                    "answer": f"I couldn't identify which file or folder you'd like me to analyze. Please use @mention or specify the exact name (e.g., 'summarize docs').\n\nAvailable: " + ", ".join([f['name'] for f in folders[:5]]),
                    "sources": [],
                    "intent": parsed.intent.value,
                }

        # 4. Auto-ingest identified items
        indexed_ids = self.vector_store.get_indexed_file_ids()
        skip_reports = []
        for item in resolved_items:
            if item["type"] == "folder":
                await self.ingest_folder(item["id"], access_token, refresh_token)
            elif item["id"] not in indexed_ids:
                res = await self.ingest_file(item["id"], item["name"], access_token, refresh_token)
                if res.get("status") == "skipped":
                    skip_reports.append(f"'{item['name']}' was skipped: {res.get('reason')}")
        
        # 5. Final Retrieval and Generation
        main_item = resolved_items[0]
        if parsed.intent == Intent.SUMMARIZE:
            if main_item["type"] == "folder":
                return await self._summarize_folder(main_item["id"], main_item["name"], access_token, refresh_token)
            return await self._summarize_file(main_item["id"], main_item["name"])
        
        # Question with specific context
        all_ids = [it["id"] for it in resolved_items]
        all_names = [it["name"] for it in resolved_items]
        folder_id = main_item["id"] if main_item["type"] == "folder" else None
        return await self._answer_question(parsed.remaining_text, all_ids, all_names, folder_id=folder_id)

    def _fuzzy_match_text_to_items(self, text: str, items: list) -> Optional[dict]:
        """Detect document/folder names buried in natural language text."""
        if not text or len(text) < 3:
            return None
            
        best_match = None
        best_score = 0
        
        # We check each item's name against the entire phrase and partial fragments
        for item in items:
            name = item["name"].lower()
            # 1. Direct contains (e.g. "key points of Dev_Dutt" matches "Dev_Dutt_vs_...")
            if name in text.lower() or text.lower() in name:
                score = 80
            else:
                # 2. Fuzzy partial match
                score = fuzz.partial_ratio(name, text.lower())
            
            if score > best_score and score >= 75: # Higher threshold for implicit matching
                best_score = score
                best_match = {
                    "id": item["id"],
                    "name": item["name"],
                    "is_folder": "folder" in item.get("mimeType", ""),
                    "score": score
                }
        
        return best_match

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
        """Ultimate optimization: Complete legal analysis + questions in a single API pass."""
        subqueries = self._generate_subqueries(DocumentType.LEGAL_CASE, file_name)
        
        # Retrieve a broader context for the all-in-one pass (Optimized top_k)
        chunks_text = await self._multi_query_retrieve(subqueries, file_id, top_k_per_query=5)
        
        # SINGLE ANALYSIS PASS WITH FALLBACK
        prompt = self.prompt_builder.LEGAL_ALL_IN_ONE_PROMPT.format(
            chunks_text=chunks_text,
            json_instruction=self.prompt_builder.JSON_FORMAT_INSTRUCTION
        )
        
        # Fallback text logic
        fallback_text = chunks_text[:1000] if chunks_text else "Legal document content retrieval failed."
        
        result_text = await self._generate_with_fallback(
            prompt, 
            PromptBuilder.LEGAL_SYSTEM_INSTRUCTION,
            file_name,
            fallback_text
        )
        
        # Parse into JSON structure for frontend
        parsed = self._parse_llm_json(result_text)
        
        return {
            "type": "legal_case",
            "answer": json.dumps(parsed), # Send as JSON string for frontend to parse
            "sources": [{"file": file_name, "type": "legal"}],
            "intent": "summarize"
        }

    async def _general_summarization_flow(self, file_id: str, file_name: str) -> dict:
        """Standard RAG flow for general documents with fallback."""
        subqueries = self._generate_subqueries(DocumentType.GENERAL_DOCUMENT, file_name)
        chunks_text = await self._multi_query_retrieve(subqueries, file_id, top_k_per_query=5)
        
        prompt = self.prompt_builder.build_general_summary_prompt(file_name, chunks_text)
        
        fallback_text = chunks_text[:1000] if chunks_text else "General document content retrieval failed."
        
        answer_text = await self._generate_with_fallback(
            prompt, 
            PromptBuilder.GENERAL_SYSTEM_INSTRUCTION,
            file_name,
            fallback_text
        )
        
        # Parse into JSON structure for frontend
        parsed = self._parse_llm_json(answer_text)
        
        return {
            "type": "general_document",
            "answer": json.dumps(parsed),
            "sources": [{"file": file_name, "type": "general"}],
            "intent": "summarize"
        }

    async def _fallback_summarization(self, file_id: str, file_name: str, error: str) -> dict:
        """Single-pass fallback if deep flow fails."""
        logger.warning(f"Falling back to single-pass summary for {file_name} due to: {error}")
        chunks_data = self.vector_store.get_all_chunks_for_file(file_id)
        text = "\n\n".join(chunks_data["documents"][:10]) # Limit to first 10 chunks
        
        prompt = f"Provide a brief summary of {file_name} based on these excerpts:\n\n{text}\n\n{PromptBuilder.JSON_FORMAT_INSTRUCTION}"
        try:
            answer_text = await generate_text(prompt)
        except Exception:
            answer_text = self._local_extractive_summary(text, file_name)
        
        # Parse into JSON structure for frontend
        parsed = self._parse_llm_json(answer_text)
        
        return {
            "type": "fallback",
            "answer": json.dumps(parsed),
            "sources": [{"file": file_name, "type": "fallback"}]
        }

    async def _summarize_folder(self, folder_id: str, folder_name: str, access_token: str, refresh_token: str = None) -> dict:
        """Generate a high-performance folder summary using collective context."""
        # 1. Check cache first
        if folder_id in self._summary_cache:
            logger.info(f"Returning cached folder summary for '{folder_name}'")
            return self._summary_cache[folder_id]

        # 2. Fast Path: Query ChromaDB for collective context across the folder
        # We retrieve more chunks (top 30) to get a good spread across files
        results = self.vector_store.query(
            query_text=f"summarize the documents in folder {folder_name}",
            folder_id=folder_id,
            top_k=30
        )
        
        chunks = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        
        if len(chunks) > 5:
            logger.info(f"Using 'Fast Path' RAG for folder '{folder_name}' ({len(chunks)} chunks found)")
            context = ""
            sources = set()
            for i, text in enumerate(chunks):
                fname = metadatas[i].get("file_name", "Unknown File")
                context += f"--- Excerpt from {fname} ---\n{text}\n\n"
                sources.add(fname)
            
            prompt = self.prompt_builder.build_folder_summary_prompt(folder_name, context, len(sources))
            
            answer_text = await self._generate_with_fallback(
                prompt,
                PromptBuilder.SYSTEM_INSTRUCTION,
                folder_name,
                context[:2000] # Fallback if API fails
            )
            
            parsed = self._parse_llm_json(answer_text)
            res = {
                "type": "folder_summary",
                "answer": json.dumps(parsed),
                "sources": [{"file": s, "type": "folder_component"} for s in sorted(list(sources))],
                "intent": "summarize"
            }
            # Cache the result
            self._summary_cache[folder_id] = res
            return res

        # 3. Slow Path (Legacy/Fallback): Summarize file-by-file if index is sparse
        logger.warning(f"Sparse index for folder '{folder_name}'; falling back to per-file summaries.")
        from app.services.google_drive_service import drive_service
        service = drive_service.get_client(access_token, refresh_token)
        query = f"'{folder_id}' in parents and trashed=false"
        results = service.files().list(q=query, fields="files(id, name, mimeType)", pageSize=200).execute()
        files = results.get("files", [])
        
        file_summaries = []
        for i, f in enumerate(files):
            if "folder" in f.get("mimeType", ""): continue
            if i > 0: await asyncio.sleep(2.0) # Reduced delay for better UX
            summary = await self._summarize_file(f["id"], f["name"])
            if summary.get("answer"):
                file_summaries.append(f"### {f['name']}\n{summary['answer']}")

        if not file_summaries:
            return {"answer": f"Folder '{folder_name}' has no summarizable files.", "sources": []}

        combined = "\n\n---\n\n".join(file_summaries)
        prompt = self.prompt_builder.build_folder_summary_prompt(folder_name, combined, len(file_summaries))
        answer_text = await self._generate_with_fallback(prompt, PromptBuilder.SYSTEM_INSTRUCTION, folder_name, combined[:1500])
        
        parsed = self._parse_llm_json(answer_text)
        res = {
            "type": "folder_summary",
            "answer": json.dumps(parsed),
            "sources": [{"file": f["name"]} for f in files if "folder" not in f.get("mimeType", "")],
            "intent": "summarize"
        }
        self._summary_cache[folder_id] = res
        return res

        # Parse into JSON structure for frontend
        parsed = self._parse_llm_json(answer_text)

        return {
            "answer": json.dumps(parsed),
            "sources": [{"file": f["name"]} for f in files if "folder" not in f.get("mimeType", "")],
            "intent": "summarize",
            "type": "folder_summary"
        }

    async def _answer_question(self, question: str, file_ids: List[str], file_names: List[str], folder_id: Optional[str] = None) -> dict:
        """Answer a question using relevant chunks (Context: File, Folder, or Global)."""
        # If no explicit context, trigger global search by calling query with empty filters
        results = self.vector_store.query(question, file_ids=file_ids, folder_id=folder_id, top_k=10)

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
        
        answer_text = await self._generate_with_fallback(
            prompt, 
            PromptBuilder.SYSTEM_INSTRUCTION,
            "Multi-File Search",
            chunks_text[:1000]
        )

        # Parse into JSON structure for frontend
        parsed = self._parse_llm_json(answer_text)

        seen_files = list({m.get("file_name", "unknown") for m in metas})
        return {
            "answer": json.dumps(parsed),
            "sources": [{"file": f} for f in seen_files],
            "intent": "question"
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

summarization_pipeline = SummarizationPipeline()
