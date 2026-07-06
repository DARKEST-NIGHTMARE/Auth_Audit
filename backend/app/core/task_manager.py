"""
TaskManager — Dual-Queue + Per-User Cap scheduler.

Design:
  • fast_queue  : Short queries, Q&A, single-file summaries (<3 files)
  • slow_queue  : Bulk folder ingestion, hierarchical summarization (≥3 files)
  • Worker always drains fast_queue first (Head-of-Line prevention).
  • Per-user cap (default 2): prevents one user from monopolising all slots.
  • Global semaphore (default 5): limits total concurrent LLM calls.
"""
import asyncio
import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

# ─── Job-type threshold ────────────────────────────────────────────────────────
# Jobs with fewer than this many resolved_items → fast_queue, otherwise slow_queue
FAST_JOB_ITEM_THRESHOLD = 3


def _classify_job(job_data: Dict[str, Any]) -> bool:
    """
    Returns True (fast) if the job looks lightweight.
    Heuristic: jobs with fewer resolved items or an explicit 'question' intent
    are fast; bulk folder ingestion / multi-file summarise jobs are slow.
    """
    resolved_items = job_data.get("resolved_items", [])
    chunks = job_data.get("chunks", [])
    intent = job_data.get("intent", "")

    # Explicit question-type intent is always fast regardless of chunks
    if intent in ("question", "qa"):
        return True

    # Classify by the number of distinct files/folders in scope
    item_count = len(resolved_items) if resolved_items else (
        len({c.get("file_id") for c in chunks if c.get("file_id")})
    )
    return item_count < FAST_JOB_ITEM_THRESHOLD


class DualQueueTaskManager:
    """
    Manages AI summarization jobs with two priority queues and per-user fairness.

    Queues:
      fast_queue  — lightweight Q&A and single-file queries
      slow_queue  — heavy multi-file / folder summarisation tasks

    The background worker always checks fast_queue first, ensuring that quick
    queries are never blocked behind long-running folder ingestions (Head-of-Line
    blocking prevention).

    Per-user cap: no user can have more than `max_per_user` jobs running
    simultaneously, so a single power-user cannot starve others.
    """

    def __init__(
        self,
        max_concurrent_llm_calls: int = 5,
        max_per_user: int = 2,
    ):
        # Two FIFO queues
        self.fast_queue: asyncio.Queue = asyncio.Queue()
        self.slow_queue: asyncio.Queue = asyncio.Queue()

        # Global LLM concurrency limiter (rate-limit guard)
        self.semaphore = asyncio.Semaphore(max_concurrent_llm_calls)

        # Per-user active-job counters  {user_id: int}
        self.active_users: Dict[str, int] = {}
        self.max_per_user = max_per_user

        # Lock protecting active_users mutations
        self._user_lock = asyncio.Lock()

        # Event signalled whenever a new job is added (wakes sleeping worker)
        self._job_available = asyncio.Event()

        # Legacy attribute kept so old references don't break
        self.worker_task: Optional[asyncio.Task] = None

        logger.info(
            f"DualQueueTaskManager initialised: "
            f"max_concurrent={max_concurrent_llm_calls}, max_per_user={max_per_user}"
        )

    # ── Public API ─────────────────────────────────────────────────────────────

    async def enqueue_job(
        self,
        job_data: Dict[str, Any],
        is_fast: Optional[bool] = None,
    ) -> str:
        """
        Adds a job to the appropriate queue and returns the job_id.

        Parameters
        ----------
        job_data : dict  — must contain at minimum: job_id, user_id
        is_fast  : bool  — override automatic classification if provided
        """
        job_id = job_data.get("job_id") or str(uuid.uuid4())
        job_data["job_id"] = job_id
        job_data["enqueued_at"] = datetime.now().isoformat()

        if is_fast is None:
            is_fast = _classify_job(job_data)

        job_data["_is_fast"] = is_fast  # store so worker can log it

        if is_fast:
            await self.fast_queue.put(job_data)
            logger.debug(f"Job {job_id} → fast_queue (user={job_data.get('user_id')})")
        else:
            await self.slow_queue.put(job_data)
            logger.debug(f"Job {job_id} → slow_queue (user={job_data.get('user_id')})")

        self._job_available.set()   # wake the worker loop
        return job_id

    async def get_next_job(self) -> Dict[str, Any]:
        """
        Pulls the next *eligible* job respecting:
          1. fast_queue has priority over slow_queue
          2. Per-user cap: skip users already at their max active slots

        Jobs that are skipped (user at cap) are re-queued at the back of their
        original queue so they are retried on the next cycle.
        """
        while True:
            # Gather all immediately available candidates
            fast_candidates = self._drain_queue(self.fast_queue)
            slow_candidates = self._drain_queue(self.slow_queue)

            # Process fast first, then slow
            all_candidates = fast_candidates + slow_candidates

            if not all_candidates:
                # Both queues empty — wait until something is added
                self._job_available.clear()
                await self._job_available.wait()
                continue

            eligible_job = None
            deferred = []

            async with self._user_lock:
                for job, queue_ref in all_candidates:
                    user_id = str(job.get("user_id", "unknown"))
                    active = self.active_users.get(user_id, 0)

                    if active < self.max_per_user:
                        # This job can run — claim a slot for the user
                        self.active_users[user_id] = active + 1
                        eligible_job = job
                        # Put the remaining candidates back
                        deferred = [
                            (j, q) for j, q in all_candidates
                            if j is not job
                        ]
                        break
                    else:
                        deferred.append((job, queue_ref))

            # Re-enqueue everything we pulled out but won't run now
            for job, queue_ref in deferred:
                await queue_ref.put(job)

            if eligible_job:
                logger.info(
                    f"Worker: dispatching job {eligible_job['job_id']} "
                    f"({'fast' if eligible_job.get('_is_fast') else 'slow'}) "
                    f"user={eligible_job.get('user_id')} "
                    f"active_users={dict(self.active_users)}"
                )
                return eligible_job

            # All candidates were at cap — wait briefly and retry
            await asyncio.sleep(0.3)

    def mark_job_done(self, user_id: Optional[str] = None):
        """
        Called by the worker after a job finishes (success, failure, or timeout).
        Decrements the user's active-job counter so the next job can be dispatched.
        """
        if user_id is not None:
            uid = str(user_id)
            current = self.active_users.get(uid, 0)
            self.active_users[uid] = max(0, current - 1)
            # Clean up the entry when the user has no active jobs
            if self.active_users[uid] == 0:
                self.active_users.pop(uid, None)
            logger.debug(f"mark_job_done: user={uid} active_users={dict(self.active_users)}")

        # Wake the worker so it can pick up the next eligible job immediately
        self._job_available.set()

    def queue_stats(self) -> Dict[str, Any]:
        """Returns a snapshot of queue depths and active users — useful for /status."""
        return {
            "fast_queue_depth": self.fast_queue.qsize(),
            "slow_queue_depth": self.slow_queue.qsize(),
            "active_users": dict(self.active_users),
            "max_per_user": self.max_per_user,
        }

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _drain_queue(self, queue: asyncio.Queue):
        """
        Non-blockingly pulls every item currently in *queue*.
        Returns a list of (job_data, queue_ref) tuples.
        """
        items = []
        while not queue.empty():
            try:
                items.append((queue.get_nowait(), queue))
            except asyncio.QueueEmpty:
                break
        return items


# ─── Global instance ──────────────────────────────────────────────────────────
task_manager = DualQueueTaskManager(
    max_concurrent_llm_calls=5,
    max_per_user=2,
)
