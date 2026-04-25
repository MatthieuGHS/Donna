"""Bonus — server-side `query` filter on /calendar/list_events, plus the
companion description truncation (Tier 3 #9). Together they make
"ma prochaine heure de conduite" return ~1 event instead of 30."""

from __future__ import annotations

from datetime import date

import pytest

from api.services import calendar_service, zimbra_service


def _make_google_events_stub(events):
    """Build a fake Google service whose events().list().execute() returns
    `{items: [...]}` with the given raw events. Each event needs at least
    `id`, `summary`, `start`, `end` to parse cleanly."""
    from unittest.mock import MagicMock

    service = MagicMock()
    raw = []
    for e in events:
        raw.append({
            "id": e["id"],
            "summary": e.get("title", ""),
            "start": {"dateTime": e["start"]},
            "end": {"dateTime": e["end"]},
            "description": e.get("description", ""),
        })
    service.events.return_value.list.return_value.execute.return_value = {"items": raw}
    return service


# ---------- query filter ----------


def test_query_matches_in_google_title(monkeypatch):
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "Heure de conduite",
             "start": "2026-04-26T14:00:00+02:00", "end": "2026-04-26T15:00:00+02:00"},
            {"id": "g2", "title": "Brunch",
             "start": "2026-04-26T11:00:00+02:00", "end": "2026-04-26T12:00:00+02:00"},
        ]),
    )

    events = calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="conduite")
    assert len(events) == 1
    assert events[0]["id"] == "g1"


def test_query_matches_in_description(monkeypatch):
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "RDV",
             "start": "2026-04-26T14:00:00+02:00", "end": "2026-04-26T15:00:00+02:00",
             "description": "Médecin généraliste, dr. Durand"},
            {"id": "g2", "title": "Brunch",
             "start": "2026-04-26T11:00:00+02:00", "end": "2026-04-26T12:00:00+02:00"},
        ]),
    )

    events = calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="médecin")
    assert len(events) == 1
    assert events[0]["id"] == "g1"


def test_query_is_case_insensitive(monkeypatch):
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "TD Modélisation",
             "start": "2026-04-26T14:00:00+02:00", "end": "2026-04-26T15:00:00+02:00"},
        ]),
    )
    assert len(calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="td")) == 1
    assert len(calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="MODÉLISATION")) == 1


def test_query_no_match_returns_empty(monkeypatch):
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "Brunch",
             "start": "2026-04-26T11:00:00+02:00", "end": "2026-04-26T12:00:00+02:00"},
        ]),
    )

    events = calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="conduite")
    assert events == []


def test_no_query_preserves_default_behavior(monkeypatch):
    """Calling without `query` (or with empty string) must return everything
    in the date range — current contract preserved for the recap path."""
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "A", "start": "2026-04-26T11:00:00+02:00", "end": "2026-04-26T12:00:00+02:00"},
            {"id": "g2", "title": "B", "start": "2026-04-26T13:00:00+02:00", "end": "2026-04-26T14:00:00+02:00"},
        ]),
    )
    assert len(calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26))) == 2
    assert len(calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="")) == 2
    assert len(calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="   ")) == 2


def test_query_filters_zimbra_too(monkeypatch):
    """Zimbra source must honor the same query filter — the bonus is
    cross-source by design."""
    monkeypatch.setattr(
        zimbra_service,
        "_get_cached_events",
        lambda: [
            {"id": "z1", "title": "TD Réseaux",
             "start": "2026-04-26T08:00:00+02:00", "end": "2026-04-26T10:00:00+02:00",
             "description": "", "source": "zimbra"},
            {"id": "z2", "title": "CM Droit",
             "start": "2026-04-26T10:00:00+02:00", "end": "2026-04-26T12:00:00+02:00",
             "description": "", "source": "zimbra"},
        ],
    )

    events = zimbra_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="droit")
    assert len(events) == 1
    assert events[0]["id"] == "z2"


# ---------- description truncation (#9) ----------


def test_description_truncated_to_200_chars(monkeypatch):
    long_desc = "x" * 500
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "Notes",
             "start": "2026-04-26T11:00:00+02:00", "end": "2026-04-26T12:00:00+02:00",
             "description": long_desc},
        ]),
    )

    events = calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26))
    assert len(events) == 1
    assert len(events[0]["description"]) == 200
    assert events[0]["description"].endswith("...")


def test_query_filters_on_full_description_before_truncation(monkeypatch):
    """A hit beyond char 200 must NOT be lost: filter runs before truncate."""
    long_desc = "filler " * 30 + "MEDECIN"  # ~210 chars, hit at the very end
    monkeypatch.setattr(
        calendar_service,
        "_get_calendar_service",
        lambda: _make_google_events_stub([
            {"id": "g1", "title": "RDV",
             "start": "2026-04-26T11:00:00+02:00", "end": "2026-04-26T12:00:00+02:00",
             "description": long_desc},
        ]),
    )

    events = calendar_service.list_events(date(2026, 4, 26), date(2026, 4, 26), query="medecin")
    assert len(events) == 1
    # The match was found pre-truncation, but the description returned to
    # Claude is still capped at 200 chars.
    assert len(events[0]["description"]) == 200


def test_zimbra_description_truncation_does_not_mutate_cache(monkeypatch):
    """Defensive: the cache returns the same dict reference each time, so
    truncating in place would compound across calls. Verify the cache row
    is not mutated."""
    cache_row = {
        "id": "z1", "title": "Notes",
        "start": "2026-04-26T08:00:00+02:00", "end": "2026-04-26T10:00:00+02:00",
        "description": "x" * 500, "source": "zimbra",
    }
    monkeypatch.setattr(zimbra_service, "_get_cached_events", lambda: [cache_row])

    events_a = zimbra_service.list_events(date(2026, 4, 26), date(2026, 4, 26))
    events_b = zimbra_service.list_events(date(2026, 4, 26), date(2026, 4, 26))

    # Cache row description still 500 chars.
    assert len(cache_row["description"]) == 500
    # Returned events are truncated.
    assert len(events_a[0]["description"]) == 200
    assert len(events_b[0]["description"]) == 200
