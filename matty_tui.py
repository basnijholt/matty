"""Matty TUI - Interactive Terminal Chat for Matrix."""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from rich.markdown import Markdown as RichMarkdown
from rich.markup import escape as rich_escape
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message as TextualMessage
from textual.widgets import (
    Footer,
    Header,
    Label,
    ListItem,
    ListView,
    OptionList,
    RichLog,
    TextArea,
)
from textual.widgets.option_list import Option

from matty import (
    Config,
    Message,
    Room,
    _create_client,
    _find_room,
    _get_event_id_from_handle,
    _get_messages,
    _get_or_create_id,
    _get_room_users,
    _get_rooms,
    _get_thread_messages,
    _get_threads,
    _load_config,
    _login,
    _send_message,
    _send_reaction,
    _sync_client,
)

if TYPE_CHECKING:
    from nio import AsyncClient
    from rich.console import RenderableType

logger = logging.getLogger(__name__)

CSS_PATH = Path(__file__).parent / "matty_tui.tcss"
POLL_INTERVAL_S = 3
SYNC_TIMEOUT_MS = 5000
_MAX_POLL_FAILURES = 5
_MESSAGE_LIMIT = 50


def _format_sender(sender: str) -> str:
    """Format a Matrix sender ID for display (show localpart only)."""
    if sender.startswith("@") and ":" in sender:
        return sender.removeprefix("@").split(":")[0]
    return sender


def _format_message_line(msg: Message) -> list[RenderableType]:
    """Format a single message for display in the message pane.

    Returns a list of renderables to write to the RichLog pane.
    """
    time_str = msg.timestamp.strftime("%H:%M")
    sender = rich_escape(_format_sender(msg.sender))

    prefix = ""
    if msg.is_thread_root and msg.thread_handle:
        safe_th = rich_escape(msg.thread_handle)
        prefix = f"[bold yellow]🧵 {safe_th}[/bold yellow] "
    elif msg.thread_handle:
        safe_th = rich_escape(msg.thread_handle)
        prefix = f"  ↳ [dim yellow]{safe_th}[/dim yellow] "

    handle = f"[bold magenta]{rich_escape(msg.handle)}[/bold magenta] " if msg.handle else ""
    header = f"{handle}{prefix}[dim]{time_str}[/dim] [bold cyan]{sender}[/bold cyan]:"

    parts: list[RenderableType] = [header, RichMarkdown(msg.content)]

    if msg.reactions:
        reaction_str = " ".join(
            f"{rich_escape(emoji)} {len(users)}" for emoji, users in msg.reactions.items()
        )
        parts.append(f"       [dim]Reactions: {reaction_str}[/dim]")

    return parts


