from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from bot.auth.telegram_initdata import InitDataError, verify_init_data
from bot.config import Settings
from bot.web.coordinator import LoginCoordinator

log = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(settings: Settings, coordinator: LoginCoordinator) -> FastAPI:
    app = FastAPI(title="pms-telegram-bot", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/webapp/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "pms_base_url": settings.pms_base_url},
        )

    @app.post("/webapp/login")
    async def login_submit(
        _initData: str = Form(..., alias="_initData"),
        email: str = Form(...),
        password: str = Form(...),
    ) -> JSONResponse:
        try:
            verified = verify_init_data(_initData, settings.telegram_bot_token)
        except InitDataError as e:
            raise HTTPException(status_code=401, detail=f"invalid initData: {e}")

        email = email.strip()
        if "@" not in email:
            raise HTTPException(status_code=400, detail="invalid email")
        if not password:
            raise HTTPException(status_code=400, detail="password required")

        try:
            await coordinator.start_login(verified.user_id, email, password)
        except RuntimeError as e:
            raise HTTPException(status_code=409, detail=str(e))
        # Password is no longer needed here; let it fall out of scope.
        return JSONResponse({"status": "started"})

    @app.get("/webapp/mfa", response_class=HTMLResponse)
    async def mfa_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("mfa.html", {"request": request})

    @app.post("/webapp/mfa")
    async def mfa_submit(
        _initData: str = Form(..., alias="_initData"),
        code: str = Form(...),
    ) -> JSONResponse:
        try:
            verified = verify_init_data(_initData, settings.telegram_bot_token)
        except InitDataError as e:
            raise HTTPException(status_code=401, detail=f"invalid initData: {e}")
        code = code.strip()
        if not code.isdigit() or len(code) not in (6, 7, 8):
            raise HTTPException(status_code=400, detail="enter the numeric code")
        accepted = await coordinator.submit_mfa(verified.user_id, code)
        if not accepted:
            raise HTTPException(status_code=404, detail="no login in progress for this user")
        return JSONResponse({"status": "received"})

    return app
