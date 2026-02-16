"""Tests for the prompt_toolkit TUI."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.application import Application
from typer.testing import CliRunner

from matty import Config, Message, Room, app
from matty_tui import (
    TuiState,
    activate_selected_thread,
    build_tui_application,
    format_messages_text,
    format_rooms_text,
    format_threads_text,
    move_room_selection,
    refresh_state,
    run_tui,
    send_current_message,
    toggle_threads,
)

runner = CliRunner()


def _sample_room(name: str, room_id: str) -> Room:
    return Room(room_id=room_id, name=name, member_count=2, topic=None, users=[])


def _sample_message(
    sender: str,
    content: str,
    room_id: str,
    *,
    event_id: str | None = None,
    thread_handle: str | None = None,
    is_thread_root: bool = False,
) -> Message:
    return Message(
        sender=sender,
        content=content,
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        room_id=room_id,
        event_id=event_id,
        thread_handle=thread_handle,
        is_thread_root=is_thread_root,
    )


def test_format_rooms_and_threads_text() -> None:
    """Render rooms and thread preview text."""
    rooms = [_sample_room("Lobby", "!lobby:matrix.org"), _sample_room("Dev", "!dev:matrix.org")]
    threads = [
        _sample_message(
            sender="@agent:matrix.org",
            content="Architecture discussion",
            room_id="!lobby:matrix.org",
            event_id="$thread1",
            thread_handle="t1",
            is_thread_root=True,
        )
    ]
    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        rooms=rooms,
        threads=threads,
        current_room_index=0,
        current_thread_index=0,
    )

    rooms_text = format_rooms_text(state)
    threads_text = format_threads_text(state)

    assert "> Lobby" in rooms_text
    assert "  Dev" in rooms_text
    assert ">  t1 Architecture discussion" in threads_text


def test_toggle_threads_and_room_selection() -> None:
    """Toggle thread visibility and clamp room movement."""
    rooms = [_sample_room("Lobby", "!lobby:matrix.org"), _sample_room("Dev", "!dev:matrix.org")]
    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        rooms=rooms,
        current_room_index=0,
        active_thread_root_id="$thread1",
        show_threads=True,
    )

    toggle_threads(state)
    assert state.show_threads is False
    assert state.active_thread_root_id is None

    move_room_selection(state, 99)
    assert state.current_room_index == 1
    move_room_selection(state, -99)
    assert state.current_room_index == 0


def test_activate_selected_thread() -> None:
    """Activate current thread selection."""
    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        threads=[
            _sample_message(
                sender="@agent:matrix.org",
                content="Bug triage",
                room_id="!room:matrix.org",
                event_id="$thread123",
                thread_handle="t3",
                is_thread_root=True,
            )
        ],
    )

    activate_selected_thread(state)
    assert state.active_thread_root_id == "$thread123"


def test_format_messages_text_thread_and_handles() -> None:
    """Render message timeline with handles/thread markers."""
    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        messages=[
            _sample_message(
                sender="@agent:matrix.org",
                content="Thread root",
                room_id="!room:matrix.org",
                event_id="$root1",
                thread_handle="t1",
                is_thread_root=True,
            ),
            _sample_message(
                sender="@me:matrix.org",
                content="Reply",
                room_id="!room:matrix.org",
                event_id="$reply1",
                thread_handle="t1",
                is_thread_root=False,
            ),
        ],
    )

    text = format_messages_text(state)
    assert "[t1]" in text
    assert "↳[t1]" in text
    assert "@agent:matrix.org: Thread root" in text


@pytest.mark.asyncio
async def test_refresh_state_loads_timeline() -> None:
    """Refresh loads room timeline by default."""
    room = _sample_room("Lobby", "!lobby:matrix.org")
    thread_root = _sample_message(
        sender="@agent:matrix.org",
        content="Thread root",
        room_id=room.room_id,
        event_id="$thread1",
        thread_handle="t1",
        is_thread_root=True,
    )
    timeline_message = _sample_message(
        sender="@agent:matrix.org",
        content="Hello",
        room_id=room.room_id,
        event_id="$msg1",
    )

    state = TuiState(client=MagicMock(), username="@me:matrix.org")

    with (
        patch("matty_tui._get_rooms", new=AsyncMock(return_value=[room])) as mock_get_rooms,
        patch(
            "matty_tui._get_threads", new=AsyncMock(return_value=[thread_root])
        ) as mock_get_threads,
        patch(
            "matty_tui._get_messages",
            new=AsyncMock(return_value=[timeline_message]),
        ) as mock_get_messages,
    ):
        await refresh_state(state)

    mock_get_rooms.assert_awaited_once_with(state.client)
    mock_get_threads.assert_awaited_once_with(state.client, room.room_id, limit=state.thread_limit)
    mock_get_messages.assert_awaited_once_with(
        state.client, room.room_id, limit=state.message_limit
    )
    assert state.status.startswith("Lobby")
    assert state.messages[0].content == "Hello"


@pytest.mark.asyncio
async def test_refresh_state_uses_active_thread() -> None:
    """Refresh switches to thread fetch when a thread is active."""
    room = _sample_room("Lobby", "!lobby:matrix.org")
    thread_root = _sample_message(
        sender="@agent:matrix.org",
        content="Root",
        room_id=room.room_id,
        event_id="$thread42",
        thread_handle="t42",
        is_thread_root=True,
    )
    thread_reply = _sample_message(
        sender="@me:matrix.org",
        content="Reply in thread",
        room_id=room.room_id,
        event_id="$reply42",
    )

    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        active_thread_root_id="$thread42",
    )

    with (
        patch("matty_tui._get_rooms", new=AsyncMock(return_value=[room])),
        patch("matty_tui._get_threads", new=AsyncMock(return_value=[thread_root])),
        patch(
            "matty_tui._get_thread_messages", new=AsyncMock(return_value=[thread_reply])
        ) as mock_get_thread_messages,
        patch("matty_tui._get_messages", new=AsyncMock(return_value=[])) as mock_get_messages,
    ):
        await refresh_state(state)

    mock_get_thread_messages.assert_awaited_once_with(
        state.client,
        room.room_id,
        "$thread42",
        limit=state.thread_limit,
    )
    mock_get_messages.assert_not_awaited()
    assert "thread view" in state.status


@pytest.mark.asyncio
async def test_refresh_state_keeps_active_thread_when_not_in_sidebar_window() -> None:
    """Thread view remains active even if sidebar thread list doesn't include active root."""
    room = _sample_room("Lobby", "!lobby:matrix.org")
    visible_sidebar_thread = _sample_message(
        sender="@agent:matrix.org",
        content="Newer thread",
        room_id=room.room_id,
        event_id="$thread-new",
        thread_handle="t100",
        is_thread_root=True,
    )
    thread_reply = _sample_message(
        sender="@me:matrix.org",
        content="Reply in older thread",
        room_id=room.room_id,
        event_id="$reply-old",
    )

    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        active_thread_root_id="$thread-old",
    )

    with (
        patch("matty_tui._get_rooms", new=AsyncMock(return_value=[room])),
        patch("matty_tui._get_threads", new=AsyncMock(return_value=[visible_sidebar_thread])),
        patch(
            "matty_tui._get_thread_messages", new=AsyncMock(return_value=[thread_reply])
        ) as mock_get_thread_messages,
        patch("matty_tui._get_messages", new=AsyncMock(return_value=[])) as mock_get_messages,
    ):
        await refresh_state(state)

    assert state.active_thread_root_id == "$thread-old"
    mock_get_thread_messages.assert_awaited_once_with(
        state.client,
        room.room_id,
        "$thread-old",
        limit=state.thread_limit,
    )
    mock_get_messages.assert_not_awaited()
    assert "thread view" in state.status


