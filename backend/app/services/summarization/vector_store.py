import os
import json
import hashlib
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from app.logger import get_logger
from .ai_clients import GeminiClient, LocalEmbeddingClient
from .document_processor import Chunk

logger = get_logger(__name__)

class VectorStoreManager:
    """Manages ChromaDB for storing and querying document embeddings."""

    COLLECTION_NAME = "audit_documents"

    def __init__(self, gemini_client: GeminiClient):
        self._client = None
        self._collection = None
        self.gemini = gemini_client
        self.local_embedder = LocalEmbeddingClient()
        from app.core.config import BASE_DIR
        self._db_path = os.path.join(BASE_DIR, "chroma_data")
        self._folder_index_path = os.path.join(self._db_path, "folder_index.json")
        self._folder_index = self._load_folder_index()

    def _load_folder_index(self) -> Dict[str, Any]:
        """Load the persistent folder index state."""
        if os.path.exists(self._folder_index_path):
            try:
                with open(self._folder_index_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading folder index: {e}")
        return {}

    def _save_folder_index(self):
        """Save the persistent folder index state."""
        try:
            os.makedirs(self._db_path, exist_ok=True)
            with open(self._folder_index_path, 'w') as f:
                json.dump(self._folder_index, f)
        except Exception as e:
            logger.error(f"Error saving folder index: {e}")

    def is_folder_indexed(self, folder_id: str) -> bool:
        """Check if a folder is marked as fully indexed."""
        entry = self._folder_index.get(folder_id)
        return entry and entry.get("status") == "complete"

    def mark_folder_indexed(self, folder_id: str, status: str = "complete"):
        """Mark a folder as indexed in the persistent state."""
        self._folder_index[folder_id] = {
            "status": status,
            "last_updated": datetime.now().isoformat()
        }
        self._save_folder_index()

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

    def add_chunks(self, chunks: List[Chunk], folder_id: Optional[str] = None, last_modified: Optional[str] = None):
        """Store chunks with their embeddings + folder context."""
        if not chunks:
            return

        texts = [c.text for c in chunks]
        embeddings = self.gemini.embed_batch(texts)
        if not embeddings:
            logger.warning("Gemini embedding failed; attempting local fallback.")
            embeddings = self.local_embedder.embed_texts(texts)

        if not embeddings:
            logger.error("Failed to generate embeddings.")
            return

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
                "content_hash": content_hash 
            }
            if last_modified:
                m["last_modified"] = last_modified
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
                self._collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )
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

        if not results["documents"] or not results["documents"][0] or (results["distances"] and results["distances"][0][0] > 0.6):
            logger.info(f"Weak vector match for '{query_text}'. Triggering keyword fallback...")
            keyword_results = self._keyword_search_fallback(query_text, where_filter, top_k=top_k)
            if keyword_results["documents"] and keyword_results["documents"][0]:
                return keyword_results

        return results

    def _keyword_search_fallback(self, query_text: str, where_filter: Optional[dict] = None, top_k: int = 10) -> dict:
        """Basic keyword fallback via ChromaDB where_document contains."""
        keywords = [w for w in re.findall(r'\w+', query_text) if len(w) > 3]
        if not keywords:
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

        keywords.sort(key=len, reverse=True)
        primary_keyword = keywords[0]

        try:
            results = self.collection.query(
                query_texts=[query_text],
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
        if results and results["metadatas"]:
            combined = list(zip(results["ids"], results["documents"], results["metadatas"]))
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
        except Exception as e:
            logger.error(f"Error deleting chunks for {file_id}: {e}")

    def clear_all_data(self):
        """Purge the entire vector database and folder index."""
        try:
            # 1. Clear Chroma Collection
            count = self.collection.count()
            if count > 0:
                # We can't easily 'delete all' by filter in some versions, 
                # but we can delete by getting all IDs.
                all_ids = self.collection.get()["ids"]
                if all_ids:
                    self.collection.delete(ids=all_ids)
                logger.info(f"Purged {len(all_ids)} chunks from Chroma.")

            # 2. Reset Folder Index
            self._folder_index = {}
            if os.path.exists(self._folder_index_path):
                os.remove(self._folder_index_path)
                logger.info("Deleted folder_index.json")
            
            return True
        except Exception as e:
            logger.error(f"Failed to clear vector data: {e}")
            return False

    def get_indexed_file_ids(self) -> set:
        """Get all unique file_ids in the collection."""
        try:
            results = self.collection.get(include=["metadatas"])
            if results and results["metadatas"]:
                return {m["file_id"] for m in results["metadatas"] if "file_id" in m}
        except Exception:
            pass
        return set()

    def get_indexed_file_ids_for_folder(self, folder_id: str) -> set:
        """Get all unique file_ids indexed under a specific folder."""
        try:
            results = self.collection.get(where={"folder_id": folder_id}, include=["metadatas"])
            if results and results["metadatas"]:
                return {m["file_id"] for m in results["metadatas"] if "file_id" in m}
        except Exception as e:
            logger.error(f"Error getting file ids for folder: {e}")
        return set()

    def is_file_indexed(self, file_id: str, content_hash: Optional[str] = None, last_modified: Optional[str] = None) -> bool:
        """Check if file exists AND hash/modified_time matches if provided."""
        try:
            where = {"file_id": file_id}
            if content_hash:
                where["content_hash"] = content_hash
            if last_modified:
                where["last_modified"] = last_modified
            
            res = self.collection.get(where=where, limit=1)
            return len(res.get("ids", [])) > 0
        except Exception:
            return False

    def get_file_metadata_from_index(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored metadata for a file to perform fast-skip checks."""
        try:
            res = self.collection.get(where={"file_id": file_id}, limit=1, include=["metadatas"])
            if res and res["metadatas"]:
                return res["metadatas"][0]
        except Exception:
            pass
        return None
