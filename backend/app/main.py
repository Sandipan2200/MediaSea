"""MediaSaver FastAPI backend — directory, not distributor.

The backend returns metadata + direct CDN URLs. It never stores or proxies
media bytes. All outbound HTTP flows through SafeFetcher (see fetcher.py).
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .config import get_settings
from .detector import analyze_url, detect_platform
from .fetcher import SafeFetcher, SafeFetchError
from .logging_util import RequestIdFilter, url_fingerprint
from .rate_limit import RateLimiter
from .schemas import (
    AnalyzeErrorResponse,
    AnalyzeRequest,
    AnalyzeSuccessResponse,
    ErrorCode,
    HealthResponse,
)

_version = "0.1.0"
_req_filter = RequestIdFilter()
logging.basicConfig(level=logging.INFO)
for _h in logging.getLogger().handlers:
    _h.addFilter(_req_filter)
logger = logging.getLogger("mediasaver")


def create_app() -> FastAPI:
    settings = get_settings()
    limiter = RateLimiter(per_minute=settings.rate_limit_per_minute)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        app.state.fetcher = SafeFetcher(
            connect_timeout=settings.connect_timeout_s,
            read_timeout=settings.read_timeout_s,
            max_bytes=settings.max_response_bytes,
            max_redirects=settings.max_redirects,
            max_url_length=settings.max_url_length,
            max_concurrency=settings.max_outbound_concurrency,
        )
        app.state.limiter = limiter
        app.state.settings = settings
        yield

    app = FastAPI(title="MediaSaver API", version=_version, lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=settings.cors_allow_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        max_age=3600,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        rid = uuid.uuid4().hex[:12]
        _req_filter.request_id = rid
        start = time.monotonic()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info("%s %s -> %s (%sms)", request.method, request.url.path,
                    response.status_code, elapsed_ms,
                    extra={"request_id": rid})
        _req_filter.request_id = "-"
        return response

    def err(code: ErrorCode, reason: str, platform: str | None, status: int) -> JSONResponse:
        return JSONResponse(status_code=status, content={"ok": False, "error": code.value,
                                                         "reason": reason, "platform": platform})

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(version=_version)

    @app.get("/platforms")
    async def platforms() -> dict[str, object]:
        return {
            "supported": ["pinterest", "instagram", "generic"],
            "refused": ["youtube"],
            "note": "instagram covers public posts/reels only and is fragile by nature "
            "(logged-out markup changes often); facebook/x not built yet. See README.",
        }

    @app.post("/analyze", response_model=AnalyzeSuccessResponse)
    async def analyze(body: AnalyzeRequest, request: Request):  # type: ignore[no-untyped-def]
        client_ip = request.client.host if request.client else "unknown"
        try:
            app.state.limiter.check(f"analyze:{client_ip}")
        except SafeFetchError as e:
            return err(e.code, e.reason, None, 429)
        url = body.url.strip()
        # Privacy: log only a hash prefix, never the full URL.
        logger.info("analyze fp=%s platform=%s", url_fingerprint(url),
                    detect_platform(url), extra={"request_id": "-"})
        try:
            fetcher: SafeFetcher = app.state.fetcher
            result = await analyze_url(url, fetcher)
        except SafeFetchError as e:
            status = {
                ErrorCode.INVALID_URL: 400,
                ErrorCode.UNSUPPORTED_PLATFORM: 422,
                ErrorCode.MEDIA_NOT_FOUND: 404,
                ErrorCode.PRIVATE_CONTENT: 403,
                ErrorCode.ACCESS_DENIED: 403,
                ErrorCode.PROTECTED_CONTENT: 422,
                ErrorCode.RATE_LIMITED: 429,
                ErrorCode.FILE_TOO_LARGE: 413,
                ErrorCode.TIMEOUT: 504,
                ErrorCode.UNSUPPORTED_ACCESS: 400,
                ErrorCode.NETWORK_ERROR: 502,
                ErrorCode.TEMPORARY_FAILURE: 502,
                ErrorCode.SERVER_ERROR: 500,
            }.get(e.code, 500)
            platform = None
            try:
                platform = detect_platform(url)
            except Exception:
                pass
            return err(e.code, e.reason, platform, status)
        except Exception:
            logger.exception("analyze failed")
            return err(ErrorCode.SERVER_ERROR, "Something went wrong. Try again.", None, 500)
        return {"ok": True, "data": result.model_dump()}

    @app.exception_handler(ValidationError)
    async def validation_handler(request: Request, exc: ValidationError) -> JSONResponse:  # type: ignore[no-untyped-def]
        return err(ErrorCode.INVALID_URL, "That doesn't look like a valid http(s) URL.", None, 400)

    from fastapi.exceptions import RequestValidationError

    @app.exception_handler(RequestValidationError)
    async def req_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:  # type: ignore[no-untyped-def]
        return err(ErrorCode.INVALID_URL, "That doesn't look like a valid http(s) URL.", None, 400)

    return app


app = create_app()
