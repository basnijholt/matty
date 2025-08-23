#!/usr/bin/env python3
"""Functional Matrix client - minimal classes, maximum functions."""

import asyncio
import json
import os
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import typer
from dotenv import load_dotenv
from nio import (
    AsyncClient,
    ErrorResponse,
    ReactionEvent,
    RedactedEvent,
    RoomMessageText,
)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    help="Functional Matrix CLI client",
    no_args_is_help=True,  # Show help when no command is provided
    context_settings={"help_option_names": ["-h", "--help"]},  # Add -h short option
)
console = Console()

# Global ID mapping storage
ID_MAP_FILE = Path.home() / ".matrix_cli_ids.json"
_id_counter = 0
_id_to_matrix: dict[int, str] = {}
_matrix_to_id: dict[str, int] = {}


# =============================================================================
# ID Mapping Functions
# =============================================================================


def _load_id_mappings() -> None:
    """Load ID mappings from persistent storage."""
    global _id_counter, _id_to_matrix, _matrix_to_id  # noqa: PLW0603

    if ID_MAP_FILE.exists():
        try:
            with ID_MAP_FILE.open() as f:
                data = json.load(f)
                _id_counter = data.get("counter", 0)
                _id_to_matrix = {
                    int(k): v for k, v in data.get("id_to_matrix", {}).items()
                }
                _matrix_to_id = data.get("matrix_to_id", {})
        except Exception as e:
            console.print(f"[yellow]Warning: Could not load ID mappings: {e}[/yellow]")


def _save_id_mappings() -> None:
    """Save ID mappings to persistent storage."""
    try:
        data = {
            "counter": _id_counter,
            "id_to_matrix": _id_to_matrix,
            "matrix_to_id": _matrix_to_id,
        }
        with ID_MAP_FILE.open("w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not save ID mappings: {e}[/yellow]")


def _get_or_create_id(matrix_id: str) -> int:
    """Get existing simple ID or create new one for a Matrix ID."""
    global _id_counter  # noqa: PLW0603

    if not _id_to_matrix:  # First run, load from disk
        _load_id_mappings()

    if matrix_id in _matrix_to_id:
        return _matrix_to_id[matrix_id]

    # Create new mapping
    _id_counter += 1
    simple_id = _id_counter
    _id_to_matrix[simple_id] = matrix_id
    _matrix_to_id[matrix_id] = simple_id

    # Save immediately to persist
    _save_id_mappings()

    return simple_id


def _resolve_id(id_or_matrix: str) -> str | None:
    """Resolve a simple ID or Matrix ID to a Matrix ID."""
    if not _id_to_matrix:  # First run, load from disk
        _load_id_mappings()

    # Check if it's a simple ID (just a number)
    try:
        simple_id = int(id_or_matrix)
        return _id_to_matrix.get(simple_id)
    except ValueError:
        pass

    # Check if it's a Matrix ID (starts with $ or !)
    if id_or_matrix.startswith(("$", "!")):
        return id_or_matrix

    return None


def _resolve_thread_id(thread_id: str) -> tuple[str | None, str | None]:
    """Resolve thread ID (t1, t2, etc.) to Matrix ID.

    Returns:
        tuple: (resolved_id, error_message) where error_message is None on success
    """
    if thread_id.startswith("t"):
        try:
            simple_id = int(thread_id[1:])
            resolved_id = _resolve_id(str(simple_id))
            if resolved_id:
                return resolved_id, None
            return None, f"[red]Thread ID {thread_id} not found[/red]"  # noqa: TRY300
        except ValueError:
            return None, f"[red]Invalid thread ID format: {thread_id}[/red]"
    else:
        return thread_id, None


# =============================================================================
# Response Handling Helper
# =============================================================================


def _is_success_response(response: any) -> bool:
    """Check if a Matrix client response indicates success.

    The nio library returns different types for success/failure:
    - Success: Specific response classes (LoginResponse, RoomSendResponse, etc.)
    - Failure: ErrorResponse or exceptions

    This helper standardizes the checking.
    """

    return response is not None and not isinstance(response, ErrorResponse)


# =============================================================================
# CLI Helper Functions
# =============================================================================


def _validate_required_args(ctx: typer.Context, **kwargs) -> None:
    """Validate that required arguments are not None. Show help and exit if any are missing.

    Args:
        ctx: Typer context for showing help
        **kwargs: Named arguments to check (name=value pairs)
    """
    if any(v is None for v in kwargs.values()):
        console.print(ctx.get_help())
        raise typer.Exit(1)


# =============================================================================
# Data Models (using dataclasses instead of Pydantic for simplicity)
# =============================================================================


@dataclass
class Config:
    """Configuration from environment."""

    homeserver: str = "https://matrix.org"
    username: str | None = None
    password: str | None = None
    ssl_verify: bool = True


