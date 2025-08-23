#!/usr/bin/env python3
"""Functional Matrix client - minimal classes, maximum functions."""

import asyncio
import json
import os
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import typer
from dotenv import load_dotenv
from nio import (
    AsyncClient,
    ErrorResponse,
    ReactionEvent,
    RedactedEvent,
    RoomMessageText,
)
from pydantic import BaseModel, Field, field_validator
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    help="Functional Matrix CLI client",
    no_args_is_help=True,  # Show help when no command is provided
    context_settings={"help_option_names": ["-h", "--help"]},  # Add -h short option
)
console = Console()


# =============================================================================
# Pydantic Models for State Management
# =============================================================================


class ThreadIdMapping(BaseModel):
    """Thread ID mapping state."""

    counter: int = 0
    id_to_matrix: dict[int, str] = Field(default_factory=dict)
    matrix_to_id: dict[str, int] = Field(default_factory=dict)

    @field_validator("id_to_matrix", mode="before")
    @classmethod
    def convert_keys_to_int(cls, v):
        """Convert string keys to int when loading from JSON."""
        if isinstance(v, dict):
            return {int(k) if isinstance(k, str) else k: val for k, val in v.items()}
        return v


class MessageHandleMapping(BaseModel):
    """Message handle mapping state."""

    handle_counter: dict[str, int] = Field(default_factory=dict)
    room_handles: dict[str, dict[str, str]] = Field(default_factory=dict)
    room_handle_to_event: dict[str, dict[str, str]] = Field(default_factory=dict)


class ServerState(BaseModel):
    """Complete state for a server."""

    thread_ids: ThreadIdMapping = Field(default_factory=ThreadIdMapping)
    message_handles: MessageHandleMapping = Field(default_factory=MessageHandleMapping)


# State storage - single state per matty instance
_state: ServerState | None = None


# =============================================================================
# ID Mapping Functions
# =============================================================================


def _get_state_file(homeserver: str) -> Path:
    """Get the state file path for a server."""
    # Extract domain from server URL
    if homeserver.startswith(("http://", "https://")):
        domain = urlparse(homeserver).netloc
    else:
        domain = homeserver

    # Create state directory if it doesn't exist
    state_dir = Path.home() / ".config" / "matty" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    return state_dir / f"{domain}.json"


def _load_state() -> ServerState:
    """Load or create state for the current server."""
    global _state  # noqa: PLW0603

    # Return cached state if available
    if _state is not None:
        return _state

    # Get the state file for the current server
    config = _load_config()
    state_file = _get_state_file(config.homeserver)

    if state_file.exists():
        with state_file.open() as f:
            _state = ServerState.model_validate(json.load(f))
    else:
        _state = ServerState()

    return _state


def _save_state() -> None:
    """Save the current state."""
    if _state is None:
        return

    config = _load_config()
    state_file = _get_state_file(config.homeserver)

    with state_file.open("w") as f:
        json.dump(_state.model_dump(), f, indent=2)


def _get_or_create_mapping(
    category: str,  # "thread_ids" or "message_handles"
    key: str,  # matrix_id for threads, event_id for handles
    room_id: str | None = None,  # Required for message handles
    prefix: str = "",  # "t" for threads, "m" for messages
) -> str:
    """Generic function to get or create ID mappings.

    Returns the mapped ID (either numeric for threads or handle for messages).
    """
    state = _load_state()

    if category == "thread_ids":
        # Thread ID logic - simple bidirectional mapping
        if key in state.thread_ids.matrix_to_id:
            return f"{prefix}{state.thread_ids.matrix_to_id[key]}"

        state.thread_ids.counter += 1
        simple_id = state.thread_ids.counter
        state.thread_ids.id_to_matrix[simple_id] = key
        state.thread_ids.matrix_to_id[key] = simple_id
        _save_state()
        return f"{prefix}{simple_id}"

    if category == "message_handles" and room_id:
        # Message handle logic - per-room bidirectional mapping
        if room_id not in state.message_handles.room_handles:
            state.message_handles.room_handles[room_id] = {}
            state.message_handles.room_handle_to_event[room_id] = {}
            state.message_handles.handle_counter[room_id] = 0

        if key in state.message_handles.room_handles[room_id]:
            return state.message_handles.room_handles[room_id][key]

        state.message_handles.handle_counter[room_id] += 1
        handle = f"{prefix}{state.message_handles.handle_counter[room_id]}"
        state.message_handles.room_handles[room_id][key] = handle
        state.message_handles.room_handle_to_event[room_id][handle] = key
        _save_state()
        return handle

    return ""


