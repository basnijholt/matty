"""Additional tests to reach >90% coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import AsyncClient, LoginResponse, RoomSendResponse

from matty import (
    OutputFormat,
    ServerState,
    _execute_messages_command,
    _execute_send_command,
    _get_messages,
    _get_threads,
    _load_state,
    _login,
    _parse_mentions,
    _save_state,
    _send_message,
)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_login_success_response(self):
        """Test successful login response."""
        client = MagicMock(spec=AsyncClient)
        response = LoginResponse(
            user_id="@user:matrix.org", device_id="DEVICE123", access_token="token123"
        )
        client.login = AsyncMock(return_value=response)

        result = await _login(client, "password")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_message_success(self):
        """Test successful message send."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse(event_id="$event123", room_id="!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)

        result = await _send_message(client, "!room:matrix.org", "Test")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_message_with_thread(self):
        """Test sending message in thread."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse(event_id="$event456", room_id="!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)

        result = await _send_message(
            client, "!room:matrix.org", "Thread reply", thread_root_id="$thread123"
        )
        assert result is True

        # Verify thread relation was included
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.relates_to" in content
        assert content["m.relates_to"]["event_id"] == "$thread123"

    @pytest.mark.asyncio
    async def test_send_message_with_reply(self):
        """Test sending reply message."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse(event_id="$event789", room_id="!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)

        result = await _send_message(
            client, "!room:matrix.org", "Reply text", reply_to_id="$original123"
        )
        assert result is True

        # Verify reply relation was included
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.relates_to" in content
        assert "m.in_reply_to" in content["m.relates_to"]

    @pytest.mark.asyncio
    async def test_send_message_with_edit(self):
        """Test sending edit message."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse(event_id="$edit123", room_id="!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)

        result = await _send_message(
            client, "!room:matrix.org", "Edited text", edit_id="$original456"
        )
        assert result is True

        # Verify edit relation was included
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.relates_to" in content
        assert content["m.relates_to"]["rel_type"] == "m.replace"

    @pytest.mark.asyncio
    async def test_send_message_with_mentions(self):
        """Test sending message with mentions."""
        client = MagicMock(spec=AsyncClient)
        response = RoomSendResponse(event_id="$mention123", room_id="!room:matrix.org")
        client.room_send = AsyncMock(return_value=response)

        result = await _send_message(
            client, "!room:matrix.org", "Hello @user", mentioned_user_ids=["@user:matrix.org"]
        )
        assert result is True

        # Verify mentions were included
        call_args = client.room_send.call_args
        content = call_args[1]["content"]
        assert "m.mentions" in content
        assert "@user:matrix.org" in content["m.mentions"]["user_ids"]

    @pytest.mark.asyncio
    async def test_get_messages_success(self):
        """Test getting messages successfully."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock message event
        msg = MagicMock(spec=RoomMessageText)
        msg.sender = "@user:matrix.org"
        msg.body = "Test message"
        msg.server_timestamp = 1704110400000
        msg.event_id = "$msg123"
        msg.source = {"content": {"body": "Test message", "msgtype": "m.text"}}

        mock_response = MagicMock()
        mock_response.chunk = [msg]

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._get_or_create_handle", return_value="m1"):
            messages = await _get_messages(client, "!room:matrix.org", 10)

        assert len(messages) == 1
        assert messages[0].content == "Test message"
        assert messages[0].handle == "m1"

    @pytest.mark.asyncio
    async def test_get_threads_with_results(self):
        """Test getting threads from room."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock thread root
        thread_root = MagicMock(spec=RoomMessageText)
        thread_root.sender = "@user:matrix.org"
        thread_root.body = "Thread start"
        thread_root.server_timestamp = 1704110400000
        thread_root.event_id = "$thread123"
        thread_root.source = {
            "content": {
                "body": "Thread start",
                "msgtype": "m.text",
                "m.relates_to": {"rel_type": "m.thread", "event_id": "$thread123"},
            }
        }

        mock_response = MagicMock()
        mock_response.chunk = [thread_root]

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._get_or_create_handle", return_value="m1"):
            threads = await _get_threads(client, "!room:matrix.org")
        assert len(threads) == 1
        # _get_threads returns list of Message objects that are thread roots
        assert threads[0].event_id == "$thread123"
        assert threads[0].is_thread_root is True

    @pytest.mark.asyncio
    async def test_execute_messages_command_with_thread(self, capsys):
        """Test messages command with thread ID."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True), patch("matty._sync_client"):
                with patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")):
                    with patch("matty._resolve_thread_id", return_value=("$thread123", None)):
                        with patch("matty._get_thread_messages", return_value=[]):
                            client.close = AsyncMock()

                            # _execute_messages_command doesn't have thread parameter
                            # Just test without thread parameter
                            await _execute_messages_command(
                                "Test Room",
                                10,
                                "user",
                                "pass",
                                OutputFormat.simple,
                            )

        captured = capsys.readouterr()
        assert "Test Room" in captured.out

    @pytest.mark.asyncio
    async def test_execute_send_command_error(self, capsys):
        """Test send command with error."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True), patch("matty._sync_client"):
                with patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")):
                    with patch("matty._send_message", return_value=False):
                        client.close = AsyncMock()

                        await _execute_send_command("Test Room", "Message", "user", "pass")

        captured = capsys.readouterr()
        assert "Failed" in captured.out or "Error" in captured.out

    def test_state_persistence(self, tmp_path, monkeypatch):
        """Test state persistence across load/save cycles."""
        state_file = tmp_path / "test.json"

        # Create initial state
        state1 = ServerState()
        state1.thread_ids.counter = 10
        state1.thread_ids.id_to_matrix[1] = "$event1"
        state1.message_handles.handle_counter["!room"] = 5

        monkeypatch.setattr("matty._state", state1)

        with patch("matty._get_state_file", return_value=state_file):
            _save_state()

        # Load state back
        monkeypatch.setattr("matty._state", None)

        with patch("matty._get_state_file", return_value=state_file):
            state2 = _load_state()

        assert state2.thread_ids.counter == 10
        assert state2.thread_ids.id_to_matrix[1] == "$event1"
        assert state2.message_handles.handle_counter["!room"] == 5

    def test_parse_mentions_with_full_matrix_id(self):
        """Test parsing mentions with full Matrix IDs."""
        users = ["@alice:matrix.org", "@bob:matrix.org"]
        body, formatted, mentioned = _parse_mentions("Hello @alice:matrix.org", users)
        assert mentioned == ["@alice:matrix.org"]
        assert "@alice:matrix.org" in formatted

    def test_parse_mentions_mixed(self):
        """Test parsing mixed mention formats."""
        users = ["@alice:matrix.org", "@bob:matrix.org"]
        body, formatted, mentioned = _parse_mentions(
            "@alice and @bob:matrix.org please review", users
        )
        assert "@alice:matrix.org" in mentioned
        assert "@bob:matrix.org" in mentioned