@dataclass
class Room:
    """Room information."""

    room_id: str
    name: str
    member_count: int
    topic: str | None = None
    users: list[str] = field(default_factory=list)


@dataclass
class Message:
    """Message data."""

    sender: str
    content: str
    timestamp: datetime
    room_id: str
    event_id: str | None = None
    thread_root_id: str | None = None  # ID of the root message if this is in a thread
    reply_to_id: str | None = None  # ID of message this replies to
    is_thread_root: bool = False  # True if this message started a thread
    reactions: dict[str, list[str]] = field(
        default_factory=dict
    )  # emoji -> list of users who reacted


class OutputFormat(str, Enum):
    """Output formats."""

    rich = "rich"
    simple = "simple"
    json = "json"


# =============================================================================
# Private Helper Functions
# =============================================================================


def _load_config() -> Config:
    """Load configuration from environment variables."""

    load_dotenv()

    return Config(
        homeserver=os.getenv("MATRIX_HOMESERVER", "https://matrix.org"),
        username=os.getenv("MATRIX_USERNAME"),
        password=os.getenv("MATRIX_PASSWORD"),
        ssl_verify=os.getenv("MATRIX_SSL_VERIFY", "true").lower() != "false",
    )


async def _create_client(config: Config) -> AsyncClient:
    """Create a Matrix client instance."""
    return AsyncClient(config.homeserver, config.username, ssl=config.ssl_verify)


async def _login(client: AsyncClient, password: str) -> bool:
    """Perform Matrix login."""
    try:
        response = await client.login(password)
        if _is_success_response(response):
            return True
        console.print(f"[red]Login failed: {response}[/red]")
        return False  # noqa: TRY300
    except Exception as e:
        console.print(f"[red]Login error: {e}[/red]")
        return False


async def _sync_client(client: AsyncClient, timeout: int = 10000) -> None:
    """Sync client with server."""
    await client.sync(timeout=timeout)


async def _get_rooms(client: AsyncClient) -> list[Room]:
    """Get list of rooms from client."""
    await _sync_client(client)

    rooms = []
    for room_id, matrix_room in client.rooms.items():
        rooms.append(
            Room(
                room_id=room_id,
                name=matrix_room.display_name or room_id,
                member_count=len(matrix_room.users),
                topic=matrix_room.topic,
                users=list(matrix_room.users.keys()),
            )
        )

    return rooms


async def _find_room(client: AsyncClient, room_query: str) -> tuple[str, str] | None:
    """Find room by ID or name. Returns (room_id, room_name) or None."""
    rooms = await _get_rooms(client)

    for room in rooms:
        if room_query == room.room_id or room_query.lower() == room.name.lower():
            return room.room_id, room.name

    return None


async def _get_messages(
    client: AsyncClient, room_id: str, limit: int = 20
) -> list[Message]:
    """Fetch messages from a room, including thread information and reactions."""
    try:
        response = await client.room_messages(room_id, limit=limit)

        messages = []
        thread_roots = set()  # Track which messages have threads
        reactions_map = {}  # event_id -> {emoji: [users]}

        for event in response.chunk:
            if isinstance(event, RoomMessageText):
                # Check if this message is part of a thread
                thread_root_id = None
                reply_to_id = None

                # Check for thread relation
                content = event.source.get("content", {})
                if "m.relates_to" in content:
                    relates_to = content["m.relates_to"]

                    # Thread relation
                    if relates_to.get("rel_type") == "m.thread":
                        thread_root_id = relates_to.get("event_id")
                        thread_roots.add(thread_root_id)

                    # Reply relation (in thread or main timeline)
                    if "m.in_reply_to" in relates_to:
                        reply_to_id = relates_to["m.in_reply_to"].get("event_id")

                messages.append(
                    Message(
                        sender=event.sender,
                        content=event.body,
                        timestamp=datetime.fromtimestamp(
                            event.server_timestamp / 1000, tz=UTC
                        ),
                        room_id=room_id,
                        event_id=event.event_id,
                        thread_root_id=thread_root_id,
                        reply_to_id=reply_to_id,
                        is_thread_root=False,  # Will update after
                        reactions={},  # Will populate below
                    )
                )
            # Handle redacted/deleted messages
            elif isinstance(event, RedactedEvent):
                messages.append(
                    Message(
                        sender=event.sender,
                        content="[Message deleted]",
                        timestamp=datetime.fromtimestamp(
                            event.server_timestamp / 1000, tz=UTC
                        ),
                        room_id=room_id,
                        event_id=event.event_id,
                        thread_root_id=None,
                        reply_to_id=None,
                        is_thread_root=False,
                        reactions={},
                    )
                )
            # Handle reaction events
            elif isinstance(event, ReactionEvent):
                # ReactionEvent has: reacts_to (event_id), key (emoji), sender
                if event.reacts_to and event.key:
                    target_event_id = event.reacts_to
                    emoji = event.key
                    sender = event.sender

                    if target_event_id and emoji and sender:
                        if target_event_id not in reactions_map:
                            reactions_map[target_event_id] = {}
                        if emoji not in reactions_map[target_event_id]:
                            reactions_map[target_event_id][emoji] = []
                        if sender not in reactions_map[target_event_id][emoji]:
                            reactions_map[target_event_id][emoji].append(sender)

        # Mark thread roots and add reactions
        for msg in messages:
            if msg.event_id in thread_roots:
                msg.is_thread_root = True
            if msg.event_id in reactions_map:
                msg.reactions = reactions_map[msg.event_id]

        return list(reversed(messages))

    except Exception as e:
        console.print(f"[red]Failed to get messages: {e}[/red]")
        return []