def _get_or_create_id(matrix_id: str) -> int:
    """Get existing simple ID or create new one for a Matrix ID."""
    result = _get_or_create_mapping("thread_ids", matrix_id, prefix="t")
    return int(result[1:])  # Remove 't' prefix and return as int


def _lookup_mapping(
    category: str,
    lookup_key: str,
    room_id: str | None = None,
    reverse: bool = False,
) -> str | None:
    """Generic lookup for ID mappings.

    Args:
        category: "thread_ids" or "message_handles"
        lookup_key: The key to look up
        room_id: Required for message handles
        reverse: If True, lookup handle->event_id, else event_id->handle
    """
    state = _load_state()

    if category == "thread_ids":
        if reverse:
            # Looking up simple_id -> matrix_id
            try:
                simple_id = int(lookup_key)
                return state.thread_ids.id_to_matrix.get(simple_id)
            except ValueError:
                return None
        else:
            # Looking up matrix_id -> simple_id
            return (
                str(state.thread_ids.matrix_to_id.get(lookup_key))
                if lookup_key in state.thread_ids.matrix_to_id
                else None
            )

    elif category == "message_handles" and room_id:
        if room_id not in state.message_handles.room_handles:
            return None

        if reverse:
            # Looking up handle -> event_id
            return state.message_handles.room_handle_to_event[room_id].get(lookup_key)
        # Looking up event_id -> handle
        return state.message_handles.room_handles[room_id].get(lookup_key)

    return None


def _resolve_id(id_or_matrix: str) -> str | None:
    """Resolve a simple ID or Matrix ID to a Matrix ID."""
    # Check if it's a simple ID (just a number)
    try:
        simple_id = int(id_or_matrix)
        return _lookup_mapping("thread_ids", str(simple_id), reverse=True)
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
# Matrix Protocol Helpers
# =============================================================================


def _get_event_content(event) -> dict:
    """Extract content from a Matrix event safely."""
    return event.source.get("content", {})


def _get_relation(content: dict) -> dict | None:
    """Extract m.relates_to from content if it exists."""
    return content.get("m.relates_to") if "m.relates_to" in content else None


def _is_relation_type(content: dict, rel_type: str) -> bool:
    """Check if content has a specific relation type."""
    if relation := _get_relation(content):
        return relation.get("rel_type") == rel_type
    return False


def _extract_thread_and_reply(content: dict) -> tuple[str | None, str | None]:
    """Extract thread root ID and reply-to ID from message content.

    Returns:
        tuple: (thread_root_id, reply_to_id)
    """
    thread_root_id = None
    reply_to_id = None

    if relation := _get_relation(content):
        # Thread relation
        if relation.get("rel_type") == "m.thread":
            thread_root_id = relation.get("event_id")

        # Reply relation (in thread or main timeline)
        if "m.in_reply_to" in relation:
            reply_to_id = relation["m.in_reply_to"].get("event_id")

    return thread_root_id, reply_to_id


def _build_message_content(
    body: str,
    formatted_body: str | None = None,
    mentioned_user_ids: list[str] | None = None,
    thread_root_id: str | None = None,
    reply_to_id: str | None = None,
) -> dict:
    """Build a message content dictionary with all necessary fields."""
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

    return content


def _build_edit_content(
    original_event_id: str,
    body: str,
    formatted_body: str | None = None,
    mentioned_user_ids: list[str] | None = None,
) -> dict:
    """Build an edit message content dictionary."""
    # Create edit content with m.replace relation
    edit_content = {
        "msgtype": "m.text",
        "body": f"* {body}",  # Convention: prefix with * for edits
        "m.new_content": {
            "msgtype": "m.text",
            "body": body,
        },
        "m.relates_to": {
            "rel_type": "m.replace",
            "event_id": original_event_id,
        },
    }

    # Add formatted body if we have mentions
    if formatted_body:
        edit_content["format"] = "org.matrix.custom.html"
        edit_content["formatted_body"] = f"* {formatted_body}"
        edit_content["m.new_content"]["format"] = "org.matrix.custom.html"
        edit_content["m.new_content"]["formatted_body"] = formatted_body

    # Add mentions field if there are any
    if mentioned_user_ids:
        edit_content["m.mentions"] = {"user_ids": mentioned_user_ids}
        edit_content["m.new_content"]["m.mentions"] = {"user_ids": mentioned_user_ids}

    return edit_content


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
    handle: str | None = None  # Display handle (m1, m2, etc.)
    thread_handle: str | None = None  # Thread handle (t1, t2, etc.)


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


