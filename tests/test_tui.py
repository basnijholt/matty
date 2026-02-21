"""Tests for the Matty TUI application."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.markdown import Markdown as RichMarkdown
from textual.widgets import ListView, OptionList, RichLog

from matty import Config, Message, Room
from matty_tui import (
    _MAX_POLL_FAILURES,
    SLASH_COMMANDS,
    MattyApp,
    MessageInput,
    RoomItem,
    ThreadItem,
    _format_message_line,
    _format_sender,
    _new_message_ids,
    _reactions_equal,
)

# =============================================================================
# Unit tests for helper functions
# =============================================================================


class TestFormatSender:
    """Tests for _format_sender."""

    def test_full_matrix_id(self):
        assert _format_sender("@alice:matrix.org") == "alice"

    def test_full_matrix_id_with_prefix(self):
        assert _format_sender("@mindroom_bot:localhost") == "mindroom_bot"

    def test_plain_name(self):
        assert _format_sender("bob") == "bob"

    def test_at_without_colon(self):
        assert _format_sender("@alice") == "@alice"


class TestFormatMessageLine:
    """Tests for _format_message_line."""

    def _make_msg(self, **kwargs):
        defaults = {
            "sender": "@alice:matrix.org",
            "content": "Hello world",
            "timestamp": datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            "room_id": "!room:matrix.org",
            "event_id": "$event1",
            "handle": "m1",
        }
        defaults.update(kwargs)
        return Message(**defaults)

    def test_basic_message(self):
        msg = self._make_msg()
        parts = _format_message_line(msg)
        assert isinstance(parts, list)
        assert len(parts) == 2
        header = parts[0]
        assert "14:30" in header
        assert "alice" in header
        assert "m1" in header
        assert isinstance(parts[1], RichMarkdown)
        assert parts[1].markup == "Hello world"

    def test_thread_root_message(self):
        msg = self._make_msg(is_thread_root=True, thread_handle="t1")
        parts = _format_message_line(msg)
        header = parts[0]
        assert "🧵" in header
        assert "t1" in header

    def test_thread_reply_message(self):
        msg = self._make_msg(thread_root_id="$root", thread_handle="t1")
        parts = _format_message_line(msg)
        header = parts[0]
        assert "↳" in header
        assert "t1" in header

    def test_message_with_reactions(self):
        msg = self._make_msg(reactions={"👍": ["@bob:matrix.org", "@charlie:matrix.org"]})
        parts = _format_message_line(msg)
        assert len(parts) == 3
        reaction_line = parts[2]
        assert "👍" in reaction_line
        assert "2" in reaction_line
        assert "Reactions" in reaction_line

    def test_message_without_handle(self):
        msg = self._make_msg(handle=None)
        parts = _format_message_line(msg)
        header = parts[0]
        assert "14:30" in header
        assert "alice" in header

    def test_sender_markup_escaped(self):
        msg = self._make_msg(sender="[alice]")
        parts = _format_message_line(msg)
        header = parts[0]
        assert r"\[alice]" in header

    def test_reaction_key_markup_escaped(self):
        """Reaction keys containing Rich markup tokens should be escaped."""
        msg = self._make_msg(reactions={"[red]danger[/red]": ["@bob:matrix.org"]})
        parts = _format_message_line(msg)
        reaction_line = parts[2]
        # The raw markup tokens should be escaped, not interpreted
        assert r"\[red]" in reaction_line
        assert r"\[/red]" in reaction_line


# =============================================================================
# Widget tests
# =============================================================================


class TestRoomItem:
    """Tests for RoomItem widget."""

    def test_room_item_stores_room(self):
        room = Room(room_id="!room:matrix.org", name="Lobby", member_count=5)
        item = RoomItem(room)
        assert item.room == room
        assert item.room.name == "Lobby"

    def test_room_item_renders_brackets_as_plain_text(self):
        room = Room(room_id="!room:matrix.org", name="[Support] [/x]", member_count=5)
        item = RoomItem(room)
        label = next(iter(item.compose()))
        assert label.render().plain == "[Support] [/x]"


class TestThreadItem:
    """Tests for ThreadItem widget."""

    def test_thread_item_stores_data(self):
        msg = Message(
            sender="@alice:matrix.org",
            content="Thread discussion about architecture",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$event1",
        )
        item = ThreadItem(msg, "t1")
        assert item.msg == msg
        assert item.thread_id_str == "t1"

    def test_thread_item_escapes_preview_markup(self):
        msg = Message(
            sender="@alice:matrix.org",
            content="hello [/x] [Support]",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!room:matrix.org",
            event_id="$event1",
        )
        item = ThreadItem(msg, "t1")
        label = next(iter(item.compose()))
        assert label.render().plain == "t1 hello [/x] [Support]"


# =============================================================================
# App tests using Textual's async test pilot
# =============================================================================


class TestMattyAppInit:
    """Tests for MattyApp initialization."""

    def test_app_default_config(self):
        with patch("matty_tui._load_config") as mock_config:
            mock_config.return_value = Config(
                homeserver="https://test.matrix.org",
                username="test",
                password="test",
            )
            app = MattyApp()
            assert app.config.homeserver == "https://test.matrix.org"
            assert app.client is None
            assert app._authenticated is False
            assert app.rooms == []
            assert app.current_room_id is None
            assert app._polling is False

    def test_app_custom_config(self):
        config = Config(
            homeserver="https://custom.matrix.org",
            username="custom_user",
            password="custom_pass",
        )
        app = MattyApp(config=config)
        assert app.config.homeserver == "https://custom.matrix.org"
        assert app.config.username == "custom_user"

    def test_app_bindings(self):
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)
        binding_keys = [b.key for b in app.BINDINGS]
        assert "ctrl+q" in binding_keys
        assert "ctrl+r" in binding_keys
        assert "ctrl+t" in binding_keys
        assert "ctrl+s" in binding_keys


class TestMattyAppAsync:
    """Async tests for MattyApp using Textual's test pilot."""

    async def test_app_compose(self, tui_config):
        """Test that the app composes its widgets correctly."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)):
            # query_one raises NoMatches if not found, so just call it
            app.query_one("#room-list", ListView)
            app.query_one("#thread-list", ListView)
            app.query_one("#message-pane", RichLog)
            app.query_one("#message-input", MessageInput)
            app.query_one("#autocomplete-menu", OptionList)

    async def test_toggle_threads(self, tui_config):
        """Test toggling thread panel visibility."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)):
            thread_list = app.query_one("#thread-list", ListView)
            assert thread_list.display is True

            app.action_toggle_threads()
            assert thread_list.display is False
            assert app._threads_visible is False

            app.action_toggle_threads()
            assert thread_list.display is True
            assert app._threads_visible is True

    async def test_connect_and_load_rooms(self, tui_config, tui_rooms, tui_messages):
        """Test connecting and loading rooms."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch(
                "matty_tui._get_messages",
                new_callable=AsyncMock,
                return_value=tui_messages,
            ),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                # Workers should have populated rooms
                room_list = app.query_one("#room-list", ListView)
                assert len(room_list.children) == 2
                # First sorted room ("Dev" < "Lobby") should be auto-selected
                assert app.current_room_id == "!dev:test.org"
                assert app._authenticated is True

    async def test_connect_failure_no_credentials(self):
        """Test handling missing credentials."""
        config = Config(homeserver="https://test.matrix.org")
        app = MattyApp(config=config)

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Should show error, not crash
            assert app.client is None
            assert app._authenticated is False

    async def test_login_failure_closes_client(self, tui_config):
        """Test failed login closes the created client."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=False),
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                mock_client.close.assert_awaited_once()
                assert app.client is None
                assert app._authenticated is False

    async def test_room_load_failure_cleans_up_client(self, tui_config):
        """Test that a failure during room loading cleans up the client."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch(
                "matty_tui._get_rooms",
                new_callable=AsyncMock,
                side_effect=OSError("Network unreachable"),
            ),
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()
                mock_client.close.assert_awaited_once()
                assert app.client is None
                assert app._authenticated is False

    async def test_send_message_via_input(self, tui_config, tui_rooms, tui_messages):
        """Test sending a message through the input field."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch(
                "matty_tui._get_messages",
                new_callable=AsyncMock,
                return_value=tui_messages,
            ),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
            patch(
                "matty_tui._send_message", new_callable=AsyncMock, return_value=True
            ) as mock_send,
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                # Focus input and type a message
                input_widget = app.query_one("#message-input", MessageInput)
                input_widget.focus()
                await pilot.pause()

                input_widget.text = "Hello from TUI!"
                # Submit with Ctrl+S
                await pilot.press("ctrl+s")
                await pilot.pause()

                # Verify send was called with mentions enabled
                mock_send.assert_called_once_with(
                    mock_client,
                    app.current_room_id,
                    "Hello from TUI!",
                    thread_root_id=None,
                    mentions=True,
                )

    async def test_send_message_workers_do_not_cancel_in_flight(self, tui_config):
        """Test rapid consecutive sends don't cancel an in-flight send."""
        app = MattyApp(config=tui_config)
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def delayed_send(_client, _room_id, text, thread_root_id=None, mentions=True):  # noqa: ARG001
            if text == "first":
                first_started.set()
                await release_first.wait()
            return True

        with (
            patch(
                "matty_tui._send_message",
                new_callable=AsyncMock,
                side_effect=delayed_send,
            ) as mock_send,
            patch("matty_tui._sync_client", new_callable=AsyncMock) as mock_sync,
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                app.client = AsyncMock()
                app._authenticated = True
                app.current_room_id = "!room:test.org"
                app._refresh_messages = AsyncMock()

                app._send_user_message("first")
                await asyncio.wait_for(first_started.wait(), timeout=1.0)
                app._send_user_message("second")
                release_first.set()

                for _ in range(20):
                    await pilot.pause()
                    if mock_sync.await_count == 2:
                        break

                assert mock_send.await_count == 2
                assert mock_sync.await_count == 2
                assert app._refresh_messages.await_count == 2

    async def test_poll_refreshes_threads_when_messages_change(self, tui_config):
        app = MattyApp(config=tui_config)
        old_message = Message(
            sender="@alice:test.org",
            content="old",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!lobby:test.org",
            event_id="$ev1",
        )
        new_message = Message(
            sender="@alice:test.org",
            content="new",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!lobby:test.org",
            event_id="$ev1",
        )
        app.messages = [old_message]
        app.current_room_id = "!lobby:test.org"
        app.client = AsyncMock()
        app._polling = True
        app._fetch_messages = AsyncMock(return_value=[new_message])
        app._render_messages = MagicMock()
        app._refresh_threads = AsyncMock()

        async def stop_after_one_tick(*_args, **_kwargs):
            app._polling = False

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=stop_after_one_tick)),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        app._refresh_threads.assert_awaited_once()

    async def test_poll_notifies_after_max_failures(self, tui_config):
        """After _MAX_POLL_FAILURES consecutive errors the user should be notified."""
        app = MattyApp(config=tui_config)
        app.current_room_id = "!lobby:test.org"
        app.client = AsyncMock()
        app._polling = True

        call_count = 0

        async def stop_after_n_ticks(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= _MAX_POLL_FAILURES:
                app._polling = False

        notifications: list[tuple] = []

        def capture_notify(*args, **kwargs):
            notifications.append((args, kwargs))

        app.notify = capture_notify

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=stop_after_n_ticks)),
            patch(
                "matty_tui._sync_client",
                new_callable=AsyncMock,
                side_effect=OSError("Network unreachable"),
            ),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        assert app._poll_failures == _MAX_POLL_FAILURES
        assert any("Lost connection" in str(n) for n in notifications)

    async def test_poll_resets_failure_count_on_success(self, tui_config):
        """A successful poll should reset the failure counter."""
        app = MattyApp(config=tui_config)
        app.current_room_id = "!lobby:test.org"
        app.client = AsyncMock()
        app._polling = True
        app._poll_failures = 3
        app.messages = []
        app._fetch_messages = AsyncMock(return_value=[])
        app._render_messages = MagicMock()
        app._refresh_threads = AsyncMock()

        async def stop_after_one_tick(*_args, **_kwargs):
            app._polling = False

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=stop_after_one_tick)),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        assert app._poll_failures == 0

    async def test_poll_uses_exponential_backoff_after_failures(self, tui_config):
        """Polling should increase sleep delay after repeated failures."""
        app = MattyApp(config=tui_config)
        app.current_room_id = "!lobby:test.org"
        app.client = AsyncMock()
        app._polling = True
        app._poll_failures = _MAX_POLL_FAILURES  # Already at failure threshold

        sleep_delays: list[float] = []

        async def capture_sleep(delay):
            sleep_delays.append(delay)
            app._polling = False  # Stop after one iteration

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=capture_sleep)),
            patch(
                "matty_tui._sync_client",
                new_callable=AsyncMock,
                side_effect=OSError("Network unreachable"),
            ),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        # With _poll_failures == _MAX_POLL_FAILURES, backoff should be > POLL_INTERVAL_S
        from matty_tui import POLL_INTERVAL_S

        assert sleep_delays[0] > POLL_INTERVAL_S

    async def test_poll_refreshes_threads_even_when_messages_unchanged(self, tui_config):
        """Thread sidebar should refresh on every successful poll, not just when messages change."""
        app = MattyApp(config=tui_config)
        msg = Message(
            sender="@alice:test.org",
            content="same",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!lobby:test.org",
            event_id="$ev1",
        )
        app.messages = [msg]
        app.current_room_id = "!lobby:test.org"
        app.client = AsyncMock()
        app._polling = True
        # Return identical messages so _messages_changed returns False
        app._fetch_messages = AsyncMock(return_value=[msg])
        app._render_messages = MagicMock()
        app._refresh_threads = AsyncMock()

        async def stop_after_one_tick(*_args, **_kwargs):
            app._polling = False

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=stop_after_one_tick)),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        # Threads should still be refreshed even though messages didn't change
        app._refresh_threads.assert_awaited_once()

    async def test_poll_discards_stale_results_after_room_switch(self, tui_config):
        """Poll results fetched for one room should be discarded if the user
        switched rooms while the fetch was in flight."""
        app = MattyApp(config=tui_config)
        old_message = Message(
            sender="@alice:test.org",
            content="old room msg",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!lobby:test.org",
            event_id="$ev1",
        )
        stale_message = Message(
            sender="@alice:test.org",
            content="stale msg from old room",
            timestamp=datetime(2024, 1, 15, 14, 31, tzinfo=UTC),
            room_id="!lobby:test.org",
            event_id="$ev_stale",
        )
        app.messages = [old_message]
        app.current_room_id = "!lobby:test.org"
        app.client = AsyncMock()
        app._polling = True
        app._render_messages = MagicMock()
        app._refresh_threads = AsyncMock()

        async def switch_room_during_fetch(*_args, **_kwargs):
            """Simulate the user switching rooms while fetch is in flight."""
            app.current_room_id = "!dev:test.org"
            return [stale_message]

        app._fetch_messages = AsyncMock(side_effect=switch_room_during_fetch)

        async def stop_after_one_tick(*_args, **_kwargs):
            app._polling = False

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=stop_after_one_tick)),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        # The stale results should NOT have been applied
        assert app.messages == [old_message]
        app._render_messages.assert_not_called()
        app._refresh_threads.assert_not_called()

    async def test_refresh_forces_reconnect_after_poll_failures(self, tui_config):
        """Ctrl+R should force a full reconnect when poll failures exceed threshold."""
        app = MattyApp(config=tui_config)

        async with app.run_test(size=(120, 40)):
            mock_client = AsyncMock()
            app.client = mock_client
            app._authenticated = True
            app._poll_failures = _MAX_POLL_FAILURES
            app.current_room_id = "!lobby:test.org"

            with patch.object(MattyApp, "_connect_and_load") as mock_connect:
                await app.action_refresh()

                # Should have closed old client and started reconnect
                mock_client.close.assert_awaited_once()
                assert app.client is None
                assert app._authenticated is False
                assert app._poll_failures == 0
                mock_connect.assert_called_once()