async def _get_threads(
    client: AsyncClient, room_id: str, limit: int = 50
) -> list[Message]:
    """Get all thread root messages in a room."""
    messages = await _get_messages(client, room_id, limit)
    return [msg for msg in messages if msg.is_thread_root]


async def _get_thread_messages(
    client: AsyncClient, room_id: str, thread_id: str, limit: int = 50
) -> list[Message]:
    """Get all messages in a specific thread."""
    messages = await _get_messages(client, room_id, limit)

    # Find the thread root
    thread_messages = [
        msg for msg in messages if thread_id in (msg.event_id, msg.thread_root_id)
    ]

    return sorted(thread_messages, key=lambda m: m.timestamp)


def _parse_mentions(
    message: str, room_users: list[str]
) -> tuple[str, str | None, list[str]]:
    """Parse @mentions in message and return (body, formatted_body, mentioned_user_ids).

    Handles:
    - @username -> finds matching Matrix user ID
    - @user:server.com -> uses full Matrix ID directly

    Returns:
        Tuple of (body, formatted_body, list of mentioned user IDs)
    """
    formatted_body = None
    body = message
    mentioned_user_ids = []

    # Find all @mentions in the message
    mention_pattern = r"@(\S+)"
    mentions = re.findall(mention_pattern, message)

    if mentions:
        formatted_body = message
        for mention in mentions:
            user_id = None

            # Check if it's already a full Matrix ID
            if ":" in mention:
                user_id = f"@{mention}"
            else:
                # Try to find a matching user in the room
                for room_user in room_users:
                    # Match by local part (before :) or display name
                    if (
                        room_user.startswith(f"@{mention}:")
                        or mention.lower() in room_user.lower()
                    ):
                        user_id = room_user
                        break

            if user_id:
                mentioned_user_ids.append(user_id)
                # Create the mention HTML
                mention_html = f'<a href="https://matrix.to/#/{user_id}">{user_id}</a>'
                formatted_body = formatted_body.replace(f"@{mention}", mention_html)

        # Only return formatted_body if we actually found valid mentions
        if mentioned_user_ids:
            return body, formatted_body, mentioned_user_ids

    return body, None, []


async def _send_message(
    client: AsyncClient,
    room_id: str,
    message: str,
    thread_root_id: str | None = None,
    reply_to_id: str | None = None,
) -> bool:
    """Send a message to a room, optionally as a thread reply or regular reply."""
    try:
        # Get room users for mention parsing
        room = client.rooms.get(room_id)
        room_users = list(room.users.keys()) if room else []

        # Parse mentions
        body, formatted_body, mentioned_user_ids = _parse_mentions(message, room_users)

        content = {"msgtype": "m.text", "body": body}

        # Add formatted body if we have mentions
        if formatted_body:
            content["format"] = "org.matrix.custom.html"
            content["formatted_body"] = formatted_body

        # Add m.mentions field if we have any mentions
        if mentioned_user_ids:
            content["m.mentions"] = {"user_ids": mentioned_user_ids}

        # Add thread or reply relations
        if thread_root_id or reply_to_id:
            content["m.relates_to"] = {}

            if thread_root_id:
                # Thread reply
                content["m.relates_to"]["rel_type"] = "m.thread"
                content["m.relates_to"]["event_id"] = thread_root_id

            if reply_to_id:
                # Reply to specific message
                content["m.relates_to"]["m.in_reply_to"] = {"event_id": reply_to_id}

        response = await client.room_send(
            room_id, message_type="m.room.message", content=content
        )
        if _is_success_response(response):
            return True
        console.print(f"[red]Failed to send message: {response}[/red]")
        return False  # noqa: TRY300
    except Exception as e:
        console.print(f"[red]Failed to send: {e}[/red]")
        return False