# Handle mapping functions moved to unified state system


def _get_or_create_handle(room_id: str, event_id: str) -> str:
    """Get existing handle or create new one for a message."""
    return _get_or_create_mapping("message_handles", event_id, room_id, prefix="m")


def _get_event_id_from_handle(room_id: str, handle: str) -> str | None:
    """Get event ID from a handle."""
    return _lookup_mapping("message_handles", handle, room_id, reverse=True)


def _assign_message_handles(messages: list[Message]) -> list[Message]:
    """Assign stable handles to messages."""
    for msg in messages:
        if msg.event_id and msg.room_id:
            # Get or create stable handle for this message
            msg.handle = _get_or_create_handle(msg.room_id, msg.event_id)

        # Handle thread IDs (using existing system)
        if msg.is_thread_root and msg.event_id:
            thread_simple_id = _get_or_create_id(msg.event_id)
            msg.thread_handle = f"t{thread_simple_id}"
        elif msg.thread_root_id:
            thread_simple_id = _get_or_create_id(msg.thread_root_id)
            msg.thread_handle = f"t{thread_simple_id}"

    return messages


async def _get_messages(client: AsyncClient, room_id: str, limit: int = 20) -> list[Message]:
    """Fetch messages from a room, including thread information, reactions, and edits."""
    try:
        response = await client.room_messages(room_id, limit=limit)

        messages = []
        thread_roots = set()  # Track which messages have threads
        reactions_map = {}  # event_id -> {emoji: [users]}
        edits_map = {}  # original_event_id -> latest_edit_event

        # First pass: collect edits
        for event in response.chunk:
            if isinstance(event, RoomMessageText):
                content = _get_event_content(event)
                # Check if this is an edit (m.replace relation)
                if (
                    _is_relation_type(content, "m.replace")
                    and (relation := _get_relation(content))
                    and (original_id := relation.get("event_id"))
                    and (
                        original_id not in edits_map
                        or event.server_timestamp > edits_map[original_id].server_timestamp
                    )
                ):
                    edits_map[original_id] = event

        # Second pass: build message list
        for event in response.chunk:
            if isinstance(event, RoomMessageText):
                # Skip if this is an edit event (already processed)
                content = _get_event_content(event)
                if _is_relation_type(content, "m.replace"):
                    continue  # Skip edit events themselves

                # Check if this message has been edited
                if event.event_id in edits_map:
                    edit_event = edits_map[event.event_id]
                    edit_content = _get_event_content(edit_event)
                    # Get the new content from m.new_content field
                    if "m.new_content" in edit_content:
                        message_content = edit_content["m.new_content"].get("body", event.body)
                    else:
                        # Fallback: remove the "* " prefix from edit body
                        message_content = edit_event.body
                        if message_content.startswith("* "):
                            message_content = message_content[2:]
                    message_content = f"{message_content} [edited]"
                else:
                    message_content = event.body

                # Extract thread and reply relations
                thread_root_id, reply_to_id = _extract_thread_and_reply(content)
                if thread_root_id:
                    thread_roots.add(thread_root_id)

                messages.append(
                    Message(
                        sender=event.sender,
                        content=message_content,
                        timestamp=datetime.fromtimestamp(event.server_timestamp / 1000, tz=UTC),
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
                        timestamp=datetime.fromtimestamp(event.server_timestamp / 1000, tz=UTC),
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

        # Reverse messages to show newest last
        messages = list(reversed(messages))

        # Assign handles to messages
        return _assign_message_handles(messages)

    except Exception as e:
        console.print(f"[red]Failed to get messages: {e}[/red]")
        return []


async def _get_threads(client: AsyncClient, room_id: str, limit: int = 50) -> list[Message]:
    """Get all thread root messages in a room."""
    messages = await _get_messages(client, room_id, limit)
    return [msg for msg in messages if msg.is_thread_root]


async def _get_thread_messages(
    client: AsyncClient, room_id: str, thread_id: str, limit: int = 50
) -> list[Message]:
    """Get all messages in a specific thread."""
    messages = await _get_messages(client, room_id, limit)

    # Find the thread root and replies
    thread_messages = []
    root_found = False

    for msg in messages:
        if msg.event_id == thread_id:
            thread_messages.append(msg)
            root_found = True
        elif msg.thread_root_id == thread_id:
            thread_messages.append(msg)

    # If we didn't find the root message but found replies, the root might be deleted or out of range
    # Add a placeholder for the missing root message
    if not root_found and thread_messages:
        # Create a placeholder for the missing root message
        # Use the earliest reply's timestamp minus 1 second for the placeholder
        earliest_timestamp = min(msg.timestamp for msg in thread_messages if msg.timestamp)
        placeholder = Message(
            sender="[system]",
            content="[Thread root message not available - may be deleted or outside message range]",
            timestamp=earliest_timestamp.replace(microsecond=0) - timedelta(seconds=1),
            room_id=room_id,
            event_id=thread_id,
            is_thread_root=True,
            handle=_get_or_create_handle(room_id, thread_id) if thread_id else None,
        )
        thread_messages.insert(0, placeholder)

    return sorted(thread_messages, key=lambda m: m.timestamp)


def _get_room_users(client: AsyncClient, room_id: str) -> list[str]:
    """Get list of user IDs in a room."""
    room = client.rooms.get(room_id)
    return list(room.users.keys()) if room else []


def _parse_mentions(message: str, room_users: list[str]) -> tuple[str, str | None, list[str]]:
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
                    if room_user.startswith(f"@{mention}:") or mention.lower() in room_user.lower():
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
        room_users = _get_room_users(client, room_id)

        # Parse mentions
        body, formatted_body, mentioned_user_ids = _parse_mentions(message, room_users)

        # Build message content using helper
        content = _build_message_content(
            body=body,
            formatted_body=formatted_body,
            mentioned_user_ids=mentioned_user_ids,
            thread_root_id=thread_root_id,
            reply_to_id=reply_to_id,
        )

        response = await client.room_send(room_id, message_type="m.room.message", content=content)
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

        response = await client.room_send(room_id, message_type="m.reaction", content=content)
        if _is_success_response(response):
            return True
        console.print(f"[red]Failed to send reaction: {response}[/red]")
        return False  # noqa: TRY300
    except Exception as e:
        console.print(f"[red]Failed to send reaction: {e}[/red]")
        return False


async def _get_message_by_handle(
    client: AsyncClient, room_id: str, handle: str, limit: int = 20
) -> Message | None:
    """Get a message by its stable handle (m1, m2, etc.)."""
    # First try to get event ID from our stable mapping
    event_id = _get_event_id_from_handle(room_id, handle)

    if event_id:
        # We know the event ID, fetch messages and find it
        messages = await _get_messages(client, room_id, limit)
        for msg in messages:
            if msg.event_id == event_id:
                return msg

        # If not in recent messages, try fetching more
        messages = await _get_messages(client, room_id, limit * 5)
        for msg in messages:
            if msg.event_id == event_id:
                return msg

    # Fallback: search by handle in current messages
    messages = await _get_messages(client, room_id, limit)
    for msg in messages:
        if msg.handle == handle:
            return msg

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

    for msg in messages:
        time_str = msg.timestamp.strftime("%H:%M")
        prefix = ""

        # Add thread indicators
        if msg.is_thread_root and msg.thread_handle:
            prefix = f"[bold yellow]🧵 {msg.thread_handle}[/bold yellow] "
        elif msg.thread_handle:
            prefix = f"  ↳ [dim yellow]{msg.thread_handle}[/dim yellow] "

        # Use the handle from the message
        handle = f"[bold magenta]{msg.handle}[/bold magenta]"

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
    for msg in messages:
        time_str = msg.timestamp.strftime("%H:%M")
        thread_mark = ""
        if msg.is_thread_root and msg.thread_handle:
            thread_mark = f" [THREAD {msg.thread_handle}]"
        elif msg.thread_handle:
            thread_mark = f" [IN-THREAD {msg.thread_handle}]"
        print(f"{msg.handle} [{time_str}] {msg.sender}: {msg.content}{thread_mark}")

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
        mention = "@" + user.split(":")[0][1:] if user.startswith("@") and ":" in user else user
        table.add_row(str(idx), user, mention)

    console.print(table)
    console.print("\n[dim]Use mentions in messages: matty send room '@username message'[/dim]")


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
    message: str = typer.Argument(None, help="Message to send (use @username for mentions)"),
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
                        thread.content[:50] + "..." if len(thread.content) > 50 else thread.content
                    )
                    # Get simple ID for thread
                    simple_id = _get_or_create_id(thread.event_id) if thread.event_id else "?"
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
    thread_id: str = typer.Argument(None, help="Thread ID (t1, t2, etc.) or full Matrix ID"),
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

            thread_messages = await _get_thread_messages(client, room_id, actual_thread_id, limit)

            if not thread_messages:
                console.print(f"[yellow]No messages found in thread {thread_id}[/yellow]")
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
                    prefix = "THREAD START: " if msg.event_id == actual_thread_id else "  > "
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
    handle: str = typer.Argument(None, help="Message handle (m1, m2, etc.) to reply to"),
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
            if await _send_message(client, room_id, message, reply_to_id=target_msg.event_id):
                console.print(f"[green]✓ Reply sent to {handle} in {room_name}[/green]")
            else:
                console.print("[red]✗ Failed to send reply[/red]")

    asyncio.run(_reply())


@app.command("thread-start")
@app.command("ts", hidden=True)
def thread_start(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(None, help="Message handle (m1, m2, etc.) to start thread from"),
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
            if await _send_message(client, room_id, message, thread_root_id=target_msg.event_id):
                console.print(f"[green]✓ Thread started from {handle} in {room_name}[/green]")
                console.print(f"[dim]Thread ID: {target_msg.event_id}[/dim]")
            else:
                console.print("[red]✗ Failed to start thread[/red]")

    asyncio.run(_thread_start())


@app.command("thread-reply")
@app.command("tr", hidden=True)
def thread_reply(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    thread_id: str = typer.Argument(None, help="Thread ID (t1, t2, etc.) or full Matrix ID"),
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
            if await _send_message(client, room_id, message, thread_root_id=actual_thread_id):
                console.print(f"[green]✓ Reply sent to thread in {room_name}[/green]")
            else:
                console.print("[red]✗ Failed to send thread reply[/red]")

    asyncio.run(_thread_reply())


@app.command("react")
@app.command("rx", hidden=True)
def react(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(None, help="Message handle (m1, m2, etc.) to react to"),
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
                console.print(f"[green]✓ Reacted with {emoji} to {handle} in {room_name}[/green]")
            else:
                console.print("[red]✗ Failed to send reaction[/red]")

    asyncio.run(_react())


@app.command("edit")
@app.command("e", hidden=True)
def edit(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(None, help="Message handle (m1, m2, etc.) to edit"),
    new_content: str = typer.Argument(None, help="New message content"),
    username: str | None = typer.Option(None, "--username", "-u"),
    password: str | None = typer.Option(None, "--password", "-p"),
):
    """Edit a message using its handle. (alias: e)"""
    _validate_required_args(ctx, room=room, handle=handle, new_content=new_content)

    async def _edit():
        async with _with_client_in_room(room, username, password) as (
            client,
            room_id,
            room_name,
        ):
            if client is None:
                return

            # Get the message to edit
            target_msg = await _get_message_by_handle(client, room_id, handle)

            if not target_msg:
                console.print(f"[red]Message {handle} not found[/red]")
                return

            if not target_msg.event_id:
                console.print(f"[red]Message {handle} has no event ID[/red]")
                return

            # Get room users for mention parsing
            room_users = _get_room_users(client, room_id)

            # Parse mentions
            body, formatted_body, mentioned_user_ids = _parse_mentions(new_content, room_users)

            # Build edit content using helper
            edit_content = _build_edit_content(
                original_event_id=target_msg.event_id,
                body=body,
                formatted_body=formatted_body,
                mentioned_user_ids=mentioned_user_ids,
            )

            try:
                response = await client.room_send(
                    room_id, message_type="m.room.message", content=edit_content
                )

                if _is_success_response(response):
                    console.print(f"[green]✓ Message {handle} edited in {room_name}[/green]")
                    if mentioned_user_ids:
                        console.print("[dim]Note: Mentions were processed[/dim]")
                else:
                    console.print(f"[red]Failed to edit message: {response}[/red]")
            except Exception as e:
                console.print(f"[red]Failed to edit message: {e}[/red]")

    asyncio.run(_edit())


@app.command("redact")
@app.command("del", hidden=True)
def redact(
    ctx: typer.Context,
    room: str = typer.Argument(None, help="Room ID or name"),
    handle: str = typer.Argument(None, help="Message handle (m1, m2, etc.) to redact/delete"),
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
                response = await client.room_redact(room_id, target_msg.event_id, reason=reason)
                if _is_success_response(response):
                    console.print(f"[green]✓ Message {handle} redacted in {room_name}[/green]")
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
    handle: str = typer.Argument(None, help="Message handle (m1, m2, etc.) to show reactions for"),
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
                table = Table(title=f"Reactions for {handle} in {room_name}", show_lines=True)
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
