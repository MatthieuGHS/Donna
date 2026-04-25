"""Tests for the server-side `force=True` override on detected conflicts.

A security boundary cannot live in the system prompt. Claude has been
observed creating create_event pendings with `force=false` despite the
display_description explicitly mentioning a conflict — confirmation then
fails with "Time slot has conflicts. Use force=true to override."

The fix: pending_service.create_pending detects the conflict itself and
flips `force=True` in the canonical payload regardless of what the model
sent. The user still sees the conflict in display_description and is
confirming knowingly.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def fake_supabase(monkeypatch):
    from api.services import pending_service

    captured: dict = {}

    class _Insert:
        def __init__(self, payload): self._payload = payload
        def execute(self):
            captured["insert"] = self._payload
            return type("R", (), {"data": [{"id": "p-1", **self._payload}]})()

    class _Table:
        def insert(self, payload): return _Insert(payload)

    class _Client:
        def table(self, _name): return _Table()

    monkeypatch.setattr(pending_service, "_get_client", lambda: _Client())
    return captured


def _payload(force: bool = False, **overrides):
    base = {
        "action": "create_event",
        "title": "Test",
        "start": "2026-04-26T13:30:00+02:00",
        "end": "2026-04-26T15:00:00+02:00",
        "force": force,
    }
    base.update(overrides)
    return base


def test_no_conflict_keeps_force_false(fake_supabase, monkeypatch):
    """Sanity: when no conflict is detected, the model's force value passes
    through untouched (False here, the safer default)."""
    from api.services import pending_service

    monkeypatch.setattr(
        pending_service.calendar_service, "list_overlapping_events", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: False)

    pending = pending_service.create_pending(_payload(force=False), "…")

    stored = pending["action_payload"]
    # `force=False` is dropped by exclude_none / model_dump because it is the
    # falsey default — equivalent to "absent". What matters is it's NOT True.
    assert stored.get("force", False) is False
    assert "chevauche" not in pending["display_description"].lower()


def test_google_conflict_overrides_force_to_true(fake_supabase, monkeypatch):
    """The bug: Claude sent force=false, real Google conflict exists, server
    must override to True so confirmation does not fail at execution time."""
    from api.services import pending_service

    monkeypatch.setattr(
        pending_service.calendar_service,
        "list_overlapping_events",
        lambda *_a, **_kw: [{"title": "test phase a", "start": "x", "end": "y"}],
    )
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: False)

    pending = pending_service.create_pending(_payload(force=False), "…")

    stored = pending["action_payload"]
    assert stored.get("force") is True, (
        f"force should have been overridden to True, got {stored.get('force')!r}"
    )
    # User still sees the conflict on the button so consent is informed.
    assert "test phase a" in pending["display_description"]
    assert "chevauche" in pending["display_description"].lower()


def test_zimbra_conflict_overrides_force_to_true(fake_supabase, monkeypatch):
    """Same override applies when only Zimbra surfaces the overlap."""
    from api.services import pending_service

    monkeypatch.setattr(
        pending_service.calendar_service, "list_overlapping_events", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: True)
    monkeypatch.setattr(
        pending_service.zimbra_service,
        "check_availability",
        lambda *_a, **_kw: [{"title": "Cours maths", "start": "x", "end": "y"}],
    )

    pending = pending_service.create_pending(_payload(force=False), "…")

    stored = pending["action_payload"]
    assert stored.get("force") is True
    assert "Cours maths" in pending["display_description"]


def test_check_failed_does_not_override_force(fake_supabase, monkeypatch):
    """If the conflict check itself failed (Google freeBusy / Zimbra outage),
    the server cannot honestly claim a conflict was detected. `force` must
    keep its model-supplied value; Google's response at confirm time decides."""
    from googleapiclient.errors import HttpError
    from api.services import pending_service

    def _boom(*_a, **_kw):
        raise HttpError(
            resp=type("R", (), {"status": 500, "reason": "Internal"})(),
            content=b"boom",
        )

    monkeypatch.setattr(pending_service.calendar_service, "list_overlapping_events", _boom)
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: False)

    pending = pending_service.create_pending(_payload(force=False), "…")

    stored = pending["action_payload"]
    # Original False preserved (or absent).
    assert stored.get("force", False) is False
    assert "non vérifié" in pending["display_description"].lower()


def test_explicit_force_true_is_preserved_when_no_conflict(fake_supabase, monkeypatch):
    """If Claude already opted into force=True (e.g. recovered from a previous
    failure), the server should not silently demote it back to False."""
    from api.services import pending_service

    monkeypatch.setattr(
        pending_service.calendar_service, "list_overlapping_events", lambda *_a, **_kw: []
    )
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: False)

    pending = pending_service.create_pending(_payload(force=True), "…")

    stored = pending["action_payload"]
    assert stored.get("force") is True
