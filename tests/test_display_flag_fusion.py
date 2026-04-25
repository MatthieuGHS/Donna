"""Tier 3 #8 — fusion of list_*/display_* tools behind a `display: bool`
flag. The two old display_unread_emails / display_todos tools no longer
exist standalone; their behavior is reachable via list_*(display=true).
"""

from __future__ import annotations

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
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls: list[dict] = []
        outer = self

        class _M:
            def create(self_inner, **kwargs):  # noqa: N805
                outer.calls.append(kwargs)
                return outer._scripted.pop(0) if outer._scripted else _end()

        self.messages = _M()


def _stub_api(monkeypatch, responses: dict):
    from bot import claude_client

    async def _call(endpoint, payload):
        return responses.get(endpoint, {"success": True, "data": {}})

    monkeypatch.setattr(claude_client.api_client, "call", _call)


def test_old_display_tools_are_no_longer_in_tools_array():
    from bot import claude_client

    names = {t["name"] for t in claude_client.TOOLS}
    assert "display_unread_emails" not in names
    assert "display_todos" not in names
    # display_email stays standalone (no list counterpart, security boundary).
    assert "display_email" in names
    assert "list_unread_emails" in names
    assert "list_todos" in names


@pytest.mark.asyncio
async def test_list_unread_emails_with_display_flag_routes_to_display_path(monkeypatch):
    """display=true must trigger the bypass-Claude rendering path: a Telegram
    message is queued and Claude only sees the {shown:true} placeholder."""
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("list_unread_emails", {"days": 7, "limit": 5, "display": True})]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)
    _stub_api(monkeypatch, {
        "/emails/list_unread": {
            "success": True,
            "data": {"emails": [
                {"id": "1", "sender_name": "Alice", "subject": "hello", "received_at": "2026-04-25T10:00:00+00:00"},
            ]},
        },
    })

    text, _, displays = await claude_client.process_message("mes mails", "2026-04-25 10:00")

    # The user receives a rendered message that bypassed Claude's context.
    assert len(displays) == 1
    assert "Alice" in displays[0]
    # The tool_result fed back to Claude is the "shown" placeholder, NOT the
    # actual email metadata.
    last_user_turn = fake.calls[1]["messages"][-1]
    tr_content = last_user_turn["content"][0]["content"]
    assert '"shown": true' in tr_content
    assert "Alice" not in tr_content


@pytest.mark.asyncio
async def test_list_unread_emails_without_display_flag_returns_to_claude(monkeypatch):
    """display omitted (or false) keeps the legacy behavior: Claude sees the
    full metadata response (so it can identify a specific mail by sender)."""
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("list_unread_emails", {"days": 7, "limit": 5})]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)
    _stub_api(monkeypatch, {
        "/emails/list_unread": {
            "success": True,
            "data": {"emails": [
                {"id": "1", "sender_name": "Bob", "subject": "found me", "received_at": "x"},
            ]},
        },
    })

    text, _, displays = await claude_client.process_message("trouve le mail de bob", "2026-04-25 10:00")

    assert displays == []
    last_user_turn = fake.calls[1]["messages"][-1]
    tr_content = last_user_turn["content"][0]["content"]
    # The tool_result reaches Claude with the actual data (wrapped untrusted).
    assert "Bob" in tr_content
    assert '<u s="email">' in tr_content


@pytest.mark.asyncio
async def test_list_todos_with_display_flag_renders_directly(monkeypatch):
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("list_todos", {"filter": "pending", "display": True})]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)
    _stub_api(monkeypatch, {
        "/todos/list": {
            "success": True,
            "data": {"todos": [{"id": "t1", "title": "Pain"}]},
        },
    })

    text, _, displays = await claude_client.process_message("mes todos", "2026-04-25 10:00")

    assert len(displays) == 1
    assert "Pain" in displays[0]


@pytest.mark.asyncio
async def test_list_todos_without_display_flag_returns_to_claude(monkeypatch):
    from bot import claude_client

    fake = _Anthropic([
        _resp([_ToolBlock("list_todos", {"filter": "pending"})]),
        _end(),
    ])
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)
    _stub_api(monkeypatch, {
        "/todos/list": {
            "success": True,
            "data": {"todos": [{"id": "t1", "title": "Pain"}]},
        },
    })

    text, _, displays = await claude_client.process_message("compte mes todos", "2026-04-25 10:00")

    assert displays == []