def _reactions_equal(a: dict[str, list[str]] | None, b: dict[str, list[str]] | None) -> bool:
    """Compare reactions dicts treating user lists as order-independent sets."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if a.keys() != b.keys():
        return False
    return all(set(a[k]) == set(b[k]) for k in a)


def _messages_changed(old: list[Message], new: list[Message]) -> bool:
    """Return True if the message lists differ in IDs, content, or reactions."""
    if len(old) != len(new):
        return True
    return any(
        a.event_id != b.event_id
        or a.content != b.content
        or not _reactions_equal(a.reactions, b.reactions)
        for a, b in zip(old, new, strict=True)
    )


def _new_message_ids(old: list[Message], new: list[Message]) -> set[str]:
    """Return event IDs present in new but not in old."""
    old_ids = {m.event_id for m in old if m.event_id}
    return {m.event_id for m in new if m.event_id and m.event_id not in old_ids}


# Keep `/edit` and `/redact` visible for discoverability; they intentionally
# fall through to the "not yet implemented" notice in `_execute_slash_command`.
SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/back", "Exit thread view"),
    ("/room", "<name> — Switch room"),
    ("/thread", "<handle> <msg> — Start thread from message"),
    ("/reply", "<handle> <msg> — Reply to a message"),
    ("/react", "<handle> <emoji> — React to a message"),
    ("/edit", "<handle> <text> — Edit your message (coming soon)"),
    ("/redact", "<handle> — Delete a message (coming soon)"),
]


class MessageInput(TextArea):
    """Multiline message input with Ctrl+S to submit."""

    class Submitted(TextualMessage):
        """Posted when the user submits the message (Ctrl+S)."""

        def __init__(self, text_area: MessageInput, text: str) -> None:
            super().__init__()
            self.text_area = text_area
            self.text = text

    def submit_message(self) -> bool:
        """Submit the current text as a message and clear the input."""
        text = self.text.strip()
        if not text:
            return False
        self.post_message(self.Submitted(self, text))
        self.text = ""
        return True

    async def _on_key(self, event: events.Key) -> None:
        # When autocomplete is visible, intercept navigation keys
        menu = self.screen.query_one("#autocomplete-menu", OptionList)
        if menu.display:
            if event.key == "up":
                menu.action_cursor_up()
                event.stop()
                event.prevent_default()
                return
            if event.key == "down":
                menu.action_cursor_down()
                event.stop()
                event.prevent_default()
                return
            if event.key in ("enter", "tab"):
                menu.action_select()
                event.stop()
                event.prevent_default()
                return
            if event.key == "escape":
                menu.display = False
                event.stop()
                event.prevent_default()
                return

        # Ctrl+S → submit
        if event.key == "ctrl+s":
            event.stop()
            event.prevent_default()
            self.submit_message()
            return

        await super()._on_key(event)


class RoomItem(ListItem):
    """A room entry in the sidebar."""

    def __init__(self, room: Room) -> None:
        super().__init__()
        self.room = room

    def compose(self) -> ComposeResult:
        yield Label(self.room.name, classes="room-item", markup=False)


class ThreadItem(ListItem):
    """A thread entry in the sidebar."""

    def __init__(self, msg: Message, thread_id_str: str) -> None:
        super().__init__()
        self.msg = msg
        self.thread_id_str = thread_id_str

    def compose(self) -> ComposeResult:
        preview = self.msg.content[:30] + "..." if len(self.msg.content) > 30 else self.msg.content
        yield Label(
            f"{self.thread_id_str} {preview}",
            classes="thread-item",
            markup=False,
        )


class MattyApp(App):
    """Interactive Matrix chat TUI."""

    TITLE = "Matty - MindRoom Chat"
    CSS_PATH = CSS_PATH

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+r", "refresh", "Refresh"),
        Binding("ctrl+t", "toggle_threads", "Threads"),
        Binding("ctrl+s", "send_message", "Send", show=True),
        Binding("tab", "focus_next", "Next pane", show=False),
        Binding("shift+tab", "focus_previous", "Prev pane", show=False),
    ]

    def __init__(self, config: Config | None = None) -> None:
        super().__init__()
        self.config = config or _load_config()
        self.client: AsyncClient | None = None
        self._authenticated = False  # True after successful login + room loading
        self.rooms: list[Room] = []
        self.current_room_id: str | None = None
        self.current_room_name: str = ""
        self.current_thread_id: str | None = None
        self.messages: list[Message] = []
        self._polling = False
        self._threads_visible = True
        self.autocomplete_mode: str | None = None  # "slash" or "mention"
        self._room_users: list[str] = []
        self._poll_failures = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label(" Rooms", classes="section-label")
                yield ListView(id="room-list")
                yield Label(" Threads", classes="section-label", id="thread-label")
                yield ListView(id="thread-list")
            with Vertical(id="main-content"):
                yield RichLog(id="message-pane", highlight=True, markup=True, wrap=True)
                yield OptionList(id="autocomplete-menu")
                yield MessageInput(
                    id="message-input",
                    compact=True,
                    placeholder="Type a message... (Ctrl+S to send)",
                )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted - connect and load rooms."""
        menu = self.query_one("#autocomplete-menu", OptionList)
        menu.display = False
        menu.can_focus = False
        self._connect_and_load()

    @work(exclusive=True, group="connect")
    async def _connect_and_load(self) -> None:
        """Connect to Matrix and load rooms."""
        if not self.config.username or not self.config.password:
            self._log_to_pane(
                "Error: Username and password required. Set MATRIX_USERNAME and MATRIX_PASSWORD."
            )
            return

        # Close any leftover client from a previous canceled attempt
        if self.client:
            await self.client.close()
            self.client = None

        self._log_to_pane("Connecting to Matrix...")
        client: AsyncClient | None = None
        should_close_client = False

        try:
            client = await _create_client(self.config)
            should_close_client = True

            if not await _login(client, self.config.password):
                self._log_to_pane("Login failed. Check credentials.")
                return

            self._log_to_pane("Loading rooms...")
            self.rooms = await _get_rooms(client)
            self.client = client
            self._populate_room_list()
            self._log_to_pane(f"Connected! {len(self.rooms)} rooms loaded.")

            # Auto-select first room (matches sorted order in sidebar)
            room_list = self.query_one("#room-list", ListView)
            if room_list.children:
                first_item = room_list.children[0]
                if isinstance(first_item, RoomItem):
                    await self._select_room(first_item.room)

            self._authenticated = True
            self._start_polling()
            should_close_client = False
        except Exception:
            logger.warning("Failed to load rooms", exc_info=True)
            self._log_to_pane("Error: Failed to load rooms. Check connection and retry (Ctrl+R).")
        finally:
            if should_close_client and client:
                try:
                    # Keep close running even if this worker is already cancelled.
                    await asyncio.shield(client.close())
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.warning("Failed to close Matrix client", exc_info=True)

                if self.client is client:
                    self.client = None

    def _log_to_pane(self, text: str) -> None:
        """Write a line to the message pane."""
        pane = self.query_one("#message-pane", RichLog)
        pane.write(text)

    def _populate_room_list(self) -> None:
        """Populate the room sidebar."""
        room_list = self.query_one("#room-list", ListView)
        room_list.clear()
        for room in sorted(self.rooms, key=lambda r: r.name.lower()):
            room_list.append(RoomItem(room))

    async def _select_room(self, room: Room) -> None:
        """Switch to a room and display its messages."""
        self.current_room_id = room.room_id
        self.current_room_name = room.name
        self.current_thread_id = None  # Reset thread view
        self.sub_title = room.name
        self._sync_room_list_selection(room.room_id)

        # Cache room users for @mention autocomplete
        if self.client:
            self._room_users = _get_room_users(self.client, room.room_id)

        await self._refresh_messages()
        await self._refresh_threads()

    async def _fetch_messages(self) -> list[Message]:
        """Fetch messages for the current room or thread."""
        if not self.client or not self.current_room_id:
            return []

        if self.current_thread_id:
            return await _get_thread_messages(
                self.client, self.current_room_id, self.current_thread_id
            )
        return await _get_messages(self.client, self.current_room_id, limit=_MESSAGE_LIMIT)

    def _render_messages(self) -> None:
        """Render the current messages to the message pane."""
        pane = self.query_one("#message-pane", RichLog)
        pane.clear()
        safe_room_name = rich_escape(self.current_room_name)

        if self.current_thread_id:
            thread_simple_id = _get_or_create_id(self.current_thread_id)
            pane.write(
                f"[bold cyan]━━━ Thread t{thread_simple_id} in {safe_room_name} ━━━[/bold cyan]"
            )
        else:
            pane.write(f"[bold cyan]━━━ {safe_room_name} ━━━[/bold cyan]")

        if not self.messages:
            pane.write("[dim]No messages yet.[/dim]")
            return

        for msg in self.messages:
            for part in _format_message_line(msg):
                pane.write(part)

    async def _refresh_messages(self) -> None:
        """Fetch and display messages for the current room or thread."""
        self.messages = await self._fetch_messages()
        self._render_messages()

    async def _refresh_threads(self) -> None:
        """Fetch and display threads for the current room."""
        if not self.client or not self.current_room_id:
            return

        thread_list = self.query_one("#thread-list", ListView)
        thread_list.clear()

        threads = await _get_threads(self.client, self.current_room_id, limit=50)
        for thread_msg in threads:
            if thread_msg.event_id:
                simple_id = _get_or_create_id(thread_msg.event_id)
                thread_list.append(ThreadItem(thread_msg, f"t{simple_id}"))

    def _sync_room_list_selection(self, room_id: str) -> None:
        """Update room sidebar highlight to match the active room."""
        room_list = self.query_one("#room-list", ListView)
        for idx, item in enumerate(room_list.children):
            if isinstance(item, RoomItem) and item.room.room_id == room_id:
                room_list.index = idx
                return

    def _start_polling(self) -> None:
        """Start background polling for new messages."""
        if not self._polling:
            self._polling = True
            self._poll_messages()

    @work(exclusive=True, group="poll")
    async def _poll_messages(self) -> None:
        """Poll for new messages periodically."""
        while self._polling and self.client:
            delay = POLL_INTERVAL_S
            if self._poll_failures >= _MAX_POLL_FAILURES:
                # Exponential backoff: 6s, 12s, 24s, ... capped at 60s
                delay = min(
                    POLL_INTERVAL_S * 2 ** (self._poll_failures - _MAX_POLL_FAILURES + 1), 60
                )
            await asyncio.sleep(delay)
            if self.current_room_id and self.client:
                try:
                    # Capture selection before async I/O so we can detect
                    # room/thread switches that happen mid-flight.
                    snapshot_room = self.current_room_id
                    snapshot_thread = self.current_thread_id
                    await _sync_client(self.client, timeout=SYNC_TIMEOUT_MS)
                    new_messages = await self._fetch_messages()
                    # Discard results if the user switched rooms/threads
                    # while we were fetching.
                    if (
                        self.current_room_id != snapshot_room
                        or self.current_thread_id != snapshot_thread
                    ):
                        self._poll_failures = 0
                        continue
                    if _messages_changed(self.messages, new_messages):
                        old_messages = self.messages
                        self.messages = new_messages
                        self._render_messages()
                        new_ids = _new_message_ids(old_messages, new_messages)
                        if new_ids:
                            self.notify(
                                f"{len(new_ids)} new message(s)",
                                title=self.current_room_name,
                                timeout=2,
                            )
                    await self._refresh_threads()
                    self._poll_failures = 0
                except Exception:
                    logger.warning("Polling error", exc_info=True)
                    self._poll_failures += 1
                    if self._poll_failures == _MAX_POLL_FAILURES:
                        self.notify(
                            "Lost connection — retrying (Ctrl+R to reconnect)",
                            severity="warning",
                            timeout=5,
                        )

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle room or thread selection."""
        item = event.item
        if isinstance(item, RoomItem):
            await self._select_room(item.room)
        elif isinstance(item, ThreadItem):
            self.current_thread_id = item.msg.event_id
            await self._refresh_messages()

    async def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        """Handle message sending."""
        text = event.text
        if not text:
            return

        # Try slash commands first
        if text.startswith("/"):
            if self._handle_slash_command(text):
                return
            # Unknown slash command
            self.notify(f"Unknown command: {text.split()[0]}", severity="warning")
            return

        # Send regular message
        self._send_user_message(text)

    def _handle_slash_command(self, text: str) -> bool:
        """Dispatch a slash command. Returns True if handled."""
        parts = text.split(None, 1)
        command = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""
        known = {c for c, _ in SLASH_COMMANDS}
        if command not in known:
            return False
        self._execute_slash_command(command, args)
        return True

    def _resolve_handle(self, handle: str) -> str | None:
        """Resolve a message handle to an event_id, notify on failure."""
        if not self.current_room_id:
            return None
        event_id = _get_event_id_from_handle(self.current_room_id, handle)
        if not event_id:
            self.notify(f"Message '{handle}' not found", severity="warning")
        return event_id

    async def _sync_and_refresh(self, *, threads: bool = False) -> None:
        """Sync client and refresh messages (and optionally threads)."""
        if self.client:
            await _sync_client(self.client, timeout=SYNC_TIMEOUT_MS)
        await self._refresh_messages()
        if threads:
            await self._refresh_threads()

    @work(exclusive=False, group="command")
    async def _execute_slash_command(self, command: str, args: str) -> None:
        """Execute a parsed slash command."""
        if command == "/back":
            if self.current_thread_id:
                self.current_thread_id = None
                await self._refresh_messages()
            return

        if not self._authenticated:
            self.notify("Not connected yet — please wait", severity="warning")
            return

        try:
            await self._dispatch_slash_command(command, args)
        except Exception:
            logger.warning("Command %s failed", command, exc_info=True)
            self.notify(f"Command failed: {command}", severity="error")

    async def _dispatch_slash_command(self, command: str, args: str) -> None:
        """Dispatch a slash command after readiness has been verified."""
        if command == "/room":
            if args:
                await self._switch_room_by_name(args)
            else:
                self.notify("Usage: /room <name>", severity="warning")
            return

        # Commands that require a handle + argument
        if command in ("/thread", "/reply", "/react"):
            if not self.client or not self.current_room_id:
                self.notify("Not connected to a room", severity="error")
                return

            cmd_parts = args.split(None, 1)
            if len(cmd_parts) < 2:
                usage = {
                    "/thread": "/thread <handle> <message>",
                    "/reply": "/reply <handle> <message>",
                    "/react": "/react <handle> <emoji>",
                }
                self.notify(
                    f"Usage: {usage.get(command, f'{command} <handle> <arg>')}", severity="warning"
                )
                return

            handle, arg = cmd_parts
            event_id = self._resolve_handle(handle)
            if not event_id:
                return

            if command == "/thread":
                success = await _send_message(
                    self.client,
                    self.current_room_id,
                    arg,
                    thread_root_id=event_id,
                )
                if success:
                    await self._sync_and_refresh(threads=True)
                else:
                    self.notify("Failed to send thread message", severity="error")

            elif command == "/reply":
                success = await _send_message(
                    self.client,
                    self.current_room_id,
                    arg,
                    reply_to_id=event_id,
                )
                if success:
                    await self._sync_and_refresh()
                else:
                    self.notify("Failed to send reply", severity="error")

            elif command == "/react":
                success = await _send_reaction(
                    self.client,
                    self.current_room_id,
                    event_id,
                    arg,
                )
                if success:
                    await self._sync_and_refresh()
                else:
                    self.notify("Failed to send reaction", severity="error")
            return

        self.notify(f"{command} is not yet implemented", severity="warning")

    @work(exclusive=False, group="send")
    async def _send_user_message(self, text: str) -> None:
        """Send a message in a background worker."""
        if not self._authenticated or not self.client or not self.current_room_id:
            self.notify("Not connected to a room", severity="error")
            return

        try:
            success = await _send_message(
                self.client,
                self.current_room_id,
                text,
                thread_root_id=self.current_thread_id,
                mentions=True,
            )

            if success:
                # Refresh to show the sent message
                await _sync_client(self.client, timeout=SYNC_TIMEOUT_MS)
                await self._refresh_messages()
            else:
                self.notify("Failed to send message", severity="error")
        except Exception:
            logger.warning("Failed to send message", exc_info=True)
            self.notify("Failed to send message", severity="error")

    # ── Autocomplete ──────────────────────────────────────────────────

    def _show_autocomplete(self, options: list[Option], mode: str) -> None:
        """Populate and show the autocomplete menu."""
        menu = self.query_one("#autocomplete-menu", OptionList)
        menu.clear_options()
        for option in options:
            menu.add_option(option)
        menu.display = True
        menu.highlighted = 0
        menu.refresh(layout=True)
        self.autocomplete_mode = mode

    def _hide_autocomplete(self) -> None:
        """Hide the autocomplete menu and reset mode."""
        menu = self.query_one("#autocomplete-menu", OptionList)
        menu.display = False
        self.autocomplete_mode = None

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Update autocomplete suggestions as the user types."""
        text = event.text_area.text
        first_line = text.split("\n")[0]

        # Slash command autocomplete: first line starts with "/" and has no space yet
        if first_line.startswith("/") and " " not in first_line:
            prefix = first_line.lower()
            matches = [
                Option(f"{cmd}  {desc}", id=cmd)
                for cmd, desc in SLASH_COMMANDS
                if cmd.startswith(prefix)
            ]
            if matches:
                self._show_autocomplete(matches, "slash")
                return
            self._hide_autocomplete()
            return

        # @mention autocomplete: use rfind to match the *last* @ so that earlier
        # mentions (already completed) are ignored and only the one being typed
        # is autocompleted.  The whitespace/position-0 check avoids triggering
        # on email addresses like "someone@example.org".
        at_pos = text.rfind("@")
        if at_pos != -1 and (at_pos == 0 or text[at_pos - 1] in (" ", "\n")):
            after_at = text[at_pos + 1 :]
            if " " not in after_at and "\n" not in after_at:
                partial = after_at.lower()
                sender_counts = Counter(_format_sender(u) for u in self._room_users)
                matches = [
                    Option(u if sender_counts[_format_sender(u)] > 1 else _format_sender(u), id=u)
                    for u in self._room_users
                    if _format_sender(u).lower().startswith(partial)
                ]
                if matches:
                    self._show_autocomplete(matches, "mention")
                    return

        # Hide autocomplete in all other cases
        if self.autocomplete_mode:
            self._hide_autocomplete()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle autocomplete selection."""
        input_widget = self.query_one("#message-input", MessageInput)
        option = event.option

        if self.autocomplete_mode == "slash":
            # Replace text with selected command + space
            input_widget.text = f"{option.id} "
        elif self.autocomplete_mode == "mention":
            # Replace @partial with selected full Matrix ID to preserve exact target user.
            text = input_widget.text
            at_pos = text.rfind("@")
            if at_pos != -1:
                selected_mxid = str(option.id)
                input_widget.text = text[:at_pos] + f"{selected_mxid} "

        menu = self.query_one("#autocomplete-menu", OptionList)
        menu.display = False
        self.autocomplete_mode = None
        input_widget.focus()

    def action_send_message(self) -> None:
        """Send message action (triggered by Ctrl+S binding)."""
        input_widget = self.query_one("#message-input", MessageInput)
        input_widget.focus()
        input_widget.submit_message()

    async def _switch_room_by_name(self, room_name: str) -> None:
        """Switch to a room by name."""
        if not self._authenticated or not self.client:
            self.notify("Not connected yet — please wait", severity="warning")
            return

        room_info = await _find_room(self.client, room_name)
        if room_info:
            room_id, name = room_info
            # Find the Room object
            for room in self.rooms:
                if room.room_id == room_id:
                    await self._select_room(room)
                    return
            # Room found but not in our list - create a minimal Room
            await self._select_room(Room(room_id=room_id, name=name, member_count=0))
        else:
            self.notify(f"Room '{room_name}' not found", severity="warning")

    async def action_refresh(self) -> None:
        """Refresh current view."""
        if not self._authenticated or not self.client or self._poll_failures >= _MAX_POLL_FAILURES:
            # Force a full reconnect when not authenticated, no client,
            # or the connection has been failing repeatedly.
            self._polling = False
            self._authenticated = False
            if self.client:
                try:
                    await self.client.close()
                except Exception:
                    logger.warning("Failed to close client during reconnect", exc_info=True)
                self.client = None
            self._poll_failures = 0
            self._connect_and_load()
            return

        if self.current_room_id:
            try:
                await _sync_client(self.client, timeout=SYNC_TIMEOUT_MS)
                await self._refresh_messages()
                await self._refresh_threads()
                self.notify("Refreshed", timeout=1)
            except Exception:
                logger.warning("Refresh failed", exc_info=True)
                self.notify("Refresh failed — check connection", severity="error")

    def action_toggle_threads(self) -> None:
        """Toggle thread panel visibility."""
        self._threads_visible = not self._threads_visible
        thread_list = self.query_one("#thread-list", ListView)
        thread_label = self.query_one("#thread-label", Label)
        thread_list.display = self._threads_visible
        thread_label.display = self._threads_visible

    async def on_unmount(self) -> None:
        """Clean up client session when the app unmounts."""
        self._polling = False
        self._authenticated = False
        if self.client:
            await self.client.close()
            self.client = None

    def action_quit(self) -> None:
        """Quit the app; on_unmount handles client cleanup."""
        self.exit()
