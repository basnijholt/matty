#!/usr/bin/env python3
"""Functional Matrix client - minimal classes, maximum functions."""

import asyncio
import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum

import typer
from pydantic_settings import BaseSettings
from nio import AsyncClient, LoginResponse, RoomMessageText, MatrixRoom
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.prompt import Prompt

app = typer.Typer(help="Functional Matrix CLI client")
console = Console()


# =============================================================================
# Data Models (using dataclasses instead of Pydantic for simplicity)
# =============================================================================

@dataclass
class Config:
    """Configuration from environment."""
    homeserver: str = "https://matrix.org"
    username: Optional[str] = None
    password: Optional[str] = None
    ssl_verify: bool = True


@dataclass
class Room:
    """Room information."""
    room_id: str
    name: str
    member_count: int
    topic: Optional[str] = None
    users: List[str] = field(default_factory=list)


@dataclass
class Message:
    """Message data."""
    sender: str
    content: str
    timestamp: datetime
    room_id: str
    event_id: Optional[str] = None
    thread_root_id: Optional[str] = None  # ID of the root message if this is in a thread
    reply_to_id: Optional[str] = None  # ID of message this replies to
    is_thread_root: bool = False  # True if this message started a thread


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
    from dotenv import load_dotenv
    load_dotenv()
    
    return Config(
        homeserver=os.getenv("MATRIX_HOMESERVER", "https://matrix.org"),
        username=os.getenv("MATRIX_USERNAME"),
        password=os.getenv("MATRIX_PASSWORD"),
        ssl_verify=os.getenv("MATRIX_SSL_VERIFY", "true").lower() != "false"
    )


async def _create_client(config: Config) -> AsyncClient:
    """Create a Matrix client instance."""
    return AsyncClient(
        config.homeserver,
        config.username,
        ssl=config.ssl_verify
    )


async def _login(client: AsyncClient, username: str, password: str) -> bool:
    """Perform Matrix login."""
    try:
        response = await client.login(password)
        return isinstance(response, LoginResponse)
    except Exception as e:
        console.print(f"[red]Login error: {e}[/red]")
        return False


async def _sync_client(client: AsyncClient, timeout: int = 10000) -> None:
    """Sync client with server."""
    await client.sync(timeout=timeout)


async def _get_rooms(client: AsyncClient) -> List[Room]:
    """Get list of rooms from client."""
    await _sync_client(client)
    
    rooms = []
    for room_id, matrix_room in client.rooms.items():
        rooms.append(Room(
            room_id=room_id,
            name=matrix_room.display_name or room_id,
            member_count=len(matrix_room.users),
            topic=matrix_room.topic,
            users=list(matrix_room.users.keys())
        ))
    
    return rooms


async def _find_room(client: AsyncClient, room_query: str) -> Optional[Tuple[str, str]]:
    """Find room by ID or name. Returns (room_id, room_name) or None."""
    rooms = await _get_rooms(client)
    
    for room in rooms:
        if room_query == room.room_id or room_query.lower() in room.name.lower():
            return room.room_id, room.name
    
    return None


async def _get_messages(client: AsyncClient, room_id: str, limit: int = 20) -> List[Message]:
    """Fetch messages from a room, including thread information."""
    try:
        response = await client.room_messages(room_id, limit=limit)
        
        messages = []
        thread_roots = set()  # Track which messages have threads
        
        for event in response.chunk:
            if isinstance(event, RoomMessageText):
                # Check if this message is part of a thread
                thread_root_id = None
                reply_to_id = None
                
                # Check for thread relation
                if hasattr(event, 'source') and event.source.get('content', {}).get('m.relates_to'):
                    relates_to = event.source['content']['m.relates_to']
                    
                    # Thread relation
                    if relates_to.get('rel_type') == 'm.thread':
                        thread_root_id = relates_to.get('event_id')
                        thread_roots.add(thread_root_id)
                    
                    # Reply relation (in thread or main timeline)
                    if 'm.in_reply_to' in relates_to:
                        reply_to_id = relates_to['m.in_reply_to'].get('event_id')
                
                messages.append(Message(
                    sender=event.sender,
                    content=event.body,
                    timestamp=datetime.fromtimestamp(event.server_timestamp / 1000),
                    room_id=room_id,
                    event_id=event.event_id,
                    thread_root_id=thread_root_id,
                    reply_to_id=reply_to_id,
                    is_thread_root=False  # Will update after
                ))
        
        # Mark thread roots
        for msg in messages:
            if msg.event_id in thread_roots:
                msg.is_thread_root = True
        
        return list(reversed(messages))
        
    except Exception as e:
        console.print(f"[red]Failed to get messages: {e}[/red]")
        return []


async def _get_threads(client: AsyncClient, room_id: str, limit: int = 50) -> List[Message]:
    """Get all thread root messages in a room."""
    messages = await _get_messages(client, room_id, limit)
    return [msg for msg in messages if msg.is_thread_root]


