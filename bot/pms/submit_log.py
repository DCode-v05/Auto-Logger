"""Fill and submit the Daily Log form on iqube.therig.in via a logged-in Playwright context."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import BrowserContext, TimeoutError as PWTimeoutError

from bot.auth.playwright_pool import ReLoginRequired
from bot.pms import selectors as S

log = logging.getLogger(__name__)


@dataclass
class LogPayload:
    activities: str
    time_spent: int
    location: str  # one of S.LOCATION_IQUBE / LOCATION_HOME / LOCATION_OTHER
    location_other: str | None  # required if location == LOCATION_OTHER
    description: str
    reference_link: str | None = None
    attachment_path: Path | None = None


class SubmitError(Exception):
    pass


class FormValidationError(SubmitError):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages) if messages else "form rejected")
        self.messages = messages


async def submit_log(
    context: BrowserContext,
    create_url: str,
    list_url: str,
    login_url: str,
    payload: LogPayload,
) -> None:
    """Navigate to the form and submit. Raises ReLoginRequired / FormValidationError."""
    page = await context.new_page()
    try:
        await page.goto(create_url, wait_until="domcontentloaded")
        # If the session is dead, iqube redirects to the login page.
        if _looks_like_login(page.url, login_url):
            raise ReLoginRequired("session expired")

        await page.wait_for_selector(S.FORM_ACTIVITIES, timeout=15_000)

        await page.fill(S.FORM_ACTIVITIES, payload.activities)
        await page.fill(S.FORM_TIME_SPENT, str(payload.time_spent))

        # Location
        try:
            await page.select_option(S.FORM_LOCATION, label=payload.location)
        except PWTimeoutError:
            # Some deployments use value attributes; fall back to value match
            await page.select_option(S.FORM_LOCATION, value=payload.location)

        if payload.location == S.LOCATION_OTHER:
            if not payload.location_other:
                raise SubmitError("location_other is required when location is 'Other'")
            # The "Specify" field may be revealed by JS; give it a moment.
            try:
                await page.wait_for_selector(S.FORM_LOCATION_OTHER, timeout=5_000, state="visible")
                await page.fill(S.FORM_LOCATION_OTHER, payload.location_other)
            except PWTimeoutError:
                log.warning("location_other field not visible; attempting best-effort fill")

        # Reference link (optional)
        if payload.reference_link:
            try:
                await page.fill(S.FORM_REFERENCE_LINK, payload.reference_link)
            except PWTimeoutError:
                log.warning("reference_link field not found; skipping")

        # Attachment (optional)
        if payload.attachment_path:
            file_input = page.locator(S.FORM_ATTACHMENT).first
            await file_input.set_input_files(str(payload.attachment_path))

        # Description — CKEditor-backed; write via editor API if loaded, else fall back
        # to the underlying textarea.
        await _set_description(page, payload.description)

        # Submit
        await page.locator(S.FORM_SUBMIT_BUTTON).first.click()

        # Success = redirect to list page. Failure = still on create page with errors.
        try:
            await page.wait_for_url(
                lambda url: _is_list_page(url, list_url) or _looks_like_login(url, login_url),
                timeout=20_000,
            )
        except PWTimeoutError:
            errors = await _scrape_errors(page)
            if errors:
                raise FormValidationError(errors)
            raise SubmitError("submit did not navigate within timeout")

        if _looks_like_login(page.url, login_url):
            raise ReLoginRequired("session expired during submit")

        errors = await _scrape_errors(page)
        if errors:
            raise FormValidationError(errors)
    finally:
        await page.close()


async def _set_description(page, text: str) -> None:
    # CKEditor 4: window.CKEDITOR.instances[...]
    done = await page.evaluate(
        """
        (text) => {
          try {
            if (window.CKEDITOR && window.CKEDITOR.instances) {
              const keys = Object.keys(window.CKEDITOR.instances);
              if (keys.length) {
                window.CKEDITOR.instances[keys[0]].setData(text);
                return true;
              }
            }
          } catch (e) {}
          return false;
        }
        """,
        text,
    )
    if done:
        return
    # Fallback: write directly into the hidden textarea
    try:
        await page.evaluate(
            "(sel, v) => { const el = document.querySelector(sel); if (el) { el.value = v; el.dispatchEvent(new Event('change', {bubbles: true})); } }",
            S.FORM_DESCRIPTION_TEXTAREA,
            text,
        )
    except Exception:  # noqa: BLE001
        log.exception("failed to set description via fallback")


async def _scrape_errors(page) -> list[str]:
    try:
        locs = page.locator(S.FORM_ERROR_LIST)
        count = await locs.count()
        out: list[str] = []
        for i in range(count):
            t = (await locs.nth(i).inner_text()).strip()
            if t:
                out.append(t)
        return out
    except Exception:  # noqa: BLE001
        return []


def _is_list_page(url: str, list_url: str) -> bool:
    return url.rstrip("/").startswith(list_url.rstrip("/"))


def _looks_like_login(url: str, login_url: str) -> bool:
    return url.rstrip("/").startswith(login_url.rstrip("/")) or "/login" in url
