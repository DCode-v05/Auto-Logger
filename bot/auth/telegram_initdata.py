"""Verify Telegram Web App `initData` per https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


class InitDataError(Exception):
    pass


@dataclass
class VerifiedInitData:
    user_id: int
    username: str | None
    auth_date: int
    raw: dict[str, Any]


def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int = 3600) -> VerifiedInitData:
    """Parse + HMAC-verify a Telegram Web App initData string.

    Raises InitDataError on any failure. Returns VerifiedInitData on success.
    """
    if not init_data:
        raise InitDataError("empty initData")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    provided_hash = pairs.pop("hash", None)
    if not provided_hash:
        raise InitDataError("missing hash")

    # Data-check-string: sorted `key=value` lines joined by \n
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed, provided_hash):
        raise InitDataError("hash mismatch")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as e:
        raise InitDataError("bad auth_date") from e
    if auth_date <= 0 or (time.time() - auth_date) > max_age_seconds:
        raise InitDataError("initData too old")

    user_json = pairs.get("user")
    if not user_json:
        raise InitDataError("missing user")
    try:
        user = json.loads(user_json)
    except json.JSONDecodeError as e:
        raise InitDataError("bad user json") from e

    user_id = user.get("id")
    if not isinstance(user_id, int):
        raise InitDataError("missing user.id")

    return VerifiedInitData(
        user_id=user_id,
        username=user.get("username"),
        auth_date=auth_date,
        raw=pairs,
    )
