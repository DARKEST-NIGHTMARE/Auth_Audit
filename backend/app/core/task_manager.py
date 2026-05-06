import asyncio
import uuid
from typing import Dict, Any, Optional
from datetime import datetime

class TaskManager:
    """
    Manages an in-memory queue of AI summarization tasks.
    Uses asyncio.Queue for job distribution and a Semaphore for LLM concurrency control.
    """
    def __init__(self, max_concurrent_llm_calls: int = 5):
        self.queue = asyncio.Queue()
        self.semaphore = asyncio.Semaphore(max_concurrent_llm_calls)
        self.active_jobs: Dict[str, Any] = {}
        self.worker_task: Optional[asyncio.Task] = None

    async def enqueue_job(self, job_data: Dict[str, Any]) -> str:
        """Adds a job to the queue and returns the Job ID."""
        job_id = job_data.get("job_id") or str(uuid.uuid4())
        job_data["job_id"] = job_id
        job_data["enqueued_at"] = datetime.now().isoformat()
        
        await self.queue.put(job_data)
        return job_id

    async def get_next_job(self) -> Dict[str, Any]:
        """Pulls the next available job from the queue."""
        return await self.queue.get()

    def mark_job_done(self):
        """Signals that a job pulling was completed."""
        self.queue.task_done()

# Global instance to be initialized at startup
task_manager = TaskManager(max_concurrent_llm_calls=5)
