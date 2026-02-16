"""Prompt-toolkit based TUI for Matty Matrix chat client."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import Frame

import matty

if TYPE_CHECKING:
    from nio import AsyncClient
    from prompt_toolkit.key_binding import KeyPressEvent

# =============================================================================
# State
# =============================================================================


@dataclass
class TUIState:
    """Mutable state for the TUI application."""

    rooms: list[matty.Room] = field(default_factory=list)
    messages: list[matty.Message] = field(default_factory=list)
    threads: list[matty.Message] = field(default_factory=list)
    selected_room_index: int = 0
    selected_room_id: str | None = None
    selected_room_name: str = ""
    show_threads: bool = False
    status_message: str = "Loading..."
    focus_index: int = 0  # 0=rooms, 1=messages, 2=input, 3=threads
    client: AsyncClient | None = None
    username: str | None = None
    poll_task: asyncio.Task[None] | None = None
    app: Application[None] | None = None
    _background_tasks: list[asyncio.Task[None]] = field(default_factory=list)


# =============================================================================
# Formatting helpers
# =============================================================================


def _format_room_list(state: TUIState) -> str:
    """Format the room list as HTML for prompt_toolkit."""
    if not state.rooms:
        return "<i>No rooms</i>"
    lines: list[str] = []
    for i, room in enumerate(state.rooms):
        name = _escape(room.name)
        if i == state.selected_room_index:
            lines.append(f'<style bg="ansiblue" fg="ansiwhite"> &gt; {name} </style>')
        else:
            lines.append(f"   {name}")
    return "\n".join(lines)


def _format_message_list(state: TUIState) -> str:
    """Format messages as HTML for prompt_toolkit."""
    if not state.messages:
        return "<i>No messages yet</i>"
    lines: list[str] = []
    for msg in state.messages:
        time_str = msg.timestamp.strftime("%H:%M")
        sender = _escape(msg.sender.split(":")[0].lstrip("@"))
        content = _escape(msg.content)
        handle = _escape(msg.handle or "")

        prefix = ""
        if msg.is_thread_root and msg.thread_handle:
            prefix = f"<ansiyellow>🧵 {_escape(msg.thread_handle)}</ansiyellow> "
        elif msg.thread_handle:
            prefix = f"  ↳ <ansiyellow>{_escape(msg.thread_handle)}</ansiyellow> "

        reaction_str = ""
        if msg.reactions:
            parts = [f"{emoji} {len(users)}" for emoji, users in msg.reactions.items()]
            reaction_str = f"\n    <i>{_escape(' '.join(parts))}</i>"

        lines.append(
            f"<ansimagenta>{handle}</ansimagenta> {prefix}"
            f"<i>{time_str}</i> "
            f"<ansicyan>{sender}</ansicyan>: {content}"
            f"{reaction_str}"
        )
    return "\n".join(lines)


def _format_thread_list(state: TUIState) -> str:
    """Format threads as HTML for prompt_toolkit."""
    if not state.threads:
        return "<i>No threads</i>"
    lines: list[str] = []
    for thread in state.threads:
        time_str = thread.timestamp.strftime("%H:%M")
        sender = _escape(thread.sender.split(":")[0].lstrip("@"))
        content = _escape(thread.content[:40])
        handle = _escape(thread.thread_handle or "")
        lines.append(
            f"<ansiyellow>{handle}</ansiyellow> "
            f"<i>{time_str}</i> "
            f"<ansicyan>{sender}</ansicyan>: {content}"
        )
    return "\n".join(lines)


def _escape(text: str) -> str:
    """Escape text for HTML formatted text in prompt_toolkit."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# =============================================================================
# Layout builders
# =============================================================================


