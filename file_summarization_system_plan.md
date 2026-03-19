# 🏗️ Production Implementation Plan: @File / @Folder Summarization System

> **Version**: 1.0 — March 18, 2026
> **Scope**: Enterprise-grade, scalable system for file/folder reference resolution and LLM-powered summarization
> **Target Scale**: Thousands to millions of documents per tenant

---

## 1. System Overview

### 1.1 What We're Building

A system that intercepts natural language queries containing `@mentions` (e.g., `"summarize @Q4-Report.pdf"`), resolves those mentions to actual files or folders in Google Drive (or any storage backend), retrieves their content, and produces **grounded, hallucination-resistant summaries** using LLMs.

### 1.2 Core User Flows

```
User Types: "summarize @ProjectAlpha"
    ↓
System Parses: intent=SUMMARIZE, mentions=[@ProjectAlpha]
    ↓
System Resolves: @ProjectAlpha → Google Drive Folder ID: 1xAb...
    ↓
System Retrieves: 47 files inside folder, extracts text
    ↓
System Chunks & Embeds: 312 chunks stored in vector DB
    ↓
System Summarizes: Hierarchical summarization (chunk → file → folder)
    ↓
User Receives: Grounded summary with citations
```

### 1.3 Design Principles

| Principle | Description |
|---|---|
| **Strict Grounding** | LLM output must be traceable to source documents. No hallucination. |
| **Incremental Processing** | Only re-process changed files. Never re-ingest entire corpus. |
| **Separation of Concerns** | Each layer is independently deployable and testable. |
| **Cost Awareness** | Minimize LLM token usage via caching, chunking, and smart retrieval. |
| **Permission Inheritance** | Users can only summarize files they have access to. |

---

## 2. Detailed Architecture

### 2.1 High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLIENT LAYER                                  │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────────┐    │
│  │  Web UI       │  │  @Mention         │  │  Chat Interface        │    │
│  │  (React)      │  │  Autocomplete     │  │  (Query Input)         │    │
│  └──────┬───────┘  └────────┬─────────┘  └───────────┬────────────┘    │
└─────────┼──────────────────┼─────────────────────────┼─────────────────┘
          │                  │                         │
          ▼                  ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         API GATEWAY (FastAPI)                           │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  POST /api/query          — Main query endpoint                  │   │
│  │  POST /api/ingest         — Trigger file ingestion               │   │
│  │  GET  /api/autocomplete   — @mention autocomplete                │   │
│  │  GET  /api/summary/:id    — Retrieve cached summary             │   │
│  │  POST /api/webhook/drive  — Drive change notifications          │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────────┐
          ▼                   ▼                       ▼
┌──────────────────┐ ┌────────────────────┐ ┌─────────────────────┐
│  QUERY ENGINE    │ │  INGESTION ENGINE  │ │  RESOLUTION ENGINE  │
│                  │ │                    │ │                     │
│ • Parse intent   │ │ • File download    │ │ • @mention → ID     │
│ • Route query    │ │ • Text extraction  │ │ • Fuzzy matching     │
│ • Build prompt   │ │ • Chunking         │ │ • Permission check   │
│ • Call LLM       │ │ • Embedding gen    │ │ • Disambiguation     │
│ • Validate resp  │ │ • Vector store     │ │ • Metadata lookup    │
└───────┬──────────┘ └────────┬───────────┘ └──────────┬──────────┘
        │                     │                        │
        ▼                     ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA LAYER                                      │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────────────────┐  │
│  │  PostgreSQL     │  │  Qdrant /     │  │  Redis                    │  │
│  │  (Metadata,     │  │  Pinecone     │  │  (Cache: summaries,       │  │
│  │   Permissions,  │  │  (Vectors,    │  │   embeddings, responses,  │  │
│  │   File Index)   │  │   Chunks)     │  │   rate limits)            │  │
│  └────────────────┘  └──────────────┘  └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
        │                     │
        ▼                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    EXTERNAL SERVICES                                    │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────────────────┐  │
│  │  Google Drive   │  │  OpenAI /     │  │  Celery + Redis           │  │
│  │  API            │  │  Anthropic    │  │  (Task Queue)             │  │
│  │  (File Source)  │  │  (LLM API)   │  │  (Async Processing)       │  │
│  └────────────────┘  └──────────────┘  └────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Microservices Breakdown

| Service | Responsibility | Tech | Port |
|---|---|---|---|
| `api-gateway` | Request routing, auth, rate limiting | FastAPI | 8000 |
| `query-engine` | NLU, intent classification, prompt construction | Python | 8001 |
| `resolution-service` | @mention → file/folder ID mapping | Python | 8002 |
| `ingestion-worker` | File download, parsing, chunking, embedding | Celery Worker | — |
| `summarization-service` | Hierarchical summarization orchestration | Python | 8003 |
| `validation-service` | Hallucination detection, grounding checks | Python | 8004 |

> [!IMPORTANT]
> For initial deployment, these can run as **modules within a single FastAPI monolith**. Extract into microservices only when scaling demands it.

---

## 3. Step-by-Step Data Flow

### 3.1 Query Flow (User asks: `"summarize @Q4-Report"`)

```mermaid
sequenceDiagram
    participant U as User
    participant API as API Gateway
    participant QE as Query Engine
    participant RS as Resolution Service
    participant VS as Vector Store
    participant LLM as LLM Provider
    participant VL as Validation Layer
    participant Cache as Redis Cache

    U->>API: POST /api/query { "text": "summarize @Q4-Report" }
    API->>Cache: Check response cache (hash of query)
    Cache-->>API: MISS

    API->>QE: Parse query
    QE->>QE: Extract intent=SUMMARIZE, mentions=[@Q4-Report]
    QE->>RS: Resolve "@Q4-Report"
    RS->>RS: Search metadata index (PostgreSQL)
    RS->>RS: Check user permissions
    RS-->>QE: { id: "1xAb...", type: "file", name: "Q4-Report.pdf" }

    QE->>Cache: Check summary cache for file ID
    Cache-->>QE: MISS

    QE->>VS: Retrieve all chunks for file ID "1xAb..."
    VS-->>QE: [chunk_1, chunk_2, ..., chunk_n]

    QE->>QE: Build grounded prompt (system + context + instruction)
    QE->>LLM: Send constructed prompt
    LLM-->>QE: Raw summary response

    QE->>VL: Validate response against source chunks
    VL-->>QE: { valid: true, grounding_score: 0.94 }

    QE->>Cache: Store summary (TTL: 1 hour)
    QE-->>API: Final grounded summary with citations
    API-->>U: Formatted response
```

