# pms-telegram-bot

A Telegram bot that submits daily logs to `iqube.therig.in` on behalf of college
users. The bot drives a headless Chromium (Playwright) per user to replay the
site's Microsoft OAuth login and POST the real form — **no changes are made to
the PMS server**.

Phase 1 ships daily log submission. Future phases will layer in tasks, projects,
announcements etc. by driving the same browser session against the rest of the
site.

## How it works

1. User sends `/login` in Telegram.
2. Bot opens a Telegram Web App with a Microsoft sign-in form (served by the bot
   over HTTPS through a Cloudflare tunnel).
3. User enters their college email + Microsoft password. The form posts to the
   bot, which uses Playwright to navigate to `iqube.therig.in` and complete the
   same Microsoft OAuth flow the website uses. MFA (push, number-matching, TOTP)
   is handled with in-chat prompts and a second Web App for code entry.
4. Django's `sessionid` cookie ends up in the per-user Chromium user-data-dir on
   disk and persists across bot restarts (~2 weeks, same lifetime as on the
   website).
5. `/log` walks the user through the form fields and POSTs the final submission
   through the same authenticated browser. Form errors from the site are
   surfaced back to the chat.

The user's Microsoft password is **only held in memory** during the login flow
and is never written to disk.

## Prerequisites

- A Windows server that stays on.
- **Docker Desktop** installed and running (uses the WSL 2 backend — Linux
  containers work transparently on Windows).
- A domain attached to a **Cloudflare** account. If you don't own one, grab a
  cheap `.xyz`/`.me` (~$2/yr) and add it to Cloudflare (free). Named tunnels
  require a domain; ad-hoc tunnel URLs change on every restart and break
  Telegram's saved domain.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).

## Deploy

### 1. Create the Cloudflare Tunnel in the dashboard

Cloudflare Zero Trust → *Networks → Tunnels → Create a tunnel* → "Cloudflared"
→ name it `pms-bot`. Copy the **token** shown on the install page.

On the same tunnel, add a **Public Hostname**:

- Subdomain: `pms-bot`
- Domain: *your domain*
- Service: `HTTP` → `bot:8765` *(this hostname resolves inside the Docker network)*

### 2. Clone and configure

Open PowerShell on the server:

```powershell
git clone <your-repo-url> C:\pms-telegram-bot
cd C:\pms-telegram-bot
copy .env.example .env

# Generate the Fernet key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Edit `.env` and fill in:

```
TELEGRAM_BOT_TOKEN=123456:ABC-from-BotFather
BOT_ENCRYPTION_KEY=<the-fernet-key-you-just-generated>
BOT_PUBLIC_URL=https://pms-bot.yourdomain.com
CLOUDFLARED_TOKEN=<the-tunnel-token-from-step-1>
```

### 3. Start everything

```powershell
docker compose up -d --build
docker compose logs -f          # watch it boot, Ctrl+C to stop tailing
```

Two containers come up:

- **`pms-bot`** — the Telegram bot + FastAPI + Playwright Chromium pool.
- **`pms-bot-tunnel`** — cloudflared, exposing `bot:8765` at
  `https://pms-bot.yourdomain.com`.

Both use `restart: unless-stopped`, so they come back automatically on server
reboot (as long as Docker Desktop is set to start with Windows — *Settings →
General → Start Docker Desktop when you sign in*).

### 4. Tell Telegram about the domain

BotFather → `/mybots` → your bot → *Bot Settings → Domain* → enter
`pms-bot.yourdomain.com`. Required for Web App buttons to render.

### 5. Verify

```powershell
curl https://pms-bot.yourdomain.com/healthz   # -> {"status":"ok"}
```

Open your bot in Telegram → `/start` → `/login`.

## Updating

```powershell
cd C:\pms-telegram-bot
git pull
docker compose up -d --build
```

## Running locally for development

Needs Python 3.11+ and Playwright's Chromium on your laptop, plus any public
HTTPS URL pointing at the FastAPI port. The easiest way is a named Cloudflare
tunnel the same way as the server deploy, just pointing at `http://localhost:8765`
from your laptop.

```powershell
pip install -e .
python -m playwright install chromium
copy .env.example .env   # fill TELEGRAM_BOT_TOKEN, BOT_PUBLIC_URL, BOT_ENCRYPTION_KEY
python -m bot.main
```

## Security notes

- The bot handles the user's Microsoft password in memory only, for the
  duration of one login call. It is never persisted.
- The bot's host owns the Playwright user-data-dirs, which contain users'
  active Django session cookies. **Restrict filesystem access on the host.**
- `BOT_ENCRYPTION_KEY` (Fernet) encrypts the email column in SQLite.
- Communication from the Web App form to the bot server is HTTPS via the
  Cloudflare tunnel. `_initData` is verified with HMAC-SHA256 using the bot
  token, so the public endpoints cannot be abused to start logins for
  arbitrary users.
- **This bot signs in to a college system on users' behalf.** Get explicit
  approval from iQube admins before deploying it.

## Troubleshooting

- *"invalid initData"* — the user opened the Web App outside Telegram, or the
  `TELEGRAM_BOT_TOKEN` in `.env` doesn't match the bot the button came from.
- *"Could not find Microsoft sign-in button"* — iqube.therig.in changed its
  HTML. Update selectors in [`bot/pms/selectors.py`](bot/pms/selectors.py).
- *MFA timeout* — bump `MFA_TIMEOUT_SECONDS` in `.env`.
- *Form always rejects* — set `LOG_LEVEL=DEBUG` in `.env`, restart, inspect
  the scraped error messages; compare to the form's own validation.

## Layout

- `bot/main.py` — boots everything
- `bot/web/app.py` — FastAPI endpoints for the Web App forms
- `bot/web/coordinator.py` — bridges the Web App + Telegram + Playwright login
- `bot/auth/login_flow.py` — replays the iqube Microsoft OAuth login
- `bot/auth/playwright_pool.py` — per-chat_id Chromium lifecycle
- `bot/auth/session_store.py` — SQLite + Fernet
- `bot/auth/telegram_initdata.py` — Telegram Web App HMAC verification
- `bot/pms/submit_log.py` — fills and submits the Daily Log form
- `bot/pms/selectors.py` — **the one place HTML coupling to iqube lives**
- `bot/handlers/submit_log.py` — the `/log` ConversationHandler
