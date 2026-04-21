import pytest

from bot.utils.validators import (
    parse_time_spent,
    validate_activities,
    validate_description,
    validate_url,
)


def test_parse_time_spent_valid():
    assert parse_time_spent("0") == 0
    assert parse_time_spent("24") == 24
    assert parse_time_spent(" 8 ") == 8


@pytest.mark.parametrize("bad", ["", "abc", "2.5", "-1", "25", "100"])
def test_parse_time_spent_invalid(bad):
    with pytest.raises(ValueError):
        parse_time_spent(bad)


def test_validate_activities():
    assert validate_activities(" hello ") == "hello"
    with pytest.raises(ValueError):
        validate_activities("")
    with pytest.raises(ValueError):
        validate_activities("x" * 256)


def test_validate_description():
    assert validate_description(" desc ") == "desc"
    with pytest.raises(ValueError):
        validate_description("   ")


def test_validate_url():
    assert validate_url("https://example.com/x") == "https://example.com/x"
    assert validate_url("http://x.y") == "http://x.y"


@pytest.mark.parametrize("bad", ["", "example.com", "ftp://x", "javascript:alert(1)"])
def test_validate_url_invalid(bad):
    with pytest.raises(ValueError):
        validate_url(bad)