@pytest.mark.asyncio
async def test_refresh_state_clears_active_thread_when_room_disappears() -> None:
    """Active thread context is reset when refresh selects a different room."""
    previous_room = _sample_room("Old Room", "!old:matrix.org")
    current_room = _sample_room("New Room", "!new:matrix.org")
    timeline_message = _sample_message(
        sender="@agent:matrix.org",
        content="Timeline message",
        room_id=current_room.room_id,
        event_id="$msg-new",
    )

    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        rooms=[previous_room],
        current_room_index=0,
        active_thread_root_id="$stale-thread",
    )

    with (
        patch("matty_tui._get_rooms", new=AsyncMock(return_value=[current_room])),
        patch("matty_tui._get_threads", new=AsyncMock(return_value=[])),
        patch(
            "matty_tui._get_messages", new=AsyncMock(return_value=[timeline_message])
        ) as mock_get_messages,
        patch(
            "matty_tui._get_thread_messages", new=AsyncMock(return_value=[])
        ) as mock_get_thread_messages,
    ):
        await refresh_state(state)

    assert state.active_thread_root_id is None
    mock_get_thread_messages.assert_not_awaited()
    mock_get_messages.assert_awaited_once_with(
        state.client, current_room.room_id, limit=state.message_limit
    )
    assert "thread view" not in state.status


