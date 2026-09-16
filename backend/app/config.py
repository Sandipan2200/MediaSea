"""MediaSaver backend configuration (env-driven, documented defaults)."""

from __future__ import annotations

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """All tunables come from the environment; see backend/.env.example."""

    # Network hardening
    connect_timeout_s: float = 5.0
    read_timeout_s: float = 10.0
    max_response_bytes: int = 2_000_000  # 2 MB: manifests + HTML pages only, never media bytes
    max_redirects: int = 5
    max_url_length: int = 2048
    max_outbound_concurrency: int = 8

    # Rate limiting (analyses per minute per IP). Reasoning: analysis is cheap
    # (a few KB of HTML/manifest), 20/min/IP stops credential-stuffing-style
    # abuse and SSRF probing while never throttling a human pasting links.
    rate_limit_per_minute: int = 20

    # CORS: exact origins (comma-separated) plus a regex. NOTE: Starlette matches
    # allow_origins EXACTLY — "chrome-extension://*" as a literal entry matches
    # nothing (only full "*" is special), which silently breaks the popup while
    # curl keeps working (curl ignores CORS). Extension origins MUST go through
    # allow_origin_regex.
    cors_allow_origins: str = "http://localhost:5173"
    cors_allow_origin_regex: str = (
        r"chrome-extension://.*|http://localhost:\d+|http://127\.0\.0\.1:\d+"
    )

    # Privacy: never log full submitted URLs at info level.
    log_level: str = "INFO"

    model_config = {"env_prefix": "MEDIASAVER_", "env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
