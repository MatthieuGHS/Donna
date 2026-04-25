# Donna

A personal assistant powered by Telegram, Claude AI, Google Calendar, Zimbra IMAP and Supabase.

Talk to Donna in natural language (text or voice) to manage your calendar, todos, personal rules, and read your school emails.

## Features

- **Natural language** — text or voice messages via Telegram
- **Unified calendar** — merges Google Calendar (personal events) + Zimbra/ICS (school/work schedule, read-only)
- **Todos** — create, complete, rename, delete tasks with priorities and deadlines
- **Rules** — define personal rules and preferences stored in database
- **Smart scheduling** — find free slots, check availability across all calendar sources
- **Conflict detection** — creating an event that overlaps with an existing one triggers a Confirmer/Annuler inline button (never an open-ended question from Donna). The conflict is detected server-side at pending creation and `force=true` is overridden by the server when a real overlap exists, regardless of what the model sent
- **Destructive action safety** — all deletions and any sensitive mutation (event update, event creation with attendees) require explicit confirmation via inline buttons. The text shown on the button is server-generated from the validated payload — the LLM cannot pick what the user sees on Confirm
- **Daily recaps** — automated morning (7h) and afternoon (13h) recaps, split into three separate messages: agenda, todos, emails
- **Voice messages** — transcribed via Google Speech-to-Text, then processed as text
- **Event invites** — create events with attendees who receive email invitations only when `notify_attendees=true` is explicitly set on a confirmed pending; never on a direct tool call. Default closed posture prevents the Google service account from being used as a phishing relay
- **Email cache (Zimbra IMAP)** — rolling window of the 30 most recent unread school emails, synced automatically 3×/day (7h/12h/17h). Donna never triggers a sync herself — she reads from the cache
- **Token-saving display pattern** — requests to *view* an email, todo list or unread mailbox bypass the LLM entirely: the bot fetches directly from Supabase and sends a separate Telegram message. Claude only sees metadata for identification, never the email body

## Architecture

```
┌─────────────────────┐       ┌──────────────────────┐
│   Bot Telegram      │──────>│   API FastAPI         │
│   (process 1)       │ HTTPS │   (process 2)         │
│                     │ + key │                       │
│ - Receives messages │       │ - Exposes tools       │
│ - Calls Claude API  │       │ - Auth + rate limit   │
│ - Sends recaps      │       │ - IMAP fetcher        │
│ - Scheduler 7h/13h  │       │ - Audit logging       │
│ - Email sync crons  │       │                       │
│   (7h/12h/17h)      │       │                       │
└─────────────────────┘       └──────────┬────────────┘
                                         │
                            ┌────────────┼───────────┬──────────┐
                            v            v           v          v
                      ┌──────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐
                      │ Supabase │ │ Google   │ │ Zimbra │ │ Zimbra    │
                      │ Postgres │ │ Calendar │ │  ICS   │ │  IMAP     │
                      └──────────┘ └──────────┘ └────────┘ └───────────┘
```

**Message pipeline:**
1. Telegram message received (text or voice)
2. Chat ID verified against whitelist
3. Voice messages: OGG → WAV (ffmpeg) → Google Speech-to-Text → text
4. Text sent to Claude API with tool definitions
5. Claude calls tools as needed (each tool = HTTP call to FastAPI API)
6. API executes operations on Supabase / Google Calendar / Zimbra
7. Results returned to Claude for final response
8. Response sent back to user on Telegram — plus, for "display" intents, one or more extra messages rendered directly by the bot from Supabase (no tokens spent on the body)

Claude is **stateless** — no conversation history. All data is retrieved via tool calls on each message.

### Token-saving "display" tools

Viewing data (emails, todos) is the most frequent interaction and would normally force Claude to echo every character — wasting output tokens. Donna ships a family of `display_*` tools that bypass the LLM entirely for rendering:

| Tool | Claude sees | User receives |
|---|---|---|
| `display_email(email_id)` | `{shown: true}` only | A second Telegram message rendered by the bot from Supabase |
| `display_unread_emails(days, limit)` | `{shown: true}` only | A second Telegram message with the list |
| `display_todos(filter)` | `{shown: true}` only | A second Telegram message with the list |

For every such request, Claude's final reply is a two-word confirmation ("Voilà."). The email body never enters Claude's context — you pay a fixed ~$0.02 per query regardless of mail size.

For analysis intents (resume, extract, compare) Claude still uses `list_unread_emails` / `list_todos`, which return lightweight metadata only.

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.11+ |
| Telegram Bot | `python-telegram-bot` (async) |
| API | `FastAPI` + `uvicorn` |
| LLM | Claude API (`anthropic` SDK) |
| Scheduler | `APScheduler` |
| Calendar | Google Calendar API (Service Account) |
| School schedule | Zimbra ICS (HTTP Basic Auth + `icalendar`) |
| School mail | Zimbra IMAPS (stdlib `imaplib` + `beautifulsoup4` for body layout) |
| Voice | Google Speech-to-Text + `ffmpeg` |
| Database | Supabase (PostgreSQL) |
| Rate limiting | `slowapi` |
| Config | `python-dotenv` + `pydantic-settings` |
| Logging | `structlog` |

