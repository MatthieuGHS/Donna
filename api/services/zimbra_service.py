"""Zimbra ICS calendar service — read-only school schedule.

Fetches the ICS from Zimbra via HTTP Basic Auth, parses it,
and caches the result in memory with a configurable TTL.
"""

import time
from datetime import date, datetime, timedelta

import httpx
import pytz
import structlog
from icalendar import Calendar

from api.utils.tz import ensure_aware
from config import settings

logger = structlog.get_logger(__name__)

# In-memory cache
_cache: dict = {"data": None, "fetched_at": 0.0}


def _fetch_ics() -> str | None:
    """Fetch ICS file from Zimbra with HTTP Basic Auth."""
    if not settings.zimbra_ics_url:
        return None

    try:
        response = httpx.get(
            settings.zimbra_ics_url,
            auth=(settings.zimbra_user, settings.zimbra_password),
            timeout=10.0,
        )
        response.raise_for_status()
        logger.info("zimbra_ics_fetched", size_bytes=len(response.text))
        return response.text
    except Exception as e:
        # Never log the password
        logger.error("zimbra_fetch_failed", url=settings.zimbra_ics_url, error=str(e))
        return None


def _parse_ics(ics_text: str) -> list[dict]:
    """Parse ICS text into a list of event dicts."""
    cal = Calendar.from_ical(ics_text)
    tz = pytz.timezone(settings.timezone)
    events = []

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dt_start = component.get("dtstart")
        dt_end = component.get("dtend")

        if not dt_start or not dt_end:
            continue

        start = dt_start.dt
        end = dt_end.dt

        # Convert date to datetime if needed
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime.combine(start, datetime.min.time())
            start = tz.localize(start)
        elif start.tzinfo is None:
            start = tz.localize(start)

        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime.combine(end, datetime.min.time())
            end = tz.localize(end)
        elif end.tzinfo is None:
            end = tz.localize(end)

        events.append({
            "id": str(component.get("uid", "")),
            "title": str(component.get("summary", "(sans titre)")),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "location": str(component.get("location", "")),
            "description": str(component.get("description", "")),
            "source": "zimbra",
        })

    logger.info("zimbra_ics_parsed", event_count=len(events))
    return events


def _get_cached_events() -> list[dict] | None:
    """Get events from cache, refreshing if TTL expired."""
    now = time.time()

    if _cache["data"] is not None and (now - _cache["fetched_at"]) < settings.zimbra_cache_ttl_seconds:
        return _cache["data"]

    ics_text = _fetch_ics()
    if ics_text is None:
        # Return stale cache if available, otherwise empty
        if _cache["data"] is not None:
            logger.warning("zimbra_using_stale_cache")
            return _cache["data"]
        return None

    events = _parse_ics(ics_text)
    _cache["data"] = events
    _cache["fetched_at"] = now
    return events


_DESCRIPTION_MAX_CHARS = 200


def _matches_query(event: dict, query: str) -> bool:
    haystack = ((event.get("title") or "") + " " + (event.get("description") or "")).lower()
    return query in haystack


def _truncate_description(event: dict) -> dict:
    desc = event.get("description") or ""
    if len(desc) > _DESCRIPTION_MAX_CHARS:
        # Mutate a copy: cached events are shared, never mutate them in place.
        out = dict(event)
        out["description"] = desc[: _DESCRIPTION_MAX_CHARS - 3] + "..."
        return out
    return event


def list_events(date_start: date, date_end: date, query: str | None = None) -> list[dict]:
    """List Zimbra events between two dates, optionally filtered by `query`."""
    all_events = _get_cached_events()

    if all_events is None:
        return []

    tz = pytz.timezone(settings.timezone)
    range_start = tz.localize(datetime.combine(date_start, datetime.min.time()))
    range_end = tz.localize(datetime.combine(date_end, datetime.max.time()))

    filtered = []
    for event in all_events:
        event_start = datetime.fromisoformat(event["start"])
        if range_start <= event_start <= range_end:
            filtered.append(event)

    if query and query.strip():
        q = query.strip().lower()
        filtered = [e for e in filtered if _matches_query(e, q)]

    filtered = [_truncate_description(e) for e in filtered]
    filtered.sort(key=lambda e: e["start"])
    return filtered


def check_availability(start: datetime, end: datetime) -> list[dict]:
    """Return Zimbra events that conflict with the given time slot."""
    all_events = _get_cached_events()

    if all_events is None:
        return []

    start = ensure_aware(start)
    end = ensure_aware(end)

    conflicts = []
    for event in all_events:
        e_start = ensure_aware(datetime.fromisoformat(event["start"]))
        e_end = ensure_aware(datetime.fromisoformat(event["end"]))

        # Overlap check
        if e_start < end and e_end > start:
            conflicts.append(event)

    return conflicts


def refresh_cache() -> int:
    """Force refresh the cache. Returns number of events loaded."""
    _cache["data"] = None
    _cache["fetched_at"] = 0.0
    events = _get_cached_events()
    return len(events) if events else 0


def is_configured() -> bool:
    """Check if Zimbra integration is configured."""
    return bool(settings.zimbra_ics_url and settings.zimbra_user and settings.zimbra_password)
