"""Pydantic models for database entities and API request/response schemas."""

from __future__ import annotations

import re
from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


# Simple RFC 5322-ish email regex. Not strictly compliant (no quoted locals,
# no IPv6 literals) but enough to keep an attacker from smuggling control
# characters or fragments through the `attendees` field.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
# Hard cap on attendees per event (Fix 3 — anti-phishing).
MAX_ATTENDEES = 5


def _validate_attendees(v: list[str] | None) -> list[str] | None:
    if v is None:
        return v
    cleaned: list[str] = []
    for raw in v:
        if not isinstance(raw, str):
            raise ValueError("attendee must be a string")
        addr = raw.strip().lower()
        if not addr:
            continue
        if len(addr) > 254:
            raise ValueError(f"attendee address too long: {addr[:30]}…")
        if not _EMAIL_RE.match(addr):
            raise ValueError(f"invalid attendee email: {addr}")
        cleaned.append(addr)
    if len(cleaned) > MAX_ATTENDEES:
        raise ValueError(f"too many attendees ({len(cleaned)} > {MAX_ATTENDEES})")
    return cleaned or None


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


class PendingActionType(str, Enum):
    """Whitelist of actions a pending_action may carry.

    Anything outside this set is rejected at creation time, so a compromised
    model cannot smuggle arbitrary tool calls through the confirmation flow.
    """
    DELETE_EVENT = "delete_event"
    DELETE_TODO = "delete_todo"
    DELETE_RULE = "delete_rule"
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"


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
    display_description: str | None = None
    executable: bool = True
    status: PendingStatus = PendingStatus.PENDING
    expires_at: datetime
    resolved_at: datetime | None = None
    created_at: datetime


class PendingActionPayload(BaseModel):
    """Validated shape of `pending_actions.action_payload`.

    Discriminated by `action`. Pydantic enforces required fields per action
    type so the model cannot inject arbitrary keys.

    Note: `attendees` length cap and per-address validation are tightened in
    Fix 3 (alongside the `create_event with attendees` ➜ pending requirement).
    """

    action: PendingActionType
    # delete_*
    event_id: str | None = Field(default=None, max_length=200)
    todo_id: UUID | None = None
    rule_id: UUID | None = None
    # create_event / update_event
    title: str | None = Field(default=None, max_length=500)
    start: datetime | None = None
    end: datetime | None = None
    description: str | None = Field(default=None, max_length=2000)
    attendees: list[str] | None = Field(default=None, max_length=MAX_ATTENDEES)
    notify_attendees: bool = False
    force: bool = False  # only meaningful for create_event after a known conflict
    fields: dict | None = None  # only meaningful for update_event

    _validate_attendees_list = field_validator("attendees")(lambda cls, v: _validate_attendees(v))

    @model_validator(mode="after")
    def _validate_shape(self) -> "PendingActionPayload":
        a = self.action
        if a == PendingActionType.DELETE_EVENT:
            if not self.event_id:
                raise ValueError("event_id required for delete_event")
        elif a == PendingActionType.DELETE_TODO:
            if not self.todo_id:
                raise ValueError("todo_id required for delete_todo")
        elif a == PendingActionType.DELETE_RULE:
            if not self.rule_id:
                raise ValueError("rule_id required for delete_rule")
        elif a == PendingActionType.CREATE_EVENT:
            if not self.title or not self.start or not self.end:
                raise ValueError("title, start and end required for create_event")
            if self.end <= self.start:
                raise ValueError("end must be strictly after start")
        elif a == PendingActionType.UPDATE_EVENT:
            if not self.event_id:
                raise ValueError("event_id required for update_event")
            if not self.fields:
                raise ValueError("fields required for update_event")
        return self


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
    # Server-side substring filter on title + description. Reduces Claude's
    # context dramatically when the user is looking for a specific class of
    # event (e.g. "ma prochaine heure de conduite").
    query: str | None = Field(default=None, max_length=200)


class CreateEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    start: datetime
    end: datetime
    description: str | None = None
    force: bool = False
    attendees: list[str] | None = Field(default=None, max_length=MAX_ATTENDEES)
    # Fix 3: invitations are NOT sent unless this flag is explicitly set.
    # Default closed prevents accidental outbound mail from the user's
    # Google identity (anti-phishing).
    notify_attendees: bool = False
    with_meet: bool = False

    _validate_attendees_list = field_validator("attendees")(lambda cls, v: _validate_attendees(v))


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


class UpdateTodoRequest(BaseModel):
    todo_id: UUID
    title: str = Field(min_length=1, max_length=500)


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


class MarkPendingObsoleteRequest(BaseModel):
    pending_id: UUID


# --- Email request schemas ---

class SyncEmailsRequest(BaseModel):
    pass


class GetEmailRequest(BaseModel):
    email_id: UUID


class ListUnreadEmailsRequest(BaseModel):
    days: int = Field(default=2, gt=0, le=30)
    limit: int = Field(default=10, gt=0, le=30)


class RecapEmailsRequest(BaseModel):
    pass


class MarkNotifiedRequest(BaseModel):
    email_ids: list[UUID] = Field(default_factory=list, max_length=30)


# --- Response schemas ---

class APIResponse(BaseModel):
    success: bool
    data: dict | list | None = None
    error: str | None = None
