import os
import json
import asyncio
import hashlib
import re
from typing import List, Optional, Dict, Any
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

        # 4. Strategy C: Boundary-based field extraction
        res = {"summary": "", "suggested_questions": []}
        summary_start = re.search(r'"summary":\s*"', text, re.I)
        if summary_start:
            start_pos = summary_start.end()
            marker = re.search(r'",\s*"suggested_questions"', text[start_pos:], re.I)
            if marker:
                res["summary"] = text[start_pos : start_pos + marker.start()].strip()
                questions_text = text[start_pos + marker.end():]
                res["suggested_questions"] = re.findall(r'"([^"]{10,}\?)"', questions_text)
            else:
                last_brace = text.rfind("}")
                if last_brace > start_pos:
                    res["summary"] = text[start_pos : last_brace].strip()
        
        if not res["summary"] or len(res["summary"]) < 50:
            res["summary"] = text
            res["suggested_questions"] = re.findall(r'"([^"]{10,}\?)"', text)

        summary_val = res.get("summary", "")
        if isinstance(summary_val, str):
            res["summary"] = summary_val.replace('\\"', '"').replace('\\n', '\n')
            
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
        return "\n\n".join([d[1] for d in all_docs])

    async def ingest_file(self, file_id: str, file_name: str, access_token: str, refresh_token: str = None, folder_id: Optional[str] = None) -> dict:
        try:
            from app.services.google_drive_service import drive_service
            meta = drive_service.get_file_metadata(file_id, access_token, refresh_token)
            mime_type = meta.get('mimeType', '')
            indexed_meta = self.vector_store.get_file_metadata_from_index(file_id)
            drive_modified = meta.get('modifiedTime')
            
            if indexed_meta and drive_modified == indexed_meta.get('last_modified'):
                return {"status": "indexed", "file": file_name, "reason": "fast_skip"}

            content = drive_service.download_file_bytes(file_id, access_token, refresh_token)
            if not content:
                return {"status": "error", "reason": "download_failed", "file": file_name}
            
            content_hash = hashlib.md5(content).hexdigest()
            if indexed_meta and content_hash == indexed_meta.get('content_hash'):
                return {"status": "indexed", "file": file_name, "reason": "hash_match"}

            text = await self.extractor.extract_from_bytes(content, mime_type, file_name)
            if not text or len(text.strip()) < 10:
                return {"status": "skipped", "reason": "too_short", "file": file_name}

            doc_type = await self._classify_document_type(text)
            chunks = self.chunker.chunk_text(text, file_id, file_name)
            self.vector_store.add_chunks(chunks, folder_id=folder_id, last_modified=drive_modified)
            
            self._summary_cache[f"{file_id}_type"] = doc_type
            self._summary_cache.pop(file_id, None)
            return {"status": "indexed", "file": file_name, "chunks": len(chunks)}
        except Exception as e:
            logger.error(f"Ingest failure for {file_id}: {e}")
            return {"status": "error", "error": str(e)}

    async def ingest_folder(self, folder_id: str, access_token: str, refresh_token: str = None) -> dict:
        from app.services.google_drive_service import drive_service
        try:
            if self.vector_store.is_folder_indexed(folder_id):
                return {"status": "complete", "message": "cached", "indexed": 0}

            service = drive_service.get_client(access_token, refresh_token)
            query = f"'{folder_id}' in parents and trashed=false"
            results = service.files().list(q=query, fields="files(id, name, mimeType)", pageSize=200).execute()
            files = results.get("files", [])
            
            ingestion_results = []
            for f in files:
                if "folder" in f.get("mimeType", ""):
                    await self.ingest_folder(f["id"], access_token, refresh_token)
                else:
                    res = await self.ingest_file(f["id"], f["name"], access_token, refresh_token, folder_id=folder_id)
                    ingestion_results.append(res)

            self.vector_store.mark_folder_indexed(folder_id)
            indexed = sum(1 for r in ingestion_results if r.get("status") == "indexed")
            return {"status": "complete", "indexed": indexed}
        except Exception as e:
            logger.error(f"Folder ingest error: {e}")
            return {"status": "error", "error": str(e)}

    async def query(self, text: str, folders: list, access_token: str, refresh_token: str = None) -> dict:
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

        if not resolved_items:
            if parsed.intent == Intent.QUESTION:
                return await self._answer_question(parsed.remaining_text, [], [], folder_id=None)
            return {"answer": "Specify a file/folder to analyze.", "sources": []}

        for item in resolved_items:
            if item["type"] == "folder":
                if not self.vector_store.is_folder_indexed(item["id"]):
                    await self.ingest_folder(item["id"], access_token, refresh_token)
            elif not self.vector_store.is_file_indexed(item["id"]):
                await self.ingest_file(item["id"], item["name"], access_token, refresh_token)
        
        main_item = resolved_items[0]
        if parsed.intent == Intent.SUMMARIZE:
            if main_item["type"] == "folder":
                return await self._summarize_folder(main_item["id"], main_item["name"], access_token, refresh_token)
            return await self._summarize_file(main_item["id"], main_item["name"])
        
        all_ids = [it["id"] for it in resolved_items]
        all_names = [it["name"] for it in resolved_items]
        folder_id = main_item["id"] if main_item["type"] == "folder" else None
        return await self._answer_question(parsed.remaining_text, all_ids, all_names, folder_id=folder_id)

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

    async def _summarize_folder(self, folder_id: str, folder_name: str, access_token: str, refresh_token: str = None) -> dict:
        if folder_id in self._summary_cache: return self._summary_cache[folder_id]
        results = self.vector_store.query(f"summarize {folder_name}", folder_id=folder_id, top_k=30)
        chunks = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]
        
        if len(chunks) > 5:
            context = ""
            sources = set()
            for i, text in enumerate(chunks):
                fname = metas[i].get("file_name", "Unknown")
                context += f"--- {fname} ---\n{text}\n\n"
                sources.add(fname)
            prompt = self.prompt_builder.build_folder_summary_prompt(folder_name, context, len(sources))
            ans = await self._generate_with_fallback(prompt, PromptBuilder.SYSTEM_INSTRUCTION, folder_name, context[:2000])
            res = {"type": "folder_summary", "answer": json.dumps(self._parse_llm_json(ans)), "sources": [{"file": s} for s in sorted(list(sources))], "intent": "summarize"}
            self._summary_cache[folder_id] = res
            return res

        return {"answer": f"Sparse index for {folder_name}.", "sources": []}

    async def _answer_question(self, question: str, file_ids: List[str], file_names: List[str], folder_id: Optional[str] = None) -> dict:
        results = self.vector_store.query(question, file_ids=file_ids, folder_id=folder_id, top_k=10)
        if not results or not results.get("documents") or not results["documents"][0]:
            return {"answer": "No relevant content found.", "sources": []}
        docs, metas = results["documents"][0], results["metadatas"][0]
        ctx = "\n\n".join([f"[{m.get('file_name', 'unknown')}]: {doc}" for doc, m in zip(docs, metas)])
        prompt = self.prompt_builder.build_question_prompt(question, ctx, ", ".join(file_names))
        ans = await self._generate_with_fallback(prompt, PromptBuilder.SYSTEM_INSTRUCTION, "Search", ctx[:1000])
        seen_files = list({m.get("file_name", "unknown") for m in metas})
        return {"answer": json.dumps(self._parse_llm_json(ans)), "sources": [{"file": f} for f in seen_files], "intent": "question"}

summarization_pipeline = SummarizationPipeline()
