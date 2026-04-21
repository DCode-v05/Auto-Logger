from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.auth.playwright_pool import PlaywrightPool, ReLoginRequired
from bot.auth.session_store import SessionStore
from bot.config import Settings
from bot.pms import selectors as S
from bot.pms.submit_log import (
    FormValidationError,
    LogPayload,
    SubmitError,
    submit_log,
)
from bot.utils import keyboards as K
from bot.utils.validators import (
    parse_time_spent,
    validate_activities,
    validate_description,
    validate_url,
)

log = logging.getLogger(__name__)

(
    CHOOSE_OPTIONALS,
    ASK_ACTIVITIES,
    ASK_TIME,
    ASK_LOCATION,
    ASK_LOCATION_OTHER,
    ASK_DESCRIPTION,
    ASK_REFERENCE_LINK,
    ASK_ATTACHMENT,
    REVIEW,
    EDIT_PICK,
) = range(10)


def _state(ctx: ContextTypes.DEFAULT_TYPE) -> dict[str, Any]:
    return ctx.user_data.setdefault("log", {})


def _reset(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    # Remove downloaded attachments
    st = ctx.user_data.get("log") or {}
    path = st.get("attachment_path")
    if path:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            pass
    ctx.user_data.pop("log", None)


def _summary(st: dict[str, Any]) -> str:
    loc = st.get("location", "—")
    if loc == S.LOCATION_OTHER and st.get("location_other"):
        loc = f"{loc}: {st['location_other']}"
    lines = [
        "*Review your log*",
        f"• Activities: {st.get('activities', '—')}",
        f"• Time spent: {st.get('time_spent', '—')} h",
        f"• Location: {loc}",
        f"• Description: {st.get('description', '—')}",
    ]
    if st.get("want_ref"):
        lines.append(f"• Reference link: {st.get('reference_link') or '—'}")
    if st.get("want_attach"):
        lines.append(f"• Attachment: {st.get('attachment_filename') or '—'}")
    return "\n".join(lines)


def register(
    app: Application,
    settings: Settings,
    session_store: SessionStore,
    pool: PlaywrightPool,
) -> None:
    async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        chat_id = update.effective_chat.id if update.effective_chat else None
        sess = session_store.get(chat_id) if chat_id is not None else None
        if not sess or sess.status != "ok":
            await update.effective_message.reply_text(
                "You need to sign in first. Use /login."
            )
            return ConversationHandler.END
        _reset(context)
        st = _state(context)
        st["want_ref"] = False
        st["want_attach"] = False
        await update.effective_message.reply_text(
            "Toggle any optional fields you want to include, then Continue.",
            reply_markup=K.optionals_keyboard(False, False),
        )
        return CHOOSE_OPTIONALS

    async def on_opt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        await q.answer()
        st = _state(context)
        data = q.data
        if data == "opt:ref":
            st["want_ref"] = not st.get("want_ref", False)
        elif data == "opt:attach":
            st["want_attach"] = not st.get("want_attach", False)
        elif data == "opt:continue":
            await q.edit_message_text("What did you work on? (activities done)")
            return ASK_ACTIVITIES
        elif data == "opt:cancel":
            _reset(context)
            await q.edit_message_text("Cancelled.")
            return ConversationHandler.END
        await q.edit_message_reply_markup(
            reply_markup=K.optionals_keyboard(st.get("want_ref", False), st.get("want_attach", False))
        )
        return CHOOSE_OPTIONALS

    async def on_activities(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        try:
            st["activities"] = validate_activities(update.effective_message.text or "")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))
            return ASK_ACTIVITIES
        if st.get("editing"):
            return await _goto_review(update, context)
        await update.effective_message.reply_text("How many hours? (whole number 0–24)")
        return ASK_TIME

    async def on_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        try:
            st["time_spent"] = parse_time_spent(update.effective_message.text or "")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))
            return ASK_TIME
        if st.get("editing"):
            return await _goto_review(update, context)
        await update.effective_message.reply_text(
            "Where are you working from?", reply_markup=K.location_keyboard()
        )
        return ASK_LOCATION

    async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        await q.answer()
        st = _state(context)
        data = q.data
        if data == "loc:cancel":
            _reset(context)
            await q.edit_message_text("Cancelled.")
            return ConversationHandler.END
        _, _, choice = data.partition(":")
        st["location"] = choice
        st.pop("location_other", None)
        if choice == S.LOCATION_OTHER:
            await q.edit_message_text("Specify location:")
            return ASK_LOCATION_OTHER
        if st.get("editing"):
            return await _goto_review_q(q, context)
        await q.edit_message_text("Write your description:")
        return ASK_DESCRIPTION

    async def on_location_other(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        text = (update.effective_message.text or "").strip()
        if not text:
            await update.effective_message.reply_text("Please specify a location.")
            return ASK_LOCATION_OTHER
        st["location_other"] = text
        if st.get("editing"):
            return await _goto_review(update, context)
        await update.effective_message.reply_text("Write your description:")
        return ASK_DESCRIPTION

    async def on_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        try:
            st["description"] = validate_description(update.effective_message.text or "")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))
            return ASK_DESCRIPTION
        if st.get("editing"):
            return await _goto_review(update, context)
        if st.get("want_ref"):
            await update.effective_message.reply_text("Send the reference link (full URL).")
            return ASK_REFERENCE_LINK
        if st.get("want_attach"):
            await update.effective_message.reply_text("Send the attachment as a file.")
            return ASK_ATTACHMENT
        return await _goto_review(update, context)

    async def on_reference_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        try:
            st["reference_link"] = validate_url(update.effective_message.text or "")
        except ValueError as e:
            await update.effective_message.reply_text(str(e))
            return ASK_REFERENCE_LINK
        if st.get("editing"):
            return await _goto_review(update, context)
        if st.get("want_attach"):
            await update.effective_message.reply_text("Send the attachment as a file.")
            return ASK_ATTACHMENT
        return await _goto_review(update, context)

    async def on_attachment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        msg = update.effective_message
        file_obj = None
        filename = None
        if msg.document:
            file_obj = await msg.document.get_file()
            filename = msg.document.file_name or f"file-{uuid.uuid4().hex}"
        elif msg.photo:
            file_obj = await msg.photo[-1].get_file()
            filename = f"photo-{uuid.uuid4().hex}.jpg"
        else:
            await msg.reply_text("Please send a file (document or photo).")
            return ASK_ATTACHMENT

        chat_id = update.effective_chat.id if update.effective_chat else 0
        safe_name = f"{chat_id}-{uuid.uuid4().hex}-{Path(filename).name}"
        dest = settings.attachment_tmp_dir / safe_name
        await file_obj.download_to_drive(str(dest))
        st["attachment_path"] = str(dest)
        st["attachment_filename"] = filename
        if st.get("editing"):
            return await _goto_review(update, context)
        return await _goto_review(update, context)

    async def _goto_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        st.pop("editing", None)
        await update.effective_message.reply_text(
            _summary(st), parse_mode="Markdown", reply_markup=K.review_keyboard()
        )
        return REVIEW

    async def _goto_review_q(q, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        st.pop("editing", None)
        await q.edit_message_text(
            _summary(st), parse_mode="Markdown", reply_markup=K.review_keyboard()
        )
        return REVIEW

    async def on_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        await q.answer()
        st = _state(context)
        data = q.data
        if data == "rev:cancel":
            _reset(context)
            await q.edit_message_text("Cancelled.")
            return ConversationHandler.END
        if data == "rev:edit":
            await q.edit_message_text(
                "What do you want to change?",
                reply_markup=K.edit_field_keyboard(
                    bool(st.get("want_ref")), bool(st.get("want_attach"))
                ),
            )
            return EDIT_PICK
        if data == "rev:submit":
            await q.edit_message_text("Submitting…")
            return await _do_submit(update, context)
        return REVIEW

    async def on_edit_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        q = update.callback_query
        await q.answer()
        st = _state(context)
        data = q.data
        st["editing"] = True
        mapping = {
            "edit:activities": (ASK_ACTIVITIES, "Send the new activities."),
            "edit:time": (ASK_TIME, "Send the new hours (whole number 0–24)."),
            "edit:description": (ASK_DESCRIPTION, "Send the new description."),
            "edit:ref": (ASK_REFERENCE_LINK, "Send the new reference link."),
            "edit:attach": (ASK_ATTACHMENT, "Send the new attachment."),
        }
        if data == "edit:back":
            st.pop("editing", None)
            return await _goto_review_q(q, context)
        if data == "edit:location":
            await q.edit_message_text(
                "Pick a new location:", reply_markup=K.location_keyboard()
            )
            return ASK_LOCATION
        if data in mapping:
            state, prompt = mapping[data]
            await q.edit_message_text(prompt)
            return state
        return EDIT_PICK

    async def _do_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        st = _state(context)
        chat_id = update.effective_chat.id if update.effective_chat else None
        if chat_id is None:
            _reset(context)
            return ConversationHandler.END

        payload = LogPayload(
            activities=st["activities"],
            time_spent=int(st["time_spent"]),
            location=st["location"],
            location_other=st.get("location_other"),
            description=st["description"],
            reference_link=st.get("reference_link") if st.get("want_ref") else None,
            attachment_path=Path(st["attachment_path"]) if st.get("want_attach") and st.get("attachment_path") else None,
        )

        message = update.effective_message

        try:
            ctx, lock = await pool.acquire(chat_id)
            async with lock:
                await submit_log(
                    ctx,
                    create_url=settings.pms_daily_log_create_url,
                    list_url=settings.pms_daily_log_list_url,
                    login_url=settings.pms_login_url,
                    payload=payload,
                )
            session_store.touch(chat_id)
            await message.reply_text("✅ Log posted.")
        except ReLoginRequired:
            session_store.mark(chat_id, "expired")
            await message.reply_text(
                "Your session expired. Run /login to sign in again, then retry /log."
            )
        except FormValidationError as e:
            pretty = "\n".join(f"• {m}" for m in e.messages) or str(e)
            await message.reply_text(f"The site rejected the form:\n{pretty}")
            # Go back to review so the user can edit
            await message.reply_text(_summary(st), parse_mode="Markdown", reply_markup=K.review_keyboard())
            return REVIEW
        except SubmitError as e:
            await message.reply_text(f"Submit failed: {e}. Try again shortly.")
        except Exception:  # noqa: BLE001
            log.exception("submit crashed")
            await message.reply_text("Unexpected error. Please try /log again.")

        _reset(context)
        return ConversationHandler.END

    async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        _reset(context)
        if update.effective_message:
            await update.effective_message.reply_text("Cancelled.")
        return ConversationHandler.END

    conv = ConversationHandler(
        entry_points=[CommandHandler("log", cmd_log)],
        states={
            CHOOSE_OPTIONALS: [CallbackQueryHandler(on_opt, pattern=r"^opt:")],
            ASK_ACTIVITIES: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_activities)],
            ASK_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_time)],
            ASK_LOCATION: [CallbackQueryHandler(on_location, pattern=r"^loc:")],
            ASK_LOCATION_OTHER: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_location_other)],
            ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_description)],
            ASK_REFERENCE_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, on_reference_link)],
            ASK_ATTACHMENT: [MessageHandler(filters.Document.ALL | filters.PHOTO, on_attachment)],
            REVIEW: [CallbackQueryHandler(on_review, pattern=r"^rev:")],
            EDIT_PICK: [CallbackQueryHandler(on_edit_pick, pattern=r"^edit:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
    app.add_handler(conv)
