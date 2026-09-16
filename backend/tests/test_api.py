"""API contract tests: error schema, YouTube refusal, validation, rate limiting."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.fetcher import SafeFetcher


def _client(handler, **kw) -> TestClient:  # type: ignore[no-untyped-def]
    # NOTE: TestClient only runs the app lifespan inside `with` blocks. We
    # deliberately avoid `with` here so the lifespan does NOT overwrite the
    # MockTransport-backed fetcher we inject for hermetic tests.
    app = create_app()

    async def public_resolver(host: str) -> list[str]:
        return ["93.184.216.34"]

    app.state.fetcher = SafeFetcher(resolver=public_resolver,
                                    transport=httpx.MockTransport(handler), **kw)
    from app.rate_limit import RateLimiter
    from app.config import get_settings
    app.state.limiter = RateLimiter(per_minute=get_settings().rate_limit_per_minute)
    return TestClient(app, raise_server_exceptions=False)


def test_health() -> None:
    c = _client(lambda r: httpx.Response(200, text="x"))
    r = c.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_platforms_lists_supported_and_refused() -> None:
    c = _client(lambda r: httpx.Response(200, text="x"))
    body = c.get("/platforms").json()
    assert "pinterest" in body["supported"]
    assert "youtube" in body["refused"]


def test_analyze_success_contract() -> None:
    html = ('<html><head><meta property="og:video" '
            'content="https://cdn.example.com/v.mp4"></head></html>')

    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    c = _client(handler)
    r = c.post("/analyze", json={"url": "https://example.com/p"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["data"]["variants"][0]["url"] == "https://cdn.example.com/v.mp4"


def test_youtube_returns_422_unsupported_platform() -> None:
    c = _client(lambda r: (_ for _ in ()).throw(AssertionError("no fetch for youtube")))
    r = c.post("/analyze", json={"url": "https://www.youtube.com/watch?v=x"})
    assert r.status_code == 422
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "UNSUPPORTED_PLATFORM"
    assert body["reason"]


def test_invalid_url_returns_400() -> None:
    c = _client(lambda r: httpx.Response(200, text="x"))
    r = c.post("/analyze", json={"url": "not a url"})
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_URL"


def test_oversize_url_rejected() -> None:
    c = _client(lambda r: httpx.Response(200, text="x"))
    r = c.post("/analyze", json={"url": "https://example.com/" + "a" * 3000})
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_URL"


def test_media_not_found_returns_404() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html>empty</html>")

    c = _client(handler)
    r = c.post("/analyze", json={"url": "https://example.com/empty"})
    assert r.status_code == 404
    assert r.json()["error"] == "MEDIA_NOT_FOUND"


def test_error_shape_is_stable() -> None:
    c = _client(lambda r: httpx.Response(200, text="x"))
    r = c.post("/analyze", json={"url": "https://youtu.be/x"})
    body = r.json()
    assert set(body.keys()) == {"ok", "error", "reason", "platform"}


def test_cors_preflight_allows_extension_origins() -> None:
    """Regression: the popup (chrome-extension://<id>) must pass preflight.

    Starlette matches allow_origins exactly, so extension origins can only be
    allowed via allow_origin_regex. Without this, curl works but the popup's
    fetch fails — the exact symptom of a dead Analyze button with 400s in the
    log coming only from hand-written curl, never from the extension.
    """
    c = _client(lambda r: httpx.Response(200, text="x"))
    origin = "chrome-extension://abcdefghijklmnopqrstuvwxyz123456"
    r = c.options(
        "/analyze",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == origin


def test_cors_preflight_rejects_random_origins() -> None:
    c = _client(lambda r: httpx.Response(200, text="x"))
    r = c.options(
        "/analyze",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert "access-control-allow-origin" not in r.headers
