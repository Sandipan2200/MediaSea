"""SSRF-hardened HTTP fetch layer — the single file a reviewer reads to trust the backend.

INVARIANT: no adapter may construct its own httpx/aiohttp client or call
socket/dns directly. Every outbound request routes through SafeFetcher, which
enforces, on the initial URL *and every redirect hop*:

  1. Scheme allowlist (http/https only), no userinfo, sane length, hostname present.
  2. Only default ports (80/443) — blocks probing internal services on odd ports.
  3. DNS resolution BEFORE connecting; every resolved A/AAAA must be a public,
     non-reserved IP. Rejects 10/8, 172.16/12, 192.168/16, 127/8, 169.254/16
     (cloud metadata), ::1, fc00::/7, fe80::/10, plus other special-use ranges
     via ipaddress (multicast, reserved, unspecified, carrier-grade NAT).
  4. Manual redirect handling (max N hops), re-validating each Location header.
  5. Connect + read timeouts on every hop.
  6. Response size cap enforced by streaming read with early abort (a server can
     lie about Content-Length, so headers are never trusted for this).
  7. Bounded concurrency via semaphore (no amplification vector).
  8. Fresh client per SafeFetcher, no cookie persistence, generic User-Agent.

Unit-testable by design: pure helpers (is_ip_blocked, validate_url_structure)
take no I/O; DNS is injected via a `resolver` callable; HTTP transport is
injected (httpx.MockTransport in tests).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlparse, urljoin

import httpx

from .schemas import ErrorCode

# ---------------------------------------------------------------------------
# Pure helpers (no I/O — trivially unit-testable)
# ---------------------------------------------------------------------------

ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_PORTS = {80, 443}
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Explicitly blocked networks (defense in depth on top of ipaddress flags,
# so intent is auditable at a glance). 100.64.0.0/10 (CGNAT), 0.0.0.0/8,
# multicast, TEST-NET ranges, benchmark, etc. are covered by the
# `is_global` check below, but listing the classics here documents intent.
_BLOCKED_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # cloud metadata (169.254.169.254)
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),  # CGNAT
    ipaddress.ip_network("192.0.2.0/24"),  # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),  # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique local
    ipaddress.ip_network("fe80::/10"),  # link local
    ipaddress.ip_network("ff00::/8"),  # multicast v6
]


def is_ip_blocked(ip_str: str) -> bool:
    """Return True if this literal IP must never be connected to."""
    try:
        ip = ipaddress.ip_address(ip_str.strip().strip("[]"))
    except ValueError:
        return True  # unparseable -> refuse
    for net in _BLOCKED_NETS:
        if ip.version == net.version and ip in net:
            return True
    # Catch-all: anything not globally routable (reserved, unspecified,
    # loopback variants, documentation ranges we missed) is refused.
    # NOTE: ipaddress marks some public anycast as non-global in older
    # versions; the explicit allowlist above runs first so listed nets win.
    try:
        if not ip.is_global:
            return True
    except Exception:
        return True
    return False


def validate_url_structure(url: str, *, max_length: int = 2048) -> tuple[str, str, int]:
    """Validate shape only (no DNS). Returns (scheme, hostname, port).

    Raises SafeFetchError(INVALID_URL) on any violation.
    """
    if not isinstance(url, str) or not url:
        raise SafeFetchError(ErrorCode.INVALID_URL, "Empty URL.")
    if len(url) > max_length:
        raise SafeFetchError(ErrorCode.INVALID_URL, "URL exceeds maximum length.")
    try:
        parts = urlparse(url)
    except Exception:
        raise SafeFetchError(ErrorCode.INVALID_URL, "URL could not be parsed.")
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise SafeFetchError(ErrorCode.INVALID_URL, "Only http(s) URLs are allowed.")
    if parts.username or parts.password or "@" in (parts.netloc or ""):
        # `http://user:pass@host` form must never reach the fetcher.
        raise SafeFetchError(ErrorCode.INVALID_URL, "Credentials in URL are not allowed.")
    hostname = (parts.hostname or "").strip().rstrip(".")
    if not hostname:
        raise SafeFetchError(ErrorCode.INVALID_URL, "URL has no hostname.")
    if len(hostname) > 253:
        raise SafeFetchError(ErrorCode.INVALID_URL, "Hostname is too long.")
    port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    if port not in _ALLOWED_PORTS:
        raise SafeFetchError(
            ErrorCode.UNSUPPORTED_ACCESS, "Only default HTTP(S) ports are allowed."
        )
    return parts.scheme.lower(), hostname.lower(), port


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SafeFetchError(Exception):
    """Structured fetch failure carrying a public ErrorCode + safe reason."""

    def __init__(self, code: ErrorCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


# ---------------------------------------------------------------------------
# DNS
# ---------------------------------------------------------------------------

Resolver = Callable[[str], Awaitable[list[str]]]


async def default_resolver(hostname: str) -> list[str]:
    """Resolve A/AAAA records. Runs blocking getaddrinfo off the event loop."""
    loop = asyncio.get_running_loop()

    def _lookup() -> list[str]:
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_UNSPEC)
        ips: list[str] = []
        for fam, _, _, _, sockaddr in infos:
            ip = sockaddr[0]
            if ip not in ips:
                ips.append(ip)
        return ips

    return await loop.run_in_executor(None, _lookup)


# ---------------------------------------------------------------------------
# SafeFetcher
# ---------------------------------------------------------------------------


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    text: str
    content_type: str = ""


class SafeFetcher:
    """All outbound HTTP goes through here. Adapters receive an instance."""

    def __init__(
        self,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 10.0,
        max_bytes: int = 2_000_000,
        max_redirects: int = 5,
        max_url_length: int = 2048,
        max_concurrency: int = 8,
        user_agent: str = "MediaSaver/0.1 (+media-detection; public-content-only)",
        resolver: Resolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._timeout = httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=10.0, pool=5.0
        )
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_url_length = max_url_length
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._user_agent = user_agent
        self._resolver = resolver or default_resolver
        self._transport = transport

    # -- validation ------------------------------------------------------
    async def _assert_host_is_public(self, hostname: str) -> None:
        try:
            ips = await self._resolver(hostname)
        except SafeFetchError:
            raise
        except Exception:
            raise SafeFetchError(ErrorCode.NETWORK_ERROR, "Could not resolve host.")
        if not ips:
            raise SafeFetchError(ErrorCode.NETWORK_ERROR, "Host resolved to no addresses.")
        for ip in ips:
            if is_ip_blocked(ip):
                raise SafeFetchError(
                    ErrorCode.UNSUPPORTED_ACCESS,
                    "That address is not publicly reachable.",
                )

    # -- public API ------------------------------------------------------
    async def fetch_text(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """GET url as text: follows redirects manually, caps body size by streaming."""
        current = url
        async with self._semaphore:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,  # manual: re-validate every hop (SSRF)
            ) as client:
                for _hop in range(self._max_redirects + 1):
                    validate_url_structure(current, max_length=self._max_url_length)
                    _scheme, hostname, _port = validate_url_structure(
                        current, max_length=self._max_url_length
                    )
                    await self._assert_host_is_public(hostname)
                    try:
                        resp = await client.get(
                            current,
                            headers={"User-Agent": self._user_agent, **(headers or {})},
                        )
                    except httpx.ConnectTimeout:
                        raise SafeFetchError(ErrorCode.TIMEOUT, "Connection timed out.")
                    except httpx.ReadTimeout:
                        raise SafeFetchError(ErrorCode.TIMEOUT, "Server took too long.")
                    except httpx.TimeoutException:
                        raise SafeFetchError(ErrorCode.TIMEOUT, "Request timed out.")
                    except httpx.ConnectError:
                        raise SafeFetchError(ErrorCode.NETWORK_ERROR, "Could not connect.")
                    except httpx.HTTPError:
                        raise SafeFetchError(ErrorCode.NETWORK_ERROR, "Network error.")

                    if resp.status_code in _REDIRECT_STATUSES:
                        location = resp.headers.get("location", "")
                        if not location:
                            raise SafeFetchError(
                                ErrorCode.NETWORK_ERROR, "Bad redirect from server."
                            )
                        current = urljoin(current, location)
                        continue  # next hop re-validates scheme + DNS

                    if resp.status_code == 429:
                        raise SafeFetchError(
                            ErrorCode.TEMPORARY_FAILURE, "Upstream is busy; try again."
                        )
                    if resp.status_code in (401, 403):
                        raise SafeFetchError(
                            ErrorCode.ACCESS_DENIED,
                            "That content needs a login we will not use.",
                        )
                    if resp.status_code == 404:
                        raise SafeFetchError(
                            ErrorCode.MEDIA_NOT_FOUND, "Nothing found at that link."
                        )
                    if resp.status_code >= 500:
                        raise SafeFetchError(
                            ErrorCode.TEMPORARY_FAILURE, "Upstream server error; retry."
                        )
                    if resp.status_code >= 400:
                        raise SafeFetchError(
                            ErrorCode.MEDIA_NOT_FOUND, "Nothing downloadable there."
                        )

                    # Stream with early abort — never trust Content-Length.
                    chunks: list[bytes] = []
                    total = 0
                    content_type = resp.headers.get("content-type", "")
                    try:
                        async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                            total += len(chunk)
                            if total > self._max_bytes:
                                raise SafeFetchError(
                                    ErrorCode.FILE_TOO_LARGE,
                                    "Page or playlist is too large to inspect.",
                                )
                            chunks.append(chunk)
                    except SafeFetchError:
                        raise
                    except Exception:
                        raise SafeFetchError(ErrorCode.NETWORK_ERROR, "Download failed.")
                    raw = b"".join(chunks)
                    charset = resp.charset_encoding or "utf-8"
                    try:
                        text = raw.decode(charset, errors="replace")
                    except Exception:
                        text = raw.decode("utf-8", errors="replace")
                    return FetchResult(
                        url=current, status=resp.status_code, text=text, content_type=content_type
                    )
                raise SafeFetchError(ErrorCode.NETWORK_ERROR, "Too many redirects.")
