import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import update

from ...core.database import AsyncSessionLocal
from ...core.task_manager import task_manager
from ...models import QueryJob, QueryJobStatus
from .pipeline import SummarizationPipeline

logger = logging.getLogger(__name__)

async def process_job(job_data: dict):
    """
    Main worker process for a single job.
    Uses a semaphore to ensure only 5 concurrent LLM calls.
    """
    job_id = job_data["job_id"]
    user_id = job_data["user_id"]
    logger.info(f"Worker picked up job {job_id} for user {user_id}")
    
    # We use a context manager for the DB to ensure fresh sessions
    async with AsyncSessionLocal() as db:
        try:
            # 1. Mark as Processing
            await db.execute(
                update(QueryJob)
                .where(QueryJob.id == job_id)
                .values(status=QueryJobStatus.PROCESSING, updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

            # 2. Acquire Semaphore (Throttling)
            async with task_manager.semaphore:
                # We use the global summarization_pipeline instance
                from .pipeline import summarization_pipeline
                
                # Retrieve pre-fetched context from job_data
                context_chunks = job_data.get("chunks", [])
                query = job_data["query"]
                
                # 3. LLM Call with Retry Logic
                max_retries = 3
                retry_delay = 2 # seconds
                
                result = None
                last_error = None
                
                for attempt in range(max_retries):
                    try:
                        # Call the pipeline's internal LLM executor directly
                        # We avoid full re-embedding by passing chunks
                        result = await summarization_pipeline.generate_summary_from_chunks(
                            query=query,
                            chunks=context_chunks
                        )
                        break
                    except Exception as e:
                        last_error = str(e)
                        logger.warning(f"LLM retry {attempt+1}/{max_retries} for job {job_id}: {e}")
                        await asyncio.sleep(retry_delay * (2 ** attempt)) # Exponential backoff
                
                if result:
                    # 4. Success: Store Result
                    await db.execute(
                        update(QueryJob)
                        .where(QueryJob.id == job_id)
                        .values(
                            status=QueryJobStatus.COMPLETED,
                            result=result,
                            updated_at=datetime.now(timezone.utc)
                        )
                    )
                else:
                    # 5. Failure after retries
                    await db.execute(
                        update(QueryJob)
                        .where(QueryJob.id == job_id)
                        .values(
                            status=QueryJobStatus.FAILED,
                            error=f"LLM failed after {max_retries} attempts: {last_error}",
                            updated_at=datetime.now(timezone.utc)
                        )
                    )
                
            await db.commit()
            
        except Exception as e:
            logger.error(f"Critical error in worker for job {job_id}: {e}")
            await db.execute(
                update(QueryJob)
                .where(QueryJob.id == job_id)
                .values(status=QueryJobStatus.FAILED, error=str(e))
            )
            await db.commit()
        finally:
            task_manager.mark_job_done()

async def worker_loop():
    """Infinite loop that pulls from task_manager queue."""
    logger.info("Summarization worker loop started.")
    while True:
        try:
            job_data = await task_manager.get_next_job()
            # Fire and forget the processing so we can pull the next job immediately
            # (Throttling happens inside process_job via the semaphore)
            asyncio.create_task(process_job(job_data))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in worker loop: {e}")
            await asyncio.sleep(1)
