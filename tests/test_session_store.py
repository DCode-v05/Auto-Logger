from cryptography.fernet import Fernet

from bot.auth.session_store import SessionStore


def test_roundtrip(tmp_path):
    key = Fernet.generate_key().decode()
    store = SessionStore(tmp_path / "s.sqlite", key)
    assert store.get(1) is None

    store.save(1, email="user@example.com", status="ok")
    s = store.get(1)
    assert s is not None
    assert s.chat_id == 1
    assert s.email == "user@example.com"
    assert s.status == "ok"

    store.mark(1, "expired")
    assert store.get(1).status == "expired"

    store.delete(1)
    assert store.get(1) is None


def test_email_encrypted_on_disk(tmp_path):
    key = Fernet.generate_key().decode()
    store = SessionStore(tmp_path / "s.sqlite", key)
    store.save(99, email="secret@example.com")
    raw = (tmp_path / "s.sqlite").read_bytes()
    assert b"secret@example.com" not in raw
