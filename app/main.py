"""FastAPI entry point: lifespan, exception handlers and router wiring."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import ask, health, stats
from app.config import RUN_MIGRATIONS_ON_STARTUP
from app.db.pool import pool
from app.logging_config import setup_logging

setup_logging()
log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if RUN_MIGRATIONS_ON_STARTUP:
        try:
            from app.db.migrate import apply_pending

            apply_pending()
        except Exception:
            # The API should still come up so /health can report the problem.
            log.exception("Startup migrations failed")

    pool.open()
    log.info("API started")
    yield
    pool.close()
    log.info("API stopped")


app = FastAPI(
    title="arXiv Ingest & RAG API",
    version="1.0.0",
    description="Aggregated arXiv statistics and retrieval-augmented question answering.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _error(422, "validation_error", str(exc.errors()))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return _error(500, "internal_error", "An unexpected error occurred.")


app.include_router(health.router)
app.include_router(stats.router, prefix=API_PREFIX)
app.include_router(ask.router, prefix=API_PREFIX)


@app.get("/")
def root():
    return {"service": "arXiv Ingest & RAG API", "docs": "/docs", "health": "/health"}
