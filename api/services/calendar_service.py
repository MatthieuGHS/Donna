"""Google Calendar API wrapper."""

import json
from datetime import date, datetime

import structlog
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from config import settings

logger = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_calendar_service():
    """Build and return Google Calendar API service."""
    sa_info = json.loads(settings.google_service_account_json)
    credentials = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return build("calendar", "v3", credentials=credentials)


def list_events(date_start: date, date_end: date) -> list[dict]:
    """List events between two dates."""
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

    events = result.get("items", [])
    logger.info("calendar_list_events", count=len(events), date_start=str(date_start), date_end=str(date_end))
    return [
        {
            "id": e["id"],
            "title": e.get("summary", "(sans titre)"),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date")),
            "description": e.get("description", ""),
        }
        for e in events
    ]


def check_availability(start: datetime, end: datetime) -> dict:
    """Check if a time slot is available."""
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


def create_event(title: str, start: datetime, end: datetime, description: str | None = None) -> dict:
    """Create a new calendar event."""
    service = _get_calendar_service()

    event_body = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": settings.timezone},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.timezone},
    }
    if description:
        event_body["description"] = description

    event = service.events().insert(calendarId=settings.google_calendar_id, body=event_body).execute()
    logger.info("calendar_create_event", event_id=event["id"], title=title)
    return {"event_id": event["id"], "title": title, "start": start.isoformat(), "end": end.isoformat()}


def update_event(event_id: str, fields: dict) -> dict:
    """Update an existing calendar event."""
    service = _get_calendar_service()

    event = service.events().get(calendarId=settings.google_calendar_id, eventId=event_id).execute()

    if "title" in fields:
        event["summary"] = fields["title"]
    if "start" in fields:
        event["start"] = {"dateTime": fields["start"], "timeZone": settings.timezone}
    if "end" in fields:
        event["end"] = {"dateTime": fields["end"], "timeZone": settings.timezone}
    if "description" in fields:
        event["description"] = fields["description"]

    updated = service.events().update(
        calendarId=settings.google_calendar_id, eventId=event_id, body=event
    ).execute()

    logger.info("calendar_update_event", event_id=event_id)
    return {"event_id": updated["id"], "updated_fields": list(fields.keys())}


def delete_event(event_id: str) -> dict:
    """Delete a calendar event."""
    service = _get_calendar_service()
    service.events().delete(calendarId=settings.google_calendar_id, eventId=event_id).execute()
    logger.info("calendar_delete_event", event_id=event_id)
    return {"deleted": event_id}
