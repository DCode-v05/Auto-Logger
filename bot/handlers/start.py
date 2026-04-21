from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.auth.playwright_pool import PlaywrightPool
from bot.auth.session_store import SessionStore
from bot.config import Settings

log = logging.getLogger(__name__)


def _login_button(settings: Settings) -> InlineKeyboardMarkup:
    url = f"{settings.bot_public_url.rstrip('/')}/webapp/login"
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔐 Sign in with Microsoft", web_app=WebAppInfo(url=url))]]
    )


def register(
    app: Application,
    settings: Settings,
    session_store: SessionStore,
    pool: PlaywrightPool,
) -> None:
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        sess = session_store.get(update.effective_chat.id) if update.effective_chat else None
        if sess and sess.status == "ok":
            await update.effective_message.reply_text(
                f"Logged in as `{sess.email}`. Send /log to post an update, "
                "/recent to see your last logs, or /logout to sign out.",
                parse_mode="Markdown",
            )
            return
        await update.effective_message.reply_text(
            "Welcome to the iQube PMS bot. Use /login to sign in with your college Microsoft account.",
        )

    async def login_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            "Tap the button below to sign in. Your Microsoft password is used once and not stored.",
            reply_markup=_login_button(settings),
        )

    async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None:
            return
        session_store.delete(chat_id)
        await pool.wipe_profile(chat_id)
        await update.effective_message.reply_text(
            "Signed out and local browser profile cleared. Run /login to sign in again."
        )

    async def whoami(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None:
            return
        sess = session_store.get(chat_id)
        if sess:
            await update.effective_message.reply_text(
                f"Signed in as `{sess.email}` (status: {sess.status}).", parse_mode="Markdown"
            )
        else:
            await update.effective_message.reply_text("Not signed in. Use /login.")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login_cmd))
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CommandHandler("whoami", whoami))
