"""FastAPI application — the ``api`` service (§A2).

Runs **no scheduled jobs**: all background work belongs to the ``scheduler``
process, which is a separate container guarded by an advisory lock. Putting a
scheduler inside a multi-worker uvicorn was V2 flaw K4.

P1 exposes only the health surface. Auth, tenant routes and the admin surface
arrive from P2 onward.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import dispose_engine, get_engine
from app.health import build_report, check_db
from app.logging_setup import configure_logging

log = logging.getLogger(__name__)

SERVICE_NAME = "api"

router = APIRouter(prefix="/api")


@router.get("/health/ready", summary="Deploy gate: can this API serve traffic?")
async def health_ready() -> Response:
    """200 as soon as the database answers. Ignores the scheduler on purpose."""
    ok = await check_db(get_engine())
    body = {"status": "ready" if ok else "unready", "db": "ok" if ok else "error"}
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/health", summary="Uptime monitor: is the whole system working?")
async def health() -> Response:
    """200 only when the database answers *and* the scheduler is beating."""
    report = await build_report(get_engine())
    return JSONResponse(report.payload, status_code=200 if report.healthy else 503)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(SERVICE_NAME, settings.LOG_LEVEL)
    log.info(
        "api starting",
        extra={
            "public_origin": settings.PUBLIC_ORIGIN,
            "cookie_secure": settings.COOKIE_SECURE,
            "proxy_mode": settings.proxy_mode,
            "user_agent": settings.user_agent,
            "log_level": settings.LOG_LEVEL,
        },
    )
    try:
        yield
    finally:
        await dispose_engine()
        log.info("api stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CompetitorTrack API",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        # Interactive docs are a development affordance. The OpenAPI document
        # itself stays available everywhere — §A10.6's secrets test walks it.
        docs_url="/api/docs" if settings.is_local_origin else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def access_log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        return response

    app.include_router(router)
    return app


app = create_app()
