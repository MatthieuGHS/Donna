"""Tests for attendees hardening (Fix 3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from db.models import (
    MAX_ATTENDEES,
    CreateEventRequest,
    PendingActionPayload,
)


def _good_event(**overrides):
    base = {
        "title": "x",
        "start": "2026-04-25T10:00:00+02:00",
        "end": "2026-04-25T11:00:00+02:00",
    }
    base.update(overrides)
    return base


def test_create_event_request_caps_attendees_at_max():
    too_many = [f"u{i}@example.com" for i in range(MAX_ATTENDEES + 1)]
    with pytest.raises(ValidationError):
        CreateEventRequest(**_good_event(attendees=too_many))


def test_create_event_request_rejects_invalid_email():
    with pytest.raises(ValidationError):
        CreateEventRequest(**_good_event(attendees=["not an email"]))


def test_create_event_request_rejects_control_chars():
    with pytest.raises(ValidationError):
        CreateEventRequest(**_good_event(attendees=["x@y.z\nBcc: someone@evil.tld"]))


def test_create_event_request_lowercases_and_strips_email():
    req = CreateEventRequest(**_good_event(attendees=["  Foo@Bar.COM  "]))
    assert req.attendees == ["foo@bar.com"]


def test_create_event_request_default_notify_is_false():
    """Defense in depth: notify_attendees default closed (no outbound mail
    unless explicitly opted in)."""
    req = CreateEventRequest(**_good_event(attendees=["a@b.com"]))
    assert req.notify_attendees is False


def test_pending_payload_caps_attendees():
    too_many = [f"u{i}@example.com" for i in range(MAX_ATTENDEES + 1)]
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({
            "action": "create_event",
            "title": "x",
            "start": "2026-04-25T10:00:00+02:00",
            "end": "2026-04-25T11:00:00+02:00",
            "attendees": too_many,
        })


def test_pending_payload_rejects_invalid_attendee_email():
    with pytest.raises(ValidationError):
        PendingActionPayload.model_validate({
            "action": "create_event",
            "title": "x",
            "start": "2026-04-25T10:00:00+02:00",
            "end": "2026-04-25T11:00:00+02:00",
            "attendees": ["not-an-email"],
        })