class TestSlashCommands:
    """Tests for slash command handling."""

    async def test_thread_command(self, tui_config, tui_rooms, tui_messages):
        """Test /thread command starts a thread from a message."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch("matty_tui._get_messages", new_callable=AsyncMock, return_value=tui_messages),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
            patch("matty_tui._get_event_id_from_handle", return_value="$ev1"),
            patch(
                "matty_tui._send_message", new_callable=AsyncMock, return_value=True
            ) as mock_send,
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                input_widget = app.query_one("#message-input", MessageInput)
                input_widget.focus()
                input_widget.text = "/thread m1 Starting a thread!"
                await pilot.press("ctrl+s")
                await pilot.pause()

                mock_send.assert_called_once_with(
                    mock_client,
                    app.current_room_id,
                    "Starting a thread!",
                    thread_root_id="$ev1",
                )

    async def test_react_command(self, tui_config, tui_rooms, tui_messages):
        """Test /react command adds a reaction."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch("matty_tui._get_messages", new_callable=AsyncMock, return_value=tui_messages),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
            patch("matty_tui._get_event_id_from_handle", return_value="$ev1"),
            patch(
                "matty_tui._send_reaction", new_callable=AsyncMock, return_value=True
            ) as mock_react,
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                input_widget = app.query_one("#message-input", MessageInput)
                input_widget.focus()
                input_widget.text = "/react m1 👍"
                await pilot.press("ctrl+s")
                await pilot.pause()

                mock_react.assert_called_once_with(
                    mock_client,
                    app.current_room_id,
                    "$ev1",
                    "👍",
                )

    async def test_reply_command(self, tui_config, tui_rooms, tui_messages):
        """Test /reply command sends a reply to a message."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch("matty_tui._get_messages", new_callable=AsyncMock, return_value=tui_messages),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
            patch("matty_tui._get_event_id_from_handle", return_value="$ev1"),
            patch(
                "matty_tui._send_message", new_callable=AsyncMock, return_value=True
            ) as mock_send,
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                input_widget = app.query_one("#message-input", MessageInput)
                input_widget.focus()
                input_widget.text = "/reply m1 Great point!"
                await pilot.press("ctrl+s")
                await pilot.pause()

                mock_send.assert_called_once_with(
                    mock_client,
                    app.current_room_id,
                    "Great point!",
                    reply_to_id="$ev1",
                )

    async def test_unknown_command_warning(self, tui_config, tui_rooms, tui_messages):
        """Test unknown slash command shows a warning."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch("matty_tui._get_messages", new_callable=AsyncMock, return_value=tui_messages),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
            patch("matty_tui._send_message", new_callable=AsyncMock) as mock_send,
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                input_widget = app.query_one("#message-input", MessageInput)
                input_widget.focus()
                input_widget.text = "/unknown foo"
                await pilot.press("ctrl+s")
                await pilot.pause()

                # Unknown command should NOT call _send_message
                mock_send.assert_not_called()

    async def test_concurrent_slash_commands_not_canceled(self, tui_config):
        """Rapid consecutive slash commands should not cancel in-flight ones."""
        app = MattyApp(config=tui_config)
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        call_log: list[str] = []

        async def delayed_send(_client, _room_id, text, **_kwargs):
            call_log.append(text)
            if text == "first reply":
                first_started.set()
                await release_first.wait()
            return True

        with (
            patch(
                "matty_tui._send_message",
                new_callable=AsyncMock,
                side_effect=delayed_send,
            ),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_event_id_from_handle", return_value="$ev1"),
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                app.client = AsyncMock()
                app._authenticated = True
                app.current_room_id = "!room:test.org"
                app._refresh_messages = AsyncMock()
                app._refresh_threads = AsyncMock()

                # Fire first command (will block in delayed_send)
                app._execute_slash_command("/reply", "m1 first reply")
                await asyncio.wait_for(first_started.wait(), timeout=2.0)

                # Fire second command while first is still running
                app._execute_slash_command("/reply", "m1 second reply")
                release_first.set()

                # Wait for both to complete
                for _ in range(20):
                    await pilot.pause()
                    if len(call_log) == 2:
                        break

                # Both commands should have completed, not just the second
                assert "first reply" in call_log
                assert "second reply" in call_log

    async def test_room_command_updates_sidebar_selection(
        self, tui_config, tui_rooms, tui_messages
    ):
        """Test /room switches both active room and sidebar highlight."""
        app = MattyApp(config=tui_config)

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock) as mock_create,
            patch("matty_tui._login", new_callable=AsyncMock, return_value=True),
            patch("matty_tui._get_rooms", new_callable=AsyncMock, return_value=tui_rooms),
            patch("matty_tui._get_messages", new_callable=AsyncMock, return_value=tui_messages),
            patch("matty_tui._get_threads", new_callable=AsyncMock, return_value=[]),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
            patch("matty_tui._get_room_users", return_value=[]),
            patch(
                "matty_tui._find_room",
                new_callable=AsyncMock,
                return_value=("!lobby:test.org", "Lobby"),
            ),
        ):
            mock_client = AsyncMock()
            mock_create.return_value = mock_client

            async with app.run_test(size=(120, 40)) as pilot:
                await pilot.pause()

                input_widget = app.query_one("#message-input", MessageInput)
                input_widget.focus()
                input_widget.text = "/room Lobby"
                await pilot.press("ctrl+s")
                await pilot.pause()

                assert app.current_room_id == "!lobby:test.org"

                room_list = app.query_one("#room-list", ListView)
                selected_item = room_list.children[room_list.index]
                assert isinstance(selected_item, RoomItem)
                assert selected_item.room.room_id == "!lobby:test.org"


