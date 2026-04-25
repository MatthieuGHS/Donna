"""Google Calendar API wrapper."""

import json
from datetime import date, datetime

import structlog
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from api.utils.tz import ensure_aware
from config import settings


class EventNotFoundError(Exception):
    """Raised when a Google Calendar event referenced by ID does not exist."""

    def __init__(self, event_id: str) -> None:
        super().__init__(f"event not found: {event_id}")
        self.event_id = event_id

logger = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_calendar_service():
    """Build and return Google Calendar API service."""
    sa_info = json.loads(settings.google_service_account_json)
    credentials = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build("calendar", "v3", credentials=credentials)


_DESCRIPTION_MAX_CHARS = 200


def _matches_query(event: dict, query: str) -> bool:
    """Case-insensitive substring match against title + description.

    Run on the FULL description (before any truncation) so a hit beyond
    the 200-char display cap is not lost.
    """
    haystack = ((event.get("title") or "") + " " + (event.get("description") or "")).lower()
    return query in haystack


def _truncate_description(event: dict) -> dict:
    """Cap description at _DESCRIPTION_MAX_CHARS so a single bloated event
    doesn't blow up Claude's input tokens. Mutates and returns the same dict
    for chainability."""
    desc = event.get("description") or ""
    if len(desc) > _DESCRIPTION_MAX_CHARS:
        event["description"] = desc[: _DESCRIPTION_MAX_CHARS - 3] + "..."
    return event


