"""Generic adapter: raw <video>/<source>, OpenGraph/Twitter meta, HLS/DASH manifests.

Zero platform-policy risk: only inspects what the page publicly serves over
unauthenticated HTTP. Manifests are fetched as TEXT (capped by SafeFetcher);
media segments are never downloaded by the backend.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from ..fetcher import SafeFetcher
from ..schemas import AnalysisResult, MediaVariant
from .quality import label_from_dims, label_from_url

_MANIFEST_RE = re.compile(r"(https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*|https?://[^\s'\"<>]+\.mpd[^\s'\"<>]*)", re.I)
_HLS_RES_RE = re.compile(r"RESOLUTION=(\d+)x(\d+)", re.I)
_HLS_BW_RE = re.compile(r"BANDWIDTH=(\d+)", re.I)

# Bare direct-file URLs embedded in page data (e.g. a "video_url" JSON field in
# a server-rendered payload). Same honesty rule as everything else: only URLs
# the page publicly serves, unescaped and validated. The trailing lookahead
# prevents truncating longer tokens (e.g. "...clip.mp4junk" must not become a
# fake "...clip.mp4" variant). Backslash-escapes (\/) are unescaped first.
_DIRECT_FILE_RE = re.compile(
    r"https?://[^\s\"'<>\\]*?\.(?:mp4|webm|mov|m4v|jpg|jpeg|png|webp|gif|bmp|mp3|m4a|wav|ogg)"
    r"(?:\?[^\s\"'<>\\]*)?(?![A-Za-z0-9_.%-])",
    re.I,
)
_DIRECT_EXT_KIND = {
    "mp4": "video", "webm": "video", "mov": "video", "m4v": "video",
    "jpg": "image", "jpeg": "image", "png": "image", "webp": "image",
    "gif": "image", "bmp": "image",
    "mp3": "audio", "m4a": "audio", "wav": "audio", "ogg": "audio",
}
_DIRECT_EXT_LABEL = {"video": "video file", "image": "image file", "audio": "audio file"}


class _MediaHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.videos: list[str] = []
        self.images: list[str] = []
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in ("video", "source") and a.get("src"):
            self.videos.append(a["src"])
        elif tag == "img" and a.get("src"):
            self.images.append(a["src"])
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content"):
                self.meta.setdefault(key, a["content"])
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data.strip())


def _ext_of(url: str) -> str:
    path = url.split("?", 1)[0].rsplit(".", 1)
    ext = path[-1].lower() if len(path) == 2 else ""
    return ext if re.fullmatch(r"[a-z0-9]{2,4}", ext) else "mp4"


def _looks_like_uri(line: str) -> bool:
    """Bare playlist lines are only renditions if they are URI-shaped.

    Without this, a garbage/error body that happens to contain a bare text
    line would be urljoin()ed into a fabricated 'variant' pointing at nonsense
    (e.g. ".../this is not a playlist"). Reject whitespace/control chars and
    absurd lengths; the extension would otherwise offer a broken download.
    """
    if not line or len(line) > 2048:
        return False
    return not re.search(r"[\s\x00-\x1f\x7f]", line)


def parse_hls_variants(manifest_text: str, manifest_url: str) -> list[MediaVariant]:
    """Parse an HLS playlist into variants.

    Master playlists (#EXT-X-STREAM-INF + URI) yield one variant per rendition
    the CDN serves. Media playlists (segments, #EXTINF/...) yield a single
    manifest-as-is variant — per-segment downloads would be dozens of 10s
    chunks and a misleading UX. Anything else (garbage, truncated headers with
    no URI) yields [] so callers degrade to MEDIA_NOT_FOUND, never fabricated
    entries and never an exception.
    """
    variants: list[MediaVariant] = []
    lines = manifest_text.splitlines()
    pending_bw: int | None = None
    pending_res: tuple[int, int] | None = None
    saw_media_tags = False
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("#EXT-X-STREAM-INF"):
            m_bw = _HLS_BW_RE.search(s)
            m_res = _HLS_RES_RE.search(s)
            pending_bw = int(m_bw.group(1)) if m_bw else None
            pending_res = (int(m_res.group(1)), int(m_res.group(2))) if m_res else None
            continue
        if s.startswith("#"):
            if s.startswith(("#EXTINF", "#EXT-X-TARGETDURATION", "#EXT-X-MEDIA-SEQUENCE")):
                saw_media_tags = True
            pending_bw, pending_res = None, None
            continue
        # Bare URI line: only meaningful directly after EXT-X-STREAM-INF.
        if pending_bw is not None or pending_res is not None:
            if _looks_like_uri(s):
                if pending_res:
                    label = label_from_dims(pending_res[0], pending_res[1])
                elif pending_bw:
                    label = f"{pending_bw // 1000}k"
                else:
                    label = "hls"
                variants.append(
                    MediaVariant(
                        url=urljoin(manifest_url, s),
                        media_type="video",
                        quality_label=label,
                        width=pending_res[0] if pending_res else None,
                        height=pending_res[1] if pending_res else None,
                        file_extension="mp4",
                        is_manifest=False,
                    )
                )
            pending_bw, pending_res = None, None
        # else: bare line outside rendition context (segment URI or garbage) —
        # deliberately ignored; media playlists are handled below.
    if not variants and saw_media_tags:
        variants.append(
            MediaVariant(
                url=manifest_url,
                media_type="video",
                quality_label="hls manifest",
                file_extension="m3u8",
                is_manifest=True,
            )
        )
    return variants


class GenericMediaAdapter:
    """Handles any public page with direct media tags or HLS/DASH manifests."""

    platform = "generic"

    def can_handle(self, url: str) -> bool:
        return url.startswith("http://") or url.startswith("https://")

    async def analyze(self, url: str, fetcher: SafeFetcher) -> AnalysisResult:
        page = await fetcher.fetch_text(url)
        parser = _MediaHTMLParser()
        parser.feed(page.text[:1_000_000])

        variants: list[MediaVariant] = []
        seen: set[str] = set()

        def add_variant(abs_url: str, media_type: str, label: str, **kw: object) -> None:
            if not abs_url.startswith(("http://", "https://")):
                return
            if abs_url in seen:
                return
            seen.add(abs_url)
            variants.append(
                MediaVariant(url=abs_url, media_type=media_type, quality_label=label, **kw)  # type: ignore[arg-type]
            )

        # 1. OpenGraph / Twitter meta (platform's own declared media).
        for key, mtype in (("og:video", "video"), ("twitter:player:stream", "video")):
            if parser.meta.get(key):
                abs_u = urljoin(page.url, parser.meta[key])
                add_variant(abs_u, "video", label_from_url(abs_u), file_extension=_ext_of(abs_u))
        for key in ("og:image", "twitter:image"):
            if parser.meta.get(key):
                abs_u = urljoin(page.url, parser.meta[key])
                add_variant(abs_u, "image", "image file", file_extension=_ext_of(abs_u) or "jpg")

        # 2. Raw <video>/<source> tags.
        for src in parser.videos:
            abs_u = urljoin(page.url, src)
            add_variant(abs_u, "video", label_from_url(abs_u), file_extension=_ext_of(abs_u))

        # 3. HLS/DASH manifests referenced anywhere in the HTML: fetch manifest
        #    TEXT only, enumerate renditions, never touch segments.
        for m_url in dict.fromkeys(_MANIFEST_RE.findall(page.text)):
            abs_m = urljoin(page.url, m_url)
            try:
                manifest = await fetcher.fetch_text(abs_m)
            except Exception:
                continue
            if ".m3u8" in abs_m.lower():
                for v in parse_hls_variants(manifest.text, abs_m):
                    add_variant(
                        v.url, "video", v.quality_label,
                        width=v.width, height=v.height,
                        file_extension=v.file_extension,
                    )
            else:  # .mpd — expose the manifest itself; extension saves it as-is
                add_variant(abs_m, "video", "dash manifest", file_extension="mpd", is_manifest=True)

        # 4. Bare direct-file URLs embedded in page data (JSON payloads, JS
        #    config). Unescape first so \/ and \u0026 forms match cleanly.
        unescaped = page.text.replace("\\/", "/").replace("\\u0026", "&")
        for m in dict.fromkeys(_DIRECT_FILE_RE.findall(unescaped)):
            abs_u = urljoin(page.url, m)
            ext = _ext_of(abs_u)
            kind = _DIRECT_EXT_KIND.get(ext)
            if not kind:
                continue
            label = label_from_url(abs_u) if kind == "video" else _DIRECT_EXT_LABEL[kind]
            add_variant(abs_u, kind, label, file_extension=ext)

        title = " ".join(parser.title_parts).strip() or None
        thumb = parser.meta.get("og:image") or (parser.images[:1] or [None])[0]
        if thumb and not thumb.startswith("http"):
            thumb = urljoin(page.url, thumb)
        return AnalysisResult(
            platform="generic",
            page_url=page.url,
            title=title,
            thumbnail_url=thumb,
            variants=variants,
        )
