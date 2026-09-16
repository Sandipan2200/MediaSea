"""URL -> adapter selection. YouTube is refused before any adapter runs."""

from __future__ import annotations

from .adapters.generic import GenericMediaAdapter
from .adapters.instagram import InstagramAdapter
from .adapters.pinterest import PinterestAdapter
from .adapters.quality import disambiguate_labels
from .adapters.youtube_guard import YOUTUBE_REFUSAL, is_youtube_url
from .fetcher import SafeFetcher
from .schemas import AnalysisResult, ErrorCode
from .fetcher import SafeFetchError

_ADAPTERS = (PinterestAdapter(), InstagramAdapter(), GenericMediaAdapter())


def select_adapter(url: str) -> PinterestAdapter | InstagramAdapter | GenericMediaAdapter:
    for adapter in _ADAPTERS:
        if adapter.can_handle(url):
            return adapter
    return GenericMediaAdapter()  # generic accepts any http(s); unreachable fallback


def detect_platform(url: str) -> str:
    if is_youtube_url(url):
        return "youtube"
    for adapter in _ADAPTERS:
        if adapter.can_handle(url):
            return adapter.platform
    return "generic"


async def analyze_url(url: str, fetcher: SafeFetcher) -> AnalysisResult:
    """Route to the right adapter. Raises SafeFetchError with public codes."""
    if is_youtube_url(url):
        raise SafeFetchError(ErrorCode.UNSUPPORTED_PLATFORM, YOUTUBE_REFUSAL)
    adapter = select_adapter(url)
    result = await adapter.analyze(url, fetcher)
    disambiguate_labels(result.variants)
    if not result.variants:
        raise SafeFetchError(
            ErrorCode.MEDIA_NOT_FOUND,
            "No downloadable media found on that page. It may be private, "
            "removed, or a type we don't support yet.",
        )
    return result
