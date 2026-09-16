"""SSRF-layer unit tests: the file that proves the fetcher is trustworthy."""

from __future__ import annotations

import pytest
import httpx

from app.fetcher import SafeFetcher, SafeFetchError, is_ip_blocked, validate_url_structure
from app.schemas import ErrorCode


# -- pure helpers ------------------------------------------------------------


@pytest.mark.parametrize("ip", [
    "10.0.0.1", "10.255.255.255", "172.16.0.1", "172.31.255.255",
    "192.168.1.1", "127.0.0.1", "169.254.169.254", "::1",
    "fc00::1", "fe80::1", "0.0.0.0", "100.64.0.1", "224.0.0.1",
])
def test_private_and_reserved_ips_blocked(ip: str) -> None:
    assert is_ip_blocked(ip) is True


@pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34"])
def test_public_ips_allowed(ip: str) -> None:
    assert is_ip_blocked(ip) is False


def test_unparseable_ip_blocked() -> None:
    assert is_ip_blocked("not-an-ip") is True


@pytest.mark.parametrize("url", [
    "ftp://example.com/file.mp4",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,hi",
    "http://user:pass@example.com/",
    "http://user@example.com/",
    "https://",
    "",
])
def test_bad_schemes_and_shapes_rejected(url: str) -> None:
    with pytest.raises(SafeFetchError) as ei:
        validate_url_structure(url)
    assert ei.value.code in (ErrorCode.INVALID_URL, ErrorCode.UNSUPPORTED_ACCESS)


def test_non_default_port_rejected() -> None:
    with pytest.raises(SafeFetchError) as ei:
        validate_url_structure("http://example.com:8080/video.mp4")
    assert ei.value.code == ErrorCode.UNSUPPORTED_ACCESS


def test_url_length_cap() -> None:
    with pytest.raises(SafeFetchError):
        validate_url_structure("https://example.com/" + "a" * 3000, max_length=2048)


# -- fetcher with injected resolver + transport --------------------------------

async def _public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]  # example.com (public)


async def _private_resolver(host: str) -> list[str]:
    return ["10.0.0.5"]


def _transport(handler) -> httpx.MockTransport:  # type: ignore[no-untyped-def]
    return httpx.MockTransport(handler)


async def test_private_ip_resolution_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="hi")

    f = SafeFetcher(resolver=_private_resolver, transport=_transport(handler))
    with pytest.raises(SafeFetchError) as ei:
        await f.fetch_text("https://example.com/")
    assert ei.value.code == ErrorCode.UNSUPPORTED_ACCESS


async def test_redirect_to_private_ip_revalidated() -> None:
    """The classic SSRF bypass: public first hop -> 302 to 169.254.169.254."""
    async def resolver(host: str) -> list[str]:
        if host == "start.example":
            return ["93.184.216.34"]
        return ["169.254.169.254"]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "start.example":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/secret"})
        return httpx.Response(200, text="should never arrive")

    f = SafeFetcher(resolver=resolver, transport=_transport(handler))
    with pytest.raises(SafeFetchError) as ei:
        await f.fetch_text("https://start.example/")
    assert ei.value.code == ErrorCode.UNSUPPORTED_ACCESS


async def test_redirect_to_bad_scheme_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "file:///etc/passwd"})

    f = SafeFetcher(resolver=_public_resolver, transport=_transport(handler))
    with pytest.raises(SafeFetchError) as ei:
        await f.fetch_text("https://example.com/")
    assert ei.value.code == ErrorCode.INVALID_URL


async def test_size_cap_aborts_streaming() -> None:
    big = b"x" * (3 * 1024 * 1024)

    def handler(request: httpx.Request) -> httpx.Response:
        # Lies about Content-Length to prove we enforce by streaming, not headers.
        return httpx.Response(200, headers={"content-length": "10"}, content=big)

    f = SafeFetcher(resolver=_public_resolver, transport=_transport(handler), max_bytes=1024)
    with pytest.raises(SafeFetchError) as ei:
        await f.fetch_text("https://example.com/big")
    assert ei.value.code == ErrorCode.FILE_TOO_LARGE


async def test_auth_required_maps_to_access_denied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="login")

    f = SafeFetcher(resolver=_public_resolver, transport=_transport(handler))
    with pytest.raises(SafeFetchError) as ei:
        await f.fetch_text("https://example.com/private")
    assert ei.value.code == ErrorCode.ACCESS_DENIED


async def test_404_maps_to_media_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="nope")

    f = SafeFetcher(resolver=_public_resolver, transport=_transport(handler))
    with pytest.raises(SafeFetchError) as ei:
        await f.fetch_text("https://example.com/missing")
    assert ei.value.code == ErrorCode.MEDIA_NOT_FOUND


async def test_too_many_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://example.com/loop"})

    f = SafeFetcher(resolver=_public_resolver, transport=_transport(handler), max_redirects=3)
    with pytest.raises(SafeFetchError):
        await f.fetch_text("https://example.com/loop")


async def test_happy_path_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html>hi</html>")

    f = SafeFetcher(resolver=_public_resolver, transport=_transport(handler))
    res = await f.fetch_text("https://example.com/")
    assert res.status == 200
    assert "hi" in res.text
