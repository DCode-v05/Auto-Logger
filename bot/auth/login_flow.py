"""Replays the iqube.therig.in Microsoft OAuth login in a Playwright Chromium.

Never persists the user's password. Coordinates MFA challenges (push, number-matching,
TOTP) via callbacks supplied by the FastAPI/Telegram layer — this module only knows
browser automation.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass
from typing import Awaitable, Callable

from playwright.async_api import BrowserContext, Page, TimeoutError as PWTimeoutError

from bot.pms import selectors as S

log = logging.getLogger(__name__)


class LoginError(Exception):
    pass


class LoginCredentialError(LoginError):
    pass


class MFATimeout(LoginError):
    pass


@dataclass
class LoginCallbacks:
    """Hooks the login flow uses to talk to the user through Telegram.

    - notify(text): send an informational message
    - request_mfa_code(): return the 6-digit TOTP / SMS code the user typed in
      the MFA Web App page (awaited until the user submits, or times out).
    """

    notify: Callable[[str], Awaitable[None]]
    request_mfa_code: Callable[[], Awaitable[str]]
    mfa_timeout_seconds: int = 180


async def perform_login(
    context: BrowserContext,
    pms_login_url: str,
    pms_me_url: str,
    email: str,
    password: str,
    callbacks: LoginCallbacks,
    pms_ms_oauth_begin_url: str | None = None,
) -> str:
    """Log in and return the user's email (as the site reports it)."""
    page = await context.new_page()
    try:
        # Fast path: if a session cookie is still valid, iqube redirects /me/ to itself.
        await page.goto(pms_me_url, wait_until="domcontentloaded")
        log.info("login step 1 (GET /me/): landed on %s", page.url)
        if _is_iqube_me(page.url, pms_me_url):
            log.info("login step 1: already authenticated; skipping OAuth")
            return await _extract_email(page) or email

        # Otherwise go straight to social-auth's AzureAD begin URL — this is what
        # the "Sign in with Microsoft" button on the PMS login page links to.
        # Navigating here triggers the OAuth redirect to Microsoft without any
        # button click on the PMS side.
        begin_url = pms_ms_oauth_begin_url or f"{pms_login_url.rstrip('/')}/azuread-oauth2/"
        log.info("login step 2: navigating to OAuth begin URL %s", begin_url)
        await page.goto(begin_url, wait_until="domcontentloaded")
        log.info("login step 2: landed on %s", page.url)

        # If we're already authenticated with Microsoft in this browser context,
        # MS may redirect us straight back to iqube.
        if _is_iqube_me(page.url, pms_me_url):
            log.info("login step 2: redirected straight to iqube /me/; no MS login needed")
            return await _extract_email(page) or email

        # Sanity: we should be on login.microsoftonline.com by now.
        if "login.microsoftonline.com" not in page.url and "microsoft.com" not in page.url:
            try:
                html_head = (await page.content())[:2000]
            except Exception:  # noqa: BLE001
                html_head = "<unreadable>"
            log.error(
                "login step 2: expected Microsoft login, got %s\nHTML:\n%s",
                page.url, html_head,
            )
            raise LoginError(
                f"Expected Microsoft sign-in, but ended up at {page.url}. "
                "Is the OAuth backend misconfigured on iqube.therig.in?"
            )

        # Microsoft: email page
        log.info("login step 3: waiting for MS email input")
        await page.wait_for_selector(S.MS_EMAIL_INPUT, timeout=30_000)
        await page.fill(S.MS_EMAIL_INPUT, email)
        await page.click(S.MS_EMAIL_NEXT_BUTTON)

        # Microsoft: password page
        try:
            await page.wait_for_selector(S.MS_PASSWORD_INPUT, timeout=30_000)
        except PWTimeoutError as e:
            # Possibly an error on the email step (user unknown, tenant blocked, etc.)
            err = await _scrape_ms_error(page)
            raise LoginCredentialError(err or "Microsoft did not accept the email") from e

        await page.fill(S.MS_PASSWORD_INPUT, password)
        # Best-effort: wipe the local reference after use
        del password
        await page.click(S.MS_PASSWORD_SUBMIT)

        # From here we need to handle several possible outcomes:
        #   - success → redirect to iqube /me/
        #   - MFA push ("Check your Authenticator app")
        #   - MFA number-matching (shows 2-digit number)
        #   - MFA TOTP (6-digit code input)
        #   - "Stay signed in?" Yes/No prompt (then success)
        #   - wrong password error
        await _handle_post_password(page, pms_me_url, callbacks)
        log.info("login step 5: post-password handling finished; final url=%s", page.url)

        email_final = await _extract_email(page)
        return email_final or email
    finally:
        await page.close()


