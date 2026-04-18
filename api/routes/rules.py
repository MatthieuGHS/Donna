"""Rules API routes."""

import structlog
from fastapi import APIRouter, Depends, Request

from api.auth import verify_api_key
from api.rate_limit import limiter
from api.services import rules_service
from db.models import (
    APIResponse,
    CreateRuleRequest,
    DeleteRuleRequest,
    ListRulesRequest,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/list", response_model=APIResponse)
@limiter.limit("100/minute")
async def list_rules(
    request: Request,
    body: ListRulesRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("list_rules", type=body.type)
    try:
        rules = rules_service.list_rules(body.type)
        return APIResponse(success=True, data={"rules": rules})
    except Exception as e:
        logger.error("list_rules_error", error=str(e))
        return APIResponse(success=False, error="Failed to list rules")


@router.post("/create", response_model=APIResponse)
@limiter.limit("100/minute")
async def create_rule(
    request: Request,
    body: CreateRuleRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("create_rule", type=body.type, rule_text=body.rule_text)
    try:
        rule = rules_service.create_rule(body.type, body.rule_text, body.structured)
        return APIResponse(success=True, data=rule)
    except Exception as e:
        logger.error("create_rule_error", error=str(e))
        return APIResponse(success=False, error="Failed to create rule")


@router.post("/delete", response_model=APIResponse)
@limiter.limit("100/minute")
async def delete_rule(
    request: Request,
    body: DeleteRuleRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("delete_rule", rule_id=str(body.rule_id))
    try:
        result = rules_service.delete_rule(body.rule_id)
        return APIResponse(success=True, data=result)
    except ValueError as e:
        return APIResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("delete_rule_error", error=str(e))
        return APIResponse(success=False, error="Failed to delete rule")
