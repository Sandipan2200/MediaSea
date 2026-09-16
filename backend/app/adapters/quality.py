"""Shared quality labeling — one place, no duplication between adapters.

Every label derives from evidence the platform itself supplied: explicit
width/height (payload fields, manifest renditions) or resolution/fps tokens in
the file's own URL (e.g. `.../clip_1080p.mp4`, `..._720w.mp4`, `.../4k/`, 60fps
markers). No dimensions and no tokens -> honest fallback ("video file"), never
an invented tier. Portrait/square media label by their smaller side, matching
common convention (1080x1920 reel -> "1080p").
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..schemas import MediaVariant

_RES_BUCKETS: tuple[tuple[int, str], ...] = (
    (4320, "8K"),
    (2160, "4K"),
    (1440, "1440p"),
    (1080, "1080p"),
    (720, "720p"),
    (480, "480p"),
    (360, "360p"),
    (240, "240p"),
)
_TAGS = {"720p": "HD", "1080p": "Full HD", "4K": "Ultra HD", "8K": "Ultra HD 8K"}

# Deliberately strict: bare numbers without a p/w/k/fps marker (IDs, hashes,
# dates) must NOT label anything. Lookarounds keep "abc1080p" and "1080p60x"
# from matching while "clip-1080p.mp4", "_720w", "/4k/" do.
_P_RES = re.compile(r"(?<![0-9a-z])(\d{3,4})p(?![0-9a-z])", re.I)
_P_FPS_RES = re.compile(r"(?<![0-9a-z])(\d{3,4})p(\d{2,3})(?![0-9a-z])", re.I)
_W_RES = re.compile(r"(?<![0-9a-z])(\d{3,4})w(?![0-9a-z])", re.I)
_K_RES = re.compile(r"(?<![0-9a-z])([48])[k](?![0-9a-z])", re.I)
_FPS_RE = re.compile(r"(?<![0-9a-z])(\d{2,3})\s?fps(?![0-9a-z])", re.I)
_WIDTH_RE = re.compile(r'"width"\s*:\s*(\d{1,5})')
_HEIGHT_RE = re.compile(r'"height"\s*:\s*(\d{1,5})')

# Codec tokens embedded in CDN paths (e.g. .../h265-pt-mp4/..., .../av1Mp4-...).
# Used ONLY to tell apart same-quality duplicates, never to claim a quality.
# expMp4 = Pinterest's standard progressive-MP4 (H.264) export flag.
_CODEC_RE = re.compile(
    r"(?<![0-9a-z])(h265|hevc|h264|avc|av1|vp9|mpeg4|expmp4)(?:mp4)?(?:v\d+)?(?![0-9a-z])",
    re.I,
)
_CODEC_NAMES = {
    "h265": "HEVC", "hevc": "HEVC", "h264": "H.264", "avc": "H.264",
    "av1": "AV1", "vp9": "VP9", "mpeg4": "MPEG-4", "expmp4": "H.264",
}


def _bucket(pixels: int) -> str:
    for threshold, name in _RES_BUCKETS:
        if pixels >= threshold:
            return name
    return f"{pixels}p"


def _compose(base: str, fps: int | None) -> str:
    if fps:
        base = f"{base}{fps}"
    tag = _TAGS.get(re.sub(r"\d+$", "", base), "")
    return f"{base} {tag}" if tag else base


def _valid_fps(n: int) -> bool:
    return 24 <= n <= 240


def label_from_dims(width: int, height: int, fps: int | None = None) -> str:
    """Label from known dimensions, e.g. (1920, 1080) -> "1080p Full HD"."""
    return _compose(_bucket(min(width, height)), fps if fps and _valid_fps(fps) else None)


def label_from_url(url: str, fallback: str = "video file") -> str:
    """Label from resolution/fps tokens in the file URL, else fallback."""
    u = url.lower()
    size: int | None = None
    m = _P_FPS_RES.search(u)
    fps: int | None = None
    if m:
        size, fps = int(m.group(1)), int(m.group(2))
        if not _valid_fps(fps):
            fps = None
    else:
        m2 = _P_RES.search(u) or _W_RES.search(u)
        if m2:
            size = int(m2.group(1))
        else:
            k = _K_RES.search(u)
            if k:
                size = 2160 if k.group(1) == "4" else 4320
        f = _FPS_RE.search(u)
        if f and _valid_fps(int(f.group(1))):
            fps = int(f.group(1))
    if size is None:
        return fallback
    return _compose(_bucket(size), fps)


def dims_near(text: str, pos: int, window: int = 500) -> tuple[int, int] | None:
    """Width/height JSON fields near a byte offset (e.g. around a video_url).

    Payloads commonly co-locate `"width":1080,"height":1920` with the URL.
    Bounds-checked so garbage numbers never label anything.
    """
    snippet = text[max(0, pos - window):pos + window]
    w = _WIDTH_RE.search(snippet)
    h = _HEIGHT_RE.search(snippet)
    if w and h:
        wi, hi = int(w.group(1)), int(h.group(1))
        if 16 <= wi <= 16000 and 16 <= hi <= 16000:
            return (wi, hi)
    return None


def codec_hint(url: str) -> str | None:
    """Codec name from CDN path tokens, e.g. .../av1Mp4-... -> "AV1"."""
    m = _CODEC_RE.search(url.lower())
    return _CODEC_NAMES.get(m.group(1)) if m else None


def disambiguate_labels(variants: list[MediaVariant]) -> None:
    """Make duplicate (media_type, format, label) entries unique in place.

    Same-quality renditions in different codecs (e.g. five "720p HD" mp4s in
    HEVC/AV1/H.264) get a codec suffix; residual collisions get a number.
    Singletons are never touched, so existing labels stay stable.
    """
    used: set[tuple[str, str, str]] = set()
    for v in variants:
        key = (v.media_type, v.file_extension, v.quality_label)
        if key not in used:
            used.add(key)
            continue
        hint = codec_hint(v.url)
        candidate = f"{v.quality_label} · {hint}" if hint else v.quality_label
        new_key = (v.media_type, v.file_extension, candidate)
        n = 2
        while new_key in used:
            candidate = (
                f"{v.quality_label} · {hint} ({n})"
                if hint else f"{v.quality_label} ({n})"
            )
            new_key = (v.media_type, v.file_extension, candidate)
            n += 1
        v.quality_label = candidate
        used.add(new_key)
