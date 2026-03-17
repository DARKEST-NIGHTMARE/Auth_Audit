import time
import os
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import engine, Base
from .routers import auth, employees, users, security
from .config import settings
from .logger import setup_logging, get_logger

setup_logging(level=settings.log_level if hasattr(settings, "log_level") else "INFO")
logger = get_logger(__name__)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    os.makedirs("static/profiles", exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("application_startup", extra={"env": "development"})

from .routers import auth, employees, users, security, google_drive

app.include_router(auth.router)
app.include_router(employees.router)
app.include_router(users.router)
app.include_router(security.router)
app.include_router(google_drive.router)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)