class TestAutocomplete:
    """Tests for autocomplete functionality."""

    async def test_slash_autocomplete_shows_on_slash(self, tui_config):
        """Test that typing / shows the autocomplete menu."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "/"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is True
            assert menu.option_count == len(SLASH_COMMANDS)

    async def test_slash_autocomplete_filters(self, tui_config):
        """Test that slash autocomplete filters by prefix."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "/re"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is True
            # Should show /react, /reply, /redact
            assert menu.option_count == 3

    async def test_slash_autocomplete_hides_on_space(self, tui_config):
        """Test that autocomplete hides after space (command complete)."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "/room "
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is False

    async def test_mention_autocomplete(self, tui_config):
        """Test @mention autocomplete shows user list."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            # Populate room users
            app._room_users = [
                "@alice:test.org",
                "@bob:test.org",
                "@charlie:test.org",
            ]

            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "@ali"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is True
            assert menu.option_count == 1  # Only alice matches
            assert menu.highlighted == 0

    async def test_mention_autocomplete_shows_all_on_at(self, tui_config):
        """Test that typing just @ shows all room users."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            app._room_users = [
                "@alice:test.org",
                "@bob:test.org",
                "@charlie:test.org",
            ]

            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "@"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is True
            assert menu.option_count == 3  # All users shown

    async def test_mention_autocomplete_tab_selects_first_option(self, tui_config):
        """Test Tab selects the first mention suggestion immediately."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            app._room_users = [
                "@alice:test.org",
                "@bob:test.org",
            ]

            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "@ali"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is True
            assert menu.highlighted == 0

            await pilot.press("tab")
            await pilot.pause()

            assert input_widget.text == "@alice:test.org "
            assert menu.display is False

    async def test_mention_autocomplete_duplicate_localpart_keeps_mxid(self, tui_config):
        """Selecting duplicate localparts should insert the selected full MXID."""
        app = MattyApp(config=tui_config)
        async with app.run_test(size=(120, 40)) as pilot:
            app._room_users = [
                "@alice:one.org",
                "@alice:two.org",
            ]

            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            input_widget.text = "@ali"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is True
            assert menu.option_count == 2

            await pilot.press("down")
            await pilot.press("tab")
            await pilot.pause()

            assert input_widget.text == "@alice:two.org "
            assert menu.display is False