async def _get_thread_messages(client: AsyncClient, room_id: str, thread_id: str, limit: int = 50) -> List[Message]:
    """Get all messages in a specific thread."""
    messages = await _get_messages(client, room_id, limit)
    
    # Find the thread root
    thread_root = None
    thread_messages = []
    
    for msg in messages:
        if msg.event_id == thread_id:
            thread_root = msg
            thread_messages.append(msg)
        elif msg.thread_root_id == thread_id:
            thread_messages.append(msg)
    
    return sorted(thread_messages, key=lambda m: m.timestamp)


async def _send_message(client: AsyncClient, room_id: str, message: str) -> bool:
    """Send a message to a room."""
    try:
        await client.room_send(
            room_id,
            message_type="m.room.message",
            content={
                "msgtype": "m.text",
                "body": message
            }
        )
        return True
    except Exception as e:
        console.print(f"[red]Failed to send: {e}[/red]")
        return False


# =============================================================================
# Display Functions
# =============================================================================

def _display_rooms_rich(rooms: List[Room]) -> None:
    """Display rooms in rich table format."""
    table = Table(title="Matrix Rooms", show_lines=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("Room Name", style="green")
    table.add_column("Room ID", style="dim")
    table.add_column("Members", style="yellow")
    
    for idx, room in enumerate(rooms, 1):
        table.add_row(
            str(idx),
            room.name,
            room.room_id,
            str(room.member_count)
        )
    
    console.print(table)


def _display_rooms_simple(rooms: List[Room]) -> None:
    """Display rooms in simple text format."""
    for room in rooms:
        print(f"{room.name} ({room.room_id}) - {room.member_count} members")


def _display_rooms_json(rooms: List[Room]) -> None:
    """Display rooms in JSON format."""
    print(json.dumps([asdict(room) for room in rooms], indent=2, default=str))


def _display_messages_rich(messages: List[Message], room_name: str) -> None:
    """Display messages in rich format with thread indicators."""
    console.print(Panel(f"[bold cyan]{room_name}[/bold cyan]", expand=False))
    
    for msg in messages:
        time_str = msg.timestamp.strftime("%H:%M")
        prefix = ""
        
        # Add thread indicators
        if msg.is_thread_root:
            prefix = "[bold yellow]🧵[/bold yellow] "
        elif msg.thread_root_id:
            prefix = "  ↳ "
        
        console.print(f"{prefix}[dim]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}")


def _display_messages_simple(messages: List[Message], room_name: str) -> None:
    """Display messages in simple format."""
    print(f"=== {room_name} ===")
    for msg in messages:
        time_str = msg.timestamp.strftime("%H:%M")
        print(f"[{time_str}] {msg.sender}: {msg.content}")


def _display_messages_json(messages: List[Message], room_name: str) -> None:
    """Display messages in JSON format."""
    data = {
        "room": room_name,
        "messages": [asdict(msg) for msg in messages]
    }
    print(json.dumps(data, indent=2, default=str))


def _display_users_rich(users: List[str], room_name: str) -> None:
    """Display users in rich table format."""
    table = Table(title=f"Users in {room_name}", show_lines=True)
    table.add_column("#", style="cyan", width=3)
    table.add_column("User ID", style="green")
    
    for idx, user in enumerate(users, 1):
        table.add_row(str(idx), user)
    
    console.print(table)


def _display_users_simple(users: List[str], room_name: str) -> None:
    """Display users in simple format."""
    print(f"=== Users in {room_name} ===")
    for user in users:
        print(user)


def _display_users_json(users: List[str], room_name: str) -> None:
    """Display users in JSON format."""
    print(json.dumps({"room": room_name, "users": users}, indent=2))


# =============================================================================
# Main Command Functions
# =============================================================================

async def _execute_rooms_command(
    username: Optional[str] = None,
    password: Optional[str] = None,
    format: OutputFormat = OutputFormat.rich
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
        if await _login(client, config.username, config.password):
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
    username: Optional[str] = None,
    password: Optional[str] = None,
    format: OutputFormat = OutputFormat.rich
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
        if await _login(client, config.username, config.password):
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
    username: Optional[str] = None,
    password: Optional[str] = None,
    format: OutputFormat = OutputFormat.rich
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
        if await _login(client, config.username, config.password):
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
    username: Optional[str] = None,
    password: Optional[str] = None
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
        if await _login(client, config.username, config.password):
            room_info = await _find_room(client, room)
            
            if not room_info:
                console.print(f"[red]Room '{room}' not found[/red]")
                return
            
            room_id, room_name = room_info
            
            if await _send_message(client, room_id, message):
                console.print(f"[green]✓ Message sent to {room_name}[/green]")
            else:
                console.print("[red]✗ Failed to send message[/red]")
    finally:
        await client.close()


# =============================================================================
# CLI Commands
# =============================================================================

@app.command()
def rooms(
    username: Optional[str] = typer.Option(None, "--username", "-u"),
    password: Optional[str] = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f")
):
    """List all joined rooms."""
    asyncio.run(_execute_rooms_command(username, password, format))


@app.command()
def messages(
    room: str = typer.Argument(..., help="Room ID or name"),
    limit: int = typer.Option(20, "--limit", "-l"),
    username: Optional[str] = typer.Option(None, "--username", "-u"),
    password: Optional[str] = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f")
):
    """Show recent messages from a room."""
    asyncio.run(_execute_messages_command(room, limit, username, password, format))


@app.command()
def users(
    room: str = typer.Argument(..., help="Room ID or name"),
    username: Optional[str] = typer.Option(None, "--username", "-u"),
    password: Optional[str] = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f")
):
    """Show users in a room."""
    asyncio.run(_execute_users_command(room, username, password, format))


@app.command()
def send(
    room: str = typer.Argument(..., help="Room ID or name"),
    message: str = typer.Argument(..., help="Message to send"),
    username: Optional[str] = typer.Option(None, "--username", "-u"),
    password: Optional[str] = typer.Option(None, "--password", "-p")
):
    """Send a message to a room."""
    asyncio.run(_execute_send_command(room, message, username, password))


@app.command()
def threads(
    room: str = typer.Argument(..., help="Room ID or name"),
    limit: int = typer.Option(50, "--limit", "-l", help="Number of messages to check"),
    username: Optional[str] = typer.Option(None, "--username", "-u"),
    password: Optional[str] = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f")
):
    """List all threads in a room."""
    
    async def _threads():
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
            if await _login(client, config.username, config.password):
                room_info = await _find_room(client, room)
                
                if not room_info:
                    console.print(f"[red]Room '{room}' not found[/red]")
                    return
                
                room_id, room_name = room_info
                threads = await _get_threads(client, room_id, limit)
                
                if not threads:
                    console.print(f"[yellow]No threads found in {room_name}[/yellow]")
                    return
                
                if format == OutputFormat.rich:
                    table = Table(title=f"Threads in {room_name}", show_lines=True)
                    table.add_column("Time", style="dim", width=8)
                    table.add_column("Author", style="cyan")
                    table.add_column("Thread Start", style="green")
                    table.add_column("Thread ID", style="dim")
                    
                    for thread in threads:
                        time_str = thread.timestamp.strftime("%H:%M")
                        # Truncate content for display
                        content = thread.content[:50] + "..." if len(thread.content) > 50 else thread.content
                        table.add_row(time_str, thread.sender, content, thread.event_id or "")
                    
                    console.print(table)
                
                elif format == OutputFormat.simple:
                    print(f"=== Threads in {room_name} ===")
                    for thread in threads:
                        time_str = thread.timestamp.strftime("%H:%M")
                        print(f"[{time_str}] {thread.sender}: {thread.content[:50]}... (ID: {thread.event_id})")
                
                elif format == OutputFormat.json:
                    print(json.dumps({
                        "room": room_name,
                        "threads": [asdict(thread) for thread in threads]
                    }, indent=2, default=str))
        finally:
            await client.close()
    
    asyncio.run(_threads())


@app.command()
def thread(
    room: str = typer.Argument(..., help="Room ID or name"),
    thread_id: str = typer.Argument(..., help="Thread ID to view"),
    limit: int = typer.Option(50, "--limit", "-l", help="Number of messages to fetch"),
    username: Optional[str] = typer.Option(None, "--username", "-u"),
    password: Optional[str] = typer.Option(None, "--password", "-p"),
    format: OutputFormat = typer.Option(OutputFormat.rich, "--format", "-f")
):
    """Show all messages in a specific thread."""
    
    async def _thread():
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
            if await _login(client, config.username, config.password):
                room_info = await _find_room(client, room)
                
                if not room_info:
                    console.print(f"[red]Room '{room}' not found[/red]")
                    return
                
                room_id, room_name = room_info
                thread_messages = await _get_thread_messages(client, room_id, thread_id, limit)
                
                if not thread_messages:
                    console.print(f"[yellow]No messages found in thread {thread_id}[/yellow]")
                    return
                
                if format == OutputFormat.rich:
                    console.print(Panel(f"[bold cyan]Thread in {room_name}[/bold cyan]", expand=False))
                    
                    for msg in thread_messages:
                        time_str = msg.timestamp.strftime("%H:%M")
                        if msg.event_id == thread_id:
                            # Thread root
                            console.print(f"[bold yellow]🧵 Thread Start[/bold yellow]")
                            console.print(f"[dim]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}")
                        else:
                            # Thread reply
                            console.print(f"  ↳ [{dim}]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}")
                
                elif format == OutputFormat.simple:
                    print(f"=== Thread in {room_name} ===")
                    for msg in thread_messages:
                        time_str = msg.timestamp.strftime("%H:%M")
                        prefix = "THREAD START: " if msg.event_id == thread_id else "  > "
                        print(f"{prefix}[{time_str}] {msg.sender}: {msg.content}")
                
                elif format == OutputFormat.json:
                    print(json.dumps({
                        "room": room_name,
                        "thread_id": thread_id,
                        "messages": [asdict(msg) for msg in thread_messages]
                    }, indent=2, default=str))
        finally:
            await client.close()
    
    asyncio.run(_thread())


if __name__ == "__main__":
    app()