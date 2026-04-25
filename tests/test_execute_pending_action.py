"""Tests for Fix 5 — re-validation of pending payload at execution time
and removal of the unconditional `force=True` injection.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def stub_api(monkeypatch):
    """Capture every api_client.call invocation made during execution."""
    from bot import handlers

    calls: list[tuple[str, dict]] = []

    async def _call(endpoint, payload):
        calls.append((endpoint, payload))
        return {"success": True, "data": {}}

    monkeypatch.setattr(handlers.api_client, "call", _call)
    return calls


@pytest.mark.asyncio
async def test_legacy_function_params_shape_is_rejected(stub_api):
    """The pre-Fix-2 `{"function": ..., "params": {...}}` shape must no longer
    be silently accepted. It does not validate against PendingActionPayload."""
    from bot import handlers

    legacy_payload = {"function": "delete_event", "params": {"event_id": "evt-1"}}
    result = await handlers._execute_pending_action("pending-1", legacy_payload)

    # Must NOT have hit the destructive endpoint.
    assert all(c[0] != "/calendar/delete_event" for c in stub_api), stub_api
    # Must have flagged the pending as obsolete + surfaced a clear message.
    assert any(c[0] == "/pending/mark_obsolete" for c in stub_api)
    assert "corrompu" in (result or "").lower()


@pytest.mark.asyncio
async def test_unknown_action_is_rejected(stub_api):
    from bot import handlers

    result = await handlers._execute_pending_action(
        "pending-1", {"action": "drop_database"}
    )
    # Only mark_obsolete may be called.
    destructive_endpoints = [
        c[0] for c in stub_api
        if not c[0].startswith("/pending/")
    ]
    assert destructive_endpoints == [], destructive_endpoints
    assert "corrompu" in (result or "").lower()


@pytest.mark.asyncio
async def test_create_event_does_not_auto_inject_force_true(stub_api):
    """If the validated payload has force=False (or absent), the bot must NOT
    silently rewrite it to True before hitting the API."""
    from bot import handlers

    payload = {
        "action": "create_event",
        "title": "Lunch",
        "start": "2026-04-26T12:00:00+02:00",
        "end": "2026-04-26T13:00:00+02:00",
    }
    await handlers._execute_pending_action("pending-1", payload)

    create_calls = [c for c in stub_api if c[0] == "/calendar/create_event"]
    assert len(create_calls) == 1
    assert create_calls[0][1]["force"] is False
    # Default closed for invitations as well.
    assert create_calls[0][1]["notify_attendees"] is False


@pytest.mark.asyncio
async def test_create_event_forwards_force_true_when_payload_says_so(stub_api):
    """When Claude explicitly opts into force=True (typically because the
    pending was created after a detected conflict), the handler honors it."""
    from bot import handlers

    payload = {
        "action": "create_event",
        "title": "Lunch",
        "start": "2026-04-26T12:00:00+02:00",
        "end": "2026-04-26T13:00:00+02:00",
        "force": True,
    }
    await handlers._execute_pending_action("pending-1", payload)

    create_calls = [c for c in stub_api if c[0] == "/calendar/create_event"]
    assert create_calls[0][1]["force"] is True


@pytest.mark.asyncio
async def test_create_event_forwards_notify_attendees_when_payload_says_so(stub_api):
    from bot import handlers

    payload = {
        "action": "create_event",
        "title": "Sync",
        "start": "2026-04-26T12:00:00+02:00",
        "end": "2026-04-26T13:00:00+02:00",
        "attendees": ["alice@example.com"],
        "notify_attendees": True,
        "force": True,
    }
    await handlers._execute_pending_action("pending-1", payload)

    create_calls = [c for c in stub_api if c[0] == "/calendar/create_event"]
    assert create_calls[0][1]["notify_attendees"] is True
    assert create_calls[0][1]["attendees"] == ["alice@example.com"]


@pytest.mark.asyncio
async def test_canonical_delete_event_passes_through(stub_api):
    """Sanity: a well-formed canonical payload still executes."""
    from bot import handlers

    await handlers._execute_pending_action(
        "pending-1", {"action": "delete_event", "event_id": "evt-42"}
    )
    delete_calls = [c for c in stub_api if c[0] == "/calendar/delete_event"]
    assert len(delete_calls) == 1
    assert delete_calls[0][1] == {"event_id": "evt-42"}
