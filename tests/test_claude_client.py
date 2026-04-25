"""Tests for bot.claude_client — tool-use loop hardening (Fix 1)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Iterable

import pytest


class _FakeToolBlock:
    """Mimic the shape of an anthropic ToolUseBlock."""

    type = "tool_use"

    def __init__(self, name: str, tool_input: dict, block_id: str = "tool-1") -> None:
        self.name = name
        self.input = tool_input
        self.id = block_id


def _looping_response() -> SimpleNamespace:
    """A response that always asks for one more tool call (never end_turn)."""
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[_FakeToolBlock("list_pending", {})],
    )


def _end_turn_response(text: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


class _FakeAnthropic:
    """Drop-in replacement for `Anthropic(...)` returning scripted responses."""

    def __init__(self, responses: Iterable[SimpleNamespace], **_kwargs):
        self._responses = list(responses)
        self.calls = 0

        # Provide a `messages.create` callable matching the SDK shape
        outer = self

        class _Messages:
            def create(self_inner, **kwargs):  # noqa: N805
                outer.calls += 1
                if outer._responses:
                    return outer._responses.pop(0)
                # Default: keep looping
                return _looping_response()

        self.messages = _Messages()


@pytest.mark.asyncio
async def test_tool_loop_caps_iterations(monkeypatch):
    """When Claude never returns end_turn, the loop must bail out cleanly
    after MAX_TOOL_ITERATIONS calls and surface a user-facing message."""
    from bot import claude_client

    fake = _FakeAnthropic([_looping_response() for _ in range(20)])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    # Stub tool dispatch so we never make HTTP calls.
    async def _fake_call(endpoint, payload):  # noqa: ARG001
        return {"success": True, "data": {}}

    monkeypatch.setattr(claude_client.api_client, "call", _fake_call)

    text, pending, displays = await claude_client.process_message(
        "ping", current_date="2026-04-25 10:00"
    )

    assert fake.calls == claude_client.MAX_TOOL_ITERATIONS, (
        f"expected exactly {claude_client.MAX_TOOL_ITERATIONS} Anthropic calls, "
        f"got {fake.calls}"
    )
    assert "Trop d'appels d'outils" in text
    assert pending == []
    assert displays == []


@pytest.mark.asyncio
async def test_tool_loop_returns_normally_when_end_turn(monkeypatch):
    """The cap must not affect normal flows: a single end_turn returns immediately."""
    from bot import claude_client

    fake = _FakeAnthropic([_end_turn_response("hello")])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    text, pending, displays = await claude_client.process_message(
        "ping", current_date="2026-04-25 10:00"
    )

    assert text == "hello"
    assert fake.calls == 1
    assert pending == []
    assert displays == []