### 3.2 Ingestion Flow (File is uploaded/changed)

```mermaid
sequenceDiagram
    participant Drive as Google Drive
    participant WH as Webhook Handler
    participant Q as Task Queue (Celery)
    participant W as Ingestion Worker
    participant DB as PostgreSQL
    participant VS as Vector Store

    Drive->>WH: POST /api/webhook/drive (file changed notification)
    WH->>DB: Lookup file metadata
    WH->>Q: Enqueue ingestion task { file_id, change_type }

    Q->>W: Dequeue task
    W->>Drive: Download file content
    W->>W: Extract text (PDF/DOCX/TXT parser)
    W->>W: Chunk text (sliding window, 512 tokens, 64 overlap)
    W->>W: Generate embeddings (text-embedding-3-small)
    
    W->>VS: Upsert chunk embeddings (delete old, insert new)
    W->>DB: Update file metadata (last_indexed, chunk_count, hash)
    W->>W: Invalidate cached summaries for this file
```

---

## 4. Component-wise Implementation Plan

### 4.1 Query Understanding Layer

**Purpose**: Parse raw user input into structured intent + entity objects.

#### Implementation

```python
# models/query.py
from pydantic import BaseModel
from enum import Enum
from typing import List, Optional

class Intent(str, Enum):
    SUMMARIZE = "summarize"
    QUESTION = "question"
    COMPARE = "compare"
    SEARCH = "search"
    GENERAL = "general"

class Mention(BaseModel):
    raw_text: str          # "@Q4-Report"
    normalized: str        # "Q4-Report"
    resolved_id: Optional[str] = None
    resolved_type: Optional[str] = None  # "file" | "folder"
    confidence: float = 0.0

class ParsedQuery(BaseModel):
    original_text: str
    intent: Intent
    mentions: List[Mention]
    remaining_text: str    # Query text without @mentions
    mode: str              # "rag" | "general" | "hybrid"
```

#### Parser Logic

```python
# services/query_parser.py
import re
from typing import List, Tuple

class QueryParser:
    # Regex patterns for @mention extraction
    MENTION_PATTERNS = [
        r'@"([^"]+)"',           # @"My Long Filename.pdf"
        r"@'([^']+)'",           # @'My Long Filename.pdf'
        r'@(\S+)',               # @simple-name
    ]

    def parse(self, raw_query: str) -> ParsedQuery:
        mentions = self._extract_mentions(raw_query)
        intent = self._classify_intent(raw_query)
        remaining = self._strip_mentions(raw_query)
        mode = self._determine_mode(intent, mentions)

        return ParsedQuery(
            original_text=raw_query,
            intent=intent,
            mentions=mentions,
            remaining_text=remaining,
            mode=mode
        )

    def _extract_mentions(self, text: str) -> List[Mention]:
        mentions = []
        for pattern in self.MENTION_PATTERNS:
            for match in re.finditer(pattern, text):
                raw = match.group(0)
                name = match.group(1)
                mentions.append(Mention(raw_text=raw, normalized=name))
        return mentions

    def _classify_intent(self, text: str) -> Intent:
        text_lower = text.lower()
        if any(w in text_lower for w in ["summarize", "summary", "tldr", "overview"]):
            return Intent.SUMMARIZE
        elif any(w in text_lower for w in ["compare", "diff", "versus"]):
            return Intent.COMPARE
        elif "?" in text or any(w in text_lower for w in ["what", "how", "why", "when"]):
            return Intent.QUESTION
        elif any(w in text_lower for w in ["find", "search", "look for"]):
            return Intent.SEARCH
        return Intent.GENERAL

    def _determine_mode(self, intent: Intent, mentions: List[Mention]) -> str:
        if not mentions:
            return "general"
        if intent == Intent.GENERAL:
            return "hybrid"
        return "rag"
```

> [!TIP]
> For production, replace the keyword-based intent classifier with a fine-tuned classifier or a small LLM call (`gpt-4o-mini`) for better accuracy on ambiguous queries.

---

### 4.2 Routing Layer

**Purpose**: Direct queries to the appropriate processing pipeline.

```python
# services/router.py
class QueryRouter:
    async def route(self, parsed: ParsedQuery) -> dict:
        if parsed.mode == "general":
            return await self._handle_general(parsed)
        elif parsed.mode == "rag":
            return await self._handle_rag(parsed)
        else:  # hybrid
            return await self._handle_hybrid(parsed)

    async def _handle_rag(self, parsed: ParsedQuery) -> dict:
        # 1. Resolve all @mentions to file/folder IDs
        resolved = await self.resolution_service.resolve_all(parsed.mentions)
        
        # 2. Check if summaries are cached
        cache_key = self._build_cache_key(parsed.intent, resolved)
        cached = await self.cache.get(cache_key)
        if cached:
            return cached

        # 3. Determine if this is a file or folder operation
        if any(r.resolved_type == "folder" for r in resolved):
            return await self.summarization_service.summarize_folder(parsed, resolved)
        else:
            return await self.summarization_service.summarize_files(parsed, resolved)

    async def _handle_general(self, parsed: ParsedQuery) -> dict:
        # Direct LLM call without RAG context
        return await self.llm_service.general_query(parsed.remaining_text)

    async def _handle_hybrid(self, parsed: ParsedQuery) -> dict:
        # Parallel: RAG pipeline + general knowledge
        rag_result = await self._handle_rag(parsed)
        return self._merge_responses(rag_result, parsed)
```

