"""Calendar API routes — merges Google Calendar + Zimbra (school EDT)."""

from datetime import datetime

import pytz
import structlog
from fastapi import APIRouter, Depends, Request

from api.auth import verify_api_key
from api.rate_limit import limiter
from api.services import calendar_service, zimbra_service
from api.services.calendar_service import EventNotFoundError
from config import settings
from db.models import (
    APIResponse,
    CheckAvailabilityRequest,
    CreateEventRequest,
    DeleteEventRequest,
    FindFreeSlotsRequest,
    ListEventsRequest,
    UpdateEventRequest,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


def _add_source_to_google_events(events: list[dict]) -> list[dict]:
    """Tag Google Calendar events with source field."""
    for e in events:
        if "source" not in e:
            e["source"] = "google"
    return events


def _merge_and_sort(google_events: list[dict], zimbra_events: list[dict]) -> list[dict]:
    """Merge events from both sources and sort by start time."""
    all_events = _add_source_to_google_events(google_events) + zimbra_events
    all_events.sort(key=lambda e: e.get("start", ""))
    return all_events


@router.post("/check_availability", response_model=APIResponse)
@limiter.limit("100/minute")
async def check_availability(
    request: Request,
    body: CheckAvailabilityRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("check_availability", start=str(body.start), end=str(body.end))
    try:
        result = calendar_service.check_availability(body.start, body.end)

        # Also check Zimbra conflicts
        zimbra_warn = None
        if zimbra_service.is_configured():
            try:
                zimbra_conflicts = zimbra_service.check_availability(body.start, body.end)
                if zimbra_conflicts:
                    result["available"] = False
                    result["conflicts"] = result.get("conflicts", []) + [
                        {"start": c["start"], "end": c["end"], "title": c["title"], "source": "zimbra"}
                        for c in zimbra_conflicts
                    ]
            except Exception:
                zimbra_warn = "EDT école indisponible"

        if zimbra_warn:
            result["zimbra_warning"] = zimbra_warn

        return APIResponse(success=True, data=result)
    except Exception as e:
        logger.error("check_availability_error", error=str(e))
        return APIResponse(success=False, error="Failed to check availability")


@router.post("/find_free_slots", response_model=APIResponse)
@limiter.limit("100/minute")
async def find_free_slots(
    request: Request,
    body: FindFreeSlotsRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("find_free_slots", duration=body.duration_minutes)
    try:
        slots = calendar_service.find_free_slots(
            body.duration_minutes, body.date_range_start, body.date_range_end
        )

        # Filter out slots that conflict with Zimbra events
        if zimbra_service.is_configured():
            try:
                tz = pytz.timezone(settings.timezone)
                filtered_slots = []
                for slot in slots:
                    slot_start = datetime.fromisoformat(slot["start"])
                    slot_end = datetime.fromisoformat(slot["end"])
                    zimbra_conflicts = zimbra_service.check_availability(slot_start, slot_end)
                    if not zimbra_conflicts:
                        filtered_slots.append(slot)
                slots = filtered_slots
            except Exception:
                logger.warning("zimbra_unavailable_for_free_slots")

        return APIResponse(success=True, data={"slots": slots})
    except Exception as e:
        logger.error("find_free_slots_error", error=str(e))
        return APIResponse(success=False, error="Failed to find free slots")


@router.post("/list_events", response_model=APIResponse)
@limiter.limit("100/minute")
async def list_events(
    request: Request,
    body: ListEventsRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("list_events", date=str(body.target_date))
    try:
        if body.target_date:
            google_events = calendar_service.list_events(body.target_date, body.target_date)
            zimbra_events = []
            zimbra_warn = None
            if zimbra_service.is_configured():
                try:
                    zimbra_events = zimbra_service.list_events(body.target_date, body.target_date)
                except Exception:
                    zimbra_warn = "EDT école indisponible"
            events = _merge_and_sort(google_events, zimbra_events)
            data = {"events": events}
            if zimbra_warn:
                data["zimbra_warning"] = zimbra_warn
            return APIResponse(success=True, data=data)

        elif body.date_range_start and body.date_range_end:
            google_events = calendar_service.list_events(body.date_range_start, body.date_range_end)
            zimbra_events = []
            zimbra_warn = None
            if zimbra_service.is_configured():
                try:
                    zimbra_events = zimbra_service.list_events(body.date_range_start, body.date_range_end)
                except Exception:
                    zimbra_warn = "EDT école indisponible"
            events = _merge_and_sort(google_events, zimbra_events)
            data = {"events": events}
            if zimbra_warn:
                data["zimbra_warning"] = zimbra_warn
            return APIResponse(success=True, data=data)

        else:
            return APIResponse(success=False, error="Provide date or date_range_start+date_range_end")
    except Exception as e:
        logger.error("list_events_error", error=str(e))
        return APIResponse(success=False, error="Failed to list events")


# create, update, delete stay Google-only

@router.post("/create_event", response_model=APIResponse)
@limiter.limit("100/minute")
async def create_event(
    request: Request,
    body: CreateEventRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("create_event", title=body.title)
    try:
        if not body.force:
            # Check Google conflicts
            availability = calendar_service.check_availability(body.start, body.end)
            conflicts = availability.get("conflicts", [])

            # Check Zimbra conflicts too
            if zimbra_service.is_configured():
                try:
                    zimbra_conflicts = zimbra_service.check_availability(body.start, body.end)
                    conflicts += [
                        {"start": c["start"], "end": c["end"], "title": c["title"], "source": "zimbra"}
                        for c in zimbra_conflicts
                    ]
                except Exception:
                    pass

            if conflicts:
                # Stable error code so the bot's tool loop can recognize this
                # specific failure and steer Claude to create_pending instead
                # of letting the model improvise a plain-text question.
                # See bot/claude_client.py for the matching directive.
                conflicting_titles = [
                    c.get("title") or c.get("summary") or "(sans titre)"
                    for c in conflicts
                ]
                return APIResponse(
                    success=False,
                    error="conflict_requires_pending",
                    data={
                        "conflicting_titles": conflicting_titles,
                        "conflicts": conflicts,
                    },
                )

        result = calendar_service.create_event(
            body.title, body.start, body.end, body.description,
            attendees=body.attendees, with_meet=body.with_meet,
            notify_attendees=body.notify_attendees,
        )
        return APIResponse(success=True, data=result)
    except Exception as e:
        logger.error("create_event_error", error=str(e))
        return APIResponse(success=False, error="Failed to create event")


@router.post("/update_event", response_model=APIResponse)
@limiter.limit("100/minute")
async def update_event(
    request: Request,
    body: UpdateEventRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("update_event", event_id=body.event_id)
    try:
        result = calendar_service.update_event(body.event_id, body.fields)
        return APIResponse(success=True, data=result)
    except EventNotFoundError:
        return APIResponse(success=False, error="event_not_found")
    except Exception as e:
        logger.error("update_event_error", error=str(e))
        return APIResponse(success=False, error="Failed to update event")


@router.post("/delete_event", response_model=APIResponse)
@limiter.limit("100/minute")
async def delete_event(
    request: Request,
    body: DeleteEventRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("delete_event", event_id=body.event_id)
    try:
        result = calendar_service.delete_event(body.event_id)
        return APIResponse(success=True, data=result)
    except EventNotFoundError:
        return APIResponse(success=False, error="event_not_found")
    except Exception as e:
        logger.error("delete_event_error", error=str(e))
        return APIResponse(success=False, error="Failed to delete event")
