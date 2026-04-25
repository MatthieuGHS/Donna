"""Shared pytest fixtures.

Sets minimal env vars before any project module is imported, so that
`config.Settings()` (which validates required fields at instantiation)
does not crash during test collection.
"""

import os

# Must run before `config` or anything that imports it.
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("ALLOWED_CHAT_IDS", "1")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic")
os.environ.setdefault("GOOGLE_CALENDAR_ID", "test@example.com")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_JSON", "{}")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("API_KEY", "x" * 40)
