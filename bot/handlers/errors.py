from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, ContextTypes

log = logging.getLogger(__name__)


def register(app: Application) -> None:
    async def handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.exception("unhandled error", exc_info=context.error)
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text(
                    "Something went wrong. Please try again, or /cancel and retry."
                )
        except Exception:  # noqa: BLE001
            log.exception("failed to notify user about error")

    app.add_error_handler(handler)