async def _send_reaction(
    client: AsyncClient,
    room_id: str,
    event_id: str,
    emoji: str,
) -> bool:
    """Send a reaction to a message."""
    try:
        content = {
            "m.relates_to": {
                "rel_type": "m.annotation",
                "event_id": event_id,
                "key": emoji,
            }
        }

        response = await client.room_send(
            room_id, message_type="m.reaction", content=content
        )
        if _is_success_response(response):
            return True
        console.print(f"[red]Failed to send reaction: {response}[/red]")
        return False  # noqa: TRY300
    except Exception as e:
        console.print(f"[red]Failed to send reaction: {e}[/red]")
        return False


async def _remove_reaction(
    client: AsyncClient,
    room_id: str,
    reaction_event_id: str | None = None,
) -> bool:
    """Remove a reaction from a message.

    Note: In Matrix, you remove a reaction by redacting the reaction event.
    This requires finding the reaction event ID first.
    """
    try:
        # If we don't have the reaction event ID, we need to find it
        # This is a limitation - we'd need to track reaction event IDs
        # For now, we'll just inform that removal needs the reaction event ID
        if not reaction_event_id:
            console.print(
                "[yellow]Note: Removing reactions requires tracking reaction event IDs.[/yellow]"
            )
            return False

        response = await client.room_redact(room_id, reaction_event_id)
        if _is_success_response(response):
            return True
        console.print(f"[red]Failed to remove reaction: {response}[/red]")
        return False  # noqa: TRY300
    except Exception as e:
        console.print(f"[red]Failed to remove reaction: {e}[/red]")
        return False


async def _get_message_by_handle(
    client: AsyncClient, room_id: str, handle: str, limit: int = 20
) -> Message | None:
    """Get a message by its handle (m1, m2, etc.) from recent messages."""
    # Extract number from handle (m1 -> 1)
    try:
        idx = int(handle[1:]) - 1 if handle.startswith("m") else int(handle) - 1
    except ValueError:
        return None

    messages = await _get_messages(client, room_id, limit)
    if 0 <= idx < len(messages):
        return messages[idx]
    return None


# =============================================================================
# Display Functions
# =============================================================================


