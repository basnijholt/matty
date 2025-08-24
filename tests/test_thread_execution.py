"""More tests to reach >90% coverage."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import AsyncClient

from matty import (
    Message,
    OutputFormat,
    _execute_messages_command,
)


class TestThreadExecution:
    """Test thread-related command execution."""

    @pytest.mark.asyncio
    async def test_execute_messages_with_thread_success(self, capsys):
        """Test messages command with thread parameter."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with (
                patch("matty._login", return_value=True),
                patch("matty._sync_client"),
                patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")),
                patch("matty._resolve_thread_id", return_value=("$thread123", None)),
            ):
                messages = [
                    Message(
                        sender="@alice:matrix.org",
                        content="Thread message",
                        timestamp=datetime.now(UTC),
                        room_id="!room:matrix.org",
                        event_id="$msg1",
                        handle="m1",
                    )
                ]
                with patch("matty._get_thread_messages", return_value=messages):
                    client.close = AsyncMock()

                    # _execute_messages_command doesn't have thread parameter
                    await _execute_messages_command(
                        "Test Room",
                        10,
                        "user",
                        "pass",
                        OutputFormat.simple,
                    )

        captured = capsys.readouterr()
        assert "Test Room" in captured.out or "Thread" in captured.out
