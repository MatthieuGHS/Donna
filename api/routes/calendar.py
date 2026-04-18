"""Calendar API routes."""

from datetime import timedelta

import structlog
from fastapi import APIRouter, Depends, Request

from api.auth import verify_api_key
from api.rate_limit import limiter
from api.services import calendar_service
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
            events = calendar_service.list_events(body.target_date, body.target_date)
        elif body.date_range_start and body.date_range_end:
            events = calendar_service.list_events(body.date_range_start, body.date_range_end)
        else:
            return APIResponse(success=False, error="Provide date or date_range_start+date_range_end")
        return APIResponse(success=True, data={"events": events})
    except Exception as e:
        logger.error("list_events_error", error=str(e))
        return APIResponse(success=False, error="Failed to list events")


@router.post("/create_event", response_model=APIResponse)
@limiter.limit("100/minute")
async def create_event(
    request: Request,
    body: CreateEventRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("create_event", title=body.title)
    try:
        # Check for conflicts unless force=true
        if not body.force:
            availability = calendar_service.check_availability(body.start, body.end)
            if not availability["available"]:
                return APIResponse(
                    success=False,
                    error="Time slot has conflicts. Use force=true to override.",
                    data={"conflicts": availability["conflicts"]},
                )
        result = calendar_service.create_event(body.title, body.start, body.end, body.description)
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
    except Exception as e:
        logger.error("delete_event_error", error=str(e))
        return APIResponse(success=False, error="Failed to delete event")
