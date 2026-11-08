# Auto-Logger

A Telegram bot that files your daily log on the iQube PMS for you. You sign in once through a Telegram Web App, then send `/log` and answer a few prompts.

The PMS (`iqube.therig.in`) sits behind a Microsoft OAuth login, usually with MFA, and the log itself is a multi-field form. I built this to stop losing a few minutes to that every day. The bot drives a headless Chromium per user with Playwright, replays the same login the website uses, keeps the session, and POSTs the real Daily Log form. It does not touch the PMS server in any other way.

## How it works

`bot/main.py` runs three things in one asyncio process and shuts them down together: the python-telegram-bot application (long polling), a FastAPI/Uvicorn server that serves the login and MFA pages, and a pool of Playwright browser contexts. `LoginCoordinator` (`bot/web/coordinator.py`) links them: the Web App posts credentials to FastAPI, the login runs as a background task in Playwright, and progress goes back to the user through the Bot API.

**Login.** `/login` sends a Web App button pointing at the FastAPI form, served over HTTPS through Tailscale Funnel. `bot/auth/login_flow.py` first checks the user's browser profile for a Django `sessionid` cookie for `iqube.therig.in` and skips OAuth if it is there. (It checks the cookie rather than a URL because `/me/` is publicly reachable.) Otherwise it opens `/login/azuread-oauth2/`, which is where the site's "Sign in with Microsoft" button points, fills in the Microsoft email and password, and waits for whichever screen comes next: a TOTP/SMS code, number matching, "Stay signed in?", a password error, a push approval, or the redirect back to iQube. When a code is needed the bot sends a second Web App button and the code goes through an `asyncio.Queue`. MFA waits are capped by `MFA_TIMEOUT_SECONDS` (180 by default). Success is only reported if a real `sessionid` cookie exists afterwards.

**Submitting a log.** `/log` is a `ConversationHandler` that asks for activities, time spent, location, description, an optional reference link and an optional attachment, with checks in `bot/utils/validators.py` (whole hours 0 to 24, activities up to 255 characters, links must be full `http(s)://` URLs). `bot/pms/submit_log.py` then skips the page UI and uses Playwright's `page.request`, which shares the Chromium cookie jar. It GETs the create page, takes the `csrfmiddlewaretoken` from inside `#DailyLogForm` (the navbar search is a separate form), and POSTs the form with `max_redirects=0`. A 302 to the list page is success. A 200 means the form came back with errors, and those are scraped and sent to the chat as they are. A redirect to the login page raises `ReLoginRequired`.

**Sessions.** `bot/auth/playwright_pool.py` keeps one persistent context per Telegram `chat_id`, each with its own on-disk profile. Contexts idle for more than `SESSION_IDLE_CLOSE_SECONDS` (600 by default) are closed, but the profile stays. `/logout` closes the context and deletes the profile.

**Security.** The Microsoft password is held in memory for one login call and not stored. Emails in the SQLite session store are Fernet-encrypted. Every Web App request carries Telegram `initData`, which `bot/auth/telegram_initdata.py` checks with HMAC-SHA256 derived from the bot token, so the public endpoints cannot be used to start a login for someone else's chat.

## Commands

| Command | What it does |
|---------|--------------|
| `/start` | Welcome and sign-in status |
| `/login` | Open the Microsoft sign-in Web App |
| `/logout` | Delete the session and the local browser profile |
| `/whoami` | Show the signed-in email and session status |
| `/log` | Submit a Daily Log |
| `/cancel` | Cancel the `/log` conversation |

## Stack

Python 3.10+, python-telegram-bot, Playwright (Chromium), FastAPI, Uvicorn, Jinja2, Pydantic settings, `cryptography`, SQLite, Docker Compose, Tailscale Funnel. Tests use pytest and pytest-asyncio, linting uses ruff.

## Setup

You need a bot token from BotFather, a Tailscale auth key (for the public HTTPS URL), and either Docker or Python 3.10+.

```bash
git clone https://github.com/DCode-v05/Auto-Logger.git
cd Auto-Logger
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Fill in `.env`: `TELEGRAM_BOT_TOKEN`, `BOT_ENCRYPTION_KEY` (the key you just generated), `BOT_PUBLIC_URL` (`https://pms-bot.<your-tailnet>.ts.net`) and `TS_AUTHKEY`. The other values in `.env.example` have defaults.

With Docker:

```bash
docker compose up -d --build
docker compose logs -f
```

This starts `pms-bot` (the bot, FastAPI and the browser pool) and `pms-bot-tailscale`, which proxies the Funnel URL to `http://bot:8765`. Then set the Web App domain in BotFather (`/mybots`, Bot Settings, Domain) to `pms-bot.<your-tailnet>.ts.net`. `curl https://pms-bot.<your-tailnet>.ts.net/healthz` should return `{"status":"ok"}`.

Without Docker:

```bash
pip install -e .
python -m playwright install chromium
python -m bot.main
```

Tests: `pip install -e ".[dev]"` then `pytest`.

## Structure

```
bot/
  main.py              entry point
  config.py            settings from .env
  auth/                login flow, Playwright pool, session store, initData check
  handlers/            /start, /login, /logout, /whoami, /log, error handler
  pms/                 Daily Log submission and the HTML selectors
  utils/               keyboards, validators
  web/                 FastAPI app, login coordinator, Jinja2 templates
tests/                 initData, session store, validators
Dockerfile
docker-compose.yml     bot + tailscale
tailscale-serve.json   Funnel config
```

## Notes

This is a personal tool for my own PMS submissions. Deploying it for other people needs approval from the iQube admins.

## Contact

[Portfolio](https://www.denistan.me) · [LinkedIn](https://www.linkedin.com/in/denistanb) · [GitHub](https://github.com/DCode-v05) · denistanb05@gmail.com
