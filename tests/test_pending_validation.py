"""Tests for the pending-action payload binding (Fix 2).

The point of these tests: a compromised model cannot smuggle arbitrary
actions through `create_pending`, and the user-visible label is generated
server-side from the *real* underlying object — not from Claude's free text.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from db.models import PendingActionPayload, PendingActionType


# ---------- payload validation ----------


def test_unknown_action_rejected():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({"action": "drop_database", "what": "all"})


def test_delete_event_requires_event_id():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({"action": "delete_event"})


def test_delete_todo_requires_todo_id():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({"action": "delete_todo"})


def test_delete_rule_requires_rule_id():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({"action": "delete_rule"})


def test_create_event_requires_title_start_end():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({
            "action": "create_event",
            "title": "x",
            # missing start/end
        })


def test_create_event_end_must_be_after_start():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({
            "action": "create_event",
            "title": "x",
            "start": "2026-04-25T10:00:00+02:00",
            "end": "2026-04-25T10:00:00+02:00",
        })


def test_update_event_requires_fields():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({
            "action": "update_event",
            "event_id": "abc",
        })


def test_valid_delete_event():
    p = PendingActionPayload.model_validate({"action": "delete_event", "event_id": "abc"})
    assert p.action == PendingActionType.DELETE_EVENT
    assert p.event_id == "abc"


def test_valid_create_event():
    p = PendingActionPayload.model_validate({
        "action": "create_event",
        "title": "Lunch",
        "start": "2026-04-25T12:00:00+02:00",
        "end": "2026-04-25T13:00:00+02:00",
    })
    assert p.action == PendingActionType.CREATE_EVENT
    assert p.title == "Lunch"


# ---------- display description generation ----------


@pytest.fixture
def fake_supabase(monkeypatch):
    """Stub `_get_client()` in pending_service so no real network call happens."""
    from api.services import pending_service

    captured: dict = {"insert": None, "update": None}

    class _Insert:
        def __init__(self, table: "_Table", payload: dict) -> None:
            self._table = table
            self._payload = payload

        def execute(self):
            captured["insert"] = self._payload
            row = {
                "id": "pending-uuid-fake",
                **self._payload,
            }
            return type("R", (), {"data": [row]})()

    class _Table:
        def __init__(self, name: str) -> None:
            self._name = name

        def insert(self, payload: dict) -> _Insert:
            return _Insert(self, payload)

    class _Client:
        def table(self, name: str) -> _Table:
            return _Table(name)

    monkeypatch.setattr(pending_service, "_get_client", lambda: _Client())
    return captured


def test_create_pending_delete_event_uses_real_title(fake_supabase, monkeypatch):
    """When Claude creates a pending to delete an event, the display string
    must come from Google's actual title — not from any free-text Claude sent."""
    from api.services import pending_service

    fake_event = {
        "id": "evt-1",
        "title": "RDV dentiste",
        "start": "2026-04-26T14:00:00+02:00",
        "end": "2026-04-26T14:30:00+02:00",
    }
    monkeypatch.setattr(pending_service.calendar_service, "get_event", lambda _id: fake_event)

    pending = pending_service.create_pending(
        action_payload={"action": "delete_event", "event_id": "evt-1"},
        description="Confirmer le RDV dentiste demain à 14h",  # would-be spoof
    )

    # The legacy `description` is preserved (audit) but display_description
    # is what the bot will surface to the user.
    assert pending["description"] == "Confirmer le RDV dentiste demain à 14h"
    assert "RDV dentiste" in pending["display_description"]
    assert pending["display_description"].startswith("Supprimer 'RDV dentiste'")
    assert pending["executable"] is True


def test_create_pending_obsolete_when_event_missing(fake_supabase, monkeypatch):
    """Event already gone at pending-create time → executable=false."""
    from api.services import pending_service

    monkeypatch.setattr(pending_service.calendar_service, "get_event", lambda _id: None)

    pending = pending_service.create_pending(
        action_payload={"action": "delete_event", "event_id": "ghost-event"},
        description="…",
    )

    assert pending["executable"] is False
    assert "obsolète" in pending["display_description"].lower()


def test_create_pending_create_event_surfaces_conflicts(fake_supabase, monkeypatch):
    """A create_event pending whose slot overlaps an existing event must
    surface that overlap in the user-visible label."""
    from api.services import pending_service

    monkeypatch.setattr(
        pending_service.calendar_service,
        "list_overlapping_events",
        lambda *_a, **_kw: [{"title": "Cours maths", "start": "2026-04-26T10:00:00+02:00",
                              "end": "2026-04-26T11:00:00+02:00"}],
    )
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: False)

    pending = pending_service.create_pending(
        action_payload={
            "action": "create_event",
            "title": "Brunch",
            "start": "2026-04-26T10:30:00+02:00",
            "end": "2026-04-26T11:30:00+02:00",
        },
        description="…",
    )

    assert "chevauche" in pending["display_description"].lower()
    assert "Cours maths" in pending["display_description"]
    # Conflicts do NOT make the pending non-executable: the user can confirm
    # in full knowledge of the overlap.
    assert pending["executable"] is True


def test_create_pending_rejects_unknown_action(fake_supabase):
    from api.services import pending_service

    with pytest.raises(ValueError):
        pending_service.create_pending(
            action_payload={"action": "drop_database"},
            description="…",
        )


# ---------- resolve_pending blocks confirm on obsolete ----------


def test_resolve_pending_blocks_confirm_on_obsolete(monkeypatch):
    """An obsolete pending must refuse `confirm`. Cancel must still work."""
    from api.services import pending_service

    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    obsolete_row = {
        "id": "pending-1",
        "action_payload": {"action": "delete_event", "event_id": "ghost"},
        "description": "x",
        "display_description": "[Pending obsolète : event introuvable]",
        "executable": False,
        "expires_at": future,
        "status": "pending",
    }

    update_calls: list[dict] = []

    class _Q:
        def __init__(self, rows): self._rows = rows
        def select(self, *_a, **_kw): return self
        def eq(self, *_a, **_kw): return self
        def lt(self, *_a, **_kw): return self
        def execute(self):
            return type("R", (), {"data": self._rows})()
        def update(self, payload):
            update_calls.append(payload)
            return self

    class _Client:
        def table(self, _name): return _Q([obsolete_row])

    monkeypatch.setattr(pending_service, "_get_client", lambda: _Client())

    with pytest.raises(ValueError, match="obsolete"):
        pending_service.resolve_pending(UUID("00000000-0000-0000-0000-000000000001"), "confirm")

    # Cancel goes through (sets status=cancelled).
    res = pending_service.resolve_pending(UUID("00000000-0000-0000-0000-000000000001"), "cancel")
    assert res["choice"] == "cancel"
    assert any(call.get("status") == "cancelled" for call in update_calls)