def list_events(date_start: date, date_end: date, query: str | None = None) -> list[dict]:
    """List events between two dates, optionally filtered by `query`.

    `query` is a case-insensitive substring matched against title + description.
    Empty / whitespace-only queries are treated as "no filter".
    """
    service = _get_calendar_service()
    time_min = datetime.combine(date_start, datetime.min.time()).isoformat() + "Z"
    time_max = datetime.combine(date_end, datetime.max.time()).isoformat() + "Z"

    result = service.events().list(
        calendarId=settings.google_calendar_id,
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    raw_events = result.get("items", [])
    events = [
        {
            "id": e["id"],
            "title": e.get("summary", "(sans titre)"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
            "description": e.get("description", ""),
        }
        for e in raw_events
    ]

    if query and query.strip():
        q = query.strip().lower()
        events = [e for e in events if _matches_query(e, q)]

    # Cap descriptions AFTER filtering so query hits beyond char 200 aren't lost.
    events = [_truncate_description(e) for e in events]

    logger.info(
        "calendar_list_events",
        count=len(events),
        date_start=str(date_start),
        date_end=str(date_end),
        filtered=bool(query and query.strip()),
    )
    return events


def _normalize_dt_field(value) -> str:
    """Coerce a Claude-supplied datetime field to RFC 3339 with explicit offset.

    Accepts a datetime (aware or naive) or an ISO string. Naive values are
    localized to settings.timezone; aware values are preserved.
    """
    if isinstance(value, datetime):
        return ensure_aware(value).isoformat()
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value  # let Google reject it explicitly rather than guess
        return ensure_aware(parsed).isoformat()
    return value


def get_event(event_id: str) -> dict | None:
    """Fetch a single event by ID. Returns None if it does not exist."""
    service = _get_calendar_service()
    try:
        event = service.events().get(
            calendarId=settings.google_calendar_id,
            eventId=event_id,
        ).execute()
    except HttpError as e:
        status = getattr(e, "resp", None) and e.resp.status
        if status in (404, 410):
            return None
        raise

    return {
        "id": event["id"],
        "title": event.get("summary", "(sans titre)"),
        "start": event["start"].get("dateTime", event["start"].get("date")),
        "end": event["end"].get("dateTime", event["end"].get("date")),
        "description": event.get("description", ""),
    }


def list_overlapping_events(start: datetime, end: datetime) -> list[dict]:
    """List Google Calendar events that overlap with [start, end].

    Uses `events().list()` instead of freeBusy because the pending-action
    display layer needs event titles to surface to the user (e.g. "chevauche
    'Cours maths'"); freeBusy returns only busy ranges, no titles.
    """
    start = ensure_aware(start)
    end = ensure_aware(end)
    events = list_events(start.date(), end.date())

    overlapping: list[dict] = []
    for e in events:
        try:
            e_start = datetime.fromisoformat(e["start"])
            e_end = datetime.fromisoformat(e["end"])
        except (ValueError, KeyError):
            continue
        e_start = ensure_aware(e_start)
        e_end = ensure_aware(e_end)
        if e_start < end and e_end > start:
            overlapping.append(e)
    return overlapping


def check_availability(start: datetime, end: datetime) -> dict:
    """Check if a time slot is available against Google Calendar freeBusy.

    `start`/`end` are normalized to a timezone-aware datetime before serializing
    to RFC 3339; freeBusy rejects offset-less times with HTTP 400.
    """
    start = ensure_aware(start)
    end = ensure_aware(end)
    service = _get_calendar_service()

    body = {
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "items": [{"id": settings.google_calendar_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy = result["calendars"][settings.google_calendar_id]["busy"]

    return {"available": len(busy) == 0, "conflicts": busy}


def find_free_slots(duration_minutes: int, date_start: date, date_end: date) -> list[dict]:
    """Find free slots of given duration within a date range.

    Respects working hours (8h-20h) and finds gaps between events.
    """
    from datetime import timedelta
    import pytz

    tz = pytz.timezone(settings.timezone)
    slots = []
    current_date = date_start

    while current_date <= date_end:
        day_start = tz.localize(datetime.combine(current_date, datetime.min.time().replace(hour=8)))
        day_end = tz.localize(datetime.combine(current_date, datetime.min.time().replace(hour=20)))

        events = list_events(current_date, current_date)
        busy_periods = []
        for e in events:
            e_start = datetime.fromisoformat(e["start"])
            e_end = datetime.fromisoformat(e["end"])
            if e_start.tzinfo is None:
                e_start = tz.localize(e_start)
            if e_end.tzinfo is None:
                e_end = tz.localize(e_end)
            busy_periods.append((e_start, e_end))

        busy_periods.sort(key=lambda x: x[0])

        # Find gaps
        cursor = day_start
        for busy_start, busy_end in busy_periods:
            if busy_start > cursor:
                gap_minutes = (busy_start - cursor).total_seconds() / 60
                if gap_minutes >= duration_minutes:
                    slots.append({
                        "start": cursor.isoformat(),
                        "end": (cursor + timedelta(minutes=duration_minutes)).isoformat(),
                        "date": str(current_date),
                    })
            cursor = max(cursor, busy_end)

        if cursor < day_end:
            gap_minutes = (day_end - cursor).total_seconds() / 60
            if gap_minutes >= duration_minutes:
                slots.append({
                    "start": cursor.isoformat(),
                    "end": (cursor + timedelta(minutes=duration_minutes)).isoformat(),
                    "date": str(current_date),
                })

        current_date += timedelta(days=1)

    logger.info("calendar_find_free_slots", count=len(slots), duration=duration_minutes)
    return slots


def create_event(
    title: str,
    start: datetime,
    end: datetime,
    description: str | None = None,
    attendees: list[str] | None = None,
    with_meet: bool = False,
    notify_attendees: bool = False,
) -> dict:
    """Create a new calendar event, optionally with attendees.

    Fix 3: outbound invitation emails are NOT sent unless `notify_attendees=True`
    is set explicitly. The default closed posture prevents the Google service
    account from being used as a phishing relay via the user's identity.
    """
    start = ensure_aware(start)
    end = ensure_aware(end)
    service = _get_calendar_service()

    event_body = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": settings.timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.timezone},
    }
    if description:
        event_body["description"] = description
    if attendees:
        event_body["attendees"] = [{"email": email} for email in attendees]

    send_updates = "all" if (attendees and notify_attendees) else "none"
    event = service.events().insert(
        calendarId=settings.google_calendar_id,
        body=event_body,
        sendUpdates=send_updates,
    ).execute()

    result = {
        "event_id": event["id"],
        "title": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }

    if attendees:
        result["attendees"] = attendees

    logger.info("calendar_create_event", event_id=event["id"], title=title)
    return result


def update_event(event_id: str, fields: dict) -> dict:
    """Update an existing calendar event. Raises EventNotFoundError if gone."""
    service = _get_calendar_service()

    try:
        event = service.events().get(calendarId=settings.google_calendar_id, eventId=event_id).execute()
    except HttpError as e:
        status = getattr(e, "resp", None) and e.resp.status
        if status in (404, 410):
            raise EventNotFoundError(event_id) from e
        raise

    if "title" in fields:
        event["summary"] = fields["title"]
    if "start" in fields:
        event["start"] = {
            "dateTime": _normalize_dt_field(fields["start"]),
            "timeZone": settings.timezone,
        }
    if "end" in fields:
        event["end"] = {
            "dateTime": _normalize_dt_field(fields["end"]),
            "timeZone": settings.timezone,
        }
    if "description" in fields:
        event["description"] = fields["description"]

    updated = service.events().update(
        calendarId=settings.google_calendar_id, eventId=event_id, body=event
    ).execute()

    logger.info("calendar_update_event", event_id=event_id)
    return {"event_id": updated["id"], "updated_fields": list(fields.keys())}


def delete_event(event_id: str) -> dict:
    """Delete a calendar event. Raises EventNotFoundError if the event is gone."""
    service = _get_calendar_service()
    try:
        service.events().delete(calendarId=settings.google_calendar_id, eventId=event_id).execute()
    except HttpError as e:
        status = getattr(e, "resp", None) and e.resp.status
        if status in (404, 410):
            raise EventNotFoundError(event_id) from e
        raise
    logger.info("calendar_delete_event", event_id=event_id)
    return {"deleted": event_id}
