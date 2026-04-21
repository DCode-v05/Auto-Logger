from __future__ import annotations

import re
from urllib.parse import urlparse


_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def parse_time_spent(text: str) -> int:
    """Return int hours 0..24 or raise ValueError."""
    t = text.strip()
    if not t.isdigit():
        raise ValueError("Enter a whole number of hours (no decimals).")
    n = int(t)
    if n < 0 or n > 24:
        raise ValueError("Hours must be between 0 and 24.")
    return n


def validate_url(text: str) -> str:
    t = text.strip()
    if not _URL_RE.match(t):
        raise ValueError("Please send a full URL starting with http:// or https://")
    parsed = urlparse(t)
    if not parsed.netloc:
        raise ValueError("URL must include a host.")
    return t


def validate_activities(text: str) -> str:
    t = text.strip()
    if not t:
        raise ValueError("Activities cannot be empty.")
    if len(t) > 255:
        raise ValueError(f"Activities must be 255 characters or fewer (got {len(t)}).")
    return t


def validate_description(text: str) -> str:
    t = text.strip()
    if not t:
        raise ValueError("Description cannot be empty.")
    return t
