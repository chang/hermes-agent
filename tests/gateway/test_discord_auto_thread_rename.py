"""Tests for Discord auto-thread title rename.

Mirrors the Telegram topic rename tests — verifies that when Hermes auto-titles
a session, a bot-owned Discord thread gets renamed to the new title, while
user-owned threads and non-thread chat types are left alone.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.session import SessionSource


def _make_thread_source(*, thread_id: str = "1507631057053155409") -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        user_id="208214988",
        chat_id=thread_id,
        user_name="tester",
        chat_type="thread",
        thread_id=thread_id,
    )


def _make_dm_source() -> SessionSource:
    return SessionSource(
        platform=Platform.DISCORD,
        user_id="208214988",
        chat_id="111",
        user_name="tester",
        chat_type="dm",
        thread_id=None,
    )


def _make_runner():
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={Platform.DISCORD: PlatformConfig(enabled=True, token="***")}
    )
    adapter = MagicMock()
    adapter.rename_thread = AsyncMock(return_value=True)
    runner.adapters = {Platform.DISCORD: adapter}
    runner.hooks = SimpleNamespace(emit=AsyncMock(), loaded_hooks=False)
    return runner


def test_is_discord_thread_lane_accepts_thread():
    runner = _make_runner()
    assert runner._is_discord_thread_lane(_make_thread_source()) is True


def test_is_discord_thread_lane_rejects_dm():
    runner = _make_runner()
    assert runner._is_discord_thread_lane(_make_dm_source()) is False


def test_is_discord_thread_lane_rejects_other_platform():
    runner = _make_runner()
    src = SessionSource(
        platform=Platform.TELEGRAM,
        user_id="x",
        chat_id="y",
        chat_type="thread",
        thread_id="z",
    )
    assert runner._is_discord_thread_lane(src) is False


def test_sanitize_discord_thread_title_collapses_whitespace():
    runner = _make_runner()
    assert runner._sanitize_discord_thread_title("  Configure   Hermes  Threads  ") == "Configure Hermes Threads"


def test_sanitize_discord_thread_title_handles_empty():
    runner = _make_runner()
    assert runner._sanitize_discord_thread_title("") == "Hermes Chat"
    assert runner._sanitize_discord_thread_title("   ") == "Hermes Chat"


def test_sanitize_discord_thread_title_truncates_at_100_chars():
    runner = _make_runner()
    long_title = "x" * 200
    result = runner._sanitize_discord_thread_title(long_title)
    assert len(result) == 100
    assert result.endswith("...")


@pytest.mark.asyncio
async def test_auto_generated_title_renames_discord_thread(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(runner, "_discord_auto_rename_threads_enabled", lambda: True)

    await runner._rename_discord_thread_for_session_title(
        _make_thread_source(thread_id="1507631057053155409"),
        "sess-discord",
        "  Configure   Hermes  Threads  ",
    )

    runner.adapters[Platform.DISCORD].rename_thread.assert_awaited_once_with(
        "1507631057053155409",
        "Configure Hermes Threads",
        only_if_bot_owned=True,
    )


@pytest.mark.asyncio
async def test_rename_discord_thread_skips_non_thread_source(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(runner, "_discord_auto_rename_threads_enabled", lambda: True)

    await runner._rename_discord_thread_for_session_title(
        _make_dm_source(),
        "sess-discord",
        "Some title",
    )

    runner.adapters[Platform.DISCORD].rename_thread.assert_not_called()


@pytest.mark.asyncio
async def test_rename_discord_thread_respects_config_flag(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(runner, "_discord_auto_rename_threads_enabled", lambda: False)

    await runner._rename_discord_thread_for_session_title(
        _make_thread_source(),
        "sess-discord",
        "Configure Hermes Threads",
    )

    runner.adapters[Platform.DISCORD].rename_thread.assert_not_called()


@pytest.mark.asyncio
async def test_rename_discord_thread_swallows_adapter_error(monkeypatch):
    runner = _make_runner()
    monkeypatch.setattr(runner, "_discord_auto_rename_threads_enabled", lambda: True)
    runner.adapters[Platform.DISCORD].rename_thread = AsyncMock(side_effect=RuntimeError("boom"))

    # Should not raise — best-effort.
    await runner._rename_discord_thread_for_session_title(
        _make_thread_source(),
        "sess-discord",
        "Configure Hermes Threads",
    )


# ──────────────────────────────────────────────────────────────────
# /rename slash command
# ──────────────────────────────────────────────────────────────────


def _make_rename_event(args: str = "", *, platform=Platform.DISCORD, chat_type: str = "thread"):
    """Build a MessageEvent that looks like a /rename slash invocation."""
    from gateway.platforms.base import MessageEvent

    src = SessionSource(
        platform=platform,
        user_id="208214988",
        chat_id="1507631057053155409",
        user_name="tester",
        chat_type=chat_type,
        thread_id="1507631057053155409" if chat_type == "thread" else None,
    )
    text = f"/rename {args}".strip()
    return MessageEvent(text=text, source=src, message_id="m-rename")


def _attach_session_store(runner, transcript=None):
    """Give the runner a minimal session_store for /rename to consume."""
    from datetime import datetime
    from gateway.session import SessionEntry

    transcript = transcript or []
    store = MagicMock()
    store.get_or_create_session.return_value = SessionEntry(
        session_key="agent:main:discord:thread:1507631057053155409:1507631057053155409",
        session_id="sess-discord",
        created_at=datetime.now(),
        updated_at=datetime.now(),
        platform=Platform.DISCORD,
        chat_type="thread",
        origin=None,
    )
    store.load_transcript.return_value = transcript
    runner.session_store = store


@pytest.mark.asyncio
async def test_rename_command_rejects_non_discord():
    runner = _make_runner()
    msg = await runner._handle_rename_command(
        _make_rename_event("Some title", platform=Platform.TELEGRAM)
    )
    assert "only works on Discord" in msg


@pytest.mark.asyncio
async def test_rename_command_rejects_non_thread():
    runner = _make_runner()
    msg = await runner._handle_rename_command(_make_rename_event("hi", chat_type="dm"))
    assert "inside a Discord thread" in msg


@pytest.mark.asyncio
async def test_rename_command_with_explicit_name():
    runner = _make_runner()
    _attach_session_store(runner)
    msg = await runner._handle_rename_command(_make_rename_event("My Cool Name"))
    runner.adapters[Platform.DISCORD].rename_thread.assert_awaited_once_with(
        "1507631057053155409",
        "My Cool Name",
        only_if_bot_owned=False,
    )
    assert "Thread renamed to" in msg
    assert "My Cool Name" in msg


@pytest.mark.asyncio
async def test_rename_command_auto_generates_when_no_arg(monkeypatch):
    runner = _make_runner()
    _attach_session_store(runner, transcript=[
        {"role": "user", "content": "How do I configure Hermes threads?"},
        {"role": "assistant", "content": "You can edit ~/.hermes/config.yaml..."},
    ])

    # Stub the title generator so we don't hit the network.
    import agent.title_generator as tg
    monkeypatch.setattr(tg, "generate_title", lambda *a, **kw: "Configure Hermes Threads")

    msg = await runner._handle_rename_command(_make_rename_event(""))
    runner.adapters[Platform.DISCORD].rename_thread.assert_awaited_once_with(
        "1507631057053155409",
        "Configure Hermes Threads",
        only_if_bot_owned=False,
    )
    assert "Configure Hermes Threads" in msg


@pytest.mark.asyncio
async def test_rename_command_empty_transcript_returns_error():
    runner = _make_runner()
    _attach_session_store(runner, transcript=[])

    msg = await runner._handle_rename_command(_make_rename_event(""))
    runner.adapters[Platform.DISCORD].rename_thread.assert_not_called()
    assert "No conversation history" in msg


@pytest.mark.asyncio
async def test_rename_command_handles_title_generation_failure(monkeypatch):
    runner = _make_runner()
    _attach_session_store(runner, transcript=[
        {"role": "user", "content": "Anything"},
    ])
    import agent.title_generator as tg
    monkeypatch.setattr(tg, "generate_title", lambda *a, **kw: None)

    msg = await runner._handle_rename_command(_make_rename_event(""))
    runner.adapters[Platform.DISCORD].rename_thread.assert_not_called()
    assert "no title" in msg.lower()


@pytest.mark.asyncio
async def test_rename_command_allows_user_owned_threads():
    """Slash command is explicit user intent — should pass only_if_bot_owned=False."""
    runner = _make_runner()
    _attach_session_store(runner)
    await runner._handle_rename_command(_make_rename_event("New Name"))
    call_kwargs = runner.adapters[Platform.DISCORD].rename_thread.call_args.kwargs
    assert call_kwargs.get("only_if_bot_owned") is False