def _build_layout(state: TUIState, input_buffer: Buffer) -> Layout:
    """Build the prompt_toolkit layout."""
    header = Window(
        content=FormattedTextControl(
            HTML('<style bg="ansiblue" fg="ansiwhite"><b> Matty - MindRoom Chat </b></style>')
        ),
        height=1,
    )

    room_body = Window(
        content=FormattedTextControl(lambda: HTML(_format_room_list(state))),
        width=Dimension(min=15, preferred=22, max=30),
        wrap_lines=True,
    )
    room_pane = Frame(room_body, title="Rooms")

    message_body = Window(
        content=FormattedTextControl(lambda: HTML(_format_message_list(state))),
        wrap_lines=True,
    )
    message_pane = Frame(message_body, title=lambda: f"Messages - {state.selected_room_name}")

    thread_body = Window(
        content=FormattedTextControl(lambda: HTML(_format_thread_list(state))),
        width=Dimension(min=15, preferred=22, max=30),
        wrap_lines=True,
    )
    thread_pane = ConditionalContainer(
        Frame(thread_body, title="Threads"),
        filter=Condition(lambda: state.show_threads),
    )

    left_pane = HSplit(
        [
            room_pane,
            thread_pane,
        ]
    )

    input_window = Window(
        content=BufferControl(buffer=input_buffer),
        height=1,
    )
    input_pane = Frame(input_window, title="> Type a message... (@mention for agents)")

    status_bar = Window(
        content=FormattedTextControl(
            lambda: HTML(
                '<style bg="ansiblue" fg="ansiwhite">'
                " [Tab] Switch pane  [Ctrl+T] Threads  [Ctrl+R] Refresh  [Ctrl+Q] Quit"
                f"  | {_escape(state.status_message)}"
                "</style>"
            )
        ),
        height=1,
    )

    body = VSplit(
        [
            left_pane,
            HSplit([message_pane, input_pane]),
        ]
    )

    root = FloatContainer(
        content=HSplit([header, body, status_bar]),
        floats=[
            Float(content=Window(width=0, height=0), transparent=True),
        ],
    )

    return Layout(root, focused_element=input_window)


# =============================================================================
# Background task helper
# =============================================================================


def _fire_and_forget(state: TUIState, coro: asyncio.coroutines) -> None:  # type: ignore[type-arg]
    """Schedule a coroutine as a background task and track it."""
    task = asyncio.ensure_future(coro)
    state._background_tasks.append(task)  # noqa: SLF001
    task.add_done_callback(lambda t: state._background_tasks.remove(t))  # noqa: SLF001


# =============================================================================
# Key bindings
# =============================================================================


def _build_key_bindings(state: TUIState, input_buffer: Buffer) -> KeyBindings:
    """Build key bindings for the TUI."""
    kb = KeyBindings()

    @kb.add("c-q")
    def _quit(event: KeyPressEvent) -> None:
        """Quit the application."""
        if state.poll_task and not state.poll_task.done():
            state.poll_task.cancel()
        event.app.exit()

    @kb.add("c-r")
    def _refresh(event: KeyPressEvent) -> None:
        """Refresh messages."""
        state.status_message = "Refreshing..."
        event.app.invalidate()
        _fire_and_forget(state, _refresh_data(state))

    @kb.add("c-t")
    def _toggle_threads(event: KeyPressEvent) -> None:
        """Toggle thread panel."""
        state.show_threads = not state.show_threads
        if state.show_threads and state.selected_room_id:
            _fire_and_forget(state, _load_threads(state))
        event.app.invalidate()

    @kb.add("tab")
    def _cycle_focus(event: KeyPressEvent) -> None:
        """Cycle focus between panes (rooms -> messages -> input -> threads)."""
        max_index = 3 if state.show_threads else 2
        state.focus_index = (state.focus_index + 1) % (max_index + 1)
        event.app.invalidate()

    @kb.add("up")
    def _room_up(event: KeyPressEvent) -> None:
        """Move room selection up."""
        if state.focus_index == 0 and state.rooms:
            state.selected_room_index = max(0, state.selected_room_index - 1)
            _fire_and_forget(state, _select_room(state))
            event.app.invalidate()

    @kb.add("down")
    def _room_down(event: KeyPressEvent) -> None:
        """Move room selection down."""
        if state.focus_index == 0 and state.rooms:
            state.selected_room_index = min(len(state.rooms) - 1, state.selected_room_index + 1)
            _fire_and_forget(state, _select_room(state))
            event.app.invalidate()

    @kb.add("enter")
    def _send(_event: KeyPressEvent) -> None:
        """Send message or select room."""
        text = input_buffer.text.strip()
        if text and state.selected_room_id:
            input_buffer.document = Document("")
            _fire_and_forget(state, _send_message(state, text))

    return kb


