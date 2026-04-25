"""Tests for the Fix 3 tool-loop gating: update_event and create_event-with-
attendees must round-trip through create_pending instead of executing directly.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class _ToolBlock:
    type = "tool_use"

    def __init__(self, name: str, tool_input: dict, block_id: str = "tu-1"):
        self.name = name
        self.input = tool_input
        self.id = block_id


def _resp(blocks):
    return SimpleNamespace(stop_reason="tool_use", content=blocks)


def _end():
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="ok")],
    )


class _Anthropic:
    """Returns scripted responses, captures messages for inspection."""

    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls = []
        outer = self

        class _M:
            def create(self_inner, **kwargs):  # noqa: N805
                outer.calls.append(kwargs.get("messages"))
                return outer._scripted.pop(0) if outer._scripted else _end()

        self.messages = _M()


@pytest.fixture
def stub_api(monkeypatch):
    """Track all api_client.call invocations so we can assert what hit the API."""
    from bot import claude_client

    calls: list[tuple[str, dict]] = []

    async def _call(endpoint, payload):
        calls.append((endpoint, payload))
        return {"success": True, "data": {}}

    monkeypatch.setattr(claude_client.api_client, "call", _call)
    return calls


@pytest.mark.asyncio
async def test_direct_update_event_is_intercepted(stub_api, monkeypatch):
    """Claude calling update_event directly must NOT hit /calendar/update_event."""
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("update_event", {"event_id": "evt-1", "fields": {"title": "hijack"}})]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    text, _, _ = await claude_client.process_message("ping", "2026-04-25 10:00")

    endpoints = [c[0] for c in stub_api]
    assert "/calendar/update_event" not in endpoints, (
        f"update_event should be intercepted, but it hit the API: {endpoints}"
    )

    # The second turn (after the rejection tool_result) ends normally.
    assert text == "ok"

    # The rejection content must steer Claude toward the pending flow.
    second_turn_messages = fake.calls[1]
    tool_results = second_turn_messages[-1]["content"]
    assert any(
        "pending" in tr.get("content", "").lower() for tr in tool_results
    ), tool_results


@pytest.mark.asyncio
async def test_create_event_with_attendees_is_intercepted(stub_api, monkeypatch):
    """create_event with attendees must NOT hit Google directly."""
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("create_event", {
            "title": "phish",
            "start": "2026-04-26T10:00:00+02:00",
            "end": "2026-04-26T11:00:00+02:00",
            "attendees": ["target@victim.tld"],
        })]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    await claude_client.process_message("ping", "2026-04-25 10:00")

    endpoints = [c[0] for c in stub_api]
    assert "/calendar/create_event" not in endpoints, (
        f"create_event with attendees should be intercepted: {endpoints}"
    )


@pytest.mark.asyncio
async def test_create_event_without_attendees_passes_through(stub_api, monkeypatch):
    """Direct create_event WITHOUT attendees stays the fast path (no pending)."""
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("create_event", {
            "title": "Brunch",
            "start": "2026-04-26T10:00:00+02:00",
            "end": "2026-04-26T11:00:00+02:00",
        })]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    await claude_client.process_message("ping", "2026-04-25 10:00")

    endpoints = [c[0] for c in stub_api]
    assert "/calendar/create_event" in endpoints, (
        f"create_event without attendees should pass through: {endpoints}"
    )
