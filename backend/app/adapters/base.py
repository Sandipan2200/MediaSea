"""Adapter protocol + shared base. Adapters NEVER do their own HTTP."""

from __future__ import annotations

from typing import Protocol

from ..fetcher import SafeFetcher
from ..schemas import AnalysisResult


class PlatformAdapter(Protocol):
    def can_handle(self, url: str) -> bool: ...
    async def analyze(self, url: str, fetcher: SafeFetcher) -> AnalysisResult: ...


ADAPTER_NAMES = ("pinterest", "instagram", "generic")