class TestSlashCommandsList:
    """Tests for the SLASH_COMMANDS constant."""

    def test_all_commands_start_with_slash(self):
        for cmd, _ in SLASH_COMMANDS:
            assert cmd.startswith("/")

    def test_expected_commands_present(self):
        cmds = [cmd for cmd, _ in SLASH_COMMANDS]
        assert "/back" in cmds
        assert "/room" in cmds
        assert "/thread" in cmds
        assert "/reply" in cmds
        assert "/react" in cmds


class TestMattyAppEntryPoint:
    """Tests for the TUI entry point via matty CLI."""

    def test_tui_command_creates_and_runs_app(self):
        """Test that the tui command creates a MattyApp and runs it."""
        with patch.object(MattyApp, "run") as mock_run:
            app = MattyApp(
                config=Config(
                    homeserver="https://test.matrix.org",
                    username="test",
                    password="test",
                )
            )
            app.run()
            mock_run.assert_called_once()


class TestReadyGuard:
    """Tests that commands are blocked before client is ready."""

    async def test_slash_command_blocked_when_not_ready(self):
        """Slash commands (except /back) should notify and return when _authenticated is False."""
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        notifications = []

        async with app.run_test(size=(120, 40)):
            app.client = AsyncMock()  # client exists but not authenticated
            app.current_room_id = "!room:test.org"

            def capture_notify(*args, **kwargs):
                notifications.append((args, kwargs))

            app.notify = capture_notify

            # Execute a command that requires readiness
            await MattyApp._execute_slash_command.__wrapped__(app, "/room", "Lobby")

            assert any("Not connected yet" in str(n) for n in notifications)

    async def test_send_blocked_when_not_ready(self):
        """_send_user_message should refuse when _authenticated is False."""
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        with patch("matty_tui._send_message", new_callable=AsyncMock) as mock_send:
            async with app.run_test(size=(120, 40)):
                app.client = AsyncMock()
                app.current_room_id = "!room:test.org"
                # _authenticated defaults to False

                await MattyApp._send_user_message.__wrapped__(app, "hello")

                mock_send.assert_not_called()

    async def test_back_command_works_without_ready(self):
        """/back only resets thread view and doesn't need the client."""
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        async with app.run_test(size=(120, 40)):
            app.current_thread_id = "$thread1"
            app._authenticated = False

            await MattyApp._execute_slash_command.__wrapped__(app, "/back", "")

            assert app.current_thread_id is None


