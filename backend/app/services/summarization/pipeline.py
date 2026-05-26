import os
import json
import asyncio
import hashlib
import re
from typing import List, Optional, Dict, Any
try:
    from langsmith import traceable
except ImportError:
    def traceable(name=None, run_type=None, **kwargs):
        def decorator(func):
            return func
        return decorator

from app.logger import get_logger
from .ai_clients import GeminiClient, generate_text
from .document_processor import DocumentChunker, DocumentExtractor, DocumentType
from .vector_store import VectorStoreManager
from .query_parser import QueryParser, Intent
from .prompt_builder import PromptBuilder
from rapidfuzz import fuzz

logger = get_logger(__name__)

class SummarizationPipeline:
    """Main orchestrator: parse → resolve → ingest → retrieve → summarize."""

    def __init__(self):
        self.ai_client = GeminiClient()
        self.chunker = DocumentChunker()
        self.extractor = DocumentExtractor()
        self.vector_store = VectorStoreManager(self.ai_client)
        self.parser = QueryParser()
        self.prompt_builder = PromptBuilder()
        self._summary_cache: Dict[str, dict] = {}
        # LangGraph agent — lazy-loaded on first query
        self._graph = None

    async def _get_graph(self):
        """Async lazy-loader for the LangGraph agent."""
        if self._graph is None:
            try:
                from .graph.graphs import get_main_graph
                self._graph = await get_main_graph()
                logger.info("LangGraph agent initialized.")
            except Exception as e:
                logger.error(f"LangGraph initialization failed: {e}. Falling back to legacy pipeline.")
        return self._graph

    def _build_graph_state(self, text: str, folders: list, access_token: str,
                           refresh_token: str = None, pre_chunks: list = None) -> dict:
        """Build the initial GraphState from a query and context."""
        parsed = self.parser.parse(text)
        resolved_items = []
        for m in (parsed.mentions or []):
            matched = self._resolve_mention(m, folders)
            if matched:
                resolved_items.append({"id": matched["id"], "name": matched["name"],
                                       "type": "folder" if matched["is_folder"] else "file"})
        if not resolved_items:
            implicit = self._fuzzy_match_text_to_items(parsed.remaining_text, folders)
            if implicit:
                resolved_items.append({"id": implicit["id"], "name": implicit["name"],
                                       "type": "folder" if implicit["is_folder"] else "file"})
        intent_map = {"summarize": "summarize", "question": "question", "general": "question"}
        return {
            "query": text,
            "intent": intent_map.get(parsed.intent.value, "question"),
            "resolved_items": resolved_items,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "retrieved_chunks": pre_chunks or [],
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

    def _parse_llm_json(self, text: str) -> dict:
        """Robustly extracts JSON data from AI provider responses."""
        if not text:
            return {"summary": "Empty response from AI.", "suggested_questions": []}
            
        # 1. Attempt pure JSON extraction
        try:
            # Strip markdown if present
            clean = re.sub(r'```(?:json)?\s*', '', text)
            clean = re.sub(r'\s*```', '', clean).strip()
            
            # Isolate the JSON object
            start = clean.find('{')
            end = clean.rfind('}')
            if start != -1 and end != -1:
                json_candidate = clean[start:end+1]
                data = json.loads(json_candidate)
                if "summary" in data:
                    return {
                        "summary": str(data["summary"]),
                        "suggested_questions": data.get("suggested_questions", [])
                    }
        except Exception:
            pass

        # 2. Case-insensitive Regex fallbacks for partially broken JSON
        res = {"summary": "", "suggested_questions": []}
        
        # Match summary field (case-insensitive)
        s_match = re.search(r'["\']summary["\']:\s*["\'](.*?)["\'](?=,\s*["\']|\s*\})', text, re.I | re.S)
        if s_match:
            res["summary"] = s_match.group(1).replace('\\"', '"').replace('\\n', '\n')
        elif not res["summary"]:
            # Aggressive fallback
            s_match_alt = re.search(r'summary["\']?:\s*([\s\S]*?)(?=,?\s*["\']suggested|$)', text, re.I)
            if s_match_alt:
                res["summary"] = s_match_alt.group(1).strip().strip('"\'{},')

        # Match questions array (case-insensitive)
        q_match = re.search(r'["\']suggested_questions["\']:\s*\[([\s\S]*?)\]', text, re.I | re.S)
        if q_match:
            res["suggested_questions"] = re.findall(r'["\']([^"\']{5,}\?)["\']', q_match.group(1))

        # 3. Final recovery: If no summary extracted, return raw text cleaned up
        if not res["summary"] or len(res["summary"]) < 20:
            # Remove JSON-like artifacts from the start/end
            refined = text.strip().strip('{}').strip()
            # Strip leading key names if the LLM didn't format it right
            refined = re.sub(r'^"?summary"?:\s*"?', '', refined, flags=re.I)
            res["summary"] = refined
            
        return res

    async def _generate_with_fallback(self, prompt: str, system_instruction: str, file_name: str, fallback_text: str) -> str:
        """Unified generator with zero-API local fallback."""
        try:
            return await generate_text(prompt, system_instruction=system_instruction)
        except Exception as e:
            logger.warning(f"Generation failed for {file_name}. Using local extraction. Error: {e}")
            return self._local_extractive_summary(fallback_text, file_name)

    def _local_extractive_summary(self, text: str, file_name: str) -> str:
        """Generates a text-based extractive summary without any API calls."""
        # Detect if we are looking at raw binary data (PDF/DOCX fall-through)
        if text.startswith("%PDF") or b"\x00" in text[:100].encode("utf-8", "ignore"):
            snippet = "(Binary data detected. Summary unavailable. Please re-index this document.)"
        else:
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
        legal_keywords = ["appellant", "respondent", "judgment", "bench", "held", "supreme court", "act", "case no"]
        text_lower = text[:5000].lower()
        points = sum(2 for k in legal_keywords if k in text_lower)
        if points >= 6:
            return DocumentType.LEGAL_CASE
        try:
            prompt = f"Categorize as 'legal_case' or 'general_document'. Only return the label.\n\nTEXT:\n{text[:2000]}"
            label = (await generate_text(prompt)).strip().lower()
            return DocumentType.LEGAL_CASE if "legal_case" in label else DocumentType.GENERAL_DOCUMENT
        except Exception:
            return DocumentType.GENERAL_DOCUMENT

    def _generate_subqueries(self, doc_type: DocumentType, original_name: str) -> List[str]:
        if doc_type == DocumentType.LEGAL_CASE:
            return [f"comprehensive facts, issues, arguments, reasoning, and judgment in {original_name}"]
        return [f"main summary, key insights, and important findings in {original_name}"]

    async def _multi_query_retrieve(self, subqueries: List[str], file_id: str, top_k_per_query: int = 4) -> str:
        all_docs = []
        seen_ids = set()
        for query in subqueries:
            results = self.vector_store.query(query, file_ids=[file_id], top_k=top_k_per_query)
            if results and results["documents"]:
                for doc, metadata, id in zip(results["documents"][0], results["metadatas"][0], results["ids"][0]):
                    if id not in seen_ids:
                        seen_ids.add(id)
                        all_docs.append((metadata.get("chunk_index", 0), doc))
            await asyncio.sleep(0.5)
        all_docs.sort(key=lambda x: x[0])
        
        ctx = ""
        for _, doc in all_docs:
            if len(ctx) > 12000:
                break
            ctx += f"{doc}\n\n"
        return ctx

    @traceable(name="Ingest File", run_type="tool")
    async def ingest_file(self, file_id: str, file_name: str, access_token: str, refresh_token: str = None, folder_id: Optional[str] = None, drive_modified: Optional[str] = None, mime_type: Optional[str] = None) -> dict:
        try:
            from app.services.google_drive_service import drive_service
            
            if not drive_modified or not mime_type:
                meta = drive_service.get_file_metadata(file_id, access_token, refresh_token)
                mime_type = meta.get('mimeType', '')
                drive_modified = meta.get('modifiedTime')
                
            indexed_meta = self.vector_store.get_file_metadata(file_id)
            
            if indexed_meta and drive_modified == indexed_meta.get('last_modified'):
                # If content is same but folder changed, update metadata so it shows up in queries
                if folder_id and indexed_meta.get('folder_id') != folder_id:
                    logger.info(f"📁 Folder move detected for {file_name}. Updating metadata.")
                    self.vector_store.update_file_metadata(file_id, {"folder_id": folder_id})
                    return {"status": "metadata_updated", "file": file_name}
                
                return {"status": "unchanged", "file": file_name, "reason": "fast_skip"}

            content = drive_service.download_file_bytes(file_id, access_token, refresh_token)
            if not content:
                return {"status": "error", "reason": "download_failed", "file": file_name}
            
            content_hash = hashlib.md5(content).hexdigest()
            if indexed_meta and content_hash == indexed_meta.get('content_hash'):
                return {"status": "unchanged", "file": file_name, "reason": "hash_match"}

            text = await self.extractor.extract_from_bytes(content, mime_type, file_name)
            if not text or len(text.strip()) < 10:
                logger.warning(f"⚠️ Text extraction returned nearly empty content for {file_name}. (Possibly a scanned document without OCR)")
                return {"status": "skipped", "reason": "too_short_possibly_scanned", "file": file_name}

            doc_type = await self._classify_document_type(text)
            chunks = self.chunker.chunk_text(text, file_id, file_name)
            self.vector_store.add_chunks(
                chunks,
                folder_id=folder_id,
                last_modified=drive_modified,
            )

            self._summary_cache[f"{file_id}_type"] = doc_type
            self._summary_cache.pop(file_id, None)

            # Invalidate QueryCache so stale summaries are not returned
            try:
                from .graph.cache import query_cache
                cache_key = query_cache.make_key(file_name, [file_id], [])
                await query_cache.invalidate_summary(cache_key)
            except Exception:
                pass  # Cache invalidation is best-effort

            return {"status": "indexed", "file": file_name, "chunks": len(chunks),
                    "doc_type": doc_type.value if hasattr(doc_type, "value") else str(doc_type)}
        except Exception as e:
            logger.error(f"Ingest failure for {file_id}: {e}")
            return {"status": "error", "error": str(e)}

    @traceable(name="Ingest Folder", run_type="tool")
    async def ingest_folder(self, folder_id: str, access_token: str, refresh_token: str = None) -> dict:
        from app.services.google_drive_service import drive_service
        try:
            # Sync index state from disk to catch external resets (reset_db.py)
            self.vector_store._folder_index = self.vector_store._load_folder_index()

            service = drive_service.get_client(access_token, refresh_token)
            query = f"'{folder_id}' in parents and trashed=false"
            logger.info(f"📁 Scanning Folder ID: {folder_id} for changes...")
            
            results = service.files().list(
                q=query, 
                fields="files(id, name, mimeType, modifiedTime)", 
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            files = results.get("files", [])
            logger.info(f"🔍 Found {len(files)} items in folder {folder_id}")
            
            total_indexed = 0
            total_found = 0
            all_folder_ids = [folder_id]
            
            # Detect deleted files from Drive and prune them from ChromaDB
            current_file_ids = {f["id"] for f in files if "folder" not in f.get("mimeType", "")}
            indexed_file_ids = self.vector_store.get_indexed_file_ids_for_folder(folder_id)
            for old_id in indexed_file_ids:
                if old_id not in current_file_ids:
                    logger.info(f"🗑️ File {old_id} removed from Drive. Deleting chunks.")
                    self.vector_store.delete_file_chunks(old_id)
                    total_indexed += 1 # Count deletion as an index change to auto-invalidate caches

            for f in files:
                item_name = f.get("name", "Unknown")
                item_id = f.get("id")
                if "folder" in f.get("mimeType", ""):
                    logger.info(f"📁 Recursing into subfolder: {item_name} ({item_id})")
                    sub_res = await self.ingest_folder(item_id, access_token, refresh_token)
                    total_indexed += sub_res.get("indexed", 0)
                    total_found += sub_res.get("total_files", 0)
                    all_folder_ids.extend(sub_res.get("all_folder_ids", []))
                else:
                    logger.info(f"📄 Processing file: {item_name} ({item_id})")
                    res = await self.ingest_file(item_id, item_name, access_token, refresh_token, folder_id=folder_id, drive_modified=f.get("modifiedTime"), mime_type=f.get("mimeType"))
                    if res.get("status") in ["indexed", "metadata_updated"]:
                        logger.info(f"✅ Successfully processed: {item_name} (Status: {res.get('status')})")
                        total_indexed += 1
                    elif res.get("status") == "unchanged":
                        logger.info(f"⏭️ Skipping unchanged file: {item_name}")
                    else:
                        logger.warning(f"⚠️ Failed to index {item_name}: {res.get('error') or res.get('status')}")
                    total_found += 1

            if total_indexed > 0:
                logger.info(f"🔄 Detected {total_indexed} changes in {folder_id} tree. Invalidating local summary cache.")
                self._summary_cache.pop(folder_id, None)

            self.vector_store.mark_folder_indexed(folder_id)
            return {
                "status": "complete", 
                "indexed": total_indexed, 
                "total_files": total_found,
                "all_folder_ids": list(set(all_folder_ids))
            }
        except Exception as e:
            logger.error(f"Folder ingest error: {e}")
            return {"status": "error", "error": str(e), "all_folder_ids": [folder_id]}

    @traceable(name="Pipeline Query", run_type="chain")
    async def query(
        self,
        text: str,
        folders: list,
        access_token: str,
        refresh_token: str = None,
        user_id: str = None,
    ) -> dict:
        """Main entry point — delegates to the LangGraph agent."""
        graph = await self._get_graph()
        if graph is None:
            logger.warning("LangGraph unavailable. Using legacy pipeline.")
            return await self._legacy_query(text, folders, access_token, refresh_token)

        # Ingest any unindexed files first
        parsed = self.parser.parse(text)
        resolved_items = []
        for m in (parsed.mentions or []):
            matched = self._resolve_mention(m, folders)
            if matched:
                resolved_items.append({"id": matched["id"], "name": matched["name"],
                                       "type": "folder" if matched["is_folder"] else "file"})
        if not resolved_items:
            implicit = self._fuzzy_match_text_to_items(parsed.remaining_text or text, folders)
            if implicit:
                resolved_items.append({"id": implicit["id"], "name": implicit["name"],
                                       "type": "folder" if implicit["is_folder"] else "file"})

        # ── Conversation Memory: resolve follow-up context ──────────────
        conversation_history = ""
        if user_id:
            try:
                from .graph.memory import conversation_memory
                resolved_items = await conversation_memory.resolve_implicit_context(
                    user_id=str(user_id),
                    query=text,
                    current_resolved_items=resolved_items,
                )
                history_turns = await conversation_memory.get_history(str(user_id))
                conversation_history = conversation_memory.build_history_context(history_turns)
            except Exception as e:
                logger.warning(f"Memory resolve failed: {e}")

        for item in resolved_items:
            if item["type"] == "folder":
                await self.ingest_folder(item["id"], access_token, refresh_token)
            elif not self.vector_store.is_file_indexed(item["id"]):
                await self.ingest_file(item["id"], item["name"], access_token, refresh_token)

        state = self._build_graph_state(text, folders, access_token, refresh_token)
        state["user_id"] = str(user_id) if user_id else None
        state["conversation_history"] = conversation_history
        state["resolved_items"] = resolved_items  # Use memory-resolved items

        result = await graph.ainvoke(state)
        final = result.get("final_result") or {"answer": "No result produced.", "sources": []}

        # ── Record this turn in memory ──────────────────────────────────
        if user_id:
            try:
                from .graph.memory import conversation_memory
                parsed_res = {}
                try:
                    import json as _json
                    parsed_res = _json.loads(final.get("answer", "{}"))
                except Exception:
                    pass
                await conversation_memory.record_turn(
                    user_id=str(user_id),
                    query=text,
                    resolved_items=resolved_items,
                    doc_type=final.get("type"),
                    summary=parsed_res.get("summary", ""),
                    source_files=[s.get("file", "") for s in final.get("sources", [])],
                )
            except Exception as e:
                logger.warning(f"Memory record failed: {e}")

        return final

    def _fuzzy_match_text_to_items(self, text: str, items: list) -> Optional[dict]:
        if not text or len(text) < 3: return None
        best_match, best_score = None, 0
        for item in items:
            name = item["name"].lower()
            score = 80 if (name in text.lower() or text.lower() in name) else fuzz.partial_ratio(name, text.lower())
            if score > best_score and score >= 75:
                best_score = score
                best_match = {"id": item["id"], "name": item["name"], "is_folder": "folder" in item.get("mimeType", ""), "score": score}
        return best_match

    def _resolve_mention(self, mention: str, items: list) -> Optional[dict]:
        best_match, best_score = None, 0
        for item in items:
            score = max(fuzz.ratio(mention.lower(), item["name"].lower()), fuzz.partial_ratio(mention.lower(), item["name"].lower()))
            if score > best_score and score >= 60:
                best_score = score
                best_match = {"id": item["id"], "name": item["name"], "is_folder": "folder" in item.get("mimeType", ""), "score": score}
        return best_match

    async def _summarize_file(self, file_id: str, file_name: str) -> dict:
        if file_id in self._summary_cache: return self._summary_cache[file_id]
        doc_type = self._summary_cache.get(f"{file_id}_type")
        if not doc_type:
            chunks_data = self.vector_store.get_all_chunks_for_file(file_id)
            if not chunks_data or not chunks_data.get("documents"):
                return {"answer": f"No content for '{file_name}'.", "sources": []}
            doc_type = await self._classify_document_type("\n".join(chunks_data["documents"][:5]))

        try:
            if doc_type == DocumentType.LEGAL_CASE:
                result = await self._legal_synthesis_flow(file_id, file_name)
            else:
                result = await self._general_summarization_flow(file_id, file_name)
            self._summary_cache[file_id] = result
            return result
        except Exception as e:
            return await self._fallback_summarization(file_id, file_name, str(e))

    async def _legal_synthesis_flow(self, file_id: str, file_name: str) -> dict:
        subqueries = self._generate_subqueries(DocumentType.LEGAL_CASE, file_name)
        chunks_text = await self._multi_query_retrieve(subqueries, file_id, top_k_per_query=5)
        prompt = self.prompt_builder.LEGAL_ALL_IN_ONE_PROMPT.format(chunks_text=chunks_text, json_instruction=self.prompt_builder.JSON_FORMAT_INSTRUCTION)
        fallback = chunks_text[:1000] if (chunks_text and isinstance(chunks_text, str)) else "Legal document retrieval failed."
        res_text = await self._generate_with_fallback(prompt, PromptBuilder.LEGAL_SYSTEM_INSTRUCTION, file_name, fallback)
        parsed = self._parse_llm_json(res_text)
        return {"type": "legal_case", "answer": json.dumps(parsed), "sources": [{"file": file_name, "type": "legal"}], "intent": "summarize"}

    async def _general_summarization_flow(self, file_id: str, file_name: str) -> dict:
        subqueries = self._generate_subqueries(DocumentType.GENERAL_DOCUMENT, file_name)
        chunks_text = await self._multi_query_retrieve(subqueries, file_id, top_k_per_query=5)
        prompt = self.prompt_builder.build_general_summary_prompt(file_name, chunks_text)
        fallback = chunks_text[:1000] if (chunks_text and isinstance(chunks_text, str)) else "General document retrieval failed."
        res_text = await self._generate_with_fallback(prompt, PromptBuilder.GENERAL_SYSTEM_INSTRUCTION, file_name, fallback)
        parsed = self._parse_llm_json(res_text)
        return {"type": "general_document", "answer": json.dumps(parsed), "sources": [{"file": file_name, "type": "general"}], "intent": "summarize"}

    async def _fallback_summarization(self, file_id: str, file_name: str, error: str) -> dict:
        chunks_data = self.vector_store.get_all_chunks_for_file(file_id)
        text = "\n\n".join(chunks_data["documents"][:10])
        prompt = f"Summarize {file_name} from snippets: {text}\n\n{PromptBuilder.JSON_FORMAT_INSTRUCTION}"
        try:
            ans = await generate_text(prompt)
        except Exception:
            ans = self._local_extractive_summary(text, file_name)
        return {"type": "fallback", "answer": json.dumps(self._parse_llm_json(ans)), "sources": [{"file": file_name, "type": "fallback"}]}

    async def _summarize_folder(self, folder_id: str, folder_name: str, access_token: str, refresh_token: str = None, all_folder_ids: Optional[List[str]] = None) -> dict:
        if folder_id in self._summary_cache: return self._summary_cache[folder_id]
        
        ids_to_query = all_folder_ids if all_folder_ids else [folder_id]
        where_filter = {"folder_id": folder_id} if len(ids_to_query) == 1 else {"folder_id": {"$in": ids_to_query}}

        # Get all chunks for the folder to ensure diverse representation
        # We set a high limit (500) to ensure we don't miss any files in a large tree
        results = self.vector_store.collection.get(
            where=where_filter,
            include=["documents", "metadatas"],
            limit=500
        )
        
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])
        
        if len(docs) > 0:
            from collections import defaultdict
            file_chunks = defaultdict(list)
            for doc, meta in zip(docs, metas):
                fname = meta.get("file_name", "Unknown")
                file_chunks[fname].append(doc)

            context = ""
            sources = set()
            
            # Sort files by name to ensure consistent summaries
            sorted_files = sorted(file_chunks.keys())
            for fname in sorted_files:
                chunks = file_chunks[fname]
                sources.add(fname)
                context += f"--- {fname} ---\n"
                # Take top 3 chunks per file for diversity
                for text in chunks[:3]:
                    if len(context) > 12000:
                        break
                    
                    if "%PDF" in text[:100]:
                        context += "[Binary content redacted for stability]\n\n"
                        continue
                        
                    context += f"{text}\n\n"
                if len(context) > 12000:
                    break
                
            prompt = self.prompt_builder.build_folder_summary_prompt(folder_name, context, len(sources))
            ans = await self._generate_with_fallback(prompt, PromptBuilder.SYSTEM_INSTRUCTION, folder_name, context[:2000])
            parsed = self._parse_llm_json(ans)
            res = {"type": "folder_summary", "answer": json.dumps(parsed), "sources": [{"file": s} for s in sorted(list(sources))], "intent": "summarize"}
            self._summary_cache[folder_id] = res
            return res

        return {"answer": f"Sparse index for {folder_name}.", "sources": []}

    async def _answer_question(self, question: str, file_ids: List[str], file_names: List[str], folder_id: Optional[Any] = None) -> dict:
        results = self.vector_store.query(question, file_ids=file_ids, folder_id=folder_id, top_k=10)
        if not results or not results.get("documents") or not results["documents"][0]:
            return {"answer": "No relevant content found.", "sources": []}
        docs, metas = results["documents"][0], results["metadatas"][0]
        
        ctx = ""
        seen_files = []
        for doc, meta in zip(docs, metas):
            if len(ctx) > 12000:
                break
            if "%PDF" in doc[:100] or b"\x00" in doc[:100].encode("utf-8", "ignore"):
                continue
                
            fname = meta.get("file_name", "unknown")
            if fname not in seen_files:
                seen_files.append(fname)
            ctx += f"[{fname}]: {doc}\n\n"
            
        files_str = ", ".join(seen_files) if seen_files else "Global Knowledge Base"
        prompt = self.prompt_builder.build_question_prompt(question, ctx, files_str)
        ans = await self._generate_with_fallback(prompt, PromptBuilder.SYSTEM_INSTRUCTION, "Search", ctx[:1000])
        return {"answer": json.dumps(self._parse_llm_json(ans)), "sources": [{"file": f} for f in seen_files], "intent": "question"}

    @traceable(name="Worker Execution", run_type="chain")
    async def generate_summary_from_chunks(self, query: str, chunks: List[Dict[str, Any]]) -> dict:
        """
        Worker-side entry point: takes pre-resolved context and makes the LLM call.
        """
        if not chunks:
            return {"answer": "No relevant content found.", "sources": []}

        # Build context string
        ctx = ""
        seen_files = []
        for chunk in chunks:
            fname = chunk.get("file_name", "unknown")
            if fname not in seen_files:
                seen_files.append(fname)
            ctx += f"[{fname}]: {chunk['document']}\n\n"
            if len(ctx) > 12000:
                break
        
        files_str = ", ".join(seen_files) if seen_files else "Knowledge Base"
        
        # Decide prompt based on query content (simple heuristic for now)
        if "summarize" in query.lower() or len(seen_files) == 1:
            prompt = self.prompt_builder.build_general_summary_prompt(files_str, ctx)
            system = PromptBuilder.GENERAL_SYSTEM_INSTRUCTION
        else:
            prompt = self.prompt_builder.build_question_prompt(query, ctx, files_str)
            system = PromptBuilder.SYSTEM_INSTRUCTION

        ans_text = await self._generate_with_fallback(prompt, system, "AsyncJob", ctx[:1000])
        parsed = self._parse_llm_json(ans_text)
        
        return {
            "answer": json.dumps(parsed),
            "sources": [{"file": f} for f in seen_files],
            "intent": "summarize" if "summarize" in query.lower() else "question"
        }

    async def _legacy_query(self, text: str, folders: list, access_token: str, refresh_token: str = None) -> dict:
        """Legacy linear pipeline — used only if LangGraph fails to load."""
        parsed = self.parser.parse(text)
        resolved_items = []
        if parsed.mentions:
            for m in parsed.mentions:
                matched = self._resolve_mention(m, folders)
                if matched:
                    resolved_items.append({"id": matched["id"], "name": matched["name"],
                                           "type": "folder" if matched["is_folder"] else "file"})
        if not resolved_items:
            implicit = self._fuzzy_match_text_to_items(parsed.remaining_text, folders)
            if implicit:
                resolved_items.append({"id": implicit["id"], "name": implicit["name"],
                                       "type": "folder" if implicit["is_folder"] else "file"})
        if not resolved_items:
            return await self._answer_question(parsed.remaining_text or text, [], [], folder_id=None)
        all_folder_ids = []
        for item in resolved_items:
            if item["type"] == "folder":
                res = await self.ingest_folder(item["id"], access_token, refresh_token)
                if "all_folder_ids" in res:
                    all_folder_ids.extend(res["all_folder_ids"])
            elif not self.vector_store.is_file_indexed(item["id"]):
                await self.ingest_file(item["id"], item["name"], access_token, refresh_token)
        main_item = resolved_items[0]
        if parsed.intent == Intent.SUMMARIZE:
            if main_item["type"] == "folder":
                return await self._summarize_folder(main_item["id"], main_item["name"],
                                                     access_token, refresh_token,
                                                     all_folder_ids=all_folder_ids)
            return await self._summarize_file(main_item["id"], main_item["name"])
        all_ids = [it["id"] for it in resolved_items]
        all_names = [it["name"] for it in resolved_items]
        target_folders = all_folder_ids if main_item["type"] == "folder" else None
        return await self._answer_question(parsed.remaining_text, all_ids, all_names,
                                           folder_id=target_folders)

    @traceable(name="Resolve Context", run_type="chain")
    async def get_query_context(self, text: str, folders: list, access_token: str, refresh_token: str = None, user_id: str = None) -> dict:
        """
        API-side entry point: resolves mentions, ingests if needed, and retrieves top 5 chunks.
        Returns a 'Job Package' for the worker.
        """
        parsed = self.parser.parse(text)
        resolved_items = []
        if parsed.mentions:
            for m in parsed.mentions:
                matched = self._resolve_mention(m, folders)
                if matched:
                    resolved_items.append({"id": matched["id"], "name": matched["name"], "type": "folder" if matched["is_folder"] else "file"})

        if not resolved_items:
            implicit = self._fuzzy_match_text_to_items(parsed.remaining_text, folders)
            if implicit:
                resolved_items.append({"id": implicit["id"], "name": implicit["name"], "type": "folder" if implicit["is_folder"] else "file"})

        # Ingest missing items
        all_folder_ids = []
        for item in resolved_items:
            if item["type"] == "folder":
                res = await self.ingest_folder(item["id"], access_token, refresh_token)
                if "all_folder_ids" in res:
                    all_folder_ids.extend(res["all_folder_ids"])
            elif not self.vector_store.is_file_indexed(item["id"]):
                await self.ingest_file(item["id"], item["name"], access_token, refresh_token)

        main_item = resolved_items[0] if resolved_items else None
        target_file_ids = [item["id"] for item in resolved_items if item["type"] == "file"]
        target_folder_ids = all_folder_ids if (main_item and main_item["type"] == "folder") else None
        
        query_str = parsed.remaining_text if parsed.remaining_text else text
        
        # Retrieve context (Top 5 relevant chunks as requested)
        results = self.vector_store.query(
            query_str, 
            file_ids=target_file_ids if target_file_ids else None, 
            folder_id=target_folder_ids if target_folder_ids else None, 
            top_k=5
        )
        
        chunks = []
        if results and results.get("documents") and results["documents"][0]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            for d, m in zip(docs, metas):
                chunks.append({
                    "document": d,
                    "file_name": m.get("file_name", "unknown"),
                    "file_id": m.get("file_id", "unknown")
                })

        return {
            "query": query_str,
            "chunks": chunks,
            "resolved_items": resolved_items,
            "cache_key": hashlib.md5(f"{query_str}:{target_file_ids}:{target_folder_ids}".encode()).hexdigest()
        }

summarization_pipeline = SummarizationPipeline()
