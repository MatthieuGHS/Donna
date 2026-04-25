"""Tests for the freeBusy 400 Bad Request bug.

Google freeBusy rejects RFC 3339 strings without an explicit timezone
offset with HTTP 400. Whenever Pydantic parses a Claude-supplied datetime
without offset (`"2026-04-26T13:00:00"`), the value lands naive at the
service boundary. The fix localizes naive datetimes to the user's local
timezone before anything reaches Google.
"""

from __future__ import annotations

import re
from datetime import datetime
from unittest.mock import MagicMock

import pytest


_ISO_WITH_TZ = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+\-]\d{2}:\d{2})$"
)


def _fake_calendar_service():
    """Build a `service` mock recording the freeBusy body it receives."""
    captured = {}

    fake_service = MagicMock()

    def _query(body):
        captured["body"] = body
        ret = MagicMock()
        ret.execute.return_value = {
            "calendars": {"test@example.com": {"busy": []}}
        }
        return ret

    fake_service.freebusy.return_value.query.side_effect = _query
    return fake_service, captured


def test_check_availability_sends_iso8601_with_tz_to_freebusy(monkeypatch):
    """Naive datetimes from Pydantic must be localized before freeBusy.

    This is the regression for the 400 Bad Request seen in prod.
    """
    from api.services import calendar_service

    fake_service, captured = _fake_calendar_service()
    monkeypatch.setattr(calendar_service, "_get_calendar_service", lambda: fake_service)
    monkeypatch.setattr(calendar_service.settings, "google_calendar_id", "test@example.com")

    naive_start = datetime(2026, 4, 26, 13, 0, 0)
    naive_end = datetime(2026, 4, 26, 14, 0, 0)

    calendar_service.check_availability(naive_start, naive_end)

    body = captured["body"]
    assert _ISO_WITH_TZ.match(body["timeMin"]), body["timeMin"]
    assert _ISO_WITH_TZ.match(body["timeMax"]), body["timeMax"]
    # Europe/Paris in late April is CEST = +02:00.
    assert body["timeMin"].endswith("+02:00") or body["timeMin"].endswith("+01:00"), body["timeMin"]
    assert body["items"] == [{"id": "test@example.com"}]


def test_check_availability_preserves_aware_offset(monkeypatch):
    """Already-aware datetimes pass through without being re-localized."""
    from api.services import calendar_service
    import pytz

    fake_service, captured = _fake_calendar_service()
    monkeypatch.setattr(calendar_service, "_get_calendar_service", lambda: fake_service)
    monkeypatch.setattr(calendar_service.settings, "google_calendar_id", "test@example.com")

    utc = pytz.UTC
    aware_start = utc.localize(datetime(2026, 4, 26, 11, 0, 0))
    aware_end = utc.localize(datetime(2026, 4, 26, 12, 0, 0))

    calendar_service.check_availability(aware_start, aware_end)

    body = captured["body"]
    assert body["timeMin"].endswith("+00:00") or body["timeMin"].endswith("Z"), body["timeMin"]


def test_list_overlapping_events_handles_naive_input(monkeypatch):
    """Regression: comparing naive vs aware datetimes raises TypeError.

    `list_overlapping_events` was localizing fetched events but not its own
    inputs; passing a naive `start` from Pydantic triggered the crash even
    when freeBusy itself wasn't called.
    """
    from api.services import calendar_service

    monkeypatch.setattr(
        calendar_service,
        "list_events",
        lambda *_a, **_kw: [
            {
                "id": "e1",
                "title": "Cours maths",
                "start": "2026-04-26T13:30:00+02:00",
                "end": "2026-04-26T14:30:00+02:00",
            }
        ],
    )

    naive_start = datetime(2026, 4, 26, 13, 0, 0)
    naive_end = datetime(2026, 4, 26, 14, 0, 0)

    overlapping = calendar_service.list_overlapping_events(naive_start, naive_end)
    assert len(overlapping) == 1
    assert overlapping[0]["title"] == "Cours maths"


@pytest.fixture
def fake_supabase_for_pending(monkeypatch):
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


def test_pending_create_event_falls_back_when_freebusy_fails(
    fake_supabase_for_pending, monkeypatch
):
    """If Google freeBusy is down, pending creation must still succeed.

    The display label tells the user the availability check could not run,
    rather than silently implying the slot is free.
    """
    from googleapiclient.errors import HttpError

    from api.services import pending_service

    def _boom(*_a, **_kw):
        raise HttpError(
            resp=type("R", (), {"status": 400, "reason": "Bad Request"})(),
            content=b"freeBusy refused",
        )

    monkeypatch.setattr(pending_service.calendar_service, "list_overlapping_events", _boom)
    monkeypatch.setattr(pending_service.zimbra_service, "is_configured", lambda: False)

    pending = pending_service.create_pending(
        action_payload={
            "action": "create_event",
            "title": "Test phase A",
            "start": "2026-04-26T13:00:00+02:00",
            "end": "2026-04-26T14:00:00+02:00",
        },
        description="…",
    )

    # The pending must still be created and confirmable.
    assert pending["executable"] is True
    assert "non vérifié" in pending["display_description"].lower()
    # Sanity: the title is still surfaced from the validated payload.
    assert "Test phase A" in pending["display_description"]