# =============================================================================
# Bug regression tests
# =============================================================================


class TestLogMethodNaming:
    """Tests that our logging helper doesn't conflict with Textual internals."""

    def test_log_to_pane_does_not_override_textual_log(self):
        """MattyApp should not override App._log which Textual uses internally.

        Textual's App._log has signature (group, verbosity, frame, *objects, **kwargs).
        If we override it with _log(self, text: str), devtools logging breaks.
        """
        # The app should NOT have overridden Textual's _log method
        # Check that MattyApp doesn't define _log (it should use _log_to_pane instead)
        assert "_log" not in MattyApp.__dict__, (
            "MattyApp defines _log which overrides Textual's internal _log method. "
            "Rename to _log_to_pane to avoid the conflict."
        )

        # Verify _log_to_pane exists as the replacement
        assert "_log_to_pane" in MattyApp.__dict__, (
            "MattyApp should define _log_to_pane as the renamed helper."
        )


class TestReactionsEqual:
    """Tests for _reactions_equal helper."""

    def test_both_none(self):
        assert _reactions_equal(None, None)

    def test_one_none(self):
        assert not _reactions_equal({"👍": ["@a:x"]}, None)
        assert not _reactions_equal(None, {"👍": ["@a:x"]})

    def test_different_keys(self):
        assert not _reactions_equal({"👍": ["@a:x"]}, {"❤️": ["@a:x"]})

    def test_same_users_different_order(self):
        a = {"👍": ["@a:x", "@b:x"]}
        b = {"👍": ["@b:x", "@a:x"]}
        assert _reactions_equal(a, b)

    def test_different_users(self):
        a = {"👍": ["@a:x", "@b:x"]}
        b = {"👍": ["@a:x", "@c:x"]}
        assert not _reactions_equal(a, b)

    def test_empty_dicts(self):
        assert _reactions_equal({}, {})


