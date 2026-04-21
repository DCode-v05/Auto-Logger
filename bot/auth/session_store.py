from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    chat_id      INTEGER PRIMARY KEY,
    enc_email    BLOB NOT NULL,
    status       TEXT NOT NULL,
    last_login   INTEGER NOT NULL,
    last_used    INTEGER NOT NULL
);
"""


@dataclass
class Session:
    chat_id: int
    email: str
    status: str  # 'ok' | 'expired' | 'logged_out'
    last_login: int
    last_used: int


class SessionStore:
    def __init__(self, db_path: Path, fernet_key: str):
        self.db_path = db_path
        self._fernet = Fernet(fernet_key.encode() if isinstance(fernet_key, str) else fernet_key)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _enc(self, s: str) -> bytes:
        return self._fernet.encrypt(s.encode("utf-8"))

    def _dec(self, b: bytes) -> str:
        return self._fernet.decrypt(b).decode("utf-8")

    def save(self, chat_id: int, email: str, status: str = "ok") -> None:
        now = int(time.time())
        with self._conn() as c:
            c.execute(
                "INSERT INTO sessions (chat_id, enc_email, status, last_login, last_used) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET "
                "enc_email=excluded.enc_email, status=excluded.status, "
                "last_login=excluded.last_login, last_used=excluded.last_used",
                (chat_id, self._enc(email), status, now, now),
            )

    def touch(self, chat_id: int) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE sessions SET last_used = ? WHERE chat_id = ?",
                (int(time.time()), chat_id),
            )

    def mark(self, chat_id: int, status: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE sessions SET status = ? WHERE chat_id = ?", (status, chat_id))

    def get(self, chat_id: int) -> Session | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT chat_id, enc_email, status, last_login, last_used "
                "FROM sessions WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        if not row:
            return None
        try:
            email = self._dec(row["enc_email"])
        except InvalidToken:
            return None
        return Session(
            chat_id=row["chat_id"],
            email=email,
            status=row["status"],
            last_login=row["last_login"],
            last_used=row["last_used"],
        )

    def delete(self, chat_id: int) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM sessions WHERE chat_id = ?", (chat_id,))
