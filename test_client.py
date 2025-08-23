#!/usr/bin/env python3
"""Test the Matrix client connection."""

import asyncio
import os
from nio import AsyncClient, LoginResponse
from dotenv import load_dotenv
from rich.console import Console

console = Console()


async def test_connection():
    """Test basic Matrix connection and login."""
    load_dotenv()

    homeserver = os.getenv("MATRIX_HOMESERVER")
    username = os.getenv("MATRIX_USERNAME")
    password = os.getenv("MATRIX_PASSWORD")
    ssl_verify = os.getenv("MATRIX_SSL_VERIFY", "true").lower() != "false"

    console.print(f"[cyan]Testing connection to {homeserver}[/cyan]")
    console.print(f"[cyan]Username: {username}[/cyan]")
    console.print(f"[cyan]SSL Verify: {ssl_verify}[/cyan]")

    try:
        client = AsyncClient(homeserver, username, ssl=ssl_verify)
        console.print("[yellow]Attempting login...[/yellow]")

        response = await client.login(password)

        if isinstance(response, LoginResponse):
            console.print("[green]✓ Login successful![/green]")
            console.print(f"[green]User ID: {response.user_id}[/green]")
            console.print(f"[green]Device ID: {response.device_id}[/green]")

            # Try to sync rooms
            console.print("[yellow]Syncing rooms...[/yellow]")
            sync_response = await client.sync(timeout=5000)

            console.print(f"[green]✓ Found {len(client.rooms)} rooms[/green]")

            # List rooms
            for room_id, room in list(client.rooms.items())[:5]:
                console.print(f"  - {room.display_name or room_id}")

            await client.close()
            return True
        else:
            console.print(f"[red]✗ Login failed: {response}[/red]")
            await client.close()
            return False

    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        return False


if __name__ == "__main__":
    asyncio.run(test_connection())