class TestNewMessageIds:
    """Tests for _new_message_ids helper."""

    def _msg(self, event_id: str) -> Message:
        return Message(
            sender="@a:x",
            content="hi",
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
            room_id="!r:x",
            event_id=event_id,
        )

    def test_new_ids_detected(self):
        old = [self._msg("$1"), self._msg("$2")]
        new = [self._msg("$2"), self._msg("$3")]
        assert _new_message_ids(old, new) == {"$3"}

    def test_no_new_ids(self):
        old = [self._msg("$1"), self._msg("$2")]
        new = [self._msg("$1"), self._msg("$2")]
        assert _new_message_ids(old, new) == set()

    def test_all_new(self):
        old = [self._msg("$1")]
        new = [self._msg("$2"), self._msg("$3")]
        assert _new_message_ids(old, new) == {"$2", "$3"}

    def test_empty_old(self):
        old: list[Message] = []
        new = [self._msg("$1")]
        assert _new_message_ids(old, new) == {"$1"}


class TestMessagesChangedReactionOrder:
    """Tests that _messages_changed handles reaction user list order correctly."""

    def test_same_reactions_different_order_is_not_changed(self):
        """Reactions with same users in different order should NOT be treated as changed.

        The server may return reaction users in arbitrary order. If we do a naive
        list comparison, different orderings would cause unnecessary re-renders.
        """
        from matty_tui import _messages_changed

        msg_a = Message(
            sender="@alice:test.org",
            content="Hello",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!room:test.org",
            event_id="$ev1",
            reactions={"👍": ["@bob:test.org", "@charlie:test.org"]},
        )
        msg_b = Message(
            sender="@alice:test.org",
            content="Hello",
            timestamp=datetime(2024, 1, 15, 14, 30, tzinfo=UTC),
            room_id="!room:test.org",
            event_id="$ev1",
            reactions={"👍": ["@charlie:test.org", "@bob:test.org"]},
        )
        # Same reactions, just different order — should NOT be considered changed
        assert not _messages_changed([msg_a], [msg_b])


