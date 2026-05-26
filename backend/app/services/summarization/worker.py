"""
Async worker for processing summarization jobs via the LangGraph agent.
Replaces the legacy generate_summary_from_chunks() call with graph.ainvoke().
"""
import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import update

from ...core.database import AsyncSessionLocal
from ...core.task_manager import task_manager
from ...models import QueryJob, QueryJobStatus

logger = logging.getLogger(__name__)


async def process_job(job_data: dict):
    """
    Main worker coroutine for a single job.
    Uses the LangGraph agent for generation; falls back to legacy pipeline on error.
    """
    job_id = job_data["job_id"]
    user_id = job_data["user_id"]
    logger.info(f"Worker: Picked up job {job_id} for user {user_id}")

    async with AsyncSessionLocal() as db:
        try:
            # 1. Mark as processing
            await db.execute(
                update(QueryJob)
                .where(QueryJob.id == job_id)
                .values(status=QueryJobStatus.PROCESSING,
                        updated_at=datetime.now(timezone.utc))
            )
            await db.commit()

            # 2. Acquire semaphore (max 5 concurrent graph runs)
            async with task_manager.semaphore:
                result = await _run_graph(job_data)

            # 3. Store result or awaiting approval
            if result and result.get("__awaiting_approval__"):
                # Graph paused — ask user to approve the Drive action
                await db.execute(
                    update(QueryJob)
                    .where(QueryJob.id == job_id)
                    .values(
                        status=QueryJobStatus.AWAITING_APPROVAL,
                        pending_action=result.get("pending_action"),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            elif result:
                await db.execute(
                    update(QueryJob)
                    .where(QueryJob.id == job_id)
                    .values(
                        status=QueryJobStatus.COMPLETED,
                        result=result,
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            else:
                await db.execute(
                    update(QueryJob)
                    .where(QueryJob.id == job_id)
                    .values(
                        status=QueryJobStatus.FAILED,
                        error="Graph returned no result after retries.",
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            await db.commit()

        except Exception as e:
            logger.error(f"Worker: Critical error in job {job_id}: {e}")
            try:
                await db.execute(
                    update(QueryJob)
                    .where(QueryJob.id == job_id)
                    .values(status=QueryJobStatus.FAILED, error=str(e))
                )
                await db.commit()
            except Exception:
                pass
        finally:
            task_manager.mark_job_done()


async def _run_graph(job_data: dict) -> dict:
    """
    Invokes the LangGraph agent with the job's context package.
    Handles the AWAITING_APPROVAL interrupt for Drive write actions.
    Falls back to legacy pipeline if graph is unavailable.
    """
    query = job_data.get("query", "")
    pre_chunks = job_data.get("chunks", [])
    resolved_items = job_data.get("resolved_items", [])
    access_token = job_data.get("access_token", "")
    refresh_token = job_data.get("refresh_token")
    job_id = job_data["job_id"]

    from app.services.summarization.pipeline import summarization_pipeline
    graph = await summarization_pipeline._get_graph()

    if graph is not None:
        from app.services.summarization.query_parser import QueryParser
        parser = QueryParser()
        parsed = parser.parse(query)
        intent_map = {"summarize": "summarize", "question": "question", "general": "question"}
        intent = intent_map.get(parsed.intent.value, "question")

        state = {
            "query": query,
            "intent": intent,
            "resolved_items": resolved_items,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "retrieved_chunks": pre_chunks,
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

        # LangGraph thread_id = job_id for checkpointing
        # tags for LangSmith trace filtering
        config = {
            "configurable": {"thread_id": job_id},
            "tags": [f"user:{job_data.get('user_id')}", f"intent:{intent}"]
        }

        @traceable(name="LangGraph Agentic Flow", run_type="chain")
        async def run_agent():
            return await graph.ainvoke(state, config=config)

        try:
            result_state = await run_agent()

            # Check if the graph paused at the execute_tool interrupt
            graph_state = await graph.aget_state(config)
            next_nodes = graph_state.next if hasattr(graph_state, "next") else []

            if "execute_tool" in next_nodes:
                # Graph is paused — persist the pending action for user approval
                pending = {
                    "tool_name": result_state.get("tool_name"),
                    "tool_args": result_state.get("tool_args", {}),
                    "summary_preview": (result_state.get("parsed_result") or {}).get("summary", "")[:500],
                }
                logger.info(f"Worker: Graph paused at execute_tool for job {job_id}. "
                            f"Awaiting user approval.")
                return {"__awaiting_approval__": True, "pending_action": pending}

            final = result_state.get("final_result")
            if final:
                logger.info(f"Worker: Graph completed job {job_id}. "
                            f"provider={final.get('provider_used')}, "
                            f"confidence={final.get('confidence_score')}")
                return final
        except Exception as e:
            logger.error(f"Worker: Graph failed for job {job_id}: {e}. Using legacy fallback.")

    # Legacy fallback
    logger.warning(f"Worker: Using legacy pipeline for job {job_id}")
    return await summarization_pipeline.generate_summary_from_chunks(
        query=query, chunks=pre_chunks
    )



async def worker_loop():
    """Infinite loop that pulls jobs from the task_manager queue."""
    logger.info("Summarization worker loop started (LangGraph mode).")
    while True:
        try:
            job_data = await task_manager.get_next_job()
            asyncio.create_task(process_job(job_data))
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(1)
