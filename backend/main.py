"""Application entrypoint for Janam."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .app.api.routes import router
from .app.core.brain import JanamBrain
from .app.core.database import init_database
from .app.core.logging_config import configure_logging
from .app.core.rate_limiter import InMemoryRateLimiter
from .app.core.request_context import reset_request_id, set_request_id
from .app.core.security import ensure_valid_key_configuration, resolve_api_key_role
from .app.repositories.report_repository import ReportRepository
from .app.services.alert_stream_service import AlertStreamService
from .app.services.analysis_service import JanamAnalysisService


logger = logging.getLogger("janam.api")


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        configure_logging()
        ensure_valid_key_configuration()
        init_database()
        app.state.analysis_service = JanamAnalysisService(
            brain=JanamBrain(report_format="text"),
            repository=ReportRepository(),
        )
        app.state.alert_stream_service = AlertStreamService()
        write_per_minute_limit = int(os.getenv("JANAM_RATE_LIMIT_WRITE_PER_MINUTE", os.getenv("JANAM_RATE_LIMIT_PER_MINUTE", "120")))
        read_per_minute_limit = int(os.getenv("JANAM_RATE_LIMIT_READ_PER_MINUTE", "60"))
        app.state.retry_after_write_seconds = int(os.getenv("JANAM_RETRY_AFTER_WRITE_SECONDS", "60"))
        app.state.retry_after_read_seconds = int(os.getenv("JANAM_RETRY_AFTER_READ_SECONDS", "60"))
        app.state.rate_limiter_write = InMemoryRateLimiter(limit=write_per_minute_limit, window_seconds=60)
        app.state.rate_limiter_read = InMemoryRateLimiter(limit=read_per_minute_limit, window_seconds=60)
        logger.info("Application startup complete")
        yield
        logger.info("Application shutdown complete")

    app = FastAPI(
        title="Janam Prototype API",
        description="Prototype backend for crime detection and realtime danger-zone display.",
        version="0.2.0",
        lifespan=lifespan,
    )

    cors_origins = [
        origin.strip()
        for origin in os.getenv("JANAM_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset", "X-RateLimit-Role"],
    )

    @app.middleware("http")
    async def log_http_requests(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        token = set_request_id(request_id)
        start_time = perf_counter()
        try:
            path = request.url.path
            if path not in {"/", "/health"}:
                client_host = request.client.host if request.client else "unknown"
                role = resolve_api_key_role(request.headers.get("X-API-Key"))
                limiter = request.app.state.rate_limiter_write if role == "write" else request.app.state.rate_limiter_read
                role_key = role or "anonymous"
                key = f"http:{client_host}:{path}:{role_key}"
                allowed, remaining, reset_in = limiter.consume_with_info(key)
                limit_value = limiter.limit
                retry_after_value = request.app.state.retry_after_write_seconds if role == "write" else request.app.state.retry_after_read_seconds
                if not allowed:
                    elapsed_ms = (perf_counter() - start_time) * 1000
                    logger.warning("rate_limit_exceeded method=%s path=%s role=%s", request.method, path, role_key)
                    response = JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})
                    response.headers["X-Request-ID"] = request_id
                    response.headers["Retry-After"] = str(retry_after_value)
                    response.headers["X-RateLimit-Limit"] = str(limit_value)
                    response.headers["X-RateLimit-Remaining"] = "0"
                    response.headers["X-RateLimit-Reset"] = str(reset_in)
                    response.headers["X-RateLimit-Role"] = role_key
                    logger.info(
                        "request method=%s path=%s status=%s duration_ms=%.2f",
                        request.method,
                        path,
                        response.status_code,
                        elapsed_ms,
                    )
                    return response

            response = await call_next(request)
            elapsed_ms = (perf_counter() - start_time) * 1000
            response.headers["X-Request-ID"] = request_id
            if path not in {"/", "/health"}:
                response.headers["X-RateLimit-Limit"] = str(limit_value)
                response.headers["X-RateLimit-Remaining"] = str(remaining)
                response.headers["X-RateLimit-Reset"] = str(reset_in)
                response.headers["X-RateLimit-Role"] = role_key
            logger.info(
                "request method=%s path=%s status=%s duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )
            return response
        finally:
            reset_request_id(token)

    app.include_router(router)
    return app


app = create_app()
