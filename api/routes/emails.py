"""Emails API routes — Zimbra IMAP cache served from Supabase."""

import structlog
from fastapi import APIRouter, Depends, Request

from api.auth import verify_api_key
from api.rate_limit import limiter
from api.services import email_service
from db.models import (
    APIResponse,
    GetEmailRequest,
    ListUnreadEmailsRequest,
    MarkNotifiedRequest,
    RecapEmailsRequest,
    SyncEmailsRequest,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/sync", response_model=APIResponse)
@limiter.limit("30/minute")
async def sync_emails(
    request: Request,
    body: SyncEmailsRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("sync_emails")
    try:
        result = email_service.sync_recent_unread(limit=5)
        return APIResponse(success=True, data=result)
    except Exception as e:
        logger.error("sync_emails_error", error=str(e))
        return APIResponse(success=False, error="Failed to sync emails")


@router.post("/get", response_model=APIResponse)
@limiter.limit("100/minute")
async def get_email(
    request: Request,
    body: GetEmailRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("get_email", email_id=str(body.email_id))
    try:
        mail = email_service.get_email(body.email_id)
        if mail is None:
            return APIResponse(success=False, error="Email not found")
        return APIResponse(success=True, data=mail)
    except Exception as e:
        logger.error("get_email_error", error=str(e))
        return APIResponse(success=False, error="Failed to get email")


@router.post("/list_unread", response_model=APIResponse)
@limiter.limit("100/minute")
async def list_unread_emails(
    request: Request,
    body: ListUnreadEmailsRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("list_unread_emails", days=body.days, limit=body.limit)
    try:
        emails = email_service.list_unread_emails(days=body.days, limit=body.limit)
        return APIResponse(success=True, data={"emails": emails})
    except Exception as e:
        logger.error("list_unread_emails_error", error=str(e))
        return APIResponse(success=False, error="Failed to list unread emails")


@router.post("/recap", response_model=APIResponse)
@limiter.limit("100/minute")
async def recap_emails(
    request: Request,
    body: RecapEmailsRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("recap_emails")
    try:
        result = email_service.get_recap_emails()
        return APIResponse(success=True, data=result)
    except Exception as e:
        logger.error("recap_emails_error", error=str(e))
        return APIResponse(success=False, error="Failed to build email recap")


@router.post("/mark_notified", response_model=APIResponse)
@limiter.limit("100/minute")
async def mark_notified(
    request: Request,
    body: MarkNotifiedRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("mark_notified", count=len(body.email_ids))
    try:
        updated = email_service.mark_as_notified(body.email_ids)
        return APIResponse(success=True, data={"updated": updated})
    except Exception as e:
        logger.error("mark_notified_error", error=str(e))
        return APIResponse(success=False, error="Failed to mark emails as notified")
