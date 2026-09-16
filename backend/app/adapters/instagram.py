"""Instagram adapter — PUBLIC posts/reels only, no login flow, no session reuse.

Fragility warning (Phase-5-grade): Instagram's logged-out markup changes often
and varies by post type. This adapter reads only what the unauthenticated page
itself serves: OpenGraph meta, the embedded JSON payload's video_url /
display_url fields, and direct file URLs. If the page carries no media data
(e.g. a login wall or JS-only shell), the result is ACCESS_DENIED (login wall)
or MEDIA_NOT_FOUND — never a bypass attempt, never fabricated URLs.

Known behavior this exists to fix: reels whose public HTML exposes only the
og:image poster frame must additionally surface video_url when present, so a
reel never degrades to "one frame image" while its video sits in the payload.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

from ..fetcher import SafeFetchError, SafeFetcher
from ..schemas import AnalysisResult, ErrorCode, MediaVariant
from .quality import dims_near, label_from_dims, label_from_url

_IG_HOSTS = {"instagram.com", "www.instagram.com"}

_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:(?:video(?::secure_url)?|image(?::secure_url)?|title)|twitter:(?:image|player:stream))["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](og:(?:video(?::secure_url)?|image(?::secure_url)?|title)|twitter:(?:image|player:stream))["\']',
    re.I,
)
# "video_url":"https:\/\/scontent....mp4?..." inside the embedded JSON payload.
_VIDEO_URL_RE = re.compile(r'"video_url"\s*:\s*"(https?://[^"]+?\.mp4[^"]*)"', re.I)
_DISPLAY_URL_RE = re.compile(r'"display_url"\s*:\s*"(https?://[^"]+?)"', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(raw: str) -> str:
    return raw.replace("\\/", "/").replace("\\u0026", "&")


def _ext(url: str) -> str:
    path = url.split("?", 1)[0].rsplit(".", 1)
    ext = path[-1].lower() if len(path) == 2 else ""
    return ext if re.fullmatch(r"[a-z0-9]{2,4}", ext) else ""


class InstagramAdapter:
    platform = "instagram"

    def can_handle(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except Exception:
            return False
        return host in _IG_HOSTS

    async def analyze(self, url: str, fetcher: SafeFetcher) -> AnalysisResult:
        page = await fetcher.fetch_text(url)
        html = page.text
        # Unescaped copy for payload scans: JSON escapes (\/) would otherwise
        # break literal matches like "https://".
        flat = _clean(html)
        variants: list[MediaVariant] = []
        seen: set[str] = set()

        def add(abs_url: str, media_type: str, label: str, ext: str) -> None:
            abs_url = _clean(abs_url)
            if not abs_url.startswith(("http://", "https://")):
                return
            if abs_url in seen:
                return
            seen.add(abs_url)
            variants.append(MediaVariant(url=abs_url, media_type=media_type,  # type: ignore[arg-type]
                                         quality_label=label, file_extension=ext))

        # 1. OpenGraph / Twitter meta (poster frame + sometimes the video).
        for pat in (_OG_RE, _OG_REV):
            for m in pat.finditer(html):
                key, content = m.group(1).lower(), m.group(2)
                abs_u = urljoin(page.url, content)
                if "video" in key or "player:stream" in key:
                    add(abs_u, "video", label_from_url(abs_u), _ext(abs_u) or "mp4")
                elif "image" in key:
                    add(abs_u, "image", "post image", _ext(abs_u) or "jpg")

        # 2. Embedded payload video URLs — the actual reel/post video.
        #    Co-located width/height fields give honest labels (1080x1920 reel
        #    -> "1080p Full HD"); otherwise URL tokens, else "video file".
        for m in _VIDEO_URL_RE.finditer(flat):
            vurl = _clean(m.group(1))
            dims = dims_near(flat, m.start())
            label = label_from_dims(*dims) if dims else label_from_url(vurl)
            add(urljoin(page.url, vurl), "video", label, "mp4")

        # 3. Embedded display URLs — post/carousel photos (for video posts this
        #    is the poster frame; kept because for photo posts it IS the content).
        for iurl in dict.fromkeys(_DISPLAY_URL_RE.findall(flat)):
            add(urljoin(page.url, _clean(iurl)), "image", "post image",
                _ext(_clean(iurl)) or "jpg")

        title = _extract_title(html)
        if not variants:
            # Login wall serves HTTP 200 with no media data: say so honestly
            # instead of reporting "not found".
            if title and "login" in title.lower():
                raise SafeFetchError(
                    ErrorCode.ACCESS_DENIED,
                    "That Instagram post needs a login to view, and MediaSaver "
                    "never logs in anywhere. Nothing was downloaded.",
                )
            return AnalysisResult(platform="instagram", page_url=page.url,
                                  title=title, thumbnail_url=None, variants=[])
        thumb = next((v.url for v in variants if v.media_type == "image"),
                     next((v.url for v in variants), None))
        return AnalysisResult(platform="instagram", page_url=page.url, title=title,
                              thumbnail_url=thumb, variants=variants)


def _extract_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    if not m:
        return None
    title = _TAG_RE.sub("", m.group(1)).strip()
    return title or None
