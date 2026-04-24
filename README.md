# Auto Logger

## Project Description
Auto Logger is a Telegram bot that submits daily logs to the iQube PMS (`iqube.therig.in`) on behalf of college users. The bot drives a headless Chromium browser (via Playwright) per user to replay the site's Microsoft OAuth login and POST the real Daily Log form — no changes are made to the PMS server. Users interact entirely through Telegram: they sign in once via an in-chat Web App and thereafter post logs using the `/log` command, with form validation errors surfaced back to the chat.

---

## Project Details

### Problem Statement
Daily log submission on the iQube PMS portal is repetitive and requires navigating a Microsoft OAuth login (often with MFA) followed by a multi-field web form. Students and employees often forget to log entries, submit late, or lose time to the click-through flow. Auto Logger eliminates that friction by letting users submit the same log from Telegram in seconds, while re-using the exact authenticated browser session the website itself would use.

### How It Works
- **Login flow:** User sends `/login`. The bot opens a Telegram Web App with a Microsoft sign-in form served over HTTPS via a Tailscale Funnel. The password is posted once to the bot, which drives Playwright through the `iqube.therig.in` Microsoft OAuth flow.
- **MFA handling:** Push, number-matching, and TOTP flows are detected automatically. In-chat prompts and a second Web App collect codes when needed.
- **Session persistence:** Django's `sessionid` cookie lands in a per-user Chromium user-data-dir on disk and persists across bot restarts (~2 weeks — the same lifetime as on the website).
- **Log submission:** `/log` launches a `ConversationHandler` that walks the user through activities, time spent, location, description, optional reference link, and optional attachment, then POSTs through the same authenticated browser.
- **Security:** The user's Microsoft password is held only in memory during login and never written to disk. Email addresses in the SQLite store are encrypted with Fernet.

### Authentication & Session Management
- **Microsoft OAuth replay:** Navigates directly to `social-auth-django`'s `/login/azuread-oauth2/` begin URL to skip the landing page click.
- **Per-user Playwright pool:** Each chat_id owns its own Chromium `user-data-dir`. Idle sessions auto-close after a configurable timeout (`SESSION_IDLE_CLOSE_SECONDS`).
- **Encrypted session store:** SQLite database with a Fernet-encrypted email column; `chat_id` → `(email, status)` mapping.
- **Telegram Web App verification:** `initData` is verified with HMAC-SHA256 against the bot token, so the public `/webapp/*` endpoints cannot be abused to start logins for arbitrary users.

### Bot Commands
| Command | Purpose |
|---------|---------|
| `/start` | Welcome / status |
| `/login` | Open the Microsoft sign-in Web App |
| `/logout` | Delete session + wipe local browser profile |
| `/whoami` | Show signed-in email and session status |
| `/log` | Guided Daily Log submission |
| `/recent` | View recently submitted logs |

### Web Application
A lightweight FastAPI app (served behind Tailscale Funnel) hosts the Telegram Web App forms used during login:
- Microsoft email + password entry
- MFA code / number-matching confirmation
- HTTPS-only, HMAC-verified `_initData` on every request

---

## Tech Stack
- **Python 3.10+**
- **python-telegram-bot** (`[webhooks]`) — Telegram Bot API + ConversationHandler
- **Playwright** (Chromium) — headless browser automation for Microsoft OAuth + form POST
- **FastAPI + Uvicorn** — Web App endpoints (login form, MFA form, healthz)
- **cryptography (Fernet)** — at-rest encryption of stored emails
- **Pydantic / pydantic-settings** — typed configuration from `.env`
- **Jinja2** — Web App HTML templates
- **SQLite** — per-chat session metadata
- **Tailscale Funnel** — public HTTPS URL without a domain
- **Docker Compose** — one-command deploy (bot + tailscale sidecar)
- **pytest / pytest-asyncio / ruff** — testing & linting

---

## Getting Started

### 1. Clone the repository
```
git clone https://github.com/DCode-v05/Auto-Logger.git
cd Auto-Logger
```

### 2. Configure environment
```
copy .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Fill in `.env` with:
```
TELEGRAM_BOT_TOKEN=123456:ABC-from-BotFather
BOT_ENCRYPTION_KEY=<the-fernet-key-you-just-generated>
BOT_PUBLIC_URL=https://pms-bot.<your-tailnet>.ts.net
TS_AUTHKEY=tskey-auth-...
```

### 3. Deploy with Docker (recommended)
```
docker compose up -d --build
docker compose logs -f
```
Two containers come up:
- `pms-bot` — Telegram bot + FastAPI + Playwright Chromium pool
- `pms-bot-tailscale` — Tailscale with Funnel, proxying `https://pms-bot.<tailnet>.ts.net` → `http://bot:8765`