@pytest.mark.asyncio
async def test_send_current_message_uses_thread_root() -> None:
    """Send operation keeps active thread context."""
    room = _sample_room("Lobby", "!lobby:matrix.org")
    state = TuiState(
        client=MagicMock(),
        username="@me:matrix.org",
        rooms=[room],
        active_thread_root_id="$thread99",
    )

    with (
        patch("matty_tui._send_message", new=AsyncMock(return_value=True)) as mock_send,
        patch("matty_tui.refresh_state", new=AsyncMock()) as mock_refresh,
    ):
        sent = await send_current_message(state, "Hello @agent")

    assert sent is True
    mock_send.assert_awaited_once_with(
        state.client,
        room.room_id,
        "Hello @agent",
        thread_root_id="$thread99",
        mentions=True,
    )
    mock_refresh.assert_awaited_once_with(state)


def test_build_tui_application_has_keybindings() -> None:
    """Build prompt_toolkit application and verify primary bindings."""
    state = TuiState(client=MagicMock(), username="@me:matrix.org")
    application = build_tui_application(state)

    assert isinstance(application, Application)
    assert state.invalidate is not None
    assert application.layout.current_control.buffer.multiline() is False
    assert application.layout.current_control.buffer.accept_handler is not None

    bindings = {
        tuple(getattr(key, "value", str(key)) for key in binding.keys)
        for binding in application.key_bindings.bindings
    }
    assert ("c-q",) in bindings
    assert ("c-r",) in bindings
    assert ("c-t",) in bindings
    assert ("c-i",) in bindings


@pytest.mark.asyncio
async def test_run_tui_success_flow() -> None:
    """run_tui logs in, refreshes, runs app, and closes client."""
    mock_client = MagicMock()
    mock_client.close = AsyncMock()
    mock_application = MagicMock()
    mock_application.run_async = AsyncMock()

    with (
        patch(
            "matty_tui._load_config",
            return_value=Config("https://matrix.org", "user", "pass"),
        ),
        patch("matty_tui._create_client", new=AsyncMock(return_value=mock_client)),
        patch("matty_tui._login", new=AsyncMock(return_value=True)),
        patch("matty_tui.refresh_state", new=AsyncMock()) as mock_refresh,
        patch("matty_tui.build_tui_application", return_value=mock_application),
    ):
        await run_tui()

    mock_refresh.assert_awaited_once()
    mock_application.run_async.assert_awaited_once()
    mock_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_tui_requires_credentials() -> None:
    """run_tui exits early when credentials are missing."""
    with (
        patch("matty_tui._load_config", return_value=Config("https://matrix.org", None, None)),
        patch("matty_tui.console.print") as mock_print,
    ):
        await run_tui()
    mock_print.assert_called_once()


def test_tui_command_invokes_asyncio_run() -> None:
    """CLI `tui` command calls asyncio.run."""
    with patch("matty.asyncio.run") as mock_run:
        mock_run.side_effect = lambda coro: coro.close()
        result = runner.invoke(app, ["tui"])
    assert result.exit_code == 0
    mock_run.assert_called_once()
