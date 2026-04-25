"""Todos CRUD operations via Supabase."""

from datetime import date
from uuid import UUID

import structlog
from supabase import create_client

from config import settings
from db.models import Priority, TodoFilter

logger = structlog.get_logger(__name__)


def _get_client():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def get_todo(todo_id: UUID) -> dict | None:
    """Fetch a single todo by ID, or None if not found."""
    client = _get_client()
    result = client.table("todos").select("*").eq("id", str(todo_id)).limit(1).execute()
    if not result.data:
        return None
    return result.data[0]


def list_todos(filter_type: TodoFilter) -> list[dict]:
    """List todos with optional filter."""
    client = _get_client()
    query = client.table("todos").select("*").order("created_at", desc=True)

    if filter_type == TodoFilter.PENDING:
        query = query.eq("done", False)
    elif filter_type == TodoFilter.DONE:
        query = query.eq("done", True)

    result = query.execute()
    logger.info("todos_list", filter=filter_type, count=len(result.data))
    return result.data


def create_todo(title: str, deadline: date | None, priority: Priority) -> dict:
    """Create a new todo."""
    client = _get_client()
    data = {"title": title, "priority": priority.value}
    if deadline:
        data["deadline"] = str(deadline)

    result = client.table("todos").insert(data).execute()
    todo = result.data[0]
    logger.info("todos_create", todo_id=todo["id"], title=title)
    return todo


def update_todo(todo_id: UUID, title: str) -> dict:
    """Rename a todo."""
    client = _get_client()
    result = client.table("todos").update({"title": title}).eq("id", str(todo_id)).execute()

    if not result.data:
        raise ValueError(f"Todo {todo_id} not found")

    logger.info("todos_update", todo_id=str(todo_id), title=title)
    return result.data[0]


def complete_todo(todo_id: UUID) -> dict:
    """Mark a todo as done."""
    client = _get_client()
    result = client.table("todos").update({"done": True}).eq("id", str(todo_id)).execute()

    if not result.data:
        raise ValueError(f"Todo {todo_id} not found")

    logger.info("todos_complete", todo_id=str(todo_id))
    return result.data[0]


def delete_todo(todo_id: UUID) -> dict:
    """Delete a todo."""
    client = _get_client()
    result = client.table("todos").delete().eq("id", str(todo_id)).execute()

    if not result.data:
        raise ValueError(f"Todo {todo_id} not found")

    logger.info("todos_delete", todo_id=str(todo_id))
    return {"deleted": str(todo_id)}
