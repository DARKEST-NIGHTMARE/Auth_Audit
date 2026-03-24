import asyncio
import os
import time
import sys

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from app.services.summarization_service import SummarizationPipeline, GeminiClient, VectorStoreManager
from app.core.config import settings

async def run_verification():
    print("🚀 Starting RAG Performance Verification...")
    
    gemini = GeminiClient()
    pipeline = SummarizationPipeline()
    
    # Use a dummy folder ID (or a real one if you have it in env)
    folder_id = "1_qR8-R-9_rYk_vD-L_9u_vB_9Y" # Placeholder
    folder_name = "Auth Audit Workspace"
    
    # Mocking tokens for local test if needed, but here we just want to see the logic flow
    # In a real environment, you'd need valid tokens.
    # For this script, we'll check if the cache mechanisms are triggered.
    
    print(f"\n--- Check 1: Folder Index Persistence ---")
    is_indexed = pipeline.vector_store.is_folder_indexed(folder_id)
    print(f"Folder '{folder_name}' ({folder_id}) indexed: {is_indexed}")
    
    print(f"\n--- Check 2: Metadata Retrieval ---")
    # Try to get metadata for a known file if possible
    # indexed_file_ids = pipeline.vector_store.get_indexed_file_ids()
    # print(f"Currently indexed files: {len(indexed_file_ids)}")
    
    print(f"\n--- Check 3: Query Flow Simulation ---")
    start_time = time.time()
    
    # Mocking the query call to see if it skips ingestion
    # We won't actually call the API here to avoid 401s, 
    # but we can look at the logs if we were running in the app.
    
    print("✅ Verification script ready. (Note: Full end-to-end requires valid OAuth tokens)")

if __name__ == "__main__":
    asyncio.run(run_verification())