## Project Structure

```
donna/
├── bot/
│   ├── main.py              # Bot entry point + scheduler
│   ├── handlers.py          # Text, voice, and inline button handlers
│   ├── security.py          # Chat ID whitelist
│   ├── claude_client.py     # Claude API wrapper + tool definitions + display_* routing
│   ├── formatting.py        # Shared Telegram renderers (emails, todos)
│   ├── api_client.py        # HTTP client for FastAPI
│   └── recap.py             # Morning/afternoon recap generation (agenda + todos + emails, 3 messages)
├── api/
│   ├── main.py              # FastAPI app
│   ├── auth.py              # API key verification (constant-time)
│   ├── rate_limit.py        # slowapi config
│   ├── logging_config.py    # structlog setup
│   ├── routes/
│   │   ├── calendar.py      # Calendar endpoints (Google + Zimbra merged)
│   │   ├── todos.py         # Todo CRUD endpoints
│   │   ├── rules.py         # Rules endpoints
│   │   ├── pending.py       # Pending action endpoints
│   │   └── emails.py        # Email cache endpoints (sync / get / list_unread / recap / mark_notified)
│   └── services/
│       ├── calendar_service.py   # Google Calendar API wrapper
│       ├── zimbra_service.py     # Zimbra ICS fetch + parse + cache
│       ├── email_service.py      # Zimbra IMAP fetcher + Supabase email cache (rolling 30)
│       ├── todos_service.py      # Supabase CRUD
│       ├── rules_service.py      # Supabase CRUD
│       └── pending_service.py    # Pending actions + expiration
├── api/
│   └── utils/
│       └── tz.py            # Shared TZ helper (ensure_aware) — naive datetimes are localized before Google freeBusy
├── db/
│   ├── models.py            # Pydantic schemas + PendingActionPayload (discriminated by `action`)
│   ├── fixtures.py          # Dev seed data (refuses to run in prod)
│   └── migrations/          # Idempotent SQL scripts (001 → 007)
├── tests/                   # pytest suite — guards on payload validation, tool-loop cap, attendees, untrusted wrapping, freeBusy, force override
├── config.py                # pydantic-settings, loads .env
├── requirements.txt
├── requirements-dev.txt     # pytest + pytest-asyncio
├── pytest.ini
├── .env.example
├── Dockerfile
├── Procfile
└── nixpacks.toml
```

## Setup Guide

### Prerequisites

- Python 3.11+
- ffmpeg installed (`sudo apt install ffmpeg` or `brew install ffmpeg`)
- Accounts: Telegram, Anthropic, Google Cloud, Supabase
- Optional: a Zimbra account (school/work) if you want the ICS calendar and mail cache

### Step 1 — Telegram Bot

1. Message **@BotFather** on Telegram
2. `/newbot` — choose a name and username
3. Save the **bot token**
4. Find your **Chat ID**: message your bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` and look for `"chat":{"id":...}`

### Step 2 — Anthropic API

1. Go to [console.anthropic.com](https://console.anthropic.com/)
2. Create an API key
3. Ensure you have credits on your account

### Step 3 — Google Cloud

#### 3a. Create project + enable APIs
1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a new project
3. Enable **Google Calendar API**
4. Enable **Cloud Speech-to-Text API**

#### 3b. Create Service Account
1. Go to **APIs & Services > Credentials**
2. Create credentials > **Service account**
3. Go to the service account > **Keys** > Add Key > **JSON**
4. Download the JSON key file

#### 3c. Share your calendar
1. Go to [calendar.google.com](https://calendar.google.com/)
2. Calendar settings > **Share with specific people**
3. Add the service account email (from the JSON file)
4. Permission: **Make changes to events**
5. Note your **Calendar ID** (usually your Gmail address)

### Step 4 — Supabase

1. Go to [supabase.com](https://supabase.com/dashboard)
2. Create a new project
3. Note the **Project URL** and **service_role key** (Settings > API)
4. Run the migration scripts from `db/migrations/` in the **SQL Editor**, in order (001 through 007)

### Step 5 — Generate internal API key

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Step 6 — Configure environment

```bash
cp .env.example .env
# Fill in all values
```

For `GOOGLE_SERVICE_ACCOUNT_JSON`, paste the entire JSON content on a single line.

Zimbra variables are **optional** — if not set, the bot works with Google Calendar only. Set `ZIMBRA_IMAP_HOST` only if you want the email cache feature (still needs `ZIMBRA_USER` and `ZIMBRA_PASSWORD`).

### Step 7 — Install and run locally

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Terminal 1:
python -m api.main

# Terminal 2:
python -m bot.main
```

