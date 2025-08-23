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
    """Fetch messages from a room."""
    try:
        response = await client.room_messages(room_id, limit=limit)
        
        messages = []
        for event in response.chunk:
            if isinstance(event, RoomMessageText):
                messages.append(Message(
                    sender=event.sender,
                    content=event.body,
                    timestamp=datetime.fromtimestamp(event.server_timestamp / 1000),
                    room_id=room_id,
                    event_id=event.event_id
                ))
        
        return list(reversed(messages))
        
    except Exception as e:
        console.print(f"[red]Failed to get messages: {e}[/red]")
        return []


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
    """Display messages in rich format."""
    console.print(Panel(f"[bold cyan]{room_name}[/bold cyan]", expand=False))
    
    for msg in messages:
        time_str = msg.timestamp.strftime("%H:%M")
        console.print(f"[dim]{time_str}[/dim] [cyan]{msg.sender}[/cyan]: {msg.content}")


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


if __name__ == "__main__":
    app()