"""Tests for the recap agenda formatter (Tier 1 #2)."""

from bot.formatting import format_events_list


def test_empty_returns_header_with_default_message():
    out = format_events_list([], header="📅 Agenda du jour :")
    assert "📅 Agenda du jour :" in out
    assert "Rien" in out


def test_google_event_uses_calendar_emoji():
    events = [{
        "source": "google",
        "start": "2026-04-25T10:00:00+02:00",
        "end": "2026-04-25T11:00:00+02:00",
        "title": "Brunch",
    }]
    out = format_events_list(events, header="📅")
    assert "🗓️" in out
    assert "Brunch" in out
    assert "10h00" in out and "11h00" in out


def test_zimbra_event_uses_school_emoji():
    events = [{
        "source": "zimbra",
        "start": "2026-04-25T13:30:00+02:00",
        "end": "2026-04-25T14:30:00+02:00",
        "title": "Cours maths",
    }]
    out = format_events_list(events)
    assert "📚" in out
    assert "Cours maths" in out


def test_chronological_order_preserved():
    """Helper preserves the order it receives — the API already sorts."""
    events = [
        {"source": "zimbra", "start": "2026-04-25T08:00:00+02:00",
         "end": "2026-04-25T09:00:00+02:00", "title": "Cours A"},
        {"source": "google", "start": "2026-04-25T10:00:00+02:00",
         "end": "2026-04-25T11:00:00+02:00", "title": "Brunch"},
    ]
    out = format_events_list(events)
    assert out.index("Cours A") < out.index("Brunch")


def test_long_title_truncated():
    events = [{
        "source": "google",
        "start": "2026-04-25T10:00:00+02:00",
        "end": "2026-04-25T11:00:00+02:00",
        "title": "x" * 200,
    }]
    out = format_events_list(events)
    assert "..." in out
    # No line should exceed 80 + emoji + range overhead.
    longest = max(len(line) for line in out.split("\n"))
    assert longest < 120
