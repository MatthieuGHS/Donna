"""Tests for Tier 1 #1 — prompt caching wiring.

The point: every messages.create call must pass `system` as a list of
content blocks with cache_control, and `tools` with cache_control on the
last entry. The temporal context lives in the user-message preamble (not
in SYSTEM_PROMPT) so the cache key on system+tools stays stable across
messages within the 5-min Anthropic cache TTL.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Anthropic:
    """Captures the kwargs of every messages.create call."""

    def __init__(self):
        self.calls: list[dict] = []
        outer = self

        class _M:
            def create(self_inner, **kwargs):  # noqa: N805
                outer.calls.append(kwargs)
                return SimpleNamespace(
                    stop_reason="end_turn",
                    content=[SimpleNamespace(type="text", text="ok")],
                    usage=SimpleNamespace(
                        input_tokens=10, output_tokens=2,
                        cache_read_input_tokens=0,
                        cache_creation_input_tokens=0,
                    ),
                )

        self.messages = _M()


@pytest.mark.asyncio
async def test_system_is_list_of_blocks_with_cache_control(monkeypatch):
    from bot import claude_client

    fake = _Anthropic()
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    await claude_client.process_message("ping", "2026-04-25 10:00")

    kwargs = fake.calls[0]
    system = kwargs["system"]
    assert isinstance(system, list), system
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # SYSTEM_PROMPT must no longer contain the per-message context — that
    # would invalidate the cache every minute.
    assert "{{current_date}}" not in system[0]["text"]
    assert "{{timezone}}" not in system[0]["text"]
    assert "Aujourd'hui nous sommes" not in system[0]["text"]


@pytest.mark.asyncio
async def test_last_tool_has_cache_control_breakpoint(monkeypatch):
    from bot import claude_client

    fake = _Anthropic()
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    await claude_client.process_message("ping", "2026-04-25 10:00")

    tools = fake.calls[0]["tools"]
    assert isinstance(tools, list)
    assert len(tools) == len(claude_client.TOOLS)
    # Only the last tool carries the breakpoint; everything before is cached.
    assert tools[-1].get("cache_control") == {"type": "ephemeral"}
    assert all("cache_control" not in t for t in tools[:-1]), (
        "only the last tool should carry the breakpoint"
    )


@pytest.mark.asyncio
async def test_user_message_carries_temporal_context(monkeypatch):
    """The current_date that used to live in the SYSTEM_PROMPT is now a
    natural-language preamble on the user message."""
    from bot import claude_client

    fake = _Anthropic()
    monkeypatch.setattr(claude_client, "Anthropic", lambda **_kw: fake)

    await claude_client.process_message("ping", "2026-04-25 10:00")

    messages = fake.calls[0]["messages"]
    first_user_content = messages[0]["content"]
    assert "Aujourd'hui" in first_user_content
    assert "2026-04-25 10:00" in first_user_content
    assert "ping" in first_user_content
    # Preamble comes before the user's actual message.
    assert first_user_content.index("Aujourd'hui") < first_user_content.index("ping")
