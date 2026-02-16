"""Tests for interactive chat command and helpers."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from matty import (
    ChatSessionState,
    Message,
    _apply_agent_prefix,
    _chat_completion_candidates,
    _chat_messages_signature,
    _chat_scope_label,
    _execute_chat_action_command,
    _execute_chat_command,
    _execute_chat_slash_command,
    _get_chat_messages,
    _normalize_agent_mention,
    _parse_chat_command,
    _read_chat_input_with_live_updates,
    _send_message_with_event_id,
    _wait_for_new_messages,
    app,
)

runner = CliRunner()


def _message(
    sender: str,
    content: str,
    *,
    event_id: str | None = "$evt",
    thread_root_id: str | None = None,
) -> Message:
    return Message(
        sender=sender,
        content=content,
        timestamp=datetime.now(UTC),
        room_id="!room:test",
        event_id=event_id,
        thread_root_id=thread_root_id,
    )


@pytest.fixture
def session() -> ChatSessionState:
    return ChatSessionState(
        room_id="!room:test",
        room_name="Lobby",
        thread_id=None,
        history_limit=20,
        poll_interval=0.01,
        wait_timeout=0.01,
        mentions=True,
        self_user_id="@me:test",
        agent_mention=None,
    )


def test_normalize_agent_mention():
    assert _normalize_agent_mention("mindroom_general") == "@mindroom_general"
    assert _normalize_agent_mention("@mindroom_general:test") == "@mindroom_general:test"
    assert _normalize_agent_mention("  ") is None
    assert _normalize_agent_mention(None) is None


def test_apply_agent_prefix():
    assert _apply_agent_prefix("hello", "@mindroom_general") == "@mindroom_general hello"
    assert _apply_agent_prefix("@alice hi", "@mindroom_general") == "@alice hi"
    assert _apply_agent_prefix("hello", None) == "hello"


def test_parse_chat_command():
    command, args, error = _parse_chat_command('/reply m1 "hello world"')
    assert error is None
    assert command == "reply"
    assert args == ["m1", "hello world"]


def test_parse_chat_command_rejects_invalid_input():
    command, args, error = _parse_chat_command("reply m1 hello")
    assert command == ""
    assert args == []
    assert error is not None


def test_parse_chat_command_rejects_bad_quotes():
    command, args, error = _parse_chat_command('/reply m1 "unclosed')
    assert command == ""
    assert args == []
    assert error is not None


def test_chat_scope_label_uses_thread_mapping(monkeypatch):
    monkeypatch.setattr("matty._lookup_mapping", lambda *_a, **_kw: "3")
    assert _chat_scope_label("$thread123") == "thread t3"
    assert _chat_scope_label(None) == "main timeline"


def test_chat_completion_candidates_show_slash_menu():
    values = {value for value, _display in _chat_completion_candidates("/", [])}
    assert "/help" in values
    assert "/thread " in values
    assert "/reply " in values


def test_chat_completion_candidates_include_known_handles():
    root = _message("@alice:test", "root", event_id="$root")
    root.thread_handle = "t7"
    root.handle = "m9"
    reply = _message("@alice:test", "reply", event_id="$reply", thread_root_id="$root")
    reply.thread_handle = "t7"
    reply.handle = "m10"

    thread_values = {
        value for value, _display in _chat_completion_candidates("/thread t", [root, reply])
    }
    action_values = {
        value for value, _display in _chat_completion_candidates("/reply m", [root, reply])
    }

    assert "/thread t7" in thread_values
    assert "/reply m9 " in action_values
    assert "/reply m10 " in action_values


@pytest.mark.asyncio
async def test_send_message_with_event_id_success():
    client = MagicMock()
    client.room_send = AsyncMock(return_value=MagicMock(event_id="$new123"))
    client.rooms = {"!room:test": MagicMock(users={})}

    success, event_id = await _send_message_with_event_id(client, "!room:test", "hello")
    assert success is True
    assert event_id == "$new123"


@pytest.mark.asyncio
async def test_send_message_with_event_id_failure():
    from nio import ErrorResponse

    client = MagicMock()
    client.room_send = AsyncMock(return_value=ErrorResponse("bad request"))
    client.rooms = {"!room:test": MagicMock(users={})}

    success, event_id = await _send_message_with_event_id(client, "!room:test", "hello")
    assert success is False
    assert event_id is None


@pytest.mark.asyncio
async def test_wait_for_new_messages_ignores_old_events_outside_known_window(session):
    session.thread_id = None
    session.wait_timeout = 1.0
    session.poll_interval = 0.01

    old_event = _message("@alice:test", "older event", event_id="$old")
    reply_event = _message(
        "@mindroom_general:test",
        "thread reply",
        event_id="$reply",
        thread_root_id="$root",
    )

    with patch(
        "matty._get_messages",
        AsyncMock(side_effect=[[old_event], [old_event, reply_event]]),
    ) as mock_get_messages:
        result = await _wait_for_new_messages(
            client=MagicMock(),
            session=session,
            known_event_ids={"$recent"},
            sent_root_event_id="$root",
        )

    assert result is True
    assert mock_get_messages.await_count == 2


@pytest.mark.asyncio
async def test_get_chat_messages_uses_large_limit_for_thread_mode(session):
    session.thread_id = "$thread123"
    session.history_limit = 20

    with patch("matty._get_thread_messages", AsyncMock(return_value=[])) as mock_thread_messages:
        await _get_chat_messages(MagicMock(), session)

    assert mock_thread_messages.await_count == 1
    assert mock_thread_messages.await_args.args[3] == 400


def test_chat_messages_signature_detects_content_changes():
    original = _message("@mindroom:test", "Thinking...", event_id="$evt")
    updated = _message("@mindroom:test", "Done", event_id="$evt")

    before = _chat_messages_signature([original], history_limit=20)
    after = _chat_messages_signature([updated], history_limit=20)

    assert before != after


@pytest.mark.asyncio
async def test_read_chat_input_with_live_updates_redraws_on_edit(session):
    session.poll_interval = 0.01
    initial = _message("@mindroom:test", "Thinking...", event_id="$evt")
    edited = _message("@mindroom:test", "Done", event_id="$evt")
    messages_holder = {"messages": [initial]}

    async def delayed_prompt(*_args, **_kwargs):
        await asyncio.sleep(0.03)
        return "/quit"

    with (
        patch("matty._prompt_chat_input", AsyncMock(side_effect=delayed_prompt)),
        patch("matty._get_chat_messages", AsyncMock(side_effect=[[edited], [edited]])),
        patch("matty._render_chat_messages") as mock_render,
    ):
        user_input = await _read_chat_input_with_live_updates(
            client=MagicMock(),
            session=session,
            prompt_session=MagicMock(),
            completer=MagicMock(),
            initial_messages=[initial],
            messages_holder=messages_holder,
        )

    assert user_input == "/quit"
    assert mock_render.call_count == 1
    assert messages_holder["messages"] == [edited]


@pytest.mark.asyncio
async def test_execute_chat_slash_command_quit(session):
    client = MagicMock()
    keep_running = await _execute_chat_slash_command("/quit", session, client)
    assert keep_running is False


@pytest.mark.asyncio
async def test_execute_chat_slash_command_thread_switch(session):
    client = MagicMock()
    with patch("matty._resolve_thread_id", return_value=("$thread9", None)):
        keep_running = await _execute_chat_slash_command("/thread t9", session, client)
    assert keep_running is True
    assert session.thread_id == "$thread9"


@pytest.mark.asyncio
async def test_execute_chat_slash_command_history(session):
    client = MagicMock()
    keep_running = await _execute_chat_slash_command("/history 42", session, client)
    assert keep_running is True
    assert session.history_limit == 42


@pytest.mark.asyncio
async def test_execute_chat_slash_command_unknown(session, capsys):
    client = MagicMock()
    keep_running = await _execute_chat_slash_command("/not-a-command", session, client)
    captured = capsys.readouterr()
    assert keep_running is True
    assert "Unknown command" in captured.out


@pytest.mark.asyncio
async def test_execute_chat_action_command_reply(session):
    client = MagicMock()
    target = _message("@alice:test", "hello", event_id="$target")
    with (
        patch("matty._get_message_by_handle", AsyncMock(return_value=target)),
        patch("matty._send_message", AsyncMock(return_value=True)) as mock_send,
    ):
        await _execute_chat_action_command("reply", ["m1", "reply text"], session, client)

    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["reply_to_id"] == "$target"


@pytest.mark.asyncio
async def test_execute_chat_action_command_react(session):
    client = MagicMock()
    target = _message("@alice:test", "hello", event_id="$target")
    with (
        patch("matty._get_message_by_handle", AsyncMock(return_value=target)),
        patch("matty._send_reaction", AsyncMock(return_value=True)) as mock_react,
    ):
        await _execute_chat_action_command("react", ["m1", "👍"], session, client)

    mock_react.assert_called_once_with(client, "!room:test", "$target", "👍")


@pytest.mark.asyncio
async def test_execute_chat_command_applies_agent_prefix():
    client = MagicMock()
    client.user_id = "@me:test"
    client.rooms = {"!room:test": MagicMock(users={})}

    @asynccontextmanager
    async def fake_room_context(*_args, **_kwargs):
        yield client, "!room:test", "Lobby"

    with (
        patch("matty._with_client_in_room", fake_room_context),
        patch("matty._get_chat_messages", AsyncMock(return_value=[_message("@alice:test", "hi")])),
        patch("matty._render_chat_messages"),
        patch("matty._wait_for_new_messages", AsyncMock(return_value=False)),
        patch(
            "matty._send_message_with_event_id", AsyncMock(return_value=(True, "$mine"))
        ) as mock_send,
        patch(
            "matty._read_chat_input_with_live_updates", AsyncMock(side_effect=["hello", "/quit"])
        ),
    ):
        await _execute_chat_command(room="Lobby", agent="mindroom_general", wait=0)

    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["message"] == "@mindroom_general hello"


@pytest.mark.asyncio
async def test_execute_chat_command_uses_thread_root():
    client = MagicMock()
    client.user_id = "@me:test"
    client.rooms = {"!room:test": MagicMock(users={})}

    @asynccontextmanager
    async def fake_room_context(*_args, **_kwargs):
        yield client, "!room:test", "Lobby"

    with (
        patch("matty._with_client_in_room", fake_room_context),
        patch("matty._resolve_thread_id", return_value=("$thread1", None)),
        patch("matty._get_chat_messages", AsyncMock(return_value=[_message("@alice:test", "hi")])),
        patch("matty._render_chat_messages"),
        patch("matty._wait_for_new_messages", AsyncMock(return_value=False)),
        patch(
            "matty._send_message_with_event_id", AsyncMock(return_value=(True, "$mine"))
        ) as mock_send,
        patch(
            "matty._read_chat_input_with_live_updates", AsyncMock(side_effect=["hello", "/quit"])
        ),
    ):
        await _execute_chat_command(room="Lobby", thread="t1", wait=0)

    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs["thread_root_id"] == "$thread1"


@pytest.mark.asyncio
async def test_execute_chat_command_auto_follows_thread_reply():
    client = MagicMock()
    client.user_id = "@me:test"
    client.rooms = {"!room:test": MagicMock(users={})}

    @asynccontextmanager
    async def fake_room_context(*_args, **_kwargs):
        yield client, "!room:test", "Lobby"

    get_chat_messages = AsyncMock(
        side_effect=[[_message("@alice:test", "hi")], [_message("@alice:test", "hi")]]
    )

    with (
        patch("matty._with_client_in_room", fake_room_context),
        patch("matty._get_chat_messages", get_chat_messages),
        patch("matty._render_chat_messages"),
        patch("matty._send_message_with_event_id", AsyncMock(return_value=(True, "$newroot"))),
        patch("matty._wait_for_new_messages", AsyncMock(return_value=True)),
        patch("matty._get_or_create_id", return_value=7),
        patch(
            "matty._read_chat_input_with_live_updates", AsyncMock(side_effect=["hello", "/quit"])
        ),
    ):
        await _execute_chat_command(room="Lobby")

    assert len(get_chat_messages.call_args_list) >= 2
    second_session = get_chat_messages.call_args_list[1].args[1]
    assert second_session.thread_id == "$newroot"


@pytest.mark.asyncio
async def test_execute_chat_command_help_stays_visible_until_next_action():
    client = MagicMock()
    client.user_id = "@me:test"
    client.rooms = {"!room:test": MagicMock(users={})}

    @asynccontextmanager
    async def fake_room_context(*_args, **_kwargs):
        yield client, "!room:test", "Lobby"

    with (
        patch("matty._with_client_in_room", fake_room_context),
        patch("matty._get_chat_messages", AsyncMock(return_value=[_message("@alice:test", "hi")])),
        patch("matty._render_chat_messages") as mock_render,
        patch(
            "matty._read_chat_input_with_live_updates",
            AsyncMock(side_effect=["/help", "/quit"]),
        ),
    ):
        await _execute_chat_command(room="Lobby")

    assert mock_render.call_count >= 2
    assert mock_render.call_args_list[0].kwargs.get("show_help") is False
    assert mock_render.call_args_list[1].kwargs.get("show_help") is True


def test_cli_chat_command_invokes_asyncio_run():
    def _consume_coroutine(coro):
        coro.close()

    with patch("matty.asyncio.run") as mock_run:
        mock_run.side_effect = _consume_coroutine
        result = runner.invoke(app, ["chat", "Lobby"])
    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_cli_chat_command_validates_limit():
    result = runner.invoke(app, ["chat", "Lobby", "--limit", "0"])
    assert result.exit_code == 2
