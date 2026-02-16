#!/usr/bin/env python3
"""prompt_toolkit-based TUI for Matty."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from nio import AsyncClient
from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import has_focus
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.processors import BeforeInput
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame

from matty import (
    Message,
    Room,
    _create_client,
    _get_messages,
    _get_rooms,
    _get_thread_messages,
    _get_threads,
    _load_config,
    _login,
    _send_message,
    console,
)

DEFAULT_POLL_INTERVAL_SECONDS = 3.0
DEFAULT_MESSAGE_LIMIT = 50
DEFAULT_THREAD_LIMIT = 100


@dataclass
class TuiState:
    """Mutable state for the prompt_toolkit TUI."""

    client: AsyncClient
    username: str
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS
    message_limit: int = DEFAULT_MESSAGE_LIMIT
    thread_limit: int = DEFAULT_THREAD_LIMIT
    rooms: list[Room] = field(default_factory=list)
    current_room_index: int = 0
    threads: list[Message] = field(default_factory=list)
    current_thread_index: int = 0
    active_thread_root_id: str | None = None
    messages: list[Message] = field(default_factory=list)
    show_threads: bool = True
    status: str = "Connecting..."
    running: bool = True
    refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    invalidate: Callable[[], None] | None = None


def _invalidate(state: TuiState) -> None:
    if state.invalidate:
        state.invalidate()


def get_current_room(state: TuiState) -> Room | None:
    """Get the currently selected room."""
    if not state.rooms:
        return None
    state.current_room_index = max(0, min(state.current_room_index, len(state.rooms) - 1))
    return state.rooms[state.current_room_index]


def get_current_thread(state: TuiState) -> Message | None:
    """Get the currently selected thread root message."""
    if not state.threads:
        return None
    state.current_thread_index = max(0, min(state.current_thread_index, len(state.threads) - 1))
    return state.threads[state.current_thread_index]


def move_room_selection(state: TuiState, delta: int) -> None:
    """Move room selection up/down."""
    if not state.rooms:
        return
    state.current_room_index = max(0, min(len(state.rooms) - 1, state.current_room_index + delta))
    state.active_thread_root_id = None
    state.current_thread_index = 0
    _invalidate(state)


def move_thread_selection(state: TuiState, delta: int) -> None:
    """Move thread selection up/down."""
    if not state.show_threads or not state.threads:
        return
    state.current_thread_index = max(
        0,
        min(len(state.threads) - 1, state.current_thread_index + delta),
    )
    _invalidate(state)


def activate_selected_thread(state: TuiState) -> None:
    """Switch message pane to the selected thread."""
    thread = get_current_thread(state)
    if thread and thread.event_id:
        state.active_thread_root_id = thread.event_id
        _invalidate(state)


def clear_active_thread(state: TuiState) -> None:
    """Return to room timeline view."""
    state.active_thread_root_id = None
    _invalidate(state)


def toggle_threads(state: TuiState) -> None:
    """Toggle visibility of thread list content."""
    state.show_threads = not state.show_threads
    if not state.show_threads:
        state.active_thread_root_id = None
    _invalidate(state)


def _format_timestamp(timestamp: datetime) -> str:
    return timestamp.astimezone().strftime("%H:%M")


def format_rooms_text(state: TuiState) -> str:
    """Render room list for the sidebar."""
    if not state.rooms:
        return "No joined rooms."

    lines = []
    for index, room in enumerate(state.rooms):
        marker = ">" if index == state.current_room_index else " "
        lines.append(f"{marker} {room.name}")
    return "\n".join(lines)


def format_threads_text(state: TuiState) -> str:
    """Render thread list below the room list."""
    if not state.show_threads:
        return "Threads hidden. Press Ctrl+T to show."
    if not state.threads:
        return "No threads in this room."

    lines = []
    for index, thread in enumerate(state.threads):
        selected = index == state.current_thread_index
        active = thread.event_id == state.active_thread_root_id
        marker = ">" if selected else " "
        active_marker = "*" if active else " "
        handle = thread.thread_handle or "t?"
        preview = thread.content.replace("\n", " ")
        if len(preview) > 28:
            preview = f"{preview[:28]}..."
        lines.append(f"{marker}{active_marker} {handle} {preview}")
    return "\n".join(lines)


def format_messages_text(state: TuiState) -> str:
    """Render message timeline for the center pane."""
    if not state.messages:
        return "No messages."

    lines = []
    if state.active_thread_root_id:
        lines.append(f"[Thread view: {state.active_thread_root_id}]")

    for message in state.messages:
        timestamp = _format_timestamp(message.timestamp)
        handle = f"{message.handle} " if message.handle else ""
        thread_prefix = ""
        if message.is_thread_root and message.thread_handle:
            thread_prefix = f"[{message.thread_handle}] "
        elif message.thread_handle:
            thread_prefix = f"↳[{message.thread_handle}] "

        reactions = ""
        if message.reactions:
            reaction_summary = " ".join(
                f"{emoji}{len(users)}" for emoji, users in sorted(message.reactions.items())
            )
            reactions = f" {reaction_summary}"

        lines.append(
            f"{timestamp} {handle}{thread_prefix}{message.sender}: {message.content}{reactions}"
        )
    return "\n".join(lines)


def format_header_text(state: TuiState) -> str:
    """Render header text."""
    return f" Matty - MindRoom Chat ({state.username}) "


def format_footer_text(state: TuiState) -> str:
    """Render footer keybinding/status line."""
    return (
        f" [Tab] Switch pane  [Ctrl+T] Threads  [Ctrl+R] Refresh  [Ctrl+Q] Quit   | {state.status}"
    )


async def refresh_state(state: TuiState) -> None:
    """Refresh rooms, threads, and messages from Matrix."""
    async with state.refresh_lock:
        previous_room_id = get_current_room(state).room_id if get_current_room(state) else None

        try:
            state.rooms = await _get_rooms(state.client)
            if not state.rooms:
                state.threads = []
                state.messages = []
                state.active_thread_root_id = None
                state.status = "No joined rooms."
                _invalidate(state)
                return

            if previous_room_id:
                matching_index = next(
                    (
                        index
                        for index, room in enumerate(state.rooms)
                        if room.room_id == previous_room_id
                    ),
                    state.current_room_index,
                )
                state.current_room_index = max(0, min(matching_index, len(state.rooms) - 1))
            else:
                state.current_room_index = max(
                    0, min(state.current_room_index, len(state.rooms) - 1)
                )

            current_room = get_current_room(state)
            if current_room is None:
                state.status = "No room selected."
                _invalidate(state)
                return

            if previous_room_id and current_room.room_id != previous_room_id:
                state.active_thread_root_id = None
                state.current_thread_index = 0

            if state.show_threads:
                state.threads = await _get_threads(
                    state.client,
                    current_room.room_id,
                    limit=state.thread_limit,
                )
            else:
                state.threads = []

            if state.threads:
                state.current_thread_index = max(
                    0,
                    min(state.current_thread_index, len(state.threads) - 1),
                )

            if state.active_thread_root_id:
                state.messages = await _get_thread_messages(
                    state.client,
                    current_room.room_id,
                    state.active_thread_root_id,
                    limit=state.thread_limit,
                )
                state.status = f"{current_room.name} (thread view)"
            else:
                state.messages = await _get_messages(
                    state.client,
                    current_room.room_id,
                    limit=state.message_limit,
                )
                state.status = f"{current_room.name} ({len(state.messages)} messages)"
        except Exception as error:
            state.status = f"Refresh failed: {error}"

        _invalidate(state)


async def send_current_message(state: TuiState, text: str) -> bool:
    """Send input text to the current room or active thread."""
    message = text.strip()
    if not message:
        return False

    current_room = get_current_room(state)
    if current_room is None:
        state.status = "No room selected."
        _invalidate(state)
        return False

    sent = await _send_message(
        state.client,
        current_room.room_id,
        message,
        thread_root_id=state.active_thread_root_id,
        mentions=True,
    )

    if sent:
        state.status = "Message sent."
        await refresh_state(state)
    else:
        state.status = "Failed to send message."
        _invalidate(state)

    return sent


async def poll_for_updates(state: TuiState) -> None:
    """Background polling task for new messages."""
    while state.running:
        await asyncio.sleep(state.poll_interval)
        if not state.running:
            return
        await refresh_state(state)


def create_key_bindings(
    state: TuiState,
    rooms_window: Window,
    threads_window: Window,
    messages_window: Window,
    input_window: Window,
) -> KeyBindings:
    """Create global key bindings for the TUI."""
    key_bindings = KeyBindings()

    @key_bindings.add("c-q")
    def _quit(event) -> None:
        state.running = False
        event.app.exit()

    @key_bindings.add("c-r")
    def _refresh(event) -> None:
        event.app.create_background_task(refresh_state(state))

    @key_bindings.add("c-t")
    def _toggle_threads(event) -> None:
        toggle_threads(state)
        event.app.create_background_task(refresh_state(state))

    @key_bindings.add("tab", eager=True)
    def _focus_next(event) -> None:
        event.app.layout.focus_next()

    @key_bindings.add("s-tab", eager=True)
    def _focus_previous(event) -> None:
        event.app.layout.focus_previous()

    @key_bindings.add("up")
    def _up(event) -> None:
        current_window = event.app.layout.current_window
        if current_window is input_window:
            return
        if current_window is rooms_window:
            previous_index = state.current_room_index
            move_room_selection(state, -1)
            if state.current_room_index != previous_index:
                event.app.create_background_task(refresh_state(state))
            return
        if current_window is threads_window:
            move_thread_selection(state, -1)
            return
        if current_window is messages_window:
            current_window.vertical_scroll = max(0, current_window.vertical_scroll - 1)

    @key_bindings.add("down")
    def _down(event) -> None:
        current_window = event.app.layout.current_window
        if current_window is input_window:
            return
        if current_window is rooms_window:
            previous_index = state.current_room_index
            move_room_selection(state, 1)
            if state.current_room_index != previous_index:
                event.app.create_background_task(refresh_state(state))
            return
        if current_window is threads_window:
            move_thread_selection(state, 1)
            return
        if current_window is messages_window:
            current_window.vertical_scroll += 1

    @key_bindings.add("escape")
    def _leave_thread(event) -> None:
        if state.active_thread_root_id:
            clear_active_thread(state)
            event.app.create_background_task(refresh_state(state))

    @key_bindings.add("enter", filter=has_focus(threads_window))
    def _enter_thread(event) -> None:
        activate_selected_thread(state)
        event.app.create_background_task(refresh_state(state))

    return key_bindings


def build_tui_application(state: TuiState) -> Application[None]:
    """Build a full-screen prompt_toolkit application."""
    rooms_window = Window(
        FormattedTextControl(lambda: format_rooms_text(state), focusable=True),
        always_hide_cursor=True,
        wrap_lines=False,
    )
    threads_window = Window(
        FormattedTextControl(lambda: format_threads_text(state), focusable=True),
        always_hide_cursor=True,
        wrap_lines=False,
    )
    messages_window = Window(
        FormattedTextControl(lambda: format_messages_text(state), focusable=True),
        always_hide_cursor=True,
        wrap_lines=True,
    )

    def _accept_input(buffer: Buffer) -> bool:
        get_app().create_background_task(send_current_message(state, buffer.text))
        return False

    input_buffer = Buffer(multiline=False, accept_handler=_accept_input)
    input_control = BufferControl(
        buffer=input_buffer,
        focusable=True,
        input_processors=[BeforeInput("> ")],
    )
    input_window = Window(content=input_control, height=1)

    root_container = HSplit(
        [
            Window(
                FormattedTextControl(lambda: format_header_text(state)),
                height=1,
                style="class:header",
            ),
            VSplit(
                [
                    HSplit(
                        [
                            Frame(rooms_window, title="Rooms"),
                            Frame(threads_window, title="Threads"),
                        ],
                        width=38,
                    ),
                    Frame(messages_window, title="Messages"),
                ]
            ),
            Frame(input_window, title="Type a message... (@mention for agents)", height=3),
            Window(
                FormattedTextControl(lambda: format_footer_text(state)),
                height=1,
                style="class:footer",
            ),
        ]
    )

    style = Style.from_dict(
        {
            "header": "reverse bold",
            "footer": "reverse",
            "frame.label": "bold",
        }
    )

    key_bindings = create_key_bindings(
        state=state,
        rooms_window=rooms_window,
        threads_window=threads_window,
        messages_window=messages_window,
        input_window=input_window,
    )

    application = Application(
        layout=Layout(root_container, focused_element=input_window),
        key_bindings=key_bindings,
        style=style,
        full_screen=True,
        mouse_support=False,
    )
    state.invalidate = application.invalidate
    return application


async def run_tui(
    username: str | None = None,
    password: str | None = None,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Run the prompt_toolkit TUI."""
    config = _load_config()
    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        console.print("[red]Username and password required[/red]")
        return

    client = await _create_client(config)
    state = TuiState(client=client, username=config.username, poll_interval=poll_interval)

    try:
        if not await _login(client, config.password):
            console.print("[red]Login failed[/red]")
            return

        await refresh_state(state)
        application = build_tui_application(state)

        def _start_background_tasks() -> None:
            application.create_background_task(poll_for_updates(state))

        await application.run_async(pre_run=_start_background_tasks)
    finally:
        state.running = False
        await client.close()