# =============================================================================
# Async data operations
# =============================================================================


async def _init_client(state: TUIState, username: str | None, password: str | None) -> bool:
    """Initialize the Matrix client and login."""
    config = matty._load_config()  # noqa: SLF001
    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        state.status_message = "Error: Username and password required"
        return False

    state.username = config.username
    client = await matty._create_client(config)  # noqa: SLF001
    if not await matty._login(client, config.password):  # noqa: SLF001
        state.status_message = "Error: Login failed"
        return False

    state.client = client
    return True


async def _load_rooms(state: TUIState) -> None:
    """Load rooms from Matrix."""
    if not state.client:
        return
    try:
        state.rooms = await matty._get_rooms(state.client)  # noqa: SLF001
        if state.rooms:
            await _select_room(state)
        state.status_message = f"Loaded {len(state.rooms)} rooms"
    except Exception as e:
        state.status_message = f"Error loading rooms: {e}"
    if state.app:
        state.app.invalidate()


async def _select_room(state: TUIState) -> None:
    """Select a room and load its messages."""
    if not state.rooms or state.selected_room_index >= len(state.rooms):
        return
    room = state.rooms[state.selected_room_index]
    state.selected_room_id = room.room_id
    state.selected_room_name = room.name
    await _load_messages(state)
    if state.show_threads:
        await _load_threads(state)


async def _load_messages(state: TUIState) -> None:
    """Load messages for the selected room."""
    if not state.client or not state.selected_room_id:
        return
    try:
        state.messages = await matty._get_messages(state.client, state.selected_room_id)  # noqa: SLF001
        state.status_message = f"{state.selected_room_name}: {len(state.messages)} messages"
    except Exception as e:
        state.status_message = f"Error loading messages: {e}"
    if state.app:
        state.app.invalidate()


async def _load_threads(state: TUIState) -> None:
    """Load threads for the selected room."""
    if not state.client or not state.selected_room_id:
        return
    try:
        state.threads = await matty._get_threads(state.client, state.selected_room_id)  # noqa: SLF001
    except Exception as e:
        state.status_message = f"Error loading threads: {e}"
    if state.app:
        state.app.invalidate()


async def _send_message(state: TUIState, text: str) -> None:
    """Send a message to the selected room."""
    if not state.client or not state.selected_room_id:
        return
    try:
        success = await matty._send_message(state.client, state.selected_room_id, text)  # noqa: SLF001
        if success:
            state.status_message = "Message sent"
            await _load_messages(state)
        else:
            state.status_message = "Failed to send message"
    except Exception as e:
        state.status_message = f"Send error: {e}"
    if state.app:
        state.app.invalidate()


async def _refresh_data(state: TUIState) -> None:
    """Refresh rooms and messages."""
    await _load_rooms(state)


async def _poll_messages(state: TUIState, interval: float = 10.0) -> None:
    """Background poll for new messages."""
    while True:
        await asyncio.sleep(interval)
        if state.selected_room_id:
            await _load_messages(state)


# =============================================================================
# Application entry point
# =============================================================================


async def _run_tui_async(username: str | None = None, password: str | None = None) -> None:
    """Run the TUI application (async)."""
    state = TUIState()

    if not await _init_client(state, username, password):
        print(f"Error: {state.status_message}")
        return

    input_buffer = Buffer(name="input")
    layout = _build_layout(state, input_buffer)
    kb = _build_key_bindings(state, input_buffer)

    application: Application[None] = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        mouse_support=True,
    )
    state.app = application

    # Start background tasks
    async def _startup() -> None:
        await _load_rooms(state)
        state.poll_task = asyncio.create_task(_poll_messages(state))

    _fire_and_forget(state, _startup())

    try:
        await application.run_async()
    finally:
        if state.poll_task and not state.poll_task.done():
            state.poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await state.poll_task
        if state.client:
            await state.client.close()


def run_tui(username: str | None = None, password: str | None = None) -> None:
    """Run the TUI application."""
    asyncio.run(_run_tui_async(username, password))
