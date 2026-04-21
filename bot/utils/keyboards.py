from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.pms import selectors as S


def optionals_keyboard(include_ref: bool, include_attach: bool) -> InlineKeyboardMarkup:
    def tick(b: bool) -> str:
        return "☑" if b else "☐"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"{tick(include_ref)} Reference link", callback_data="opt:ref")],
            [InlineKeyboardButton(f"{tick(include_attach)} Attachment", callback_data="opt:attach")],
            [InlineKeyboardButton("Continue ▶", callback_data="opt:continue")],
            [InlineKeyboardButton("Cancel", callback_data="opt:cancel")],
        ]
    )


def location_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(S.LOCATION_IQUBE, callback_data=f"loc:{S.LOCATION_IQUBE}")],
            [InlineKeyboardButton(S.LOCATION_HOME, callback_data=f"loc:{S.LOCATION_HOME}")],
            [InlineKeyboardButton(S.LOCATION_OTHER, callback_data=f"loc:{S.LOCATION_OTHER}")],
            [InlineKeyboardButton("Cancel", callback_data="loc:cancel")],
        ]
    )


def review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Submit", callback_data="rev:submit")],
            [InlineKeyboardButton("✏️ Edit", callback_data="rev:edit")],
            [InlineKeyboardButton("❌ Cancel", callback_data="rev:cancel")],
        ]
    )


def edit_field_keyboard(has_ref: bool, has_attach: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("Activities", callback_data="edit:activities")],
        [InlineKeyboardButton("Time spent", callback_data="edit:time")],
        [InlineKeyboardButton("Location", callback_data="edit:location")],
        [InlineKeyboardButton("Description", callback_data="edit:description")],
    ]
    if has_ref:
        rows.append([InlineKeyboardButton("Reference link", callback_data="edit:ref")])
    if has_attach:
        rows.append([InlineKeyboardButton("Attachment", callback_data="edit:attach")])
    rows.append([InlineKeyboardButton("◀ Back to review", callback_data="edit:back")])
    return InlineKeyboardMarkup(rows)