async def _handle_post_password(
    page: Page, pms_me_url: str, callbacks: LoginCallbacks
) -> None:
    # Race several possible next-states.
    deadline = _time.monotonic() + callbacks.mfa_timeout_seconds

    while True:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            raise MFATimeout("Login timed out waiting for MFA / redirect")

        # Already at iqube? Done.
        if _is_iqube_me(page.url, pms_me_url):
            return

        # Password error?
        err = await _scrape_ms_error(page)
        if err and any(w in err.lower() for w in ("password", "incorrect", "wrong")):
            raise LoginCredentialError(err)

        # TOTP / SMS code entry?
        if await _visible(page, S.MS_MFA_CODE_INPUT):
            await callbacks.notify(
                "Microsoft is asking for a verification code. "
                "Open the MFA form (the button I sent) and enter your 6-digit code."
            )
            try:
                code = await asyncio.wait_for(
                    callbacks.request_mfa_code(), timeout=remaining
                )
            except asyncio.TimeoutError as e:
                raise MFATimeout("No MFA code received in time") from e
            await page.fill(S.MS_MFA_CODE_INPUT, code.strip())
            await page.click(S.MS_MFA_SUBMIT)
            # loop again — might land on success or "stay signed in"
            await page.wait_for_load_state("domcontentloaded")
            continue

        # Number-matching challenge?
        num = await _text_or_none(page, S.MS_MFA_NUMBER_MATCH_DISPLAY)
        if num:
            await callbacks.notify(
                f"Open your Microsoft Authenticator app and tap the number: *{num.strip()}*"
            )
            # Then Microsoft just redirects when the user approves.
            try:
                await page.wait_for_url(
                    lambda url: _is_iqube_me(url, pms_me_url) or "Kmsi" in url,
                    timeout=int(remaining * 1000),
                )
            except PWTimeoutError as e:
                raise MFATimeout("Authenticator approval not received in time") from e
            continue

        # "Stay signed in?" prompt?
        if await _visible(page, S.MS_STAY_SIGNED_IN_YES):
            await page.click(S.MS_STAY_SIGNED_IN_YES)
            await page.wait_for_load_state("domcontentloaded")
            continue

        # Push-approval implicit state: just a spinner waiting for user.
        # Tell the user once, then keep polling.
        # (Detecting this reliably is hard; we fall through to the wait below.)
        try:
            await page.wait_for_url(
                lambda url: (
                    _is_iqube_me(url, pms_me_url)
                    or "Kmsi" in url
                    or "login.microsoftonline.com" not in url
                ),
                timeout=min(5_000, int(remaining * 1000)),
            )
        except PWTimeoutError:
            # Still waiting — tell the user to approve if we haven't already.
            await callbacks.notify(
                "Waiting on Microsoft sign-in. "
                "If you see a prompt in your Authenticator app, approve it."
            )
            # loop again until deadline
            continue


def _is_iqube_me(url: str, pms_me_url: str) -> bool:
    # pms_me_url is like 'https://iqube.therig.in/me/'.  We want to match
    # '/me' itself or '/me/...anything...' but NOT '/media', '/mentor', etc.
    base = pms_me_url.rstrip("/")
    u = url.rstrip("/")
    return u == base or u.startswith(base + "/")


async def _visible(page: Page, selector: str) -> bool:
    try:
        el = page.locator(selector).first
        return await el.is_visible()
    except PWTimeoutError:
        return False
    except Exception:  # noqa: BLE001
        return False


async def _text_or_none(page: Page, selector: str) -> str | None:
    try:
        el = page.locator(selector).first
        if await el.is_visible():
            return await el.inner_text()
    except Exception:  # noqa: BLE001
        return None
    return None


async def _scrape_ms_error(page: Page) -> str | None:
    try:
        el = page.locator(S.MS_ERROR_BOX).first
        if await el.is_visible():
            return (await el.inner_text()).strip()
    except Exception:  # noqa: BLE001
        return None
    return None


async def _extract_email(page: Page) -> str | None:
    """Try to pull the logged-in email from iqube's /me/ page navbar. Best effort."""
    try:
        # iqube shows user's name/email in the header; try common selectors.
        for sel in ['[data-user-email]', 'a[href*="mailto:"]']:
            loc = page.locator(sel).first
            if await loc.count() and await loc.is_visible():
                val = await loc.get_attribute("data-user-email") or await loc.inner_text()
                if val and "@" in val:
                    return val.strip()
    except Exception:  # noqa: BLE001
        pass
    return None
