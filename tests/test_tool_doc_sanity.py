"""Tier 2 #4 — sanity: the trim of update_event/create_event tool docs
must keep the pedagogical signal "use create_pending instead". Aggressive
future trims could otherwise strip the mention entirely and Claude would
lose the cue, even though the security is in the code."""

from __future__ import annotations


def _tool(name: str) -> dict:
    from bot import claude_client
    for t in claude_client.TOOLS:
        if t["name"] == name:
            return t
    raise AssertionError(f"tool {name} not in TOOLS")


def test_update_event_tool_doc_mentions_create_pending():
    desc = _tool("update_event")["description"]
    assert "create_pending" in desc, desc
    # Trim sanity: keep it under ~25 tokens (≈100 chars).
    assert len(desc) < 200, len(desc)


def test_create_event_tool_doc_mentions_create_pending_for_attendees():
    desc = _tool("create_event")["description"]
    assert "create_pending" in desc, desc
    assert "attendees" in desc, desc
    # Trim sanity: keep it under ~40 tokens (≈160 chars).
    assert len(desc) < 250, len(desc)