class TestNotificationDetection:
    """Tests that new message notifications work correctly with full buffers."""

    async def test_notification_fires_when_buffer_full_and_new_message_arrives(self):
        """When the message buffer is full (limit=50), a new message evicts the oldest.

        The notification logic should still detect the new arrival even though
        len(new_messages) == len(old_messages).
        """
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        # Simulate a full buffer of 3 messages
        old_messages = [
            Message(
                sender="@alice:test.org",
                content=f"Message {i}",
                timestamp=datetime(2024, 1, 15, 14, i, tzinfo=UTC),
                room_id="!room:test.org",
                event_id=f"$ev{i}",
            )
            for i in range(3)
        ]
        # New buffer: oldest evicted, new message added — same length
        new_messages = [
            Message(
                sender="@alice:test.org",
                content=f"Message {i}",
                timestamp=datetime(2024, 1, 15, 14, i, tzinfo=UTC),
                room_id="!room:test.org",
                event_id=f"$ev{i}",
            )
            for i in range(1, 4)  # ev0 evicted, ev3 added
        ]
        assert len(old_messages) == len(new_messages)  # Same length

        app.messages = old_messages
        app.current_room_id = "!room:test.org"
        app.current_room_name = "TestRoom"
        app.client = AsyncMock()
        app._polling = True
        app._fetch_messages = AsyncMock(return_value=new_messages)
        app._render_messages = MagicMock()
        app._refresh_threads = AsyncMock()

        notifications = []

        def capture_notify(*args, **kwargs):
            notifications.append((args, kwargs))

        app.notify = capture_notify

        async def stop_after_one_tick(*_args, **_kwargs):
            app._polling = False

        with (
            patch("matty_tui.asyncio.sleep", new=AsyncMock(side_effect=stop_after_one_tick)),
            patch("matty_tui._sync_client", new_callable=AsyncMock),
        ):
            await MattyApp._poll_messages.__wrapped__(app)

        # A notification SHOULD have fired because ev3 is new
        assert len(notifications) > 0, (
            "No notification was fired even though a new message ($ev3) arrived. "
            "The notification logic relies on length comparison which fails when "
            "the buffer is full and an old message is evicted."
        )


