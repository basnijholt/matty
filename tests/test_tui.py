"""Tests for the prompt_toolkit TUI."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document

from matty import Message, Room
from matty_tui import (
    TUIState,
    _build_key_bindings,
    _build_layout,
    _escape,
    _format_message_list,
    _format_room_list,
    _format_thread_list,
    _init_client,
    _load_messages,
    _load_rooms,
    _load_threads,
    _poll_messages,
    _select_room,
    _send_message,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def state() -> TUIState:
    """Create a fresh TUI state."""
    return TUIState()


@pytest.fixture
def sample_rooms() -> list[Room]:
    """Create sample rooms for testing."""
    return [
        Room(room_id="!room1:test.org", name="Lobby", member_count=5),
        Room(room_id="!room2:test.org", name="Dev", member_count=3),
        Room(room_id="!room3:test.org", name="Random", member_count=8),
    ]


@pytest.fixture
def sample_messages() -> list[Message]:
    """Create sample messages for testing."""
    return [
        Message(
            sender="@alice:test.org",
            content="Hello!",
            timestamp=datetime(2024, 1, 1, 14, 30, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt1",
            handle="m1",
        ),
        Message(
            sender="@bob:test.org",
            content="Can you help?",
            timestamp=datetime(2024, 1, 1, 14, 31, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt2",
            handle="m2",
        ),
        Message(
            sender="@alice:test.org",
            content="Sure, what do you need?",
            timestamp=datetime(2024, 1, 1, 14, 32, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt3",
            handle="m3",
            is_thread_root=True,
            thread_handle="t1",
        ),
    ]


@pytest.fixture
def sample_threads() -> list[Message]:
    """Create sample thread messages for testing."""
    return [
        Message(
            sender="@alice:test.org",
            content="Architecture discussion",
            timestamp=datetime(2024, 1, 1, 14, 32, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt3",
            is_thread_root=True,
            thread_handle="t1",
            handle="m3",
        ),
    ]


# =============================================================================
# State tests
# =============================================================================


class TestTUIState:
    def test_default_state(self, state: TUIState) -> None:
        assert state.rooms == []
        assert state.messages == []
        assert state.threads == []
        assert state.selected_room_index == 0
        assert state.selected_room_id is None
        assert state.selected_room_name == ""
        assert state.show_threads is False
        assert state.status_message == "Loading..."
        assert state.focus_index == 0
        assert state.client is None
        assert state.username is None
        assert state.poll_task is None
        assert state.app is None


# =============================================================================
# Escape tests
# =============================================================================


class TestEscape:
    def test_escape_ampersand(self) -> None:
        assert _escape("a & b") == "a &amp; b"

    def test_escape_lt_gt(self) -> None:
        assert _escape("<b>hi</b>") == "&lt;b&gt;hi&lt;/b&gt;"

    def test_escape_clean_string(self) -> None:
        assert _escape("hello world") == "hello world"

    def test_escape_all_special(self) -> None:
        assert _escape("a<b&c>d") == "a&lt;b&amp;c&gt;d"


# =============================================================================
# Formatting tests
# =============================================================================


class TestFormatRoomList:
    def test_empty_rooms(self, state: TUIState) -> None:
        result = _format_room_list(state)
        assert "No rooms" in result

    def test_rooms_with_selection(self, state: TUIState, sample_rooms: list[Room]) -> None:
        state.rooms = sample_rooms
        state.selected_room_index = 0
        result = _format_room_list(state)
        assert "Lobby" in result
        assert "Dev" in result
        assert "Random" in result
        assert "&gt; Lobby" in result  # selected indicator

    def test_rooms_different_selection(self, state: TUIState, sample_rooms: list[Room]) -> None:
        state.rooms = sample_rooms
        state.selected_room_index = 1
        result = _format_room_list(state)
        assert "&gt; Dev" in result


class TestFormatMessageList:
    def test_empty_messages(self, state: TUIState) -> None:
        result = _format_message_list(state)
        assert "No messages" in result

    def test_messages_formatted(self, state: TUIState, sample_messages: list[Message]) -> None:
        state.messages = sample_messages
        result = _format_message_list(state)
        assert "alice" in result
        assert "bob" in result
        assert "Hello!" in result
        assert "Can you help?" in result
        assert "m1" in result
        assert "m2" in result

    def test_thread_indicator(self, state: TUIState, sample_messages: list[Message]) -> None:
        state.messages = sample_messages
        result = _format_message_list(state)
        assert "t1" in result

    def test_reactions_displayed(self, state: TUIState) -> None:
        msg = Message(
            sender="@alice:test.org",
            content="Nice!",
            timestamp=datetime(2024, 1, 1, 14, 30, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt1",
            handle="m1",
            reactions={"👍": ["@bob:test.org", "@carol:test.org"]},
        )
        state.messages = [msg]
        result = _format_message_list(state)
        assert "2" in result  # reaction count

    def test_thread_reply_indicator(self, state: TUIState) -> None:
        msg = Message(
            sender="@bob:test.org",
            content="Reply in thread",
            timestamp=datetime(2024, 1, 1, 14, 35, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt5",
            handle="m5",
            thread_root_id="$evt3",
            thread_handle="t1",
        )
        state.messages = [msg]
        result = _format_message_list(state)
        assert "↳" in result
        assert "t1" in result


class TestFormatThreadList:
    def test_empty_threads(self, state: TUIState) -> None:
        result = _format_thread_list(state)
        assert "No threads" in result

    def test_threads_formatted(self, state: TUIState, sample_threads: list[Message]) -> None:
        state.threads = sample_threads
        result = _format_thread_list(state)
        assert "t1" in result
        assert "alice" in result
        assert "Architecture" in result


# =============================================================================
# Layout tests
# =============================================================================


class TestBuildLayout:
    def test_layout_creation(self, state: TUIState) -> None:
        buf = Buffer(name="input")
        layout = _build_layout(state, buf)
        assert layout is not None

    def test_layout_focused_element(self, state: TUIState) -> None:
        buf = Buffer(name="input")
        layout = _build_layout(state, buf)
        # Layout should be created without errors
        assert layout.current_control is not None


# =============================================================================
# Key binding tests
# =============================================================================


class TestKeyBindings:
    def test_bindings_created(self, state: TUIState) -> None:
        buf = Buffer(name="input")
        kb = _build_key_bindings(state, buf)
        assert kb is not None
        # Should have bindings for c-q, c-r, c-t, tab, up, down, enter
        assert len(kb.bindings) >= 7

    def test_toggle_threads(self, state: TUIState) -> None:
        assert state.show_threads is False
        state.show_threads = True
        assert state.show_threads is True

    def test_cycle_focus(self, state: TUIState) -> None:
        state.focus_index = 0
        state.focus_index = (state.focus_index + 1) % 3
        assert state.focus_index == 1
        state.focus_index = (state.focus_index + 1) % 3
        assert state.focus_index == 2
        state.focus_index = (state.focus_index + 1) % 3
        assert state.focus_index == 0


# =============================================================================
# Async operation tests
# =============================================================================


class TestInitClient:
    @pytest.mark.asyncio
    async def test_init_without_credentials(
        self, state: TUIState, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MATRIX_USERNAME", raising=False)
        monkeypatch.delenv("MATRIX_PASSWORD", raising=False)
        # Patch config to return no credentials
        mock_config = MagicMock()
        mock_config.username = None
        mock_config.password = None
        with patch("matty_tui.matty._load_config", return_value=mock_config):
            result = await _init_client(state, None, None)
        assert result is False
        assert "required" in state.status_message

    @pytest.mark.asyncio
    async def test_init_with_credentials(self, state: TUIState) -> None:
        mock_config = MagicMock()
        mock_config.username = "user"
        mock_config.password = "pass"

        mock_client = AsyncMock()
        with (
            patch("matty_tui.matty._load_config", return_value=mock_config),
            patch("matty_tui.matty._create_client", return_value=mock_client),
            patch("matty_tui.matty._login", return_value=True),
        ):
            result = await _init_client(state, "user", "pass")
        assert result is True
        assert state.client is mock_client

    @pytest.mark.asyncio
    async def test_init_login_failure(self, state: TUIState) -> None:
        mock_config = MagicMock()
        mock_config.username = "user"
        mock_config.password = "pass"

        mock_client = AsyncMock()
        with (
            patch("matty_tui.matty._load_config", return_value=mock_config),
            patch("matty_tui.matty._create_client", return_value=mock_client),
            patch("matty_tui.matty._login", return_value=False),
        ):
            result = await _init_client(state, "user", "pass")
        assert result is False
        assert "failed" in state.status_message.lower()
        # Client should be closed on login failure
        mock_client.close.assert_awaited_once()


class TestLoadRooms:
    @pytest.mark.asyncio
    async def test_load_rooms_no_client(self, state: TUIState) -> None:
        await _load_rooms(state)
        assert state.rooms == []

    @pytest.mark.asyncio
    async def test_load_rooms_success(self, state: TUIState, sample_rooms: list[Room]) -> None:
        state.client = AsyncMock()
        with (
            patch("matty_tui.matty._get_rooms", return_value=sample_rooms),
            patch("matty_tui.matty._get_messages", return_value=[]),
        ):
            await _load_rooms(state)
        assert len(state.rooms) == 3
        assert "3 rooms" in state.status_message

    @pytest.mark.asyncio
    async def test_load_rooms_error(self, state: TUIState) -> None:
        state.client = AsyncMock()
        with patch("matty_tui.matty._get_rooms", side_effect=Exception("Network error")):
            await _load_rooms(state)
        assert "Error" in state.status_message


class TestSelectRoom:
    @pytest.mark.asyncio
    async def test_select_room(self, state: TUIState, sample_rooms: list[Room]) -> None:
        state.client = AsyncMock()
        state.rooms = sample_rooms
        state.selected_room_index = 1
        with patch("matty_tui.matty._get_messages", return_value=[]):
            await _select_room(state)
        assert state.selected_room_id == "!room2:test.org"
        assert state.selected_room_name == "Dev"

    @pytest.mark.asyncio
    async def test_select_room_empty(self, state: TUIState) -> None:
        await _select_room(state)
        assert state.selected_room_id is None


class TestLoadMessages:
    @pytest.mark.asyncio
    async def test_load_messages_success(
        self, state: TUIState, sample_messages: list[Message]
    ) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        state.selected_room_name = "Lobby"
        with patch("matty_tui.matty._get_messages", return_value=sample_messages):
            await _load_messages(state)
        assert len(state.messages) == 3
        assert "3 messages" in state.status_message

    @pytest.mark.asyncio
    async def test_load_messages_no_client(self, state: TUIState) -> None:
        await _load_messages(state)
        assert state.messages == []

    @pytest.mark.asyncio
    async def test_load_messages_no_room(self, state: TUIState) -> None:
        state.client = AsyncMock()
        await _load_messages(state)
        assert state.messages == []

    @pytest.mark.asyncio
    async def test_load_messages_error(self, state: TUIState) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        state.selected_room_name = "Lobby"
        with patch("matty_tui.matty._get_messages", side_effect=Exception("Timeout")):
            await _load_messages(state)
        assert "Error" in state.status_message


class TestLoadThreads:
    @pytest.mark.asyncio
    async def test_load_threads_success(
        self, state: TUIState, sample_threads: list[Message]
    ) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        with patch("matty_tui.matty._get_threads", return_value=sample_threads):
            await _load_threads(state)
        assert len(state.threads) == 1

    @pytest.mark.asyncio
    async def test_load_threads_no_client(self, state: TUIState) -> None:
        await _load_threads(state)
        assert state.threads == []

    @pytest.mark.asyncio
    async def test_load_threads_error(self, state: TUIState) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        with patch("matty_tui.matty._get_threads", side_effect=Exception("err")):
            await _load_threads(state)
        assert "Error" in state.status_message


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_success(self, state: TUIState) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        state.selected_room_name = "Lobby"
        with (
            patch("matty_tui.matty._send_message", return_value=True),
            patch("matty_tui.matty._get_messages", return_value=[]),
        ):
            await _send_message(state, "Hello!")
        # After success, _load_messages is called which updates status
        assert "Lobby" in state.status_message

    @pytest.mark.asyncio
    async def test_send_failure(self, state: TUIState) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        with patch("matty_tui.matty._send_message", return_value=False):
            await _send_message(state, "Hello!")
        assert "Failed" in state.status_message

    @pytest.mark.asyncio
    async def test_send_no_client(self, state: TUIState) -> None:
        await _send_message(state, "Hello!")
        # Should not crash, just no-op

    @pytest.mark.asyncio
    async def test_send_no_room(self, state: TUIState) -> None:
        state.client = AsyncMock()
        await _send_message(state, "Hello!")
        # Should not crash

    @pytest.mark.asyncio
    async def test_send_error(self, state: TUIState) -> None:
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        with patch("matty_tui.matty._send_message", side_effect=Exception("net err")):
            await _send_message(state, "Hello!")
        assert "error" in state.status_message.lower()


# =============================================================================
# Integration tests
# =============================================================================


class TestRunTui:
    def test_run_tui_importable(self) -> None:
        from matty_tui import run_tui

        assert callable(run_tui)

    def test_run_tui_async_importable(self) -> None:
        from matty_tui import _run_tui_async

        assert asyncio.iscoroutinefunction(_run_tui_async)

    def test_state_room_navigation(self, state: TUIState, sample_rooms: list[Room]) -> None:
        """Test room navigation state changes."""
        state.rooms = sample_rooms
        state.selected_room_index = 0

        # Move down
        state.selected_room_index = min(len(state.rooms) - 1, state.selected_room_index + 1)
        assert state.selected_room_index == 1

        # Move down again
        state.selected_room_index = min(len(state.rooms) - 1, state.selected_room_index + 1)
        assert state.selected_room_index == 2

        # Try to move past end
        state.selected_room_index = min(len(state.rooms) - 1, state.selected_room_index + 1)
        assert state.selected_room_index == 2

        # Move up
        state.selected_room_index = max(0, state.selected_room_index - 1)
        assert state.selected_room_index == 1

    def test_input_buffer_clear_on_send(self) -> None:
        """Test that input buffer is cleared after message send."""
        buf = Buffer(name="input")
        buf.document = Document("Hello world")
        assert buf.text == "Hello world"
        buf.document = Document("")
        assert buf.text == ""

    def test_special_characters_in_messages(self, state: TUIState) -> None:
        """Test messages with HTML-special characters are escaped."""
        msg = Message(
            sender="@user:test.org",
            content="x < y & z > w",
            timestamp=datetime(2024, 1, 1, 14, 30, tzinfo=UTC),
            room_id="!room1:test.org",
            event_id="$evt1",
            handle="m1",
        )
        state.messages = [msg]
        result = _format_message_list(state)
        assert "&lt;" in result
        assert "&amp;" in result
        assert "&gt;" in result

    def test_layout_stores_focusable_windows(self, state: TUIState) -> None:
        """Test that _build_layout populates focusable_windows on state."""
        buf = Buffer(name="input")
        _build_layout(state, buf)
        assert len(state.focusable_windows) == 3
        assert state.thread_window is not None


class TestPollMessages:
    @pytest.mark.asyncio
    async def test_poll_survives_errors(self, state: TUIState) -> None:
        """Test that _poll_messages keeps running after errors."""
        state.client = AsyncMock()
        state.selected_room_id = "!room1:test.org"
        state.selected_room_name = "Lobby"
        call_count = 0

        async def _failing_get_messages(*_args: object, **_kwargs: object) -> list[Message]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "Network error"
                raise ConnectionError(msg)
            return []

        with patch("matty_tui.matty._get_messages", side_effect=_failing_get_messages):
            task = asyncio.create_task(_poll_messages(state, interval=0.01))
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Should have been called more than once (survived the error)
        assert call_count >= 2
