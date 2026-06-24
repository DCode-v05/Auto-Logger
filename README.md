# Auto Logger

**A Telegram bot that submits your daily logs to the iQube PMS for you — sign in once, then post from chat in a few seconds.**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white) ![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-21.6-26A5E4?style=flat&logo=telegram&logoColor=white) ![Playwright](https://img.shields.io/badge/Playwright-1.58-2EAD33?style=flat&logo=playwright&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=flat&logo=pydantic&logoColor=white) ![SQLite](https://img.shields.io/badge/SQLite-003B57?style=flat&logo=sqlite&logoColor=white) ![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white) ![Tailscale](https://img.shields.io/badge/Tailscale-Funnel-242424?style=flat&logo=tailscale&logoColor=white)

## Overview

The iQube PMS (`iqube.therig.in`) asks students and employees to file a daily log. The catch is the path to get there: a Microsoft OAuth sign-in, usually with MFA, then a multi-field web form. It's the kind of small, repetitive task people forget, file late, or just lose a couple of minutes to every day.

Auto Logger removes that friction without touching the PMS server. It's a Telegram bot that drives a real headless Chromium browser (via Playwright) per user. It replays the exact Microsoft OAuth login the website itself uses, keeps the resulting session alive, and POSTs the genuine Daily Log form. From the user's side it's: sign in once through an in-chat Web App, then send `/log` and answer a few prompts. Form validation errors from the PMS come straight back into the chat.

I built this as a personal tool to automate my own college PMS submissions. It's the most engineering-heavy of my projects — real OAuth/MFA replay, per-user browser isolation, in-memory-only password handling, encrypted storage, a containerized two-service deploy, and unit tests — rather than anything ML. Roughly 14 commits over a focused few-day build.

## Key Features

- **Submit a daily log from Telegram** — `/log` runs a guided conversation: activities, time spent, location, description, optional reference link, optional attachment. Review the summary, confirm, done.
- **Microsoft OAuth login replayed in a real browser** — the bot navigates the `iqube.therig.in` AzureAD sign-in flow in headless Chromium, so the session it produces is identical to one you'd get by logging in yourself.
- **MFA handled in-chat** — push approval, Authenticator number-matching, and 6-digit TOTP/SMS codes are all detected automatically. The bot prompts you for whatever Microsoft asks and feeds it back into the browser.
- **Sign in once, stay signed in** — the Django `sessionid` cookie persists in a per-user Chromium profile on disk and survives bot restarts (~2 weeks, the same lifetime the website gives you).
- **Per-user browser isolation** — every Telegram `chat_id` gets its own Chromium `user-data-dir` and its own context. No shared cookie jar between users.
- **Password never hits disk** — your Microsoft password is held in memory only for the duration of one login call, then dropped.
- **Encrypted at rest** — stored email addresses in the SQLite session store are Fernet-encrypted.
- **Tamper-checked Web App requests** — the Telegram Web App `initData` is HMAC-SHA256 verified against the bot token, so the public login/MFA endpoints can't be used to start a login for someone else.
- **Six bot commands** — `/start`, `/login`, `/logout`, `/whoami`, `/log`, `/recent`.
- **One-command deploy** — `docker compose up` brings up the bot plus a Tailscale Funnel sidecar that gives you a public HTTPS URL with no domain to register.

## How It Works

The whole thing runs as a single asyncio process. `bot/main.py` boots three things together and ties their lifecycles to one shutdown handler:

1. the **python-telegram-bot** application (long-polling the Telegram Bot API),
2. a **FastAPI/Uvicorn** server that hosts the Web App login and MFA pages,
3. a **Playwright pool** of per-user Chromium contexts.

A `LoginCoordinator` sits in the middle and bridges all three — the Web App posts credentials to FastAPI, the actual login runs as a background task driving Playwright, and progress messages go back to the user through the Bot API.

### Logging in (OAuth + MFA replay)

When a user sends `/login`, the bot opens a Telegram Web App button pointing at the FastAPI login form, served over HTTPS via Tailscale Funnel. The user enters their email and password once; that gets posted to the bot and never written anywhere.

`bot/auth/login_flow.py` then drives the browser:

- It first checks whether the user's context already holds a Django `sessionid` cookie for `iqube.therig.in`. If so, it skips OAuth entirely (cookie-based, not URL-based — `/me/` is publicly reachable on this site, so a URL check would lie).
- Otherwise it navigates straight to `social-auth-django`'s begin URL, `/login/azuread-oauth2/`, which is exactly where the site's "Sign in with Microsoft" button links. Hitting it triggers the redirect to `login.microsoftonline.com` with no button-clicking on the PMS side.
- On Microsoft's pages it fills the email and password fields, then enters a small state machine that races every possible next screen: a TOTP/SMS code input, a number-matching display, a "Stay signed in?" prompt, a password-error box, a silent push-approval spinner, or a straight redirect back to iQube.

MFA is coordinated through callbacks. When Microsoft wants a 6-digit code, the coordinator sends a second Web App button; the code the user types lands on an `asyncio.Queue` that `request_mfa_code()` awaits. Number-matching just waits for the redirect after the user taps the right number in their Authenticator. Everything is bounded by `MFA_TIMEOUT_SECONDS` (default 180s).

After the flow finishes, the coordinator re-checks the cookie jar and only reports success if a real `sessionid` cookie is present — guarding against a flow that "looked" done but never authenticated (for example, an account not yet approved on the PMS).

### Submitting a log

`/log` is a python-telegram-bot `ConversationHandler` that walks through each field with inline keyboards, validating as it goes (`bot/utils/validators.py`): time spent must be a whole number of hours 0–24, activities capped at 255 characters, reference links must be full `http(s)://` URLs.

Submission itself (`bot/pms/submit_log.py`) deliberately avoids the browser UI. It uses Playwright's `page.request` HTTP client, which inherits the Chromium cookie jar, so it's authenticated as the user without any JavaScript or selector hunting:

1. GET the Daily Log create page so Chromium attaches its session cookies.
2. Parse out the `csrfmiddlewaretoken` — scoped to the `#DailyLogForm` block specifically, because the navbar search is a separate form whose inputs would otherwise get picked up.
3. POST the real field names (`activities_done`, `time_spent`, `location`, `custom_location`, `reference_link`, `attachment`, `description`) as multipart, with `max_redirects=0` so the result can be read directly.
4. Interpret it the Django way: a **302 to the list page is success**; a **200 means the form was re-rendered with errors**, which are scraped from the `errorlist` / `invalid-feedback` / `alert-danger` markup and sent back to the user verbatim. A redirect to the login page raises `ReLoginRequired`.

### Session and browser lifecycle

`bot/auth/playwright_pool.py` keeps one `BrowserContext` per `chat_id`, launched as a persistent context against that user's on-disk profile directory. A background reaper closes contexts that have been idle past `SESSION_IDLE_CLOSE_SECONDS` (default 600s), but leaves the profile on disk so the next use is a cheap relaunch with the session intact. `/logout` closes the context and deletes the profile directory entirely.

### Web layer and verification

`bot/web/app.py` is a small FastAPI app serving the Jinja2 login and MFA templates plus a `/healthz` check. Every Web App request carries Telegram's `initData`, which `bot/auth/telegram_initdata.py` verifies with HMAC-SHA256 derived from the bot token — so the public endpoints behind the Funnel can't be abused to kick off logins for arbitrary chat IDs.

### Bot commands

| Command | What it does |
|---------|--------------|
| `/start` | Welcome and current sign-in status |
| `/login` | Open the Microsoft sign-in Web App |
| `/logout` | Delete the session and wipe the local browser profile |
| `/whoami` | Show the signed-in email and session status |
| `/log` | Guided Daily Log submission |
| `/recent` | View recently submitted logs |

## Tech Stack

- **Language:** Python 3.10+
- **Bot framework:** python-telegram-bot 21.6+ (`[webhooks]`, `ConversationHandler`)
- **Browser automation:** Playwright 1.58 (Chromium, persistent contexts)
- **Web / API:** FastAPI 0.115+, Uvicorn, Jinja2, python-multipart
- **Config & validation:** Pydantic v2, pydantic-settings
- **Security:** cryptography / Fernet (email encryption), HMAC-SHA256 (`initData` verification)
- **Storage:** SQLite (per-chat session metadata)
- **Networking:** Tailscale Funnel (public HTTPS, Let's Encrypt cert at the Tailscale edge)
- **Deploy:** Docker, Docker Compose (bot + tailscale sidecar)
- **Tooling:** pytest, pytest-asyncio, ruff

## Getting Started

### Prerequisites

- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Tailscale account and an auth key (for the public HTTPS Funnel URL)
- Docker + Docker Compose (recommended), or Python 3.10+ for local dev
- An iQube PMS account — and, to deploy this for others, approval from the iQube admins

### Installation

```bash
git clone https://github.com/DCode-v05/Auto-Logger.git
cd Auto-Logger
```

Create your config and generate a Fernet key for at-rest email encryption:

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Fill in `.env`:

```
TELEGRAM_BOT_TOKEN=123456:ABC-from-BotFather
BOT_ENCRYPTION_KEY=<the-fernet-key-you-just-generated>
BOT_PUBLIC_URL=https://pms-bot.<your-tailnet>.ts.net
TS_AUTHKEY=tskey-auth-...
```

### Running with Docker (recommended)

```bash
docker compose up -d --build
docker compose logs -f
```

Two containers come up:

- `pms-bot` — the Telegram bot, FastAPI server, and Playwright Chromium pool
- `pms-bot-tailscale` — Tailscale with Funnel, proxying `https://pms-bot.<tailnet>.ts.net` → `http://bot:8765`

Then point the bot's Web App domain at your Funnel URL: in BotFather, go to `/mybots` → *Bot Settings → Domain* → enter `pms-bot.<your-tailnet>.ts.net`.

### Running locally for development

```bash
pip install -e .
python -m playwright install chromium
python -m bot.main
```

### Verify

```bash
curl https://pms-bot.<your-tailnet>.ts.net/healthz   # -> {"status":"ok"}
```

Open the bot in Telegram, send `/start`, then `/login`.

## Usage

1. Send `/login` and complete the Microsoft sign-in via the Web App button. If MFA fires, the bot prompts you for the code or asks you to approve the Authenticator number — handle it and the bot finishes the login.
2. Once signed in, send `/log` and answer the prompts: activities, time spent (hours), location, description, an optional reference link, and an optional attachment.
3. Review the summary, confirm, and the bot POSTs the Daily Log on your behalf. If the PMS rejects the form, the exact validation message comes back to you in chat.
4. Use `/recent` to see your last few submissions, `/whoami` to check your session, or `/logout` to clear the session and wipe your local browser profile.

## Project Structure

```
Auto-Logger/
├── bot/
│   ├── main.py                  # Entry point — boots PTB + FastAPI + Playwright pool in one process
│   ├── config.py                # Pydantic settings from .env, plus derived PMS URLs
│   ├── auth/
│   │   ├── login_flow.py        # Replays the iQube Microsoft OAuth login + MFA state machine
│   │   ├── playwright_pool.py   # Per-chat_id Chromium lifecycle + idle reaper
│   │   ├── session_store.py     # SQLite store with a Fernet-encrypted email column
│   │   └── telegram_initdata.py # HMAC-SHA256 verification of Telegram Web App initData
│   ├── handlers/
│   │   ├── start.py             # /start, /login, /logout, /whoami
│   │   ├── submit_log.py        # /log ConversationHandler
│   │   └── errors.py            # Global error handler
│   ├── pms/
│   │   ├── submit_log.py        # Fills + POSTs the Daily Log form via the browser's cookie jar
│   │   └── selectors.py         # All HTML selectors — the one place HTML coupling lives
│   ├── utils/
│   │   ├── keyboards.py         # Inline keyboard builders
│   │   └── validators.py        # Input validators (time 0–24, activities ≤255, URL)
│   └── web/
│       ├── app.py               # FastAPI endpoints for the Web App forms + /healthz
│       ├── coordinator.py       # Bridges Web App ↔ Telegram ↔ Playwright login tasks
│       └── templates/           # Jinja2 HTML for the login / MFA pages
├── tests/
│   ├── test_initdata.py         # initData HMAC verification
│   ├── test_session_store.py    # encrypted store round-trips
│   └── test_validators.py       # input validation
├── Dockerfile                   # Built on mcr.microsoft.com/playwright/python (Chromium preinstalled)
├── docker-compose.yml           # bot + tailscale sidecar
├── tailscale-serve.json         # Tailscale Funnel config (proxies to port 8765)
├── pyproject.toml
└── .env.example
```

---

## Contact

**Portfolio:** [Denistan](https://www.denistan.me)<br>
**LinkedIn:** [Denistan](https://www.linkedin.com/in/denistanb)<br>
**GitHub:** [DCode-v05](https://github.com/DCode-v05)<br>
**LeetCode:** [Denistan_B](https://leetcode.com/u/Denistan_B)<br>
**Email:** [denistanb05@gmail.com](mailto:denistanb05@gmail.com)

Made with ❤️ by **Denistan B**