---

### 4.3 Resource Resolution Layer

**Purpose**: Map `@mentions` to actual file/folder IDs with permission checks.

#### Database Schema

```sql
-- File/Folder metadata index
CREATE TABLE file_index (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_file_id   VARCHAR(255) NOT NULL UNIQUE,
    name            VARCHAR(1024) NOT NULL,
    name_normalized VARCHAR(1024) NOT NULL,  -- lowercase, stripped
    mime_type       VARCHAR(255),
    parent_id       VARCHAR(255),            -- parent folder Drive ID
    owner_email     VARCHAR(255),
    size_bytes      BIGINT,
    content_hash    VARCHAR(64),             -- SHA-256 of content
    last_modified   TIMESTAMPTZ,
    last_indexed    TIMESTAMPTZ,
    chunk_count     INTEGER DEFAULT 0,
    is_folder       BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    
    -- Full-text search index
    -- For fuzzy matching on file names
);

CREATE INDEX idx_file_name_normalized ON file_index (name_normalized);
CREATE INDEX idx_file_parent ON file_index (parent_id);
CREATE INDEX idx_file_owner ON file_index (owner_email);

-- Trigram index for fuzzy search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX idx_file_name_trgm ON file_index 
    USING gin (name_normalized gin_trgm_ops);

-- Permissions cache
CREATE TABLE file_permissions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    drive_file_id   VARCHAR(255) NOT NULL,
    user_email      VARCHAR(255) NOT NULL,
    role            VARCHAR(50),  -- 'reader', 'writer', 'owner'
    expires_at      TIMESTAMPTZ,
    UNIQUE(drive_file_id, user_email)
);
```

#### Resolution Service

```python
# services/resolution.py
from rapidfuzz import fuzz, process

class ResolutionService:
    SIMILARITY_THRESHOLD = 75  # Minimum fuzzy match score

    async def resolve(self, mention: Mention, user_email: str) -> Mention:
        # Step 1: Exact match (fastest)
        exact = await self.db.fetch_one(
            "SELECT * FROM file_index WHERE name_normalized = $1",
            mention.normalized.lower()
        )
        if exact:
            return self._check_permission_and_return(exact, mention, user_email)

        # Step 2: Trigram fuzzy match (fast, DB-level)
        fuzzy_results = await self.db.fetch_all(
            """
            SELECT *, similarity(name_normalized, $1) as sim_score
            FROM file_index
            WHERE similarity(name_normalized, $1) > $2
            ORDER BY sim_score DESC
            LIMIT 5
            """,
            mention.normalized.lower(),
            self.SIMILARITY_THRESHOLD / 100
        )

        if len(fuzzy_results) == 1:
            return self._check_permission_and_return(fuzzy_results[0], mention, user_email)
        
        if len(fuzzy_results) > 1:
            # Disambiguation needed — return candidates
            raise AmbiguousMentionError(
                mention=mention,
                candidates=[
                    {"name": r["name"], "id": r["drive_file_id"], "score": r["sim_score"]}
                    for r in fuzzy_results
                ]
            )

        # Step 3: Semantic search (slowest, most flexible)
        embedding = await self.embedding_service.embed(mention.normalized)
        semantic_results = await self.vector_store.search_metadata(
            embedding, top_k=3, filter={"owner_email": user_email}
        )

        if semantic_results:
            best = semantic_results[0]
            return self._build_resolved(best, mention, confidence=best.score)

        raise MentionNotFoundError(mention=mention)

    async def _check_permission_and_return(self, record, mention, user_email):
        has_access = await self.db.fetch_one(
            "SELECT 1 FROM file_permissions WHERE drive_file_id=$1 AND user_email=$2",
            record["drive_file_id"], user_email
        )
        if not has_access:
            raise PermissionDeniedError(file_name=record["name"])

        mention.resolved_id = record["drive_file_id"]
        mention.resolved_type = "folder" if record["is_folder"] else "file"
        mention.confidence = 1.0
        return mention
```

> [!WARNING]
> **Disambiguation is critical.** If a user writes `@Report` and there are 5 files named "Report", the system MUST NOT guess. It should return a disambiguation prompt: *"Did you mean: Report-Q4.pdf, Report-Annual.docx, or Report-Draft.txt?"*

---

### 4.4 Data Ingestion & Processing

**Purpose**: Download files, extract text, chunk, embed, and store.

#### Supported File Types & Parsers