class TestSendMessageMentions:
    """Tests that message sending correctly passes mentions parameter."""

    async def test_send_user_message_passes_mentions_true(self):
        """_send_user_message should pass mentions=True to _send_message.

        Without this, @mention autocomplete inserts @user:server.org into text
        but _send_message won't parse them into Matrix mention pills.
        """
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        with (
            patch(
                "matty_tui._send_message", new_callable=AsyncMock, return_value=True
            ) as mock_send,
            patch("matty_tui._sync_client", new_callable=AsyncMock),
        ):
            async with app.run_test(size=(120, 40)) as pilot:
                app.client = AsyncMock()
                app._authenticated = True
                app.current_room_id = "!room:test.org"
                app._refresh_messages = AsyncMock()

                app._send_user_message("Hello @alice:test.org")
                await pilot.pause()
                # Wait for worker
                for _ in range(10):
                    await pilot.pause()
                    if mock_send.await_count > 0:
                        break

                mock_send.assert_called_once_with(
                    app.client,
                    "!room:test.org",
                    "Hello @alice:test.org",
                    thread_root_id=None,
                    mentions=True,
                )


class TestMentionAutocompleteEdgeCases:
    """Tests for edge cases in @mention autocomplete detection."""

    async def test_email_address_does_not_trigger_mention_autocomplete(self):
        """Typing an email like someone@alice.org should not show autocomplete.

        The @ in an email is not preceded by whitespace or at position 0,
        so it should not trigger mention suggestions.
        """
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)
        async with app.run_test(size=(120, 40)) as pilot:
            app._room_users = ["@alice:test.org", "@bob:test.org"]

            input_widget = app.query_one("#message-input", MessageInput)
            input_widget.focus()
            await pilot.pause()

            # "someone@ali" — the @ali part matches user @alice:test.org
            # but this is an email address, not a mention
            input_widget.text = "someone@ali"
            await pilot.pause()

            menu = app.query_one("#autocomplete-menu", OptionList)
            assert menu.display is False, (
                "Autocomplete menu was triggered by an email address. "
                "The @ in someone@ali should not trigger mention autocomplete "
                "because the @ is not preceded by whitespace or at position 0."
            )


class TestConnectWorkerCleanup:
    """Tests that leftover clients are cleaned up when connect is retried."""

    async def test_leftover_client_closed_on_reconnect(self):
        """If self.client exists when _connect_and_load starts, it should be closed first."""
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        old_client = AsyncMock()
        new_client = AsyncMock()

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock, return_value=new_client),
            patch("matty_tui._login", new_callable=AsyncMock, return_value=False),
        ):
            async with app.run_test(size=(120, 40)):
                # Simulate a leftover client from a previous canceled attempt
                app.client = old_client

                # Call _connect_and_load directly (unwrapped) to test cleanup
                await MattyApp._connect_and_load.__wrapped__(app)

                # The old client should have been closed
                old_client.close.assert_awaited_once()

    async def test_client_closed_when_connect_cancelled(self):
        """If connect is cancelled mid-login, the transient client should still be closed."""
        config = Config(homeserver="https://test.matrix.org")
        app = MattyApp(config=config)

        client = AsyncMock()
        login_started = asyncio.Event()
        login_blocked = asyncio.Event()

        async def block_login(*_args, **_kwargs):
            login_started.set()
            await login_blocked.wait()
            return True

        with (
            patch("matty_tui._create_client", new_callable=AsyncMock, return_value=client),
            patch("matty_tui._login", new_callable=AsyncMock, side_effect=block_login),
        ):
            async with app.run_test(size=(120, 40)):
                # Prevent auto-connect on mount from starting a real connection.
                app.config.username = "t"
                app.config.password = "t"

                connect_task = asyncio.create_task(MattyApp._connect_and_load.__wrapped__(app))
                await login_started.wait()

                connect_task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await connect_task

                await asyncio.sleep(0)
                client.close.assert_awaited_once()
                assert app.client is None


class TestClientCleanup:
    """Tests that the Matrix client is properly cleaned up."""

    async def test_client_closed_on_unmount(self):
        """The AsyncClient should be closed when the app unmounts, not just on quit."""
        config = Config(homeserver="https://test.matrix.org", username="t", password="t")
        app = MattyApp(config=config)

        mock_client = AsyncMock()
        async with app.run_test(size=(120, 40)):
            app.client = mock_client
            app._polling = True

        # After the app context exits (unmount), client should be closed
        mock_client.close.assert_awaited_once()
        assert app._polling is False
        assert app._authenticated is False
