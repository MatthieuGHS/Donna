"""Todos API routes."""

import structlog
from fastapi import APIRouter, Depends, Request

from api.auth import verify_api_key
from api.rate_limit import limiter
from api.services import todos_service
from db.models import (
    APIResponse,
    CompleteTodoRequest,
    CreateTodoRequest,
    DeleteTodoRequest,
    ListTodosRequest,
)

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.post("/list", response_model=APIResponse)
@limiter.limit("100/minute")
async def list_todos(
    request: Request,
    body: ListTodosRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("list_todos", filter=body.filter)
    try:
        todos = todos_service.list_todos(body.filter)
        return APIResponse(success=True, data={"todos": todos})
    except Exception as e:
        logger.error("list_todos_error", error=str(e))
        return APIResponse(success=False, error="Failed to list todos")


@router.post("/create", response_model=APIResponse)
@limiter.limit("100/minute")
async def create_todo(
    request: Request,
    body: CreateTodoRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("create_todo", title=body.title)
    try:
        todo = todos_service.create_todo(body.title, body.deadline, body.priority)
        return APIResponse(success=True, data=todo)
    except Exception as e:
        logger.error("create_todo_error", error=str(e))
        return APIResponse(success=False, error="Failed to create todo")


@router.post("/complete", response_model=APIResponse)
@limiter.limit("100/minute")
async def complete_todo(
    request: Request,
    body: CompleteTodoRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("complete_todo", todo_id=str(body.todo_id))
    try:
        result = todos_service.complete_todo(body.todo_id)
        return APIResponse(success=True, data=result)
    except ValueError as e:
        return APIResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("complete_todo_error", error=str(e))
        return APIResponse(success=False, error="Failed to complete todo")


@router.post("/delete", response_model=APIResponse)
@limiter.limit("100/minute")
async def delete_todo(
    request: Request,
    body: DeleteTodoRequest,
    _api_key: str = Depends(verify_api_key),
) -> APIResponse:
    logger.info("delete_todo", todo_id=str(body.todo_id))
    try:
        result = todos_service.delete_todo(body.todo_id)
        return APIResponse(success=True, data=result)
    except ValueError as e:
        return APIResponse(success=False, error=str(e))
    except Exception as e:
        logger.error("delete_todo_error", error=str(e))
        return APIResponse(success=False, error="Failed to delete todo")
