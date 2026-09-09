"""FastAPI app factory — CORS, routers, and one global exception handler (C4)."""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.controllers import (
    case_controller,
    chat_controller,
    eval_controller,
    health_controller,
    screening_controller,
    search_controller,
)

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"


def _error(code: str, message: str, detail: dict | None = None, status_code: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title="Conflict Screening Multi-Agent Assistant",
        description=(
            "Conflict-of-interest screening assistant for Deloitte SEA Tax & Transformation. "
            "A drafting aid, not an approval engine — every conclusion cites the QRC rule it came from."
        ),
        version="0.1.0",
    )

    # Opening the app from another device on the network means the browser's
    # Origin is that machine's LAN address, not localhost. Allow private-range
    # origins so a demo laptop or phone works without per-device config, while
    # still refusing arbitrary public origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()],
        allow_origin_regex=settings.CORS_ORIGIN_REGEX or None,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for controller in (
        case_controller,
        screening_controller,
        eval_controller,
        search_controller,
        chat_controller,
        health_controller,
    ):
        app.include_router(controller.router, prefix=API_PREFIX)

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return _error(
                detail["code"], detail.get("message", ""), detail.get("detail"), status_code=exc.status_code
            )
        return _error("VALIDATION_ERROR", str(detail), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        return _error("VALIDATION_ERROR", "Request validation failed", {"errors": exc.errors()}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return _error("SCREENING_FAILED", str(exc), status_code=500)

    return app


app = create_app()
