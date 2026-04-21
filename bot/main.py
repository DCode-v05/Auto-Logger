"""Entry point: boots python-telegram-bot + FastAPI (uvicorn) + Playwright pool in one process."""
from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn
from telegram.ext import Application

from bot.auth.playwright_pool import PlaywrightPool
from bot.auth.session_store import SessionStore
from bot.config import get_settings
from bot.handlers import errors as errors_handler
from bot.handlers import start as start_handler
from bot.handlers import submit_log as submit_log_handler
from bot.web.app import create_app
from bot.web.coordinator import LoginCoordinator


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.INFO)


async def _run() -> None:
    settings = get_settings()
    settings.ensure_dirs()
    _configure_logging(settings.log_level)
    log = logging.getLogger("bot.main")

    session_store = SessionStore(settings.bot_db_path, settings.bot_encryption_key)
    pool = PlaywrightPool(settings.playwright_profiles_dir, settings.session_idle_close_seconds)

    application = Application.builder().token(settings.telegram_bot_token).build()

    start_handler.register(application, settings, session_store, pool)
    submit_log_handler.register(application, settings, session_store, pool)
    errors_handler.register(application)

    coordinator = LoginCoordinator(settings, pool, session_store, application.bot)
    web_app = create_app(settings, coordinator)

    config = uvicorn.Config(
        web_app,
        host=settings.fastapi_host,
        port=settings.fastapi_port,
        log_level=settings.log_level.lower(),
        lifespan="on",
    )
    server = uvicorn.Server(config)

    await pool.start()
    try:
        await application.initialize()
        await application.start()
        if application.updater:
            await application.updater.start_polling()

        log.info(
            "bot online — FastAPI on %s:%d (public %s)",
            settings.fastapi_host,
            settings.fastapi_port,
            settings.bot_public_url,
        )

        stop_event = asyncio.Event()

        def _stop(*_: object) -> None:
            log.info("shutdown signal received")
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler; rely on KeyboardInterrupt
                pass

        server_task = asyncio.create_task(server.serve())
        stop_task = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {server_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )

        server.should_exit = True
        for t in done:
            if exc := t.exception():
                log.error("component exited with error: %s", exc)
        if not server_task.done():
            await server_task
    finally:
        log.info("stopping…")
        if application.updater and application.updater.running:
            await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await pool.stop()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
