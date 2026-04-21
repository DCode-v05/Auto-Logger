import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from bot.auth.telegram_initdata import InitDataError, verify_init_data


BOT_TOKEN = "123456:ABCDEF"


def _build(payload: dict, token: str = BOT_TOKEN) -> str:
    pairs = {k: (v if isinstance(v, str) else json.dumps(v)) for k, v in payload.items()}
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**pairs, "hash": sig})


def test_verify_ok():
    raw = _build({
        "user": {"id": 42, "username": "alice"},
        "auth_date": str(int(time.time())),
    })
    v = verify_init_data(raw, BOT_TOKEN)
    assert v.user_id == 42
    assert v.username == "alice"


def test_verify_bad_hash():
    raw = _build({"user": {"id": 42}, "auth_date": str(int(time.time()))}, token="wrong:token")
    with pytest.raises(InitDataError):
        verify_init_data(raw, BOT_TOKEN)


def test_verify_stale():
    raw = _build({
        "user": {"id": 42},
        "auth_date": str(int(time.time()) - 999_999),
    })
    with pytest.raises(InitDataError):
        verify_init_data(raw, BOT_TOKEN)


def test_verify_missing_user():
    raw = _build({"auth_date": str(int(time.time()))})
    with pytest.raises(InitDataError):
        verify_init_data(raw, BOT_TOKEN)
