import os
import sys
import shutil

# Add current directory to path so app can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from app.services.summarization.vector_store import VectorStoreManager
    from app.services.summarization.ai_clients import GeminiClient
    from app.core.config import settings
except ImportError as e:
    print(f"Error: Could not import app modules. Ensure you are running from the backend root. {e}")
    sys.exit(1)

def reset():
    print("🚀 Starting Vector Database Reset...")
    
    # 1. Initialize manager
    gemini = GeminiClient()
    vsm = VectorStoreManager(gemini)
    
    # 2. Run internal purge (clears collection and folder_index.json)
    success = vsm.clear_all_data()
    
    # 3. Force delete chroma directories to ensure binary artifacts are gone
    # BASE_DIR would be the parent of 'app', so it's the current directory if run from 'backend/'
    base_dir = os.path.dirname(os.path.abspath(__file__))
    paths_to_wipe = [
        os.path.join(base_dir, "chroma_data"),
        os.path.join(base_dir, "chroma_db")
    ]
    
    for p in paths_to_wipe:
        if os.path.exists(p):
            try:
                print(f"📁 Removing physical directory: {p}")
                # We use rmtree but keep the folder itself if we want to be safe, 
                # though Chroma will recreate it.
                shutil.rmtree(p)
                os.makedirs(p, exist_ok=True) # Recreate empty
            except Exception as e:
                print(f"⚠️ Warning: Could not remove {p}: {e}")
            
    if success:
        print("\n✨ SUCCESS: Vector database and folder index have been purged.")
        print("💡 You can now restart the backend and re-index your folders.")
    else:
        print("\n❌ PARTIAL SUCCESS: Directories wiped but internal purge reported errors.")

if __name__ == "__main__":
    reset()