### Step 8 — Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Deploy to Railway

1. Push your code to a **private** GitHub repo
2. Go to [railway.app](https://railway.app/) and create a new project from your repo
3. Railway detects the `Procfile` and creates two services: `bot` and `api`
4. For each service, set the **Custom Start Command** in Settings > Deploy:
   - bot: `python -m bot.main`
   - api: `python -m api.main`
5. Add all environment variables to **both services** (use prod values)
6. Set `ENVIRONMENT=prod`
7. Generate a domain for the **api** service (Settings > Networking > Generate Domain)
8. Set `API_URL=https://your-api-domain.up.railway.app` in the **bot** service variables

## Security

| Layer | Protection |
|-------|-----------|
| Telegram | Chat ID whitelist — unauthorized users silently ignored |
| API | `X-API-Key` header with constant-time comparison (anti timing attack) |
| Rate limiting | 100 requests/minute per IP (30 req/min on `/emails/sync`) |
| Database | Row Level Security on all tables (deny all for anon role) |
| Pending actions | `action_payload` is validated server-side against a typed enum (`PendingActionPayload`), so the LLM cannot smuggle arbitrary actions. The `display_description` shown on the Confirm button is generated server-side from the validated payload + real Google/Supabase data — Claude's free-text label is stored only for audit, never displayed |
| Deletions | All destructive actions require confirmation via inline buttons |
| Event mutations | `update_event` and `create_event` with attendees are forbidden as direct tool calls — they must round-trip through `create_pending`. Conflicts are detected at pending creation and `force=true` is overridden server-side when a real overlap exists |
| Outbound mail | Google Calendar invitations are sent only when `notify_attendees=true` is explicitly set on a confirmed pending. Attendees are capped at 5, validated as RFC 5322 (rejects `\n` BCC-smuggling), default `sendUpdates="none"` |
| Indirect prompt injection | Tool results from `list_unread_emails` and `list_events` (attacker-controllable via mail subjects, calendar invites, Zimbra upstream) are wrapped in `<untrusted_data>` markers; system prompt instructs the model to ignore embedded instructions; inner escape attempts (`</untrusted_data>` in the payload) are sanitized |
| Tool-use DoS | Claude's tool-use loop is capped at 8 iterations per user message — bounded by code, not by prompt |
| Prompt injection | Max 5 destructive actions per message, locked system prompt, payload validation as the real boundary |
| Secrets | All in environment variables, never in code |
| Zimbra IMAP | IMAPS only (TLS on port 993), password never logged, `BODY.PEEK[]` keeps server-side unread status untouched |
| Email access | Claude sees metadata only (sender/subject/date) — email bodies never enter LLM context |
| Production | FastAPI docs/OpenAPI disabled, no stack traces exposed |

## API Endpoints

All endpoints require `X-API-Key` header.

| Endpoint | Description |
|----------|-------------|
| `POST /calendar/list_events` | List events (Google + Zimbra merged) |
| `POST /calendar/check_availability` | Check time slot availability |
| `POST /calendar/find_free_slots` | Find free slots in date range |
| `POST /calendar/create_event` | Create event (Google only, with optional attendees) |
| `POST /calendar/update_event` | Update event (Google only) |
| `POST /calendar/delete_event` | Delete event (Google only) |
| `POST /todos/list` | List todos |
| `POST /todos/create` | Create todo |
| `POST /todos/update` | Rename todo |
| `POST /todos/complete` | Mark todo as done |
| `POST /todos/delete` | Delete todo |
| `POST /rules/list` | List rules |
| `POST /rules/create` | Create rule |
| `POST /rules/delete` | Delete rule |
| `POST /pending/create` | Create pending action (validates `action_payload` against `PendingActionPayload`, fetches real data to build `display_description`) |
| `POST /pending/list` | List pending actions |
| `POST /pending/resolve` | Confirm or cancel pending action (refuses `confirm` on a non-executable / obsolete pending; cancel still allowed) |
| `POST /pending/mark_obsolete` | Flip `executable=false` on a pending whose underlying object disappeared between creation and execution |
| `POST /emails/sync` | Pull the most recent UNSEEN mails from Zimbra IMAP into the cache (rolling 30) |
| `POST /emails/list_unread` | List cached emails from the last N days (metadata only) |
| `POST /emails/get` | Return a single cached email with its body (used internally by the bot for direct rendering) |
| `POST /emails/recap` | Return up to 5 non-notified emails for the recap + overflow count |
| `POST /emails/mark_notified` | Flag emails as shown in a recap |
| `GET /health` | Health check |

## License

MIT
