"""Timezone helpers shared by services.

Lives outside `api/services/` so calendar_service and zimbra_service can both
depend on it without creating a cycle, and so the rule "datetimes hitting the
Google freeBusy API must be RFC 3339 with an explicit offset" has one home.
"""

from __future__ import annotations

from datetime import datetime

import pytz

from config import settings


def ensure_aware(dt: datetime) -> datetime:
    """Return a timezone-aware datetime in the user's local timezone.

    If `dt` is naive, localize to `settings.timezone` (Europe/Paris in prod).
    Aware datetimes pass through unchanged. Required before any datetime is
    sent to Google freeBusy, which rejects RFC 3339 strings without an
    explicit offset (HTTP 400 Bad Request).
    """
    if dt.tzinfo is None:
        return pytz.timezone(settings.timezone).localize(dt)
    return dt
