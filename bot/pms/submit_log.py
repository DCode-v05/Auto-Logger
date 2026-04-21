"""Submit the Daily Log form on iqube.therig.in.

Uses Playwright's BrowserContext.request (an HTTP client that inherits the Chromium
cookie jar), not the browser UI. We GET the form once to pick up the CSRF token,
then POST the fields directly — no selector hunting, no JS required.
"""
from __future__ import annotations

import logging
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import BrowserContext

from bot.auth.playwright_pool import ReLoginRequired
from bot.pms import selectors as S

log = logging.getLogger(__name__)


@dataclass
class LogPayload:
    activities: str
    time_spent: int
    location: str  # one of S.LOCATION_IQUBE / LOCATION_HOME / LOCATION_OTHER
    location_other: str | None
    description: str
    reference_link: str | None = None
    attachment_path: Path | None = None


class SubmitError(Exception):
    pass


class FormValidationError(SubmitError):
    def __init__(self, messages: list[str]):
        super().__init__("; ".join(messages) if messages else "form rejected")
        self.messages = messages


_CSRF_IN_HTML = re.compile(
    r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']'
)
_INPUT_NAME = re.compile(
    r'<(?:input|select|textarea)[^>]*\bname=["\']([^"\']+)["\']', re.IGNORECASE
)
# Scope input-name parsing to the actual DailyLogForm — there are other forms
# on the page (navbar search posts to /me/bigboss/) whose inputs would
# otherwise be picked up and cause confusion.
_DAILY_LOG_FORM_BLOCK = re.compile(
    r'<form[^>]*\bid=["\']DailyLogForm["\'][^>]*>(.*?)</form>',
    re.IGNORECASE | re.DOTALL,
)
_ERROR_BLOCK = re.compile(
    r'<(?:li|div|span|p)[^>]*class=["\'][^"\']*'
    r'(?:errorlist|invalid-feedback|alert-danger|text-danger)[^"\']*["\'][^>]*>(.*?)</'
    r'(?:li|div|span|p)>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_STRIP = re.compile(r"<[^>]+>")


async def submit_log(
    context: BrowserContext,
    create_url: str,
    list_url: str,
    login_url: str,
    payload: LogPayload,
) -> None:
    """Submit via direct HTTP POST using the browser's session cookies.

    Uses a real Page for the GET (which we know carries cookies — login works
    this way) and `page.request` for the POST (inherits the same cookie jar).
    """
    page = await context.new_page()
    try:
        # Log cookie names currently held for the PMS domain so we can tell if
        # the session cookie is present without dumping its value.
        try:
            cookies = await context.cookies(create_url)
            names = [c.get("name") for c in cookies]
            log.info("daily_log pre-GET cookies for %s: %s", create_url, names)
        except Exception:  # noqa: BLE001
            log.exception("could not list cookies")

        # 1. Navigate to the form page so Chromium uses its cookie jar.
        await page.goto(create_url, wait_until="domcontentloaded")
        log.info("daily_log GET landed on %s", page.url)
        if _looks_like_login(page.url, login_url):
            log.warning(
                "daily_log GET landed on login page: %s (started at %s)",
                page.url, create_url,
            )
            raise ReLoginRequired("session expired (redirected to login)")

        html = await page.content()

        # Scope parsing to the DailyLogForm block so we don't pick up the
        # navbar search input (name="detail") or other unrelated forms.
        form_block_match = _DAILY_LOG_FORM_BLOCK.search(html)
        if not form_block_match:
            log.error(
                "daily_log GET succeeded but DailyLogForm not found on page url=%s\nbody head:\n%s",
                page.url, html[:2000],
            )
            raise SubmitError(
                f"Loaded {page.url} but the daily-log form was not on the page; "
                "the site may require profile completion first."
            )
        form_html = form_block_match.group(1)

        csrf_match = _CSRF_IN_HTML.search(form_html)
        if not csrf_match:
            raise SubmitError("csrfmiddlewaretoken not found inside DailyLogForm")
        csrf = csrf_match.group(1)

        found_names = sorted({m.group(1) for m in _INPUT_NAME.finditer(form_html)})
        log.info("daily_log form fields on server: %s", found_names)

        # Hardcoded field names matching the production HTML
        # (iqube.therig.in DailyLogForm, verified 2026-04):
        #   activities_done, time_spent, location, custom_location,
        #   reference_link, attachment, description
        fields: dict[str, object] = {
            "csrfmiddlewaretoken": csrf,
            "activities_done": payload.activities,
            "time_spent": str(payload.time_spent),
            "location": payload.location,  # "iQube" / "Home/Hostel" / "Other"
            "description": payload.description,
        }
        if payload.location == S.LOCATION_OTHER and payload.location_other:
            fields["custom_location"] = payload.location_other
        if payload.reference_link:
            fields["reference_link"] = payload.reference_link

        if payload.attachment_path is not None:
            att = payload.attachment_path
            mime, _ = mimetypes.guess_type(str(att))
            fields["attachment"] = {
                "name": att.name,
                "mimeType": mime or "application/octet-stream",
                "buffer": att.read_bytes(),
            }

        # 3. POST using the page's request context (shares cookies with this page).
        #    max_redirects=0 so we can detect 302 -> list page ourselves.
        post_resp = await page.request.post(
            create_url,
            multipart=fields,
            headers={"Referer": create_url},
            max_redirects=0,
        )

        # 4. Interpret the response.
        status = post_resp.status
        headers = post_resp.headers
        location_hdr = headers.get("location", "")

        # Django form-view pattern: success = 302 to list page; failure = 200 + form re-rendered.
        if status in (301, 302):
            redir = location_hdr
            if _looks_like_login(redir, login_url):
                raise ReLoginRequired("POST redirected to login")
            if _is_list_page(redir, list_url) or "/me/daily_log" in redir:
                return  # success
            # Some deployments redirect elsewhere after post; treat any non-login 302 as success.
            log.info("daily_log POST redirected to %s — assuming success", redir)
            return

        if status == 200:
            # Re-rendered form — try to scrape errors
            body = await post_resp.text()
            errs = _scrape_errors_from_html(body)
            if errs:
                raise FormValidationError(errs)
            log.error(
                "POST %s returned 200 with no redirect and no visible errors",
                create_url,
            )
            raise SubmitError(
                "Form POST returned 200 but did not redirect; unclear whether it was saved. "
                "Check iqube Your Updates to confirm."
            )

        raise SubmitError(f"POST {create_url} returned unexpected status {status}")
    finally:
        await page.close()


def _scrape_errors_from_html(html: str) -> list[str]:
    out: list[str] = []
    for m in _ERROR_BLOCK.finditer(html):
        inner = _TAG_STRIP.sub("", m.group(1)).strip()
        if inner and inner.lower() != "errors":
            out.append(inner)
    # Dedupe preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for e in out:
        if e not in seen:
            seen.add(e)
            deduped.append(e)
    return deduped


def _is_list_page(url: str, list_url: str) -> bool:
    return url.rstrip("/").startswith(list_url.rstrip("/"))


def _looks_like_login(url: str, login_url: str) -> bool:
    # Direct login page
    if url.rstrip("/").startswith(login_url.rstrip("/")):
        return True
    if "/login" in url:
        return True
    # Django @login_required bounces to the site root with ?next=... when the
    # LOGIN_URL points at '/' (iqube does this).
    if "?next=" in url or "&next=" in url:
        return True
    return False
