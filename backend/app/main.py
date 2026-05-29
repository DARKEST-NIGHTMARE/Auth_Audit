import time
import os
import asyncio
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
import httpx
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.database import engine, Base
from .core.config import settings
from .logger import setup_logging, get_logger
from .api import employees, users, security, clio
from .routers import auth, google_drive, summarization

setup_logging(level=settings.log_level if hasattr(settings, "log_level") else "INFO")
logger = get_logger(__name__)

# Re-apply logger filters now that all engines/clients are imported
import logging as _logging
_logging.getLogger("sqlalchemy").setLevel(_logging.WARNING)
_logging.getLogger("sqlalchemy.engine").setLevel(_logging.WARNING)
_logging.getLogger("httpx").setLevel(_logging.ERROR)
_logging.getLogger("google_auth_httplib2").setLevel(_logging.WARNING)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
            "client": request.client.host if request.client else "unknown",
        }
    )
    return response

@app.on_event("startup")
async def startup():
    app.state.http_client = httpx.AsyncClient(timeout=20.0)
    os.makedirs("static/profiles", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Start the background summarization worker
    from .services.summarization.worker import worker_loop
    asyncio.create_task(worker_loop())

    # Start the periodic cleanup task (every hour)
    async def cleanup_loop():
        from sqlalchemy import delete
        from datetime import datetime, timedelta, timezone
        from .models import QueryJob
        while True:
            try:
                async with engine.begin() as conn:
                    # Delete jobs older than 24 hours
                    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
                    await conn.execute(
                        delete(QueryJob).where(QueryJob.created_at < cutoff)
                    )
                logger.info("Cleanup task: Removed jobs older than 24h.")
            except Exception as e:
                logger.error(f"Cleanup task error: {e}")
            await asyncio.sleep(3600) # Wait 1 hour
            
    asyncio.create_task(cleanup_loop())

    logger.info("application_startup", extra={"env": "development"})

@app.on_event("shutdown")
async def shutdown():
    if hasattr(app.state, "http_client"):
        await app.state.http_client.aclose()
        logger.info("application_shutdown", extra={"status": "http_client_closed"})

# Using routers from .routers which is the newer structure
app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(users.router)
app.include_router(security.router)
app.include_router(google_drive.router)
app.include_router(summarization.router)

# Clio is still in .api (or check if it was moved)
app.include_router(clio.router)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)