Then in BotFather → `/mybots` → *Bot Settings → Domain* → enter `pms-bot.<your-tailnet>.ts.net`.

### 4. Run locally for development
```
pip install -e .
python -m playwright install chromium
python -m bot.main
```

### 5. Verify
```
curl https://pms-bot.<your-tailnet>.ts.net/healthz    # -> {"status":"ok"}
```
Open the bot in Telegram → `/start` → `/login`.

---

## Usage
- Send `/login` in Telegram and complete Microsoft sign-in via the Web App button.
- Once signed in, send `/log` and answer the prompts (activities, time spent, location, description, optional reference link, optional attachment).
- Review the summary, confirm, and the bot POSTs the Daily Log on your behalf.
- Use `/recent` to see your last submissions or `/logout` to clear your session and wipe the local browser profile.

---

## Project Structure
```
Auto-Logger/
│
├── bot/
│   ├── main.py                     # Entry point — boots PTB + FastAPI + Playwright pool
│   ├── config.py                   # Pydantic settings loaded from .env
│   ├── auth/
│   │   ├── login_flow.py           # Replays the iQube Microsoft OAuth login
│   │   ├── playwright_pool.py      # Per-chat_id Chromium lifecycle
│   │   ├── session_store.py        # SQLite + Fernet encrypted email store
│   │   └── telegram_initdata.py    # Telegram Web App HMAC verification
│   ├── handlers/
│   │   ├── start.py                # /start, /login, /logout, /whoami
│   │   ├── submit_log.py           # /log ConversationHandler
│   │   └── errors.py               # Global error handler
│   ├── pms/
│   │   ├── submit_log.py           # Fills and submits the Daily Log form
│   │   └── selectors.py            # HTML selectors — the one place HTML coupling lives
│   ├── utils/
│   │   ├── keyboards.py            # Inline keyboard builders
│   │   └── validators.py           # Input validators (URL, time, description)
│   └── web/
│       ├── app.py                  # FastAPI endpoints for the Web App forms
│       ├── coordinator.py          # Bridges Web App ↔ Telegram ↔ Playwright
│       └── templates/              # Jinja2 HTML for login / MFA forms
├── data/
│   ├── profiles/                   # Per-user Playwright user-data-dirs
│   └── tmp/                        # Attachment downloads
├── tests/
│   ├── test_initdata.py
│   ├── test_session_store.py
│   └── test_validators.py
├── Dockerfile
├── docker-compose.yml
├── tailscale-serve.json            # Tailscale Funnel config (port 8765)
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Security Notes
- The bot handles the user's Microsoft password **in memory only**, for the duration of one login call. It is never persisted.
- The bot's host owns the Playwright `user-data-dirs`, which contain users' active Django session cookies. **Restrict filesystem access on the host.**
- `BOT_ENCRYPTION_KEY` (Fernet) encrypts the email column in SQLite at rest.
- Web App ↔ bot communication is HTTPS via Tailscale Funnel (Let's Encrypt cert at the Tailscale edge). `initData` is HMAC-verified on every request.
- **This bot signs in to a college system on users' behalf.** Get explicit approval from the iQube admins before deploying it.

---

## Troubleshooting
- *"invalid initData"* — the user opened the Web App outside Telegram, or `TELEGRAM_BOT_TOKEN` in `.env` doesn't match the bot the button came from.
- *"Could not find Microsoft sign-in button"* — iqube.therig.in changed its HTML. Update selectors in [bot/pms/selectors.py](bot/pms/selectors.py).
- *MFA timeout* — bump `MFA_TIMEOUT_SECONDS` in `.env`.
- *Form always rejects* — set `LOG_LEVEL=DEBUG` in `.env`, restart, inspect the scraped error messages; compare to the form's own validation.

---

## Contributing

Contributions are welcome! To contribute:
1. Fork the repository
2. Create a new branch:
   ```bash
   git checkout -b feature/your-feature
   ```
3. Commit your changes:
   ```bash
   git commit -m "Add your feature"
   ```
4. Push to your branch:
   ```bash
   git push origin feature/your-feature
   ```
5. Open a pull request describing your changes.

---

## Contact
- **GitHub:** [DCode-v05](https://github.com/DCode-v05)
- **Email:** denistanb05@gmail.com
