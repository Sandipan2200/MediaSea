"""YouTube guard — hard refusal, never extraction (non-negotiable rule #1)."""

from __future__ import annotations

from urllib.parse import urlparse

_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return False
    return host in _YOUTUBE_HOSTS or host.endswith(".youtube.com") or host.endswith(".youtu.be")


YOUTUBE_REFUSAL = (
    "YouTube downloads are not supported: YouTube's Terms of Service prohibit "
    "third-party download tools, and Chrome Web Store policy treats facilitating "
    "them as grounds for removal. This is intentional and permanent."
)
