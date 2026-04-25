"""Tests for the regression #1 fix — direct create_event with a conflict
must surface a structured error code, and the bot's tool loop must steer
the model toward create_pending instead of letting it improvise text.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


# ---------- API route side ----------


@pytest.fixture
def fastapi_client(monkeypatch):
    """Build a FastAPI test client with calendar/zimbra services stubbed.

    `verify_api_key` is replaced via `app.dependency_overrides` (the only
    sound way — FastAPI captures dependencies at routing time, so patching
    the module attribute after the fact doesn't reach the route).
    """
    from fastapi.testclient import TestClient

    from api import main
    from api.auth import verify_api_key
    from api.services import calendar_service, zimbra_service

    main.app.dependency_overrides[verify_api_key] = lambda: "test-key"

    monkeypatch.setattr(
        calendar_service,
        "check_availability",
        lambda *_a, **_kw: {
            "available": False,
            "conflicts": [
                {
                    "start": "2026-04-26T15:00:00+02:00",
                    "end": "2026-04-26T16:00:00+02:00",
                    "title": "test",
                }
            ],
        },
    )
    monkeypatch.setattr(zimbra_service, "is_configured", lambda: False)

    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(verify_api_key, None)


def test_create_event_with_conflict_returns_structured_error(fastapi_client):
    response = fastapi_client.post(
        "/calendar/create_event",
        json={
            "title": "test2",
            "start": "2026-04-26T15:30:00+02:00",
            "end": "2026-04-26T16:30:00+02:00",
            "force": False,
        },
        headers={"X-API-Key": "test-key"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "conflict_requires_pending"
    titles = (body.get("data") or {}).get("conflicting_titles") or []
    assert "test" in titles


# ---------- bot tool loop side ----------


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
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls: list[dict] = []
        outer = self

        class _M:
            def create(self_inner, **kwargs):  # noqa: N805
                outer.calls.append(kwargs)
                return outer._scripted.pop(0) if outer._scripted else _end()

        self.messages = _M()


@pytest.mark.asyncio
async def test_tool_loop_injects_pending_directive_on_conflict(monkeypatch):
    """When the API returns conflict_requires_pending, the tool_result fed
    back to the model must contain an explicit directive mentioning
    `create_pending` — not a raw "Time slot has conflicts" string."""
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("create_event", {
            "title": "test2",
            "start": "2026-04-26T15:30:00+02:00",
            "end": "2026-04-26T16:30:00+02:00",
        })]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    async def _api_call(endpoint, payload):
        if endpoint == "/calendar/create_event":
            return {
                "success": False,
                "error": "conflict_requires_pending",
                "data": {"conflicting_titles": ["test"]},
            }
        return {"success": True, "data": {}}

    monkeypatch.setattr(claude_client.api_client, "call", _api_call)

    await claude_client.process_message("Crée test2 demain 15h30-16h30", "2026-04-25 18:00")

    # Iteration 2 carries the tool_result. Pull it out and inspect.
    second_call = fake.calls[1]
    last_user_turn = second_call["messages"][-1]
    assert last_user_turn["role"] == "user"
    tr_content = last_user_turn["content"][0]["content"]

    # Must NOT be the bare "Time slot has conflicts" string anymore.
    assert "Time slot has conflicts" not in tr_content
    # Must steer to create_pending and mention the conflicting title so the
    # model has all it needs without re-querying.
    assert "create_pending" in tr_content
    assert "'test'" in tr_content
    assert "conflict_requires_pending" in tr_content


def test_system_prompt_documents_agenda_format():
    """Régression 2 — keep the agenda format directive in SYSTEM_PROMPT so
    Claude formats interactive agenda answers as one-day-per-block."""
    from bot import claude_client

    prompt = claude_client.SYSTEM_PROMPT
    assert "Format agenda" in prompt
    # Must mention all the layout signals: bold day header, per-line emoji,
    # time range, source distinction.
    assert "**Jour" in prompt
    assert "📚" in prompt and "🗓️" in prompt
    assert "HHhMM" in prompt
