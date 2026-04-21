"""Per-chat_id Playwright Chromium lifecycle.

One BrowserContext per chat, with a persistent user-data-dir so Django session
cookies survive bot restarts. Idle contexts are closed after
`session_idle_close_seconds`; the on-disk profile stays and is reused on next
use (cheap relaunch).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

log = logging.getLogger(__name__)


class ReLoginRequired(Exception):
    """Raised when the persisted session is no longer valid."""


@dataclass
class _Entry:
    context: BrowserContext
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_used: float = field(default_factory=time.monotonic)


class PlaywrightPool:
    def __init__(self, profiles_dir: Path, idle_close_seconds: int = 600):
        self.profiles_dir = profiles_dir
        self.idle_close_seconds = idle_close_seconds
        self._pw: Playwright | None = None
        self._browser: Browser | None = None  # unused when using launch_persistent_context
        self._entries: dict[int, _Entry] = {}
        self._global_lock = asyncio.Lock()
        self._reaper_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._pw is not None:
            return
        self._pw = await async_playwright().start()
        self._reaper_task = asyncio.create_task(self._reap_idle())

    async def stop(self) -> None:
        if self._reaper_task:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
        async with self._global_lock:
            for entry in self._entries.values():
                try:
                    await entry.context.close()
                except Exception:  # noqa: BLE001
                    log.exception("error closing context")
            self._entries.clear()
        if self._pw:
            await self._pw.stop()
            self._pw = None

    def _profile_dir(self, chat_id: int) -> Path:
        p = self.profiles_dir / str(chat_id)
        p.mkdir(parents=True, exist_ok=True)
        return p

    async def acquire(self, chat_id: int) -> tuple[BrowserContext, asyncio.Lock]:
        """Return (context, lock) for chat_id. Caller must `async with lock:`."""
        if self._pw is None:
            raise RuntimeError("PlaywrightPool not started")

        async with self._global_lock:
            entry = self._entries.get(chat_id)
            if entry is None or not self._is_alive(entry.context):
                ctx = await self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(self._profile_dir(chat_id)),
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                    viewport={"width": 1280, "height": 800},
                )
                entry = _Entry(context=ctx)
                self._entries[chat_id] = entry
            entry.last_used = time.monotonic()
            return entry.context, entry.lock

    @staticmethod
    def _is_alive(ctx: BrowserContext) -> bool:
        try:
            return ctx.browser is None or ctx.browser.is_connected()
        except Exception:  # noqa: BLE001
            return False

    async def close_for(self, chat_id: int) -> None:
        async with self._global_lock:
            entry = self._entries.pop(chat_id, None)
        if entry:
            try:
                await entry.context.close()
            except Exception:  # noqa: BLE001
                log.exception("error closing context for %s", chat_id)

    async def wipe_profile(self, chat_id: int) -> None:
        """Close browser and delete on-disk profile. Used on /logout."""
        await self.close_for(chat_id)
        import shutil

        p = self._profile_dir(chat_id)
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    async def _reap_idle(self) -> None:
        try:
            while True:
                await asyncio.sleep(max(30, self.idle_close_seconds // 4))
                cutoff = time.monotonic() - self.idle_close_seconds
                async with self._global_lock:
                    for chat_id in list(self._entries.keys()):
                        entry = self._entries.get(chat_id)
                        if not entry:
                            continue
                        if entry.last_used >= cutoff or entry.lock.locked():
                            continue
                        # Pop and close atomically under the global lock so
                        # a concurrent acquire() cannot grab an entry we're
                        # about to tear down.
                        self._entries.pop(chat_id, None)
                        log.info("reaping idle playwright context for %s", chat_id)
                        try:
                            await entry.context.close()
                        except Exception:  # noqa: BLE001
                            log.exception("error closing context for %s", chat_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("reaper crashed")
