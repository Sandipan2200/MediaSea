"""Pinterest adapter — public pins only, no login.

Source of truth: the pin page's own public HTML (OpenGraph meta, JSON-LD, and
the embedded __PWS_DATA__ payload). Only URLs the page itself serves are
returned, plus pinimg size-prefix variants of an *observed* image URL.

Why size-prefix derivation is honest, not fabrication: i.pinimg.com serves the
same image bytes at documented resize prefixes (236x/474x/736x/originals) with
an identical content hash path. We never invent a path — we swap only the
prefix of a URL the page already gave us — and label each variant plainly.
Video renditions (V_720P/V_480P/...) are taken verbatim from the payload.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin

from ..fetcher import SafeFetcher
from ..schemas import AnalysisResult, MediaVariant
from .quality import label_from_dims, label_from_url

_PIN_HOSTS = {"pinterest.com", "www.pinterest.com", "pin.it", "www.pin.it"}

_OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:(?:video(?::secure_url)?|image(?::secure_url)?|title)|twitter:(?:image|player:stream))["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_REV = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](og:(?:video(?::secure_url)?|image(?::secure_url)?|title)|twitter:(?:image|player:stream))["\']',
    re.I,
)
_LD_JSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
_PINIMG_RE = re.compile(
    r"https://i\.pinimg\.com/[A-Za-z0-9_\-./]+?\.(?:jpg|jpeg|png|gif|webp)"
    r"(?:\?[A-Za-z0-9_\-./=&%]+)?",
    re.I,
)
_VIDEO_URL_RE = re.compile(r"https://(?:v1|v\d)\.pinimg\.com/videos/[^\s'\"<>\\]+?\.mp4[^\s'\"<>\\]*", re.I)
# Platform's own rendition blocks: "V_720P":{"url":"...","width":720,...}.
# Parsed for honest per-rendition labels (dims first, V_KEY name second).
_V_BLOCK_RE = re.compile(r'"(V_[A-Za-z0-9]+)"\s*:\s*\{([^}]*)\}', re.S)
_V_BLOCK_URL_RE = re.compile(r'"url"\s*:\s*"([^"]+)"')
_V_BLOCK_DIM_RE = re.compile(r'"(width|height)"\s*:\s*(\d{1,5})')
_V_KEY_RES_RE = re.compile(r"V_(\d+)[Pp]")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


class PinterestAdapter:
    platform = "pinterest"

    def can_handle(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except Exception:
            return False
        return host in _PIN_HOSTS or host.endswith(".pinterest.com")

    async def analyze(self, url: str, fetcher: SafeFetcher) -> AnalysisResult:
        page = await fetcher.fetch_text(url)
        html = page.text
        variants: list[MediaVariant] = []
        seen: set[str] = set()
        # Content-paths (after the size prefix) of images declared via primary
        # evidence. Used to (a) gate sibling derivation — no invented sizes for
        # random page-chrome images — and (b) trim page chrome on video pins.
        known_image_paths: set[str] = set()
        # True once the page DECLARES pin media via meta/structured data/video
        # files. Bare pinimg URLs alone (UI sprites in CSS/JS bundles on error
        # or shell pages) must never constitute a "successful" analysis —
        # without this, a deleted pin (HTTP 200 shell page) would return bogus
        # asset URLs as downloadable variants instead of MEDIA_NOT_FOUND.
        has_primary = False

        def add(abs_url: str, media_type: str, label: str, ext: str, w: int | None = None,
                h: int | None = None, primary: bool = False) -> None:
            nonlocal has_primary
            abs_url = abs_url.replace("\\u0026", "&").replace("\\/", "/")
            if not abs_url.startswith(("http://", "https://")):
                return
            if abs_url in seen:
                return
            seen.add(abs_url)
            if primary:
                has_primary = True
                if media_type == "image":
                    path = _pinimg_path(abs_url)
                    if path:
                        known_image_paths.add(path)
            variants.append(MediaVariant(url=abs_url, media_type=media_type,  # type: ignore[arg-type]
                                         quality_label=label, file_extension=ext,
                                         width=w, height=h))

        # 1. OpenGraph / Twitter meta.
        for pat in (_OG_RE, _OG_REV):
            for m in pat.finditer(html):
                key, content = m.group(1).lower(), m.group(2)
                abs_u = urljoin(page.url, content)
                if "video" in key or "player:stream" in key:
                    add(abs_u, "video", label_from_url(abs_u), _ext(abs_u), primary=True)
                elif "image" in key:
                    add(abs_u, "image", _pinimg_label(abs_u), _ext(abs_u) or "jpg", primary=True)

        # 2. JSON-LD blocks (contentUrl / thumbnailUrl).
        for m in _LD_JSON_RE.finditer(html):
            try:
                data = json.loads(m.group(1))
            except Exception:
                continue
            for obj in data if isinstance(data, list) else [data]:
                if not isinstance(obj, dict):
                    continue
                for k, mt, lb in (("contentUrl", "video", "video file"),
                                  ("thumbnailUrl", "image", "image file")):
                    v = obj.get(k)
                    if isinstance(v, str) and v.startswith("http"):
                        label = label_from_url(v) if mt == "video" else lb
                        add(urljoin(page.url, v), mt, label, _ext(v) or ("mp4" if mt == "video" else "jpg"), primary=True)  # type: ignore[arg-type]

        # 3. Platform rendition blocks (V_720P -> url + width/height): best
        #    labels first. Runs before the plain URL scan so these win; the
        #    scan below only picks up leftovers (dedupe via `seen`).
        for bm in _V_BLOCK_RE.finditer(html):
            key, block = bm.group(1), bm.group(2)
            um = _V_BLOCK_URL_RE.search(block)
            if not um:
                continue
            clean = um.group(1).replace("\\u0026", "&").replace("\\/", "/")
            dims = {k: int(n) for k, n in _V_BLOCK_DIM_RE.findall(block)}
            label: str | None = None
            if "width" in dims and "height" in dims:
                w, h = dims["width"], dims["height"]
                if 16 <= w <= 16000 and 16 <= h <= 16000:
                    label = label_from_dims(w, h)
            if label is None:
                km = _V_KEY_RES_RE.search(key)
                if km:
                    label = label_from_dims(int(km.group(1)), int(km.group(1)))
            add(urljoin(page.url, clean), "video",
                label or label_from_url(clean), "mp4", primary=True)

        # 3b. Direct pinimg video file URLs not covered above.
        for vurl in dict.fromkeys(_VIDEO_URL_RE.findall(html)):
            clean = vurl.replace("\\u0026", "&").replace("\\/", "/")
            add(urljoin(page.url, clean), "video", label_from_url(clean), "mp4", primary=True)

        # 4. Image variants: every pinimg image URL observed, plus size-prefix
        #    siblings ONLY for known pin content paths (same hash path — the
        #    platform's own delivery). Siblings for random page-chrome images
        #    (avatars, covers) would be invented sizes that likely 404.
        #    Gated on has_primary (see above).
        if has_primary:
            for img in dict.fromkeys(_PINIMG_RE.findall(html)):
                abs_u = urljoin(page.url, img.replace("\\/", "/"))
                path = _pinimg_path(abs_u)
                add(abs_u, "image", _pinimg_label(abs_u), _ext(abs_u) or "jpg")
                if path and path in known_image_paths:
                    for sib in _pinimg_siblings(abs_u):
                        add(sib, "image", _pinimg_label(sib), _ext(sib) or "jpg")

        # 5. On video pins, the post's media is the video + its poster frame.
        #    Related-pin images, board covers and avatars are page chrome, not
        #    this post — drop them so the image section stays meaningful.
        if any(v.media_type == "video" for v in variants):
            variants = [
                v for v in variants
                if v.media_type != "image"
                or not v.url.startswith("https://i.pinimg.com/")
                or _pinimg_path(v.url) in known_image_paths
            ]

        title = _extract_title(html)
        thumb = next((v.url for v in variants if v.media_type == "image"), None)
        return AnalysisResult(platform="pinterest", page_url=page.url, title=title,
                              thumbnail_url=thumb, variants=variants)


def _ext(url: str) -> str:
    path = url.split("?", 1)[0].rsplit(".", 1)
    ext = path[-1].lower() if len(path) == 2 else ""
    return ext if re.fullmatch(r"[a-z0-9]{2,4}", ext) else ""


_PINIMG_SIZE_RE = re.compile(r"^(https://i\.pinimg\.com/)([^/]+)(/.*)$")
_PINIMG_PATH_RE = re.compile(r"^https://i\.pinimg\.com/[^/]+(/.*)$")


def _pinimg_path(url: str) -> str:
    """Content path after the size prefix, e.g. '/ab/cd/ef.jpg'."""
    m = _PINIMG_PATH_RE.match(url.split("?", 1)[0])
    return m.group(1) if m else ""


def _pinimg_label(url: str) -> str:
    m = _PINIMG_SIZE_RE.match(url)
    if m:
        prefix = m.group(2)
        if prefix == "originals":
            return "original"
        return f"{prefix}"
    return "image file"


def _pinimg_siblings(url: str) -> list[str]:
    """Sibling resize prefixes for an observed pinimg URL (same content path)."""
    m = _PINIMG_SIZE_RE.match(url)
    if not m or "/videos/" in url:
        return []
    base, _prefix, rest = m.group(1), m.group(2), m.group(3)
    out = []
    for p in ("originals", "736x", "474x", "236x"):
        cand = f"{base}{p}{rest}"
        if cand != url:
            out.append(cand)
    return out


def _extract_title(html: str) -> str | None:
    m = _TITLE_RE.search(html)
    if not m:
        return None
    title = _TAG_RE.sub("", m.group(1)).strip()
    return title or None
