"""
Central logging configuration for the Login Auth Audit backend.
Import `logger` from here in every module.

Usage:
    from app.logger import get_logger
    logger = get_logger(__name__)

    logger.info("user_login", email=email, ip=ip)
    logger.warning("rate_limit_hit", ip=ip, count=count)
    logger.error("db_query_failed", error=str(e), exc_info=True)
"""

import logging
import json
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for easy parsing/grepping."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Merge any extra fields passed via `extra=` or direct kwargs
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                log_obj[key] = value

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_obj, default=str)


def setup_logging(level: str = "INFO") -> None:
    """Call once at application startup (in main.py lifespan)."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers (avoids duplicate logs with uvicorn)
    root_logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)

    # ── Silence noisy third-party loggers ──────────────────────────────────────
    # SQLAlchemy: suppress all SQL echo (SELECT, INSERT, COMMIT, BEGIN, etc.)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.WARNING)

    # Google auth: suppress token refresh info messages
    logging.getLogger("google_auth_httplib2").setLevel(logging.WARNING)
    logging.getLogger("google.auth").setLevel(logging.WARNING)

    # httpx: suppress per-request HTTP logs (e.g. Cerebras, Gemini calls)
    # Keep ERROR so failed requests still surface
    logging.getLogger("httpx").setLevel(logging.ERROR)
    logging.getLogger("httpcore").setLevel(logging.ERROR)

    # LangChain/LangSmith: suppress verbose internal tracing logs
    logging.getLogger("langchain").setLevel(logging.WARNING)
    logging.getLogger("langsmith").setLevel(logging.WARNING)
    logging.getLogger("langgraph").setLevel(logging.WARNING)

    # uvicorn access logs: keep INFO but mask ?token= values so JWTs are
    # never written to log files in plaintext.
    class _MaskTokenFilter(logging.Filter):
        import re as _re
        _pattern = _re.compile(r"([\?&]token=)[^&\s\"']+", _re.IGNORECASE)

        def filter(self, record: logging.LogRecord) -> bool:
            if record.args:
                # Uvicorn formats the access line via %-style args; mask in each arg
                record.args = tuple(
                    self._pattern.sub(r"\1[REDACTED]", str(a)) if isinstance(a, str) else a
                    for a in record.args
                )
            return True

    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.setLevel(logging.INFO)
    uvicorn_access.addFilter(_MaskTokenFilter())


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call at module level: logger = get_logger(__name__)"""
    return logging.getLogger(name)