def _display_rooms_rich(rooms: list[Room]) -> None:
    """Display rooms in rich table format."""
    table = Table(title="Matrix Rooms", show_lines=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("Room Name", style="green")
    table.add_column("Room ID", style="dim")
    table.add_column("Members", style="yellow")

    for idx, room in enumerate(rooms, 1):
        table.add_row(str(idx), room.name, room.room_id, str(room.member_count))

    console.print(table)


def _display_rooms_simple(rooms: list[Room]) -> None:
    """Display rooms in simple text format."""
    for room in rooms:
        print(f"{room.name} ({room.room_id}) - {room.member_count} members")


def _display_rooms_json(rooms: list[Room]) -> None:
    """Display rooms in JSON format."""
    print(json.dumps([asdict(room) for room in rooms], indent=2, default=str))


def _display_messages_rich(messages: list[Message], room_name: str) -> None:
    """Display messages in rich format with thread indicators, message handles, and reactions."""
    console.print(Panel(f"[bold cyan]{room_name}[/bold cyan]", expand=False))

    for idx, msg in enumerate(messages, 1):
        time_str = msg.timestamp.strftime("%H:%M")
        prefix = ""

        # Add thread indicators
        if msg.is_thread_root:
            # Get simple ID for thread
            if msg.event_id:
                thread_simple_id = _get_or_create_id(msg.event_id)
                prefix = f"[bold yellow]🧵 t{thread_simple_id}[/bold yellow] "
            else:
                prefix = "[bold yellow]🧵[/bold yellow] "
        elif msg.thread_root_id:
            # Show which thread this message belongs to
            thread_simple_id = _get_or_create_id(msg.thread_root_id)
            prefix = f"  ↳ [dim yellow]t{thread_simple_id}[/dim yellow] "

        # Create a short handle for the message (m1, m2, etc.)
        handle = f"[bold magenta]m{idx}[/bold magenta]"

        # Show the message with handle
        console.print(
            f"{handle} {prefix}[dim]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}"
        )

        # Show reactions if any
        if msg.reactions:
            reaction_str = " ".join(
                f"{emoji} {len(users)}" for emoji, users in msg.reactions.items()
            )
            console.print(f"    [dim]Reactions: {reaction_str}[/dim]")

    # Show available actions
    if messages:
        console.print(
            "\n[dim]Use handles (m1, m2, etc.) or thread IDs (t1, t2, etc.) with commands[/dim]"
        )


def _display_messages_simple(messages: list[Message], room_name: str) -> None:
    """Display messages in simple format with handles and reactions."""
    print(f"=== {room_name} ===")
    for idx, msg in enumerate(messages, 1):
        time_str = msg.timestamp.strftime("%H:%M")
        handle = f"m{idx}"
        thread_mark = ""
        if msg.is_thread_root and msg.event_id:
            thread_simple_id = _get_or_create_id(msg.event_id)
            thread_mark = f" [THREAD t{thread_simple_id}]"
        elif msg.thread_root_id:
            thread_simple_id = _get_or_create_id(msg.thread_root_id)
            thread_mark = f" [IN-THREAD t{thread_simple_id}]"
        print(f"{handle} [{time_str}] {msg.sender}: {msg.content}{thread_mark}")

        # Show reactions if any
        if msg.reactions:
            reaction_str = " ".join(
                f"{emoji}:{len(users)}" for emoji, users in msg.reactions.items()
            )
            print(f"    Reactions: {reaction_str}")


def _display_messages_json(messages: list[Message], room_name: str) -> None:
    """Display messages in JSON format."""
    data = {"room": room_name, "messages": [asdict(msg) for msg in messages]}
    print(json.dumps(data, indent=2, default=str))


def _display_users_rich(users: list[str], room_name: str) -> None:
    """Display users in rich table format."""
    table = Table(title=f"Users in {room_name}", show_lines=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("User ID", style="green")
    table.add_column("Mention", style="yellow")

    for idx, user in enumerate(users, 1):
        # Extract username for mention (part before :)
        if user.startswith("@") and ":" in user:
            mention = "@" + user.split(":")[0][1:]
        else:
            mention = user
        table.add_row(str(idx), user, mention)

    console.print(table)
    console.print(
        "\n[dim]Use mentions in messages: matty send room '@username message'[/dim]"
    )


def _display_users_simple(users: list[str], room_name: str) -> None:
    """Display users in simple format."""
    print(f"=== Users in {room_name} ===")
    for user in users:
        print(user)


def _display_users_json(users: list[str], room_name: str) -> None:
    """Display users in JSON format."""
    print(json.dumps({"room": room_name, "users": users}, indent=2))


# =============================================================================
# Main Command Functions
# =============================================================================


async def _execute_rooms_command(
    username: str | None = None,
    password: str | None = None,
    format: OutputFormat = OutputFormat.rich,
) -> None:
    """Execute the rooms command."""
    config = _load_config()

    # Override with command line args if provided
    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        console.print("[red]Username and password required[/red]")
        return

    client = await _create_client(config)

    try:
        if await _login(client, config.password):
            rooms = await _get_rooms(client)

            if format == OutputFormat.rich:
                _display_rooms_rich(rooms)
            elif format == OutputFormat.simple:
                _display_rooms_simple(rooms)
            elif format == OutputFormat.json:
                _display_rooms_json(rooms)
    finally:
        await client.close()


async def _execute_messages_command(
    room: str,
    limit: int = 20,
    username: str | None = None,
    password: str | None = None,
    format: OutputFormat = OutputFormat.rich,
) -> None:
    """Execute the messages command."""
    config = _load_config()

    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        console.print("[red]Username and password required[/red]")
        return

    client = await _create_client(config)

    try:
        if await _login(client, config.password):
            room_info = await _find_room(client, room)

            if not room_info:
                console.print(f"[red]Room '{room}' not found[/red]")
                return

            room_id, room_name = room_info
            messages = await _get_messages(client, room_id, limit)

            if format == OutputFormat.rich:
                _display_messages_rich(messages, room_name)
            elif format == OutputFormat.simple:
                _display_messages_simple(messages, room_name)
            elif format == OutputFormat.json:
                _display_messages_json(messages, room_name)
    finally:
        await client.close()


async def _execute_users_command(
    room: str,
    username: str | None = None,
    password: str | None = None,
    format: OutputFormat = OutputFormat.rich,
) -> None:
    """Execute the users command."""
    config = _load_config()

    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        console.print("[red]Username and password required[/red]")
        return

    client = await _create_client(config)

    try:
        if await _login(client, config.password):
            rooms = await _get_rooms(client)

            # Find the room
            target_room = None
            for r in rooms:
                if room == r.room_id or room.lower() in r.name.lower():
                    target_room = r
                    break

            if not target_room:
                console.print(f"[red]Room '{room}' not found[/red]")
                return

            if format == OutputFormat.rich:
                _display_users_rich(target_room.users, target_room.name)
            elif format == OutputFormat.simple:
                _display_users_simple(target_room.users, target_room.name)
            elif format == OutputFormat.json:
                _display_users_json(target_room.users, target_room.name)
    finally:
        await client.close()


async def _execute_send_command(
    room: str,
    message: str,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Execute the send command."""
    config = _load_config()

    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        console.print("[red]Username and password required[/red]")
        return

    client = await _create_client(config)

    try:
        if await _login(client, config.password):
            # Sync to get room users for mentions
            await _sync_client(client)

            room_info = await _find_room(client, room)

            if not room_info:
                console.print(f"[red]Room '{room}' not found[/red]")
                return

            room_id, room_name = room_info

            if await _send_message(client, room_id, message):
                console.print(f"[green]✓ Message sent to {room_name}[/green]")
                if "@" in message:
                    console.print("[dim]Note: Mentions were processed[/dim]")
            else:
                console.print("[red]✗ Failed to send message[/red]")
    finally:
        await client.close()


# =============================================================================
# DRY Helper Functions for CLI Commands
# =============================================================================


@asynccontextmanager
async def _with_client(username: str | None = None, password: str | None = None):
    """Context manager that handles client creation, login, and cleanup.

    Yields:
        tuple[AsyncClient, str, str]: (client, username, password)
    """
    config = _load_config()
    if username:
        config.username = username
    if password:
        config.password = password

    if not config.username or not config.password:
        console.print("[red]Username and password required[/red]")
        yield None, None, None
        return

    client = await _create_client(config)

    try:
        if await _login(client, config.password):
            yield client, config.username, config.password
        else:
            console.print("[red]Login failed[/red]")
            yield None, None, None
    finally:
        await client.close()


@asynccontextmanager
async def _with_client_in_room(
    room: str,
    username: str | None = None,
    password: str | None = None,
    sync: bool = False,
):
    """Context manager that handles client creation, login, room finding, and cleanup.

    Args:
        room: Room ID or name to find
        username: Optional username override
        password: Optional password override
        sync: Whether to sync client before finding room (needed for mentions)

    Yields:
        tuple[AsyncClient, str, str]: (client, room_id, room_name)
    """
    async with _with_client(username, password) as (client, user, pwd):
        if client is None:
            yield None, None, None
            return

        if sync:
            await _sync_client(client)

        room_info = await _find_room(client, room)

        if not room_info:
            console.print(f"[red]Room '{room}' not found[/red]")
            yield None, None, None
            return

        room_id, room_name = room_info
        yield client, room_id, room_name


async def _run_with_room(
    room: str,
    action: Callable,
    username: str | None = None,
    password: str | None = None,
    sync: bool = False,
):
    """Run an action with a client connected to a specific room.

    Args:
        room: Room ID or name
        action: Async function to run with (client, room_id, room_name) arguments
        username: Optional username override
        password: Optional password override
        sync: Whether to sync client before finding room
    """
    async with _with_client_in_room(room, username, password, sync) as (
        client,
        room_id,
        room_name,
    ):
        if client is not None:
            await action(client, room_id, room_name)


# =============================================================================
# CLI Commands
# =============================================================================


@app.command("rooms")
@app.command("r", hidden=True)
def rooms(
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f"),
):
    """List all joined rooms. (alias: r)"""
    asyncio.run(_execute_rooms_command(username, password, format))


@app.command("messages")
@app.command("m", hidden=True)
def messages(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    limit: int = typer.Option(20, "--limit", "-l"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f"),
):
    """Show recent messages from a room. (alias: m)"""
    _validate_required_args(ctx, room=room)
    asyncio.run(_execute_messages_command(room, limit, username, password, format))


@app.command("users")
@app.command("u", hidden=True)
def users(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f"),
):
    """Show users in a room. (alias: u)"""
    _validate_required_args(ctx, room=room)
    asyncio.run(_execute_users_command(room, username, password, format))


@app.command("send")
@app.command("s", hidden=True)
def send(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    message: str = typer.Argument(
        None, help="Message to send (use @username for mentions)"
    ),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Send a message to a room. Supports @mentions. (alias: s)"""
    _validate_required_args(ctx, room=room, message=message)
    asyncio.run(_execute_send_command(room, message, username, password))


@app.command("threads")
@app.command("t", hidden=True)
def threads(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    limit: int = typer.Option(50, "--limit", "-l", help="Number of messages to check"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f"),
):
    """List all threads in a room. (alias: t)"""
    _validate_required_args(ctx, room=room)

    async def _threads():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            threads = await _get_threads(client, room_id, limit)

            if not threads:
                console.print(f"[yellow]No threads found in {room_name}[/yellow]")
                return

            if format == OutputFormat.rich:
                table = Table(title=f"Threads in {room_name}", show_lines=True)
                table.add_column("ID", style="bold yellow", width=6)
                table.add_column("Time", style="dim", width=8)
                table.add_column("Author", style="cyan")
                table.add_column("Thread Start", style="green")

                for thread in threads:
                    time_str = thread.timestamp.strftime("%H:%M")
                    # Truncate content for display
                    content = (
                        thread.content[:50] + "..."
                        if len(thread.content) > 50
                        else thread.content
                    )
                    # Get simple ID for thread
                    simple_id = (
                        _get_or_create_id(thread.event_id) if thread.event_id else "?"
                    )
                    table.add_row(f"t{simple_id}", time_str, thread.sender, content)

                console.print(table)

            elif format == OutputFormat.simple:
                print(f"=== Threads in {room_name} ===")
                for thread in threads:
                    time_str = thread.timestamp.strftime("%H:%M")
                    print(
                        f"[{time_str}] {thread.sender}: {thread.content[:50]}... (ID: {thread.event_id})"
                    )

            elif format == OutputFormat.json:
                print(
                    json.dumps(
                        {
                            "room": room_name,
                            "threads": [asdict(thread) for thread in threads],
                        },
                        indent=2,
                        default=str,
                    )
                )

    asyncio.run(_threads())


@app.command("thread")
@app.command("th", hidden=True)
def thread(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    thread_id: str = typer.Argument(
        None, help="Thread ID (t1, t2, etc.) or full Matrix ID"
    ),
    limit: int = typer.Option(50, "--limit", "-l", help="Number of messages to fetch"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f"),
):
    """Show all messages in a specific thread. (alias: th)"""
    _validate_required_args(ctx, room=room, thread_id=thread_id)

    async def _thread():
        # Resolve thread ID if it's a simple ID (t1, t2, etc.)
        actual_thread_id, error_msg = _resolve_thread_id(thread_id)
        if error_msg:
            console.print(error_msg)
            return

        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            thread_messages = await _get_thread_messages(
                client, room_id, actual_thread_id, limit
            )

            if not thread_messages:
                console.print(
                    f"[yellow]No messages found in thread {thread_id}[/yellow]"
                )
                return

            if format == OutputFormat.rich:
                console.print(
                    Panel(
                        f"[bold cyan]Thread in {room_name}[/bold cyan]",
                        expand=False,
                    )
                )

                for msg in thread_messages:
                    time_str = msg.timestamp.strftime("%H:%M")
                    if msg.event_id == actual_thread_id:
                        # Thread root
                        console.print("[bold yellow]🧵 Thread Start[/bold yellow]")
                        console.print(
                            f"[dim]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}"
                        )
                    else:
                        # Thread reply
                        console.print(
                            f"  ↳ [dim]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}"
                        )

            elif format == OutputFormat.simple:
                print(f"=== Thread in {room_name} ===")
                for msg in thread_messages:
                    time_str = msg.timestamp.strftime("%H:%M")
                    prefix = (
                        "THREAD START: " if msg.event_id == actual_thread_id else "  > "
                    )
                    print(f"{prefix}[{time_str}] {msg.sender}: {msg.content}")

            elif format == OutputFormat.json:
                print(
                    json.dumps(
                        {
                            "room": room_name,
                            "thread_id": thread_id,
                            "messages": [asdict(msg) for msg in thread_messages],
                        },
                        indent=2,
                        default=str,
                    )
                )

    asyncio.run(_thread())


@app.command("reply")
@app.command("re", hidden=True)
def reply(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(
        None, help="Message handle (m1, m2, etc.) to reply to"
    ),
    message: str = typer.Argument(None, help="Reply message"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Reply to a specific message using its handle. (alias: re)"""
    _validate_required_args(ctx, room=room, handle=handle, message=message)

    async def _reply():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Get the message to reply to
            target_msg = await _get_message_by_handle(client, room_id, handle)

            if not target_msg:
                console.print(f"[red]Message {handle} not found[/red]")
                return

            # Send reply
            if await _send_message(
                client, room_id, message, reply_to_id=target_msg.event_id
            ):
                console.print(f"[green]✓ Reply sent to {handle} in {room_name}[/green]")
            else:
                console.print("[red]✗ Failed to send reply[/red]")

    asyncio.run(_reply())


@app.command("thread-start")
@app.command("ts", hidden=True)
def thread_start(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(
        None, help="Message handle (m1, m2, etc.) to start thread from"
    ),
    message: str = typer.Argument(None, help="First message in the thread"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Start a new thread from a message using its handle. (alias: ts)"""
    _validate_required_args(ctx, room=room, handle=handle, message=message)

    async def _thread_start():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Get the message to start thread from
            target_msg = await _get_message_by_handle(client, room_id, handle)

            if not target_msg:
                console.print(f"[red]Message {handle} not found[/red]")
                return

            # Send thread message
            if await _send_message(
                client, room_id, message, thread_root_id=target_msg.event_id
            ):
                console.print(
                    f"[green]✓ Thread started from {handle} in {room_name}[/green]"
                )
                console.print(f"[dim]Thread ID: {target_msg.event_id}[/dim]")
            else:
                console.print("[red]✗ Failed to start thread[/red]")

    asyncio.run(_thread_start())


@app.command("thread-reply")
@app.command("tr", hidden=True)
def thread_reply(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    thread_id: str = typer.Argument(
        None, help="Thread ID (t1, t2, etc.) or full Matrix ID"
    ),
    message: str = typer.Argument(None, help="Reply message"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Reply within an existing thread. (alias: tr)"""
    _validate_required_args(ctx, room=room, thread_id=thread_id, message=message)

    async def _thread_reply():
        # Resolve thread ID if it's a simple ID (t1, t2, etc.)
        actual_thread_id, error_msg = _resolve_thread_id(thread_id)
        if error_msg:
            console.print(error_msg)
            return

        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Send thread reply
            if await _send_message(
                client, room_id, message, thread_root_id=actual_thread_id
            ):
                console.print(f"[green]✓ Reply sent to thread in {room_name}[/green]")
            else:
                console.print("[red]✗ Failed to send thread reply[/red]")

    asyncio.run(_thread_reply())


@app.command("react")
@app.command("rx", hidden=True)
def react(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(
        None, help="Message handle (m1, m2, etc.) to react to"
    ),
    emoji: str = typer.Argument(None, help="Emoji reaction (e.g., 👍, ❤️, 😄)"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Add a reaction to a message using its handle. (alias: rx)"""
    _validate_required_args(ctx, room=room, handle=handle, emoji=emoji)

    async def _react():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Get the message to react to
            target_msg = await _get_message_by_handle(client, room_id, handle)

            if not target_msg:
                console.print(f"[red]Message {handle} not found[/red]")
                return

            if not target_msg.event_id:
                console.print(f"[red]Message {handle} has no event ID[/red]")
                return

            # Send reaction
            if await _send_reaction(client, room_id, target_msg.event_id, emoji):
                console.print(
                    f"[green]✓ Reacted with {emoji} to {handle} in {room_name}[/green]"
                )
            else:
                console.print("[red]✗ Failed to send reaction[/red]")

    asyncio.run(_react())


@app.command("redact")
@app.command("del", hidden=True)
def redact(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(
        None, help="Message handle (m1, m2, etc.) to redact/delete"
    ),
    reason: str = typer.Option(None, "--reason", "-r", help="Reason for redaction"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Delete/redact a message using its handle. (alias: del)"""
    _validate_required_args(ctx, room=room, handle=handle)

    async def _redact():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Get the message to redact
            target_msg = await _get_message_by_handle(client, room_id, handle)

            if not target_msg:
                console.print(f"[red]Message {handle} not found[/red]")
                return

            if not target_msg.event_id:
                console.print(f"[red]Message {handle} has no event ID[/red]")
                return

            # Redact the message
            try:
                response = await client.room_redact(
                    room_id, target_msg.event_id, reason=reason
                )
                if _is_success_response(response):
                    console.print(
                        f"[green]✓ Message {handle} redacted in {room_name}[/green]"
                    )
                    if reason:
                        console.print(f"[dim]Reason: {reason}[/dim]")
                else:
                    console.print(f"[red]Failed to redact message: {response}[/red]")
            except Exception as e:
                console.print(f"[red]Failed to redact message: {e}[/red]")

    asyncio.run(_redact())


@app.command("reactions")
@app.command("rxs", hidden=True)
def reactions(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(
        None, help="Message handle (m1, m2, etc.) to show reactions for"
    ),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f"),
):
    """Show detailed reactions for a specific message. (alias: rxs)"""
    _validate_required_args(ctx, room=room, handle=handle)

    async def _reactions():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Get the message
            target_msg = await _get_message_by_handle(client, room_id, handle)

            if not target_msg:
                console.print(f"[red]Message {handle} not found[/red]")
                return

            if not target_msg.reactions:
                console.print(f"[yellow]No reactions on message {handle}[/yellow]")
                return

            if format == OutputFormat.rich:
                table = Table(
                    title=f"Reactions for {handle} in {room_name}", show_lines=True
                )
                table.add_column("Emoji", style="yellow")
                table.add_column("Count", style="cyan")
                table.add_column("Users", style="green")

                for emoji, users in target_msg.reactions.items():
                    user_list = ", ".join(users[:3])
                    if len(users) > 3:
                        user_list += f" ... and {len(users) - 3} more"
                    table.add_row(emoji, str(len(users)), user_list)

                console.print(table)

            elif format == OutputFormat.simple:
                print(f"=== Reactions for {handle} in {room_name} ===")
                for emoji, users in target_msg.reactions.items():
                    print(f"{emoji}: {len(users)} - {', '.join(users)}")

            elif format == OutputFormat.json:
                print(
                    json.dumps(
                        {
                            "room": room_name,
                            "message_handle": handle,
                            "reactions": target_msg.reactions,
                        },
                        indent=2,
                    )
                )

    asyncio.run(_reactions())


if __name__ == "__main__":
    app()
