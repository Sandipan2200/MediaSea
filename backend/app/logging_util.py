"""Structured logging with request IDs; never logs full submitted URLs."""

from __future__ import annotations

import hashlib
import logging
import sys
import uuid


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s req=%(request_id)s %(name)s %(message)s"
        ))
        handler.addFilter(RequestIdFilter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def url_fingerprint(url: str) -> str:
    """SHA-256 prefix of the URL — enough to correlate abuse, useless for replay."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]


class RequestIdFilter(logging.Filter):
    def __init__(self) -> None:
        super().__init__()
        self.request_id = "-"

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = getattr(self, "request_id", "-")
        return True
