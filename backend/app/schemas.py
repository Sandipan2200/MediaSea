"""Shared error codes + Pydantic schemas for every request/response.

The extension translates each ErrorCode into a plain-language message and must
never display raw backend strings (see extension/src/errors.ts for the mapping).
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ErrorCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    MEDIA_NOT_FOUND = "MEDIA_NOT_FOUND"
    PRIVATE_CONTENT = "PRIVATE_CONTENT"
    ACCESS_DENIED = "ACCESS_DENIED"
    PROTECTED_CONTENT = "PROTECTED_CONTENT"
    RATE_LIMITED = "RATE_LIMITED"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    NETWORK_ERROR = "NETWORK_ERROR"
    SERVER_ERROR = "SERVER_ERROR"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED_ACCESS = "UNSUPPORTED_ACCESS"


class MediaVariant(BaseModel):
    """One concrete downloadable rendition the platform itself serves.

    `url` is a direct, time-bounded CDN URL. The backend never proxies bytes;
    the extension downloads this URL via chrome.downloads.download().
    """

    url: str = Field(..., max_length=2048)
    media_type: Literal["video", "image", "audio"] = "video"
    quality_label: str = Field(..., description="e.g. '1080p', 'original', '720p mp4'")
    width: int | None = None
    height: int | None = None
    file_extension: str = Field(default="mp4")
    file_size_bytes: int | None = None
    is_manifest: bool = Field(
        default=False,
        description="True for HLS/DASH playlists: extension downloads the manifest URL as-is.",
    )


class AnalyzeRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2048)

    @field_validator("url")
    @classmethod
    def must_be_http(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("URL must start with http:// or https://")
        return v


class AnalysisResult(BaseModel):
    platform: str
    page_url: str
    title: str | None = None
    thumbnail_url: str | None = None
    variants: list[MediaVariant] = Field(default_factory=list)


class AnalyzeSuccessResponse(BaseModel):
    ok: Literal[True] = True
    data: AnalysisResult


class AnalyzeErrorResponse(BaseModel):
    ok: Literal[False] = False
    error: ErrorCode
    reason: str = Field(..., description="Human-readable, safe to display; no internals.")
    platform: str | None = None


class HealthResponse(BaseModel):
    ok: Literal[True] = True
    version: str = "0.1.0"
