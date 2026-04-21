"""Coordinates in-progress logins across FastAPI (Web App) and the Telegram bot.

FastAPI receives credentials + MFA codes from the user's Web App page; the actual
login runs as a background task that drives Playwright. Notifications back to the
user are sent through the Telegram Bot API.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from telegram import Bot

from bot.auth.login_flow import (
    LoginCallbacks,
    LoginCredentialError,
    LoginError,
    MFATimeout,
    perform_login,
)
from bot.auth.playwright_pool import PlaywrightPool
from bot.auth.session_store import SessionStore
from bot.config import Settings

log = logging.getLogger(__name__)


@dataclass
class _LoginSession:
    chat_id: int
    mfa_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None


class LoginCoordinator:
    def __init__(
        self,
        settings: Settings,
        pool: PlaywrightPool,
        session_store: SessionStore,
        bot: Bot,
    ):
        self.settings = settings
        self.pool = pool
        self.session_store = session_store
        self.bot = bot
        self._sessions: dict[int, _LoginSession] = {}
        self._lock = asyncio.Lock()

    async def start_login(self, chat_id: int, email: str, password: str) -> None:
        async with self._lock:
            existing = self._sessions.get(chat_id)
            if existing and existing.task and not existing.task.done():
                raise RuntimeError("A login is already in progress for this chat.")
            sess = _LoginSession(chat_id=chat_id)
            self._sessions[chat_id] = sess

        async def notify(text: str) -> None:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception:  # noqa: BLE001
                log.exception("notify failed for %s", chat_id)

        async def request_mfa_code() -> str:
            await self.bot.send_message(
                chat_id=chat_id,
                text=(
                    "🔐 Enter your 6-digit Microsoft verification code in the MFA form "
                    "I'm sending now."
                ),
            )
            # Send a second Web App button for MFA entry
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

            mfa_url = f"{self.settings.bot_public_url.rstrip('/')}/webapp/mfa"
            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Enter MFA code", web_app=WebAppInfo(url=mfa_url))]]
            )
            await self.bot.send_message(chat_id=chat_id, text="Open the form:", reply_markup=kb)
            code = await sess.mfa_queue.get()
            return code

        callbacks = LoginCallbacks(
            notify=notify,
            request_mfa_code=request_mfa_code,
            mfa_timeout_seconds=self.settings.mfa_timeout_seconds,
        )

        async def _run() -> None:
            try:
                ctx, lock = await self.pool.acquire(chat_id)
                async with lock:
                    resolved_email = await perform_login(
                        context=ctx,
                        pms_login_url=self.settings.pms_login_url,
                        pms_me_url=self.settings.pms_me_url,
                        email=email,
                        password=password,
                        callbacks=callbacks,
                        pms_ms_oauth_begin_url=self.settings.pms_ms_oauth_begin_url,
                    )
                self.session_store.save(chat_id, email=resolved_email, status="ok")
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ Logged in as `{resolved_email}`. Send /log to post an update.",
                    parse_mode="Markdown",
                )
            except LoginCredentialError as e:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Sign-in failed: {e}\nRun /login to try again.",
                )
            except MFATimeout as e:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"⌛ {e}\nRun /login to try again.",
                )
            except LoginError as e:
                await self.bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Login error: {e}\nRun /login to try again.",
                )
            except Exception:  # noqa: BLE001
                log.exception("unexpected login error for %s", chat_id)
                await self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Unexpected error during login. Please try /login again.",
                )
            finally:
                async with self._lock:
                    self._sessions.pop(chat_id, None)

        sess.task = asyncio.create_task(_run())

    async def submit_mfa(self, chat_id: int, code: str) -> bool:
        async with self._lock:
            sess = self._sessions.get(chat_id)
        if sess is None:
            return False
        await sess.mfa_queue.put(code)
        return True

    async def has_active(self, chat_id: int) -> bool:
        async with self._lock:
            sess = self._sessions.get(chat_id)
            return bool(sess and sess.task and not sess.task.done())