| File Type | Parser | Library |
|---|---|---|
| PDF | `PyPDF2` / `pdfplumber` | `pdfplumber` (preferred for tables) |
| DOCX | `python-docx` | `python-docx` |
| TXT / MD | Built-in | Python [open()](file:///home/manmath/Documents/OAuth%20dummy/Login%20Auth%20Audit/frontend/src/components/integrations/GoogleDriveManager.jsx#14-15) |
| Google Docs | Google Drive Export API | Export as `text/plain` |
| Google Sheets | Google Drive Export API | Export as `text/csv` |
| Slides (PPTX) | `python-pptx` | `python-pptx` |
| Images | OCR via Google Cloud Vision | `google-cloud-vision` |
| Code Files | Direct text read | Syntax-aware chunking |

#### Chunking Strategy

```python
# services/chunker.py
from typing import List
from dataclasses import dataclass

@dataclass
class Chunk:
    text: str
    chunk_index: int
    start_char: int
    end_char: int
    file_id: str
    file_name: str
    metadata: dict  # page number, section heading, etc.

class DocumentChunker:
    DEFAULT_CHUNK_SIZE = 512     # tokens
    DEFAULT_OVERLAP = 64         # tokens
    MAX_CHUNK_SIZE = 1024        # tokens

    def chunk_document(self, text: str, file_id: str, file_name: str) -> List[Chunk]:
        """
        Intelligent chunking strategy:
        1. Try semantic boundaries first (paragraphs, sections, headings)
        2. Fall back to sliding window with overlap
        3. Never split mid-sentence
        """
        # Phase 1: Split by semantic boundaries
        sections = self._split_by_sections(text)

        chunks = []
        for section in sections:
            if self._token_count(section) <= self.DEFAULT_CHUNK_SIZE:
                chunks.append(section)
            else:
                # Phase 2: Sliding window within large sections
                sub_chunks = self._sliding_window(
                    section,
                    window_size=self.DEFAULT_CHUNK_SIZE,
                    overlap=self.DEFAULT_OVERLAP
                )
                chunks.extend(sub_chunks)

        return [
            Chunk(
                text=c,
                chunk_index=i,
                start_char=0,  # compute actual positions
                end_char=len(c),
                file_id=file_id,
                file_name=file_name,
                metadata={}
            )
            for i, c in enumerate(chunks)
        ]

    def _split_by_sections(self, text: str) -> List[str]:
        """Split text by headings, double newlines, or similar markers."""
        import re
        # Split on markdown headings or double newlines
        sections = re.split(r'\n#{1,6}\s|\n\n', text)
        return [s.strip() for s in sections if s.strip()]

    def _sliding_window(self, text: str, window_size: int, overlap: int) -> List[str]:
        """Token-aware sliding window that respects sentence boundaries."""
        sentences = self._split_sentences(text)
        chunks = []
        current_chunk = []
        current_tokens = 0

        for sentence in sentences:
            sent_tokens = self._token_count(sentence)
            if current_tokens + sent_tokens > window_size and current_chunk:
                chunks.append(" ".join(current_chunk))
                # Keep overlap
                overlap_tokens = 0
                overlap_start = len(current_chunk)
                for i in range(len(current_chunk) - 1, -1, -1):
                    overlap_tokens += self._token_count(current_chunk[i])
                    if overlap_tokens >= overlap:
                        overlap_start = i
                        break
                current_chunk = current_chunk[overlap_start:]
                current_tokens = sum(self._token_count(s) for s in current_chunk)
            
            current_chunk.append(sentence)
            current_tokens += sent_tokens

        if current_chunk:
            chunks.append(" ".join(current_chunk))

        return chunks
```

#### Ingestion Worker (Celery)

```python
# workers/ingestion.py
from celery import Celery
import hashlib

app = Celery('ingestion', broker='redis://localhost:6379/0')

@app.task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_file(self, file_id: str, user_email: str):
    try:
        # 1. Download file from Google Drive
        content_bytes = drive_service.download_file(file_id)
        
        # 2. Compute content hash for change detection
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        
        existing = db.get_file_metadata(file_id)
        if existing and existing.content_hash == content_hash:
            logger.info(f"File {file_id} unchanged, skipping ingestion")
            return {"status": "skipped", "reason": "unchanged"}

        # 3. Extract text based on MIME type
        mime_type = drive_service.get_mime_type(file_id)
        text = text_extractor.extract(content_bytes, mime_type)

        if not text or len(text.strip()) < 10:
            logger.warning(f"File {file_id} has no extractable text")
            return {"status": "skipped", "reason": "no_text"}

        # 4. Chunk the document
        chunks = chunker.chunk_document(text, file_id, existing.name if existing else "")

        # 5. Generate embeddings (batch for efficiency)
        embeddings = embedding_service.embed_batch([c.text for c in chunks])

        # 6. Delete old vectors for this file, insert new ones
        vector_store.delete_by_filter({"file_id": file_id})
        vector_store.upsert([
            {
                "id": f"{file_id}_chunk_{c.chunk_index}",
                "vector": emb,
                "metadata": {
                    "file_id": file_id,
                    "file_name": c.file_name,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    **c.metadata
                }
            }
            for c, emb in zip(chunks, embeddings)
        ])

        # 7. Update metadata
        db.update_file_metadata(file_id, {
            "content_hash": content_hash,
            "last_indexed": datetime.utcnow(),
            "chunk_count": len(chunks)
        })

        # 8. Invalidate cached summaries
        cache.delete_pattern(f"summary:*:{file_id}:*")

        return {"status": "indexed", "chunks": len(chunks)}
    
    except Exception as exc:
        logger.error(f"Ingestion failed for {file_id}: {exc}")
        raise self.retry(exc=exc)
```

---

### 4.5 RAG Pipeline

**Purpose**: Retrieve relevant chunks and build context for LLM.

```python
# services/rag.py
class RAGPipeline:
    TOP_K_CHUNKS = 20           # Retrieve top 20 chunks
    MAX_CONTEXT_TOKENS = 8000   # Max tokens for context window
    RERANK_TOP_N = 10           # After reranking, keep top 10

    async def retrieve_context(
        self,
        query: str,
        file_ids: List[str],
        intent: Intent
    ) -> List[RetrievedChunk]:
        
        # Step 1: Generate query embedding
        query_embedding = await self.embedding_service.embed(query)

        # Step 2: Vector search with file_id filter
        raw_results = await self.vector_store.search(
            vector=query_embedding,
            top_k=self.TOP_K_CHUNKS,
            filter={"file_id": {"$in": file_ids}}
        )

        # Step 3: Rerank using cross-encoder (optional but recommended)
        if self.reranker:
            reranked = await self.reranker.rerank(
                query=query,
                documents=[r.text for r in raw_results],
                top_n=self.RERANK_TOP_N
            )
            raw_results = [raw_results[r.index] for r in reranked]

        # Step 4: Enforce token budget
        context_chunks = []
        total_tokens = 0
        for chunk in raw_results:
            chunk_tokens = self._token_count(chunk.text)
            if total_tokens + chunk_tokens > self.MAX_CONTEXT_TOKENS:
                break
            context_chunks.append(chunk)
            total_tokens += chunk_tokens

        return context_chunks

    async def retrieve_all_chunks(self, file_id: str) -> List[RetrievedChunk]:
        """For summarization: retrieve ALL chunks for a file, ordered by index."""
        return await self.vector_store.fetch_all(
            filter={"file_id": file_id},
            sort_by="chunk_index",
            order="asc"
        )
```

---

### 4.6 Hierarchical Summarization

**Purpose**: Generate summaries at chunk, file, and folder levels.

```python
# services/summarization.py
class HierarchicalSummarizer:
    MAX_CHUNKS_PER_LLM_CALL = 15  # Avoid exceeding token limits
    
    async def summarize_file(self, file_id: str, file_name: str) -> str:
        """Generate file-level summary from all chunks."""
        
        # Check cache first
        cached = await self.cache.get(f"summary:file:{file_id}")
        if cached:
            return cached

        # Retrieve all chunks for this file
        chunks = await self.rag.retrieve_all_chunks(file_id)

        if len(chunks) <= self.MAX_CHUNKS_PER_LLM_CALL:
            # Small file: summarize all chunks at once
            summary = await self._summarize_chunks(chunks, file_name)
        else:
            # Large file: Map-Reduce summarization
            summary = await self._map_reduce_summarize(chunks, file_name)

        await self.cache.set(f"summary:file:{file_id}", summary, ttl=3600)
        return summary

    async def summarize_folder(self, folder_id: str, folder_name: str) -> str:
        """Generate folder-level summary (summary of file summaries)."""
        
        cached = await self.cache.get(f"summary:folder:{folder_id}")
        if cached:
            return cached

        # Get all files in folder
        files = await self.db.get_files_in_folder(folder_id)

        # Generate individual file summaries (parallel)
        file_summaries = await asyncio.gather(*[
            self.summarize_file(f["drive_file_id"], f["name"])
            for f in files
        ])

        # Combine file summaries into folder summary
        combined = "\n\n".join([
            f"### {files[i]['name']}\n{s}"
            for i, s in enumerate(file_summaries)
            if s
        ])

        # Generate folder-level summary from file summaries
        prompt = self.prompt_builder.build_folder_summary_prompt(
            folder_name=folder_name,
            file_summaries=combined,
            file_count=len(files)
        )

        summary = await self.llm.generate(prompt)
        await self.cache.set(f"summary:folder:{folder_id}", summary, ttl=3600)
        return summary

    async def _map_reduce_summarize(self, chunks: List, file_name: str) -> str:
        """Map-Reduce for large files."""
        
        # MAP phase: Summarize chunk groups in parallel
        groups = self._split_into_groups(chunks, self.MAX_CHUNKS_PER_LLM_CALL)
        group_summaries = await asyncio.gather(*[
            self._summarize_chunks(group, file_name)
            for group in groups
        ])

        # REDUCE phase: Combine group summaries
        if len(group_summaries) <= self.MAX_CHUNKS_PER_LLM_CALL:
            return await self._combine_summaries(group_summaries, file_name)
        else:
            # Recursive reduce for very large files
            return await self._map_reduce_summarize(
                [Chunk(text=s, chunk_index=i, ...) for i, s in enumerate(group_summaries)],
                file_name
            )
```

---

### 4.7 Prompt Orchestration (Critical Layer)

> [!CAUTION]
> This is the **most critical** component of the system. A poorly constructed prompt is the #1 cause of hallucinations. The raw user query must **NEVER** be sent directly to the LLM.

```python
# services/prompt_builder.py
class PromptBuilder:
    
    SYSTEM_PROMPT = """You are a document analysis assistant with strict grounding rules.

CRITICAL RULES — VIOLATIONS ARE NOT ACCEPTABLE:
1. You may ONLY use information from the PROVIDED CONTEXT below.
2. If the answer cannot be found in the context, say: "This information is not available in the provided documents."
3. NEVER generate information from your training data when answering about specific documents.
4. When making claims, cite the source document and chunk using [Source: filename, Section N].
5. If the context is insufficient for a complete answer, explicitly state what is missing.
6. Maintain the factual accuracy of numbers, dates, names, and statistics from the source.
7. Do not infer, extrapolate, or make assumptions beyond what the context states.

RESPONSE FORMAT:
- Use clear, structured formatting (headers, bullets)
- Include source citations inline
- End with a "Sources" section listing all referenced documents
"""

    def build_summarization_prompt(
        self,
        file_name: str,
        context_chunks: List[RetrievedChunk],
        user_instruction: str = ""
    ) -> List[dict]:
        
        # Format context with chunk identifiers
        formatted_context = "\n\n".join([
            f"[Chunk {c.chunk_index + 1} from '{c.file_name}']:\n{c.text}"
            for c in context_chunks
        ])

        user_message = f"""TASK: Summarize the document "{file_name}"

CONTEXT (from the actual document):
---
{formatted_context}
---

INSTRUCTIONS:
- Provide a comprehensive summary of the document based ONLY on the context above.
- Highlight key findings, decisions, metrics, and action items.
- Organize the summary with clear headings.
- Cite specific chunks when referencing particular information.
{f"- Additional user request: {user_instruction}" if user_instruction else ""}

Generate the summary now, using ONLY the provided context."""

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

    def build_question_prompt(
        self,
        question: str,
        context_chunks: List[RetrievedChunk],
        file_names: List[str]
    ) -> List[dict]:
        
        formatted_context = "\n\n".join([
            f"[Chunk {c.chunk_index + 1} from '{c.file_name}']:\n{c.text}"
            for c in context_chunks
        ])

        user_message = f"""TASK: Answer the following question about {', '.join(file_names)}

QUESTION: {question}

CONTEXT (retrieved from the actual documents):
---
{formatted_context}
---

Answer the question using ONLY the context provided above. If the answer is not in the context, say so explicitly."""

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]

    def build_folder_summary_prompt(
        self,
        folder_name: str,
        file_summaries: str,
        file_count: int
    ) -> List[dict]:
        
        user_message = f"""TASK: Create a high-level summary of the folder "{folder_name}" containing {file_count} files.

INDIVIDUAL FILE SUMMARIES:
---
{file_summaries}
---

INSTRUCTIONS:
- Synthesize the individual summaries into a coherent overview of the folder.
- Identify common themes, patterns, and key takeaways across all files.
- Organize by topic or theme, not by individual file.
- Only use information from the provided summaries above.

Generate the folder summary now."""

        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_message}
        ]
```

---

### 4.8 LLM Integration

```python
# services/llm.py
import openai
from typing import List, Optional

class LLMService:
    """Production LLM integration with fallback, retry, and cost tracking."""

    PRIMARY_MODEL = "gpt-4o"              # Best quality
    FALLBACK_MODEL = "gpt-4o-mini"        # Cost-effective fallback
    EMBEDDING_MODEL = "text-embedding-3-small"  # 1536 dimensions

    def __init__(self):
        self.client = openai.AsyncOpenAI()
        self.total_tokens_used = 0
        self.total_cost_usd = 0.0

    async def generate(
        self,
        messages: List[dict],
        temperature: float = 0.1,       # Low temp for factual accuracy
        max_tokens: int = 2000,
        model: Optional[str] = None
    ) -> str:
        model = model or self.PRIMARY_MODEL

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                top_p=0.9,
            )

            # Track usage
            usage = response.usage
            self.total_tokens_used += usage.total_tokens
            self._track_cost(model, usage)

            return response.choices[0].message.content

        except openai.RateLimitError:
            # Fallback to cheaper model
            if model != self.FALLBACK_MODEL:
                return await self.generate(
                    messages, temperature, max_tokens,
                    model=self.FALLBACK_MODEL
                )
            raise

        except openai.APIError as e:
            logger.error(f"LLM API Error: {e}")
            raise

    async def embed(self, text: str) -> List[float]:
        response = await self.client.embeddings.create(
            model=self.EMBEDDING_MODEL,
            input=text
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Batch embedding for efficiency."""
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = await self.client.embeddings.create(
                model=self.EMBEDDING_MODEL,
                input=batch
            )
            all_embeddings.extend([d.embedding for d in response.data])
        return all_embeddings

    def _track_cost(self, model: str, usage):
        """Track costs per model."""
        # Pricing as of 2026 (adjust as needed)
        pricing = {
            "gpt-4o": {"input": 2.5 / 1_000_000, "output": 10.0 / 1_000_000},
            "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
        }
        if model in pricing:
            cost = (
                usage.prompt_tokens * pricing[model]["input"] +
                usage.completion_tokens * pricing[model]["output"]
            )
            self.total_cost_usd += cost
```

#### Cost Estimation Table

| Operation | Model | Tokens | Cost per 1K ops |
|---|---|---|---|
| File summary (10 pages) | gpt-4o | ~4000 in + 1000 out | ~$0.02 |
| File summary (10 pages) | gpt-4o-mini | ~4000 in + 1000 out | ~$0.0012 |
| Folder summary (20 files) | gpt-4o | ~8000 in + 2000 out | ~$0.04 |
| Embedding (1 chunk) | text-embedding-3-small | ~512 | ~$0.00001 |
| Embedding (100 chunks) | text-embedding-3-small | ~51200 | ~$0.001 |

> [!TIP]
> Use `gpt-4o-mini` for initial file-level summaries in map-reduce, and `gpt-4o` for the final reduction and folder-level synthesis. This reduces costs by ~80% with minimal quality loss.

---

### 4.9 Response Validation Layer

**Purpose**: Detect hallucinations and ensure grounding.

```python
# services/validator.py
class ResponseValidator:
    GROUNDING_THRESHOLD = 0.6      # Minimum grounding score
    HALLUCINATION_KEYWORDS = [
        "as an AI",
        "I don't have access",
        "based on my training",
        "I believe",
        "in general",          # Signals non-grounded response
    ]

    async def validate(
        self,
        response: str,
        source_chunks: List[RetrievedChunk],
        intent: Intent
    ) -> ValidationResult:
        
        checks = await asyncio.gather(
            self._check_grounding(response, source_chunks),
            self._check_hallucination_signals(response),
            self._check_citation_accuracy(response, source_chunks),
        )

        grounding_score, hallucination_flags, citation_check = checks

        is_valid = (
            grounding_score >= self.GROUNDING_THRESHOLD
            and not hallucination_flags
            and citation_check.all_valid
        )

        return ValidationResult(
            is_valid=is_valid,
            grounding_score=grounding_score,
            hallucination_flags=hallucination_flags,
            citation_accuracy=citation_check,
            recommendation="accept" if is_valid else "regenerate"
        )

    async def _check_grounding(
        self,
        response: str,
        source_chunks: List[RetrievedChunk]
    ) -> float:
        """
        Check what percentage of response claims are supported by source.
        Uses sentence-level embedding similarity.
        """
        response_sentences = self._split_sentences(response)
        source_text = " ".join([c.text for c in source_chunks])
        source_embedding = await self.llm.embed(source_text)

        grounded_count = 0
        for sentence in response_sentences:
            if self._is_structural(sentence):
                grounded_count += 1
                continue
            sent_embedding = await self.llm.embed(sentence)
            similarity = self._cosine_similarity(sent_embedding, source_embedding)
            if similarity >= 0.7:
                grounded_count += 1

        return grounded_count / max(len(response_sentences), 1)

    async def _check_hallucination_signals(self, response: str) -> List[str]:
        """Flag responses containing known hallucination patterns."""
        flags = []
        for keyword in self.HALLUCINATION_KEYWORDS:
            if keyword.lower() in response.lower():
                flags.append(f"Contains: '{keyword}'")
        return flags
```

---

### 4.10 API Endpoints

```python
# routers/query.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["query"])

class QueryRequest(BaseModel):
    text: str
    conversation_id: str | None = None

class QueryResponse(BaseModel):
    answer: str
    sources: list[dict]
    grounding_score: float
    cached: bool
    processing_time_ms: float

@router.post("/query", response_model=QueryResponse)
async def handle_query(
    request: QueryRequest,
    current_user: User = Depends(get_current_user)
):
    start = time.time()

    # 1. Parse query
    parsed = query_parser.parse(request.text)

    # 2. Route and process
    result = await query_router.route(parsed, user_email=current_user.email)

    # 3. Validate
    validation = await validator.validate(
        result.answer, result.source_chunks, parsed.intent
    )

    if not validation.is_valid:
        # Regenerate with stricter prompt
        result = await query_router.route(
            parsed, user_email=current_user.email, strict_mode=True
        )

    return QueryResponse(
        answer=result.answer,
        sources=[{"file": c.file_name, "chunk": c.chunk_index} for c in result.source_chunks],
        grounding_score=validation.grounding_score,
        cached=result.from_cache,
        processing_time_ms=(time.time() - start) * 1000
    )

@router.get("/autocomplete")
async def autocomplete_mentions(
    q: str,
    current_user: User = Depends(get_current_user)
):
    """Typeahead for @mentions."""
    results = await resolution_service.search_files(
        query=q,
        user_email=current_user.email,
        limit=10
    )
    return [
        {"name": r.name, "type": "folder" if r.is_folder else "file", "id": r.drive_file_id}
        for r in results
    ]

@router.post("/ingest")
async def trigger_ingestion(
    file_ids: list[str],
    current_user: User = Depends(get_current_user)
):
    """Manually trigger ingestion for specific files."""
    tasks = []
    for fid in file_ids:
        task = ingest_file.delay(fid, current_user.email)
        tasks.append({"file_id": fid, "task_id": task.id})
    return {"status": "queued", "tasks": tasks}

@router.post("/webhook/drive")
async def drive_webhook(request: Request):
    """Handle Google Drive push notifications for file changes."""
    change_data = await request.json()
    for change in change_data.get("changes", []):
        file_id = change.get("fileId")
        if file_id:
            ingest_file.delay(file_id, change.get("ownerEmail"))
    return {"status": "accepted"}
```

---

## 5. Technology Stack

### 5.1 Complete Stack

| Layer | Technology | Justification |
|---|---|---|
| **Backend Framework** | FastAPI (Python 3.12+) | Async-native, Pydantic validation, auto-docs |
| **Task Queue** | Celery + Redis | Battle-tested async job processing |
| **Primary Database** | PostgreSQL 16 | ACID, pg_trgm for fuzzy search, JSON support |
| **Vector Database** | Qdrant (self-hosted) or Pinecone (managed) | Qdrant: open-source, excellent filtering. Pinecone: zero-ops. |
| **Cache** | Redis 7+ | Response caching, rate limiting, pub/sub |
| **LLM Provider** | OpenAI (primary), Anthropic (fallback) | GPT-4o for quality, Claude for long-context |
| **Embedding Model** | `text-embedding-3-small` (OpenAI) | Good quality/cost ratio, 1536 dimensions |
| **Reranker** | Cohere Rerank v3 | Improves retrieval precision by 20-30% |
| **File Storage** | Google Drive API v3 | Source of truth for files |
| **Monitoring** | Prometheus + Grafana | Latency, token usage, error rates |
| **Logging** | Structured JSON (Loki) | Queryable, correlation IDs |
| **Frontend** | React + TypeScript | Existing codebase compatibility |

### 5.2 Environment Configuration

```env
# .env.production
# LLM
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Vector DB
QDRANT_HOST=qdrant.internal
QDRANT_PORT=6333
QDRANT_COLLECTION=document_chunks

# Database
DATABASE_URL=postgresql+asyncpg://user:pass@db.internal:5432/summarization

# Cache
REDIS_URL=redis://redis.internal:6379/0

# Google
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...

# Reranker
COHERE_API_KEY=...

# Performance
MAX_CONCURRENT_LLM_CALLS=10
EMBEDDING_BATCH_SIZE=100
SUMMARY_CACHE_TTL_SECONDS=3600
MAX_FILE_SIZE_MB=50
```

---

## 6. Scaling Strategy

### 6.1 Performance Optimization Matrix

| Bottleneck | Solution | Impact |
|---|---|---|
| Repeated summaries | Redis cache (TTL 1hr) | 80% cache hit rate expected |
| Large file embedding | Batch embedding API | 10x throughput vs. sequential |
| Folder with 1000 files | Parallel file summaries (10 concurrent) | Linear speedup |
| Slow re-indexing | Content hash comparison (skip unchanged) | 90% fewer re-ingestions |
| LLM rate limits | Request queuing + model fallback | Zero failed requests |
| Token limits exceeded | Map-Reduce chunked summarization | Handles unlimited file sizes |

### 6.2 Scaling Tiers

```
┌────────────────────────────────────────────────────────────┐
│ TIER 1: Startup (< 10K documents)                          │
│ • Single FastAPI instance                                  │
│ • PostgreSQL (single node)                                 │
│ • Qdrant (single node, Docker)                             │
│ • Redis (single node)                                      │
│ • 1-2 Celery workers                                       │
│ • Estimated cost: $100-300/month                           │
├────────────────────────────────────────────────────────────┤
│ TIER 2: Growth (10K - 1M documents)                        │
│ • FastAPI behind load balancer (3 replicas)                │
│ • PostgreSQL with read replicas                            │
│ • Qdrant cluster (3 nodes, sharded)                        │
│ • Redis cluster                                            │
│ • 5-10 Celery workers (auto-scaling)                       │
│ • Pinecone instead of self-hosted Qdrant                   │
│ • Estimated cost: $500-2000/month                          │
├────────────────────────────────────────────────────────────┤
│ TIER 3: Enterprise (1M+ documents)                         │
│ • Kubernetes orchestration                                 │
│ • PostgreSQL (Aurora/Cloud SQL)                            │
│ • Pinecone Serverless                                      │
│ • Redis Cluster (ElastiCache)                              │
│ • Celery workers on K8s (HPA)                              │
│ • Dedicated LLM endpoints (provisioned throughput)         │
│ • CDN for cached responses                                 │
│ • Estimated cost: $2000-10000/month                        │
└────────────────────────────────────────────────────────────┘
```

### 6.3 Caching Architecture

```python
# Cache hierarchy (fastest → slowest)
class CacheManager:
    """Three-tier cache for maximum performance."""

    async def get_summary(self, cache_key: str) -> Optional[str]:
        # L1: In-memory (process-local, 100ms TTL)
        result = self.local_cache.get(cache_key)
        if result:
            return result

        # L2: Redis (shared, 1hr TTL)
        result = await self.redis.get(cache_key)
        if result:
            self.local_cache.set(cache_key, result, ttl=100)
            return result

        # L3: PostgreSQL (persistent, never expires)
        result = await self.db.get_cached_summary(cache_key)
        if result:
            await self.redis.set(cache_key, result, ex=3600)
            self.local_cache.set(cache_key, result, ttl=100)
            return result

        return None  # Cache miss — generate fresh
```

---

## 7. Risks & Mitigations

| Risk | Severity | Probability | Mitigation |
|---|---|---|---|
| **LLM hallucination** | 🔴 Critical | Medium | Multi-layer validation, strict prompts, citation enforcement |
| **Ambiguous @mentions** | 🟡 Medium | High | Disambiguation UI, fuzzy matching with confirmation |
| **Token limit exceeded** | 🟡 Medium | Medium | Map-Reduce summarization, dynamic chunk selection |
| **Google Drive API rate limits** | 🟡 Medium | Medium | Exponential backoff, request batching, webhook-based updates |
| **Stale summaries** | 🟢 Low | High | TTL-based cache, Drive webhooks for invalidation |
| **Large folder (10K+ files)** | 🔴 Critical | Low | Progressive summarization, sampling strategy, user warning |
| **Permission leakage** | 🔴 Critical | Low | Permission check at resolution time, never cache across users |
| **Cost explosion** | 🟡 Medium | Medium | Token budgets, model tiering, aggressive caching |
| **Embedding drift** | 🟢 Low | Low | Version embeddings, re-index on model change |

### Detailed Mitigation: Large Folders

```python
class LargeFolderStrategy:
    MAX_FILES_FULL_SUMMARY = 100
    SAMPLING_THRESHOLD = 500

    async def handle_large_folder(self, folder_id: str, file_count: int):
        if file_count <= self.MAX_FILES_FULL_SUMMARY:
            # Full summarization
            return await self.summarizer.summarize_folder(folder_id)
        
        elif file_count <= self.SAMPLING_THRESHOLD:
            # Summarize most recent / most important files
            files = await self.db.get_files_in_folder(
                folder_id,
                order_by="last_modified DESC",
                limit=self.MAX_FILES_FULL_SUMMARY
            )
            summary = await self.summarizer.summarize_files(files)
            return f"⚠️ This folder contains {file_count} files. " \
                   f"Showing summary of the {len(files)} most recent:\n\n{summary}"
        
        else:
            # Statistical overview + sampled summary
            stats = await self._compute_folder_stats(folder_id)
            sample = await self._smart_sample(folder_id, n=50)
            summary = await self.summarizer.summarize_files(sample)
            return f"📊 Folder Overview ({file_count} files):\n{stats}\n\n" \
                   f"📝 Sample Summary:\n{summary}"
```

---

## 8. Bonus: Improvements Beyond Google Drive

### 8.1 Advanced Anti-Hallucination Techniques

| Technique | Description | Implementation Effort |
|---|---|---|
| **Dual-LLM Verification** | Use a second LLM to verify the first's output against source | Medium |
| **Extractive + Abstractive Hybrid** | First extract key sentences, then abstract | Low |
| **Confidence Scoring** | LLM self-reports confidence per claim (logprobs) | Low |
| **Semantic Entailment** | NLI model checks if response is entailed by source | Medium |
| **User Feedback Loop** | Users flag inaccurate summaries → fine-tune prompts | High |

### 8.2 UX Enhancements for @Mentions

```
1. TYPEAHEAD AUTOCOMPLETE
   User types: "summarize @Q4"
   System shows: dropdown with matching files, icons, last modified dates

2. INLINE PREVIEWS
   User hovers @Q4-Report in chat
   System shows: file preview card (name, type, size, last modified)

3. MULTI-SELECT
   User types: "compare @file1 vs @file2"
   System shows: side-by-side comparison UI

4. SMART SUGGESTIONS
   After opening a folder, system suggests:
   "Would you like me to summarize this folder? (47 files, ~2.3 MB)"

5. PROGRESSIVE DISCLOSURE
   For large summaries, show:
   • One-line TLDR
   • Expandable key findings
   • Full summary on demand
   • Source citations at the bottom
```

### 8.3 Future Capabilities

| Capability | Description |
|---|---|
| **Cross-file Q&A** | "What changed between @v1 and @v2 of the report?" |
| **Scheduled Summaries** | "Email me a summary of @Inbox every Monday" |
| **Multi-modal** | OCR for images, transcription for audio/video files |
| **Collaborative Annotations** | Team members annotate summaries, corrections feed back |
| **Compliance Mode** | Audit trail of every LLM input/output for regulated industries |

---

## 9. Implementation Timeline

| Phase | Duration | Deliverables |
|---|---|---|
| **Phase 1: Foundation** | 2 weeks | Query parser, resolution service, DB schema, basic ingestion |
| **Phase 2: RAG Core** | 2 weeks | Chunking, embedding, vector store, basic retrieval |
| **Phase 3: Summarization** | 2 weeks | File summary, folder summary, prompt builder |
| **Phase 4: Validation** | 1 week | Grounding checks, hallucination detection |
| **Phase 5: UX** | 2 weeks | @mention autocomplete, chat UI, progressive disclosure |
| **Phase 6: Production** | 2 weeks | Caching, monitoring, error handling, load testing |
| **Phase 7: Scale** | Ongoing | Performance optimization, model tuning, cost reduction |

**Total MVP**: ~8-10 weeks with a team of 2-3 engineers.

---

> [!NOTE]
> This plan is designed to be **incrementally implementable**. Start with Phase 1-3 for a working prototype, then layer on validation, caching, and scaling as usage grows. Each component is independently testable and deployable.
