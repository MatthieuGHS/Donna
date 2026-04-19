"""Pydantic models for database entities and API request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


# --- Enums ---

class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PendingStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class AuditResult(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


class RuleType(str, Enum):
    AVAILABILITY = "availability"
    RECAP = "recap"


class TodoFilter(str, Enum):
    ALL = "all"
    PENDING = "pending"
    DONE = "done"


# --- Database models ---

class Todo(BaseModel):
    id: UUID
    title: str
    deadline: date | None = None
    priority: Priority = Priority.MEDIUM
    done: bool = False
    created_at: datetime


class Rule(BaseModel):
    id: UUID
    type: RuleType
    rule_text: str
    structured: dict
    active: bool = True
    created_at: datetime


class PendingAction(BaseModel):
    id: UUID
    action_payload: dict
    description: str
    status: PendingStatus = PendingStatus.PENDING
    expires_at: datetime
    resolved_at: datetime | None = None
    created_at: datetime


class AuditLog(BaseModel):
    id: UUID
    endpoint: str
    payload: dict | None = None
    result: AuditResult
    error_message: str | None = None
    created_at: datetime


# --- Request schemas ---

class CheckAvailabilityRequest(BaseModel):
    start: datetime
    end: datetime


class FindFreeSlotsRequest(BaseModel):
    duration_minutes: int = Field(gt=0, le=480)
    date_range_start: date
    date_range_end: date


class ListEventsRequest(BaseModel):
    target_date: date | None = None
    date_range_start: date | None = None
    date_range_end: date | None = None


class CreateEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start: datetime
    end: datetime
    description: str | None = None
    force: bool = False
    attendees: list[str] | None = None
    with_meet: bool = False


class UpdateEventRequest(BaseModel):
    event_id: str
    fields: dict


class DeleteEventRequest(BaseModel):
    event_id: str


class ListTodosRequest(BaseModel):
    filter: TodoFilter = TodoFilter.ALL


class CreateTodoRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    deadline: date | None = None
    priority: Priority = Priority.MEDIUM


class CompleteTodoRequest(BaseModel):
    todo_id: UUID


class DeleteTodoRequest(BaseModel):
    todo_id: UUID


class ListRulesRequest(BaseModel):
    type: str = "all"  # "all", "availability", "recap"


class CreateRuleRequest(BaseModel):
    type: RuleType
    rule_text: str = Field(min_length=1, max_length=1000)
    structured: dict


class DeleteRuleRequest(BaseModel):
    rule_id: UUID


class CreatePendingRequest(BaseModel):
    action_payload: dict
    description: str = Field(min_length=1, max_length=500)


class ResolvePendingRequest(BaseModel):
    pending_id: UUID
    choice: str = Field(pattern=r"^(confirm|cancel)$")


# --- Response schemas ---

class APIResponse(BaseModel):
    success: bool
    data: dict | list | None = None
    error: str | None = None
