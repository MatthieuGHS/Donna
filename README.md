# Donna

A personal assistant powered by Telegram, Claude AI, Google Calendar and Supabase.

Talk to Donna in natural language (text or voice) to manage your calendar, todos, and personal rules.

## Features

- **Natural language** — text or voice messages via Telegram
- **Unified calendar** — merges Google Calendar (personal events) + Zimbra/ICS (school/work schedule, read-only)
- **Todos** — create, complete, rename, delete tasks with priorities and deadlines
- **Rules** — define personal rules and preferences stored in database
- **Smart scheduling** — find free slots, check availability across all calendar sources
- **Conflict detection** — refuses to create events that overlap with existing ones (unless forced)
- **Destructive action safety** — all deletions require explicit confirmation via inline buttons
- **Daily recaps** — automated morning (today's schedule) and afternoon (tomorrow's preview) summaries
- **Voice messages** — transcribed via Google Speech-to-Text, then processed as text
- **Event invites** — create events with attendees who receive email invitations

## Architecture

```
┌─────────────────────┐       ┌──────────────────────┐
│   Bot Telegram      │──────>│   API FastAPI         │
│   (process 1)       │ HTTPS │   (process 2)         │
│                     │ + key │                       │
│ - Receives messages │       │ - Exposes tools       │
│ - Calls Claude API  │       │ - Auth + rate limit   │
│ - Sends recaps      │       │ - Audit logging       │
│ - Scheduler 7h/13h  │       │                       │
└─────────────────────┘       └──────────┬────────────┘
                                         │
                             ┌───────────┼───────────┐
                             v           v           v
                      ┌──────────┐ ┌──────────┐ ┌────────┐
                      │ Supabase │ │ Google   │ │ Zimbra │
                      │ Postgres │ │ Calendar │ │  ICS   │
                      └──────────┘ └──────────┘ └────────┘
```

**Message pipeline:**
1. Telegram message received (text or voice)
2. Chat ID verified against whitelist
3. Voice messages: OGG -> WAV (ffmpeg) -> Google Speech-to-Text -> text
4. Text sent to Claude API with tool definitions
5. Claude calls tools as needed (each tool = HTTP call to FastAPI API)
6. API executes operations on Supabase / Google Calendar / Zimbra
7. Results returned to Claude for final response
8. Response sent back to user on Telegram

Claude is **stateless** — no conversation history. All data is retrieved via tool calls on each message.

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
│   ├── claude_client.py     # Claude API wrapper + tool definitions
│   ├── api_client.py        # HTTP client for FastAPI
│   └── recap.py             # Morning/afternoon recap generation
├── api/
│   ├── main.py              # FastAPI app
│   ├── auth.py              # API key verification (constant-time)
│   ├── rate_limit.py        # slowapi config
│   ├── logging_config.py    # structlog setup
│   ├── routes/
│   │   ├── calendar.py      # Calendar endpoints (Google + Zimbra merged)
│   │   ├── todos.py         # Todo CRUD endpoints
│   │   ├── rules.py         # Rules endpoints
│   │   └── pending.py       # Pending action endpoints
│   └── services/
│       ├── calendar_service.py   # Google Calendar API wrapper
│       ├── zimbra_service.py     # Zimbra ICS fetch + parse + cache
│       ├── todos_service.py      # Supabase CRUD
│       ├── rules_service.py      # Supabase CRUD
│       └── pending_service.py    # Pending actions + expiration
├── db/
│   ├── models.py            # Pydantic schemas
│   ├── fixtures.py          # Dev seed data (refuses to run in prod)
│   └── migrations/          # Idempotent SQL scripts
├── config.py                # pydantic-settings, loads .env
├── requirements.txt
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
4. Run the migration scripts from `db/migrations/` in the **SQL Editor**, in order (001 through 005)

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

Zimbra variables are **optional** — if not set, the bot works with Google Calendar only.

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
| Rate limiting | 100 requests/minute per IP |
| Database | Row Level Security on all tables (deny all for anon role) |
| Deletions | All destructive actions require confirmation via inline buttons |
| Prompt injection | Max 5 destructive actions per message, locked system prompt |
| Secrets | All in environment variables, never in code |
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
| `POST /pending/create` | Create pending action |
| `POST /pending/list` | List pending actions |
| `POST /pending/resolve` | Confirm or cancel pending action |
| `GET /health` | Health check |

## License

MIT
