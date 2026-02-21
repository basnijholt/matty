"""Snapshot tests for the Matty TUI application.

These tests capture SVG snapshots of the TUI in various states
to catch visual regressions. Run with --snapshot-update to regenerate.

These tests are skipped on CI because snapshot rendering depends on the
local font and terminal environment, causing mismatches between developer
machines and CI runners.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

from matty import Config, Message, Room
from matty_tui import MattyApp

# Snapshots render differently across environments (fonts, terminal, OS).
# Skip in CI to avoid false failures; run locally with --snapshot-update.
pytestmark = pytest.mark.skipif(
    os.environ.get("CI") == "true",
    reason="Snapshot tests are environment-dependent; run locally only",
)


def _make_config() -> Config:
    return Config(
        homeserver="https://test.matrix.org",
        username="test_user",
        password="test_pass",
    )


def _make_rooms() -> list[Room]:
    return [
        Room(room_id="!lobby:test.org", name="Lobby", member_count=12),
        Room(room_id="!dev:test.org", name="Dev", member_count=5),
        Room(room_id="!random:test.org", name="Random", member_count=8),
        Room(room_id="!announcements:test.org", name="Announcements", member_count=20),
    ]


def _make_messages() -> list[Message]:
    return [
        Message(
            sender="@alice:test.org",
            content="Hey everyone! How's the new release going?",
            timestamp=datetime(2024, 6, 15, 9, 30, tzinfo=UTC),
            room_id="!dev:test.org",
            event_id="$ev1",
            handle="m1",
        ),
        Message(
            sender="@bob:test.org",
            content="Looking good so far. CI is green.",
            timestamp=datetime(2024, 6, 15, 9, 32, tzinfo=UTC),
            room_id="!dev:test.org",
            event_id="$ev2",
            handle="m2",
            reactions={"👍": ["@alice:test.org", "@charlie:test.org"]},
        ),
        Message(
            sender="@charlie:test.org",
            content="I found a minor issue with the sidebar layout, filing a bug now.",
            timestamp=datetime(2024, 6, 15, 9, 35, tzinfo=UTC),
            room_id="!dev:test.org",
            event_id="$ev3",
            handle="m3",
            is_thread_root=True,
            thread_handle="t1",
        ),
        Message(
            sender="@alice:test.org",
            content="Thanks for catching that! Can you assign it to me?",
            timestamp=datetime(2024, 6, 15, 9, 36, tzinfo=UTC),
            room_id="!dev:test.org",
            event_id="$ev4",
            handle="m4",
            thread_root_id="$ev3",
            thread_handle="t1",
        ),
        Message(
            sender="@mindroom_bot:test.org",
            content="Build #142 passed. All 87 tests green. Coverage: 92%.",
            timestamp=datetime(2024, 6, 15, 9, 40, tzinfo=UTC),
            room_id="!dev:test.org",
            event_id="$ev5",
            handle="m5",
            reactions={"✅": ["@alice:test.org"], "🎉": ["@bob:test.org", "@charlie:test.org"]},
        ),
    ]


def _make_thread_roots() -> list[Message]:
    return [
        Message(
            sender="@charlie:test.org",
            content="I found a minor issue with the sidebar layout, filing a bug now.",
            timestamp=datetime(2024, 6, 15, 9, 35, tzinfo=UTC),
            room_id="!dev:test.org",
            event_id="$ev3",
            handle="m3",
            is_thread_root=True,
            thread_handle="t1",
        ),
    ]


async def _populate_app(pilot):
    """Manually populate the TUI with test data.

    Workers run in background tasks that may not complete during
    snapshot rendering, so we directly populate the UI instead.
    ListView.append() returns an AwaitMount that must be awaited
    for the child widgets to actually mount and render.
    """
    from matty_tui import ListView, RichLog, ThreadItem, _format_message_line, _get_or_create_id

    app = pilot.app
    # Cancel any workers that started from on_mount
    app._polling = False
    app.workers.cancel_all()
    await pilot.pause()

    # Populate rooms - must await each append for widgets to mount
    app.rooms = _make_rooms()
    room_list = app.query_one("#room-list", ListView)
    room_list.clear()
    from matty_tui import RoomItem

    for room in sorted(app.rooms, key=lambda r: r.name.lower()):
        await room_list.append(RoomItem(room))

    # Select the first room (alphabetically: Announcements)
    sorted_rooms = sorted(app.rooms, key=lambda r: r.name.lower())
    first_room = sorted_rooms[0]
    app.current_room_id = first_room.room_id
    app.current_room_name = first_room.name
    app.sub_title = first_room.name

    # Write messages to the message pane
    pane = app.query_one("#message-pane", RichLog)
    pane.clear()
    pane.write(f"[bold cyan]━━━ {first_room.name} ━━━[/bold cyan]")
    messages = _make_messages()
    for msg in messages:
        for part in _format_message_line(msg):
            pane.write(part)
    app.messages = messages

    # Populate threads - must await each append
    thread_list = app.query_one("#thread-list", ListView)
    thread_list.clear()
    for thread_msg in _make_thread_roots():
        if thread_msg.event_id:
            simple_id = _get_or_create_id(thread_msg.event_id)
            await thread_list.append(ThreadItem(thread_msg, f"t{simple_id}"))

    await pilot.pause()


class TestTuiSnapshots:
    """Snapshot tests for the TUI layout and rendering."""

    def test_initial_load(self, snap_compare):
        """App after connecting and loading rooms with messages."""
        app = MattyApp(config=_make_config())
        assert snap_compare(app, terminal_size=(120, 40), run_before=_populate_app)

    def test_no_credentials(self, snap_compare):
        """App when no credentials are provided - shows empty state."""
        config = Config(homeserver="https://test.matrix.org")
        app = MattyApp(config=config)

        async def wait_for_mount(pilot):
            pilot.app._polling = False
            pilot.app.workers.cancel_all()
            await pilot.pause()

        assert snap_compare(app, terminal_size=(120, 40), run_before=wait_for_mount)

    def test_threads_hidden(self, snap_compare):
        """App with thread panel toggled off."""
        app = MattyApp(config=_make_config())

        async def populate_and_toggle(pilot):
            await _populate_app(pilot)
            pilot.app.action_toggle_threads()
            await pilot.pause()

        assert snap_compare(app, terminal_size=(120, 40), run_before=populate_and_toggle)

    def test_narrow_terminal(self, snap_compare):
        """App rendered in a narrow terminal (80x24)."""
        app = MattyApp(config=_make_config())
        assert snap_compare(app, terminal_size=(80, 24), run_before=_populate_app)

    def test_wide_terminal(self, snap_compare):
        """App rendered in a wide terminal (160x50)."""
        app = MattyApp(config=_make_config())
        assert snap_compare(app, terminal_size=(160, 50), run_before=_populate_app)

    def test_input_focused(self, snap_compare):
        """App with the message input field focused and text entered."""
        app = MattyApp(config=_make_config())

        async def populate_and_focus(pilot):
            await _populate_app(pilot)
            input_widget = pilot.app.query_one("#message-input")
            input_widget.focus()
            input_widget.text = "Hello, this is a test message!"
            await pilot.pause()

        assert snap_compare(app, terminal_size=(120, 40), run_before=populate_and_focus)

    def test_slash_autocomplete(self, snap_compare):
        """App showing slash command autocomplete menu."""
        app = MattyApp(config=_make_config())

        async def populate_and_slash(pilot):
            await _populate_app(pilot)
            input_widget = pilot.app.query_one("#message-input")
            input_widget.focus()
            input_widget.text = "/"
            await pilot.pause()

        assert snap_compare(app, terminal_size=(120, 40), run_before=populate_and_slash)

    def test_multiline_input(self, snap_compare):
        """App with multiline text in the input area."""
        app = MattyApp(config=_make_config())

        async def populate_and_multiline(pilot):
            await _populate_app(pilot)
            input_widget = pilot.app.query_one("#message-input")
            input_widget.focus()
            input_widget.text = "First line\nSecond line\nThird line"
            await pilot.pause()

        assert snap_compare(app, terminal_size=(120, 40), run_before=populate_and_multiline)
