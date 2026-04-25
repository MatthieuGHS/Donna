"""Pending actions API routes."""

import structlog
from fastapi import APIRouter, Depends, Request

from api.auth import verify_api_key
from api.rate_limit import limiter
from api.services import pending_service
from db.models import (
    APIResponse,
    CreatePendingRequest,
    MarkPendingObsoleteRequest,
    ResolvePendingRequest,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/create", response_model=APIResponse)
@limiter.limit("100/minute")
async def create_pending(
    request: Request,
    body: CreatePendingRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("create_pending")
    try:
        pending = pending_service.create_pending(body.action_payload, body.description)
        return APIResponse(success=True, data=pending)
    except ValueError as e:
        # Validation failure surfaces back to the model as a tool_result error.
        return APIResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("create_pending_error", error=str(e))
        return APIResponse(success=False, error="Failed to create pending action")


@router.post("/list", response_model=APIResponse)
@limiter.limit("100/minute")
async def list_pending(
    request: Request,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("list_pending")
    try:
        pending_actions = pending_service.list_pending()
        return APIResponse(success=True, data={"pending_actions": pending_actions})
    except Exception as e:
        logger.error("list_pending_error", error=str(e))
        return APIResponse(success=False, error="Failed to list pending actions")


@router.post("/resolve", response_model=APIResponse)
@limiter.limit("100/minute")
async def resolve_pending(
    request: Request,
    body: ResolvePendingRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("resolve_pending", pending_id=str(body.pending_id), choice=body.choice)
    try:
        result = pending_service.resolve_pending(body.pending_id, body.choice)
        return APIResponse(success=True, data=result)
    except ValueError as e:
        return APIResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("resolve_pending_error", error=str(e))
        return APIResponse(success=False, error="Failed to resolve pending action")


@router.post("/mark_obsolete", response_model=APIResponse)
@limiter.limit("100/minute")
async def mark_pending_obsolete(
    request: Request,
    body: MarkPendingObsoleteRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    """Flip `executable` to false on a pending action.

    Used by the bot when execution discovers the underlying object is missing,
    so a future confirmation attempt yields a clear message instead of a
    generic Google API failure.
    """
    logger.info("mark_pending_obsolete", pending_id=str(body.pending_id))
    try:
        result = pending_service.mark_obsolete(body.pending_id)
        return APIResponse(success=True, data=result)
    except Exception as e:
        logger.error("mark_pending_obsolete_error", error=str(e))
        return APIResponse(success=False, error="Failed to mark pending as obsolete")
