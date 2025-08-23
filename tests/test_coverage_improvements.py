"""Additional tests to improve coverage to >90%."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nio import AsyncClient, ErrorResponse, MatrixRoom
from typer.testing import CliRunner

from matty import (
    Config,
    Message,
    MessageHandleMapping,
    OutputFormat,
    Room,
    ServerState,
    ThreadIdMapping,
    _build_edit_content,
    _build_message_content,
    _create_client,
    _display_messages_json,
    _display_messages_rich,
    _display_messages_simple,
    _display_rooms_json,
    _display_rooms_rich,
    _display_rooms_simple,
    _display_users_json,
    _display_users_rich,
    _display_users_simple,
    _execute_messages_command,
    _execute_rooms_command,
    _execute_send_command,
    _execute_users_command,
    _extract_thread_and_reply,
    _find_room,
    _get_event_content,
    _get_event_id_from_handle,
    _get_message_by_handle,
    _get_messages,
    _get_or_create_handle,
    _get_relation,
    _get_room_users,
    _get_state_file,
    _get_thread_messages,
    _get_threads,
    _is_relation_type,
    _load_config,
    _load_state,
    _login,
    _lookup_mapping,
    _parse_mentions,
    _resolve_thread_id,
    _save_state,
    _send_message,
    _sync_client,
    _validate_required_args,
    app,
)

runner = CliRunner()


class TestStateManagement:
    """Test state file management functions."""

    def test_get_state_file_with_http(self):
        """Test state file path generation with http URLs."""
        result = _get_state_file("http://matrix.example.com")
        assert result.name == "matrix.example.com.json"
        assert ".config/matty/state" in str(result)

    def test_get_state_file_with_https(self):
        """Test state file path generation with https URLs."""
        result = _get_state_file("https://matrix.example.com")
        assert result.name == "matrix.example.com.json"

    def test_get_state_file_with_domain_only(self):
        """Test state file path generation with domain only."""
        result = _get_state_file("matrix.example.com")
        assert result.name == "matrix.example.com.json"

    def test_load_state_new_file(self, tmp_path, monkeypatch):
        """Test loading state when file doesn't exist."""
        monkeypatch.setattr("matty._state", None)
        state_file = tmp_path / "test.json"

        with patch("matty._get_state_file", return_value=state_file):
            state = _load_state()
            assert isinstance(state, ServerState)
            assert state.thread_ids.counter == 0
            assert state.message_handles.handle_counter == {}

    def test_load_state_existing_file(self, tmp_path, monkeypatch):
        """Test loading state from existing file."""
        monkeypatch.setattr("matty._state", None)
        state_file = tmp_path / "test.json"

        # Create a state file
        state_data = {
            "thread_ids": {
                "counter": 5,
                "id_to_matrix": {"1": "$event1", "2": "$event2"},
                "matrix_to_id": {"$event1": 1, "$event2": 2},
            },
            "message_handles": {
                "handle_counter": {"!room1": 10},
                "room_handles": {"!room1": {"$msg1": "m1"}},
                "room_handle_to_event": {"!room1": {"m1": "$msg1"}},
            },
        }
        state_file.write_text(json.dumps(state_data))

        with patch("matty._get_state_file", return_value=state_file):
            state = _load_state()
            assert state.thread_ids.counter == 5
            assert state.thread_ids.id_to_matrix[1] == "$event1"
            assert state.message_handles.handle_counter["!room1"] == 10

    def test_save_state(self, tmp_path, monkeypatch):
        """Test saving state to file."""
        state_file = tmp_path / "test.json"
        state = ServerState()
        state.thread_ids.counter = 3
        state.thread_ids.id_to_matrix[1] = "$test"

        # Set the global state
        monkeypatch.setattr("matty._state", state)

        with patch("matty._get_state_file", return_value=state_file):
            _save_state()  # No arguments needed

        # Verify file was written
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["thread_ids"]["counter"] == 3
        assert data["thread_ids"]["id_to_matrix"]["1"] == "$test"

    def test_lookup_mapping_thread_ids(self, monkeypatch):
        """Test looking up thread ID mappings."""
        state = ServerState()
        state.thread_ids.id_to_matrix[1] = "$event123"
        state.thread_ids.matrix_to_id["$event123"] = 1
        monkeypatch.setattr("matty._state", state)

        # Test forward lookup
        result = _lookup_mapping("thread_ids", "1", reverse=True)
        assert result == "$event123"

        # Test reverse lookup
        result = _lookup_mapping("thread_ids", "$event123", reverse=False)
        assert result == "1"

        # Test invalid ID
        result = _lookup_mapping("thread_ids", "invalid", reverse=True)
        assert result is None

    def test_lookup_mapping_message_handles(self, monkeypatch):
        """Test looking up message handle mappings."""
        state = ServerState()
        room_id = "!room:matrix.org"
        state.message_handles.room_handles[room_id] = {"$msg1": "m1"}
        state.message_handles.room_handle_to_event[room_id] = {"m1": "$msg1"}
        monkeypatch.setattr("matty._state", state)

        # Test forward lookup (event_id -> handle)
        result = _lookup_mapping("message_handles", "$msg1", room_id=room_id, reverse=False)
        assert result == "m1"

        # Test reverse lookup (handle -> event_id)
        result = _lookup_mapping("message_handles", "m1", room_id=room_id, reverse=True)
        assert result == "$msg1"

        # Test missing room
        result = _lookup_mapping("message_handles", "m1", room_id="!other:matrix.org", reverse=True)
        assert result is None


class TestMessageHandles:
    """Test message handle management."""

    def test_get_or_create_handle_new(self, monkeypatch):
        """Test creating new handle for message."""
        state = ServerState()
        room_id = "!room:matrix.org"
        event_id = "$new_event"
        monkeypatch.setattr("matty._state", state)

        with patch("matty._save_state"):
            handle = _get_or_create_handle(room_id, event_id)
            assert handle == "m1"
            assert state.message_handles.handle_counter[room_id] == 1
            assert state.message_handles.room_handles[room_id][event_id] == "m1"

    def test_get_or_create_handle_existing(self, monkeypatch):
        """Test getting existing handle for message."""
        state = ServerState()
        room_id = "!room:matrix.org"
        event_id = "$existing_event"
        state.message_handles.room_handles[room_id] = {event_id: "m5"}
        monkeypatch.setattr("matty._state", state)

        handle = _get_or_create_handle(room_id, event_id)
        assert handle == "m5"

    def test_get_event_id_from_handle(self):
        """Test getting event ID from handle."""
        state = ServerState()
        room_id = "!room:matrix.org"
        # Also need to initialize room_handles for the category check
        state.message_handles.room_handles[room_id] = {"$event123": "m5"}
        state.message_handles.room_handle_to_event[room_id] = {"m5": "$event123"}

        # Mock _load_state to return our state
        with patch("matty._load_state", return_value=state):
            result = _get_event_id_from_handle(room_id, "m5")
            assert result == "$event123"

            # Test missing handle
            result = _get_event_id_from_handle(room_id, "m999")
            assert result is None


class TestThreadManagement:
    """Test thread ID resolution and management."""

    def test_resolve_thread_id_with_t_prefix(self, monkeypatch):
        """Test resolving thread ID with t prefix."""
        state = ServerState()
        state.thread_ids.id_to_matrix[5] = "$thread_event"
        state.thread_ids.matrix_to_id["$thread_event"] = 5
        monkeypatch.setattr("matty._state", state)

        result, error = _resolve_thread_id("t5")
        assert result == "$thread_event"
        assert error is None

    def test_resolve_thread_id_direct(self):
        """Test resolving thread ID with direct event ID."""
        result, error = _resolve_thread_id("$direct_event_id")
        assert result == "$direct_event_id"
        assert error is None

    def test_resolve_thread_id_invalid(self, monkeypatch):
        """Test resolving invalid thread ID."""
        state = ServerState()
        monkeypatch.setattr("matty._state", state)

        # Test with t prefix but no mapping
        result, error = _resolve_thread_id("t999")
        assert result is None
        assert "not found" in error.lower()

        # Test with invalid format
        result, error = _resolve_thread_id("tabc")
        assert result is None
        assert "invalid" in error.lower()


class TestDisplayFunctions:
    """Test various display output functions."""

    def test_display_rooms_rich(self, capsys):
        """Test rich display of rooms."""
        rooms = [
            Room(room_id="!room1:matrix.org", name="Room 1", member_count=5, topic="Topic 1"),
            Room(room_id="!room2:matrix.org", name="Room 2", member_count=10, topic=None),
        ]
        _display_rooms_rich(rooms)
        captured = capsys.readouterr()
        # Rich output includes table formatting
        assert captured.out != ""

    def test_display_rooms_simple(self, capsys):
        """Test simple display of rooms."""
        rooms = [
            Room(room_id="!room1:matrix.org", name="Room 1", member_count=5, topic="Topic 1"),
            Room(room_id="!room2:matrix.org", name="Room 2", member_count=10, topic=None),
        ]
        _display_rooms_simple(rooms)
        captured = capsys.readouterr()
        assert "Room 1" in captured.out
        assert "Room 2" in captured.out
        assert "5 members" in captured.out
        assert "10 members" in captured.out

    def test_display_rooms_json(self, capsys):
        """Test JSON display of rooms."""
        rooms = [
            Room(room_id="!room1:matrix.org", name="Room 1", member_count=5, topic="Topic 1"),
        ]
        _display_rooms_json(rooms)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 1
        assert data[0]["name"] == "Room 1"
        assert data[0]["member_count"] == 5

    def test_display_messages_rich(self, capsys):
        """Test rich display of messages."""
        messages = [
            Message(
                sender="@user:matrix.org",
                content="Hello world",
                timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$msg1",
                handle="m1",
            )
        ]
        _display_messages_rich(messages, "Test Room")
        captured = capsys.readouterr()
        assert captured.out != ""

    def test_display_messages_simple(self, capsys):
        """Test simple display of messages."""
        messages = [
            Message(
                sender="@user:matrix.org",
                content="Hello world",
                timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$msg1",
                handle="m1",
                thread_handle="t1",  # Use thread_handle instead of thread_root_id
                reactions={"👍": ["@other:matrix.org"]},
            )
        ]
        _display_messages_simple(messages, "Test Room")
        captured = capsys.readouterr()
        assert "Test Room" in captured.out
        assert "@user:matrix.org" in captured.out
        assert "Hello world" in captured.out
        assert "m1" in captured.out
        assert "IN-THREAD t1" in captured.out  # Check for actual thread marker format
        assert "👍" in captured.out  # Reaction

    def test_display_messages_json(self, capsys):
        """Test JSON display of messages."""
        messages = [
            Message(
                sender="@user:matrix.org",
                content="Test message",
                timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC),
                room_id="!room:matrix.org",
                event_id="$msg1",
                handle="m1",
            )
        ]
        _display_messages_json(messages, "Test Room")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["room"] == "Test Room"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Test message"

    def test_display_users_rich(self, capsys):
        """Test rich display of users."""
        users = ["@alice:matrix.org", "@bob:matrix.org", "@charlie:matrix.org"]
        _display_users_rich(users, "Test Room")
        captured = capsys.readouterr()
        assert captured.out != ""

    def test_display_users_simple(self, capsys):
        """Test simple display of users."""
        users = ["@alice:matrix.org", "@bob:matrix.org"]
        _display_users_simple(users, "Test Room")
        captured = capsys.readouterr()
        assert "Test Room" in captured.out
        assert "@alice:matrix.org" in captured.out
        assert "@bob:matrix.org" in captured.out

    def test_display_users_json(self, capsys):
        """Test JSON display of users."""
        users = ["@alice:matrix.org", "@bob:matrix.org"]
        _display_users_json(users, "Test Room")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["room"] == "Test Room"
        assert len(data["users"]) == 2
        assert "@alice:matrix.org" in data["users"]


class TestMatrixProtocolHelpers:
    """Test Matrix protocol helper functions."""

    def test_get_event_content_with_content(self):
        """Test getting event content when present."""
        event = MagicMock()
        event.source = {"content": {"body": "test", "msgtype": "m.text"}}
        content = _get_event_content(event)
        assert content == {"body": "test", "msgtype": "m.text"}

    def test_get_event_content_without_content(self):
        """Test getting event content when missing."""
        event = MagicMock()
        event.source = {}
        content = _get_event_content(event)
        assert content == {}

    def test_get_relation_with_relation(self):
        """Test getting relation when present."""
        content = {"m.relates_to": {"rel_type": "m.thread", "event_id": "$123"}}
        relation = _get_relation(content)
        assert relation == {"rel_type": "m.thread", "event_id": "$123"}

    def test_get_relation_without_relation(self):
        """Test getting relation when missing."""
        content = {"body": "test"}
        relation = _get_relation(content)
        assert relation is None

    def test_is_relation_type_matching(self):
        """Test checking relation type when matching."""
        content = {"m.relates_to": {"rel_type": "m.thread", "event_id": "$123"}}
        assert _is_relation_type(content, "m.thread") is True
        assert _is_relation_type(content, "m.replace") is False

    def test_is_relation_type_no_relation(self):
        """Test checking relation type with no relation."""
        content = {"body": "test"}
        assert _is_relation_type(content, "m.thread") is False

    def test_extract_thread_and_reply_thread(self):
        """Test extracting thread relation."""
        content = {"m.relates_to": {"rel_type": "m.thread", "event_id": "$thread123"}}
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id == "$thread123"
        assert reply_id is None

    def test_extract_thread_and_reply_reply(self):
        """Test extracting reply relation."""
        content = {"m.relates_to": {"m.in_reply_to": {"event_id": "$reply123"}}}
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id is None
        assert reply_id == "$reply123"

    def test_extract_thread_and_reply_both(self):
        """Test extracting both thread and reply relations."""
        content = {
            "m.relates_to": {
                "rel_type": "m.thread",
                "event_id": "$thread456",
                "m.in_reply_to": {"event_id": "$reply456"},
            }
        }
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id == "$thread456"
        assert reply_id == "$reply456"

    def test_extract_thread_and_reply_none(self):
        """Test extracting when no relations."""
        content = {"body": "test"}
        thread_id, reply_id = _extract_thread_and_reply(content)
        assert thread_id is None
        assert reply_id is None

    def test_build_message_content_simple(self):
        """Test building simple message content."""
        content = _build_message_content("Hello world")
        assert content == {"msgtype": "m.text", "body": "Hello world"}

    def test_build_message_content_with_formatted(self):
        """Test building message with formatted body."""
        content = _build_message_content("Hello", formatted_body="<b>Hello</b>")
        assert content["body"] == "Hello"
        assert content["formatted_body"] == "<b>Hello</b>"
        assert content["format"] == "org.matrix.custom.html"

    def test_build_message_content_with_mentions(self):
        """Test building message with mentions."""
        content = _build_message_content("Hello @user", mentioned_user_ids=["@user:matrix.org"])
        assert content["m.mentions"] == {"user_ids": ["@user:matrix.org"]}

    def test_build_message_content_thread(self):
        """Test building thread message."""
        content = _build_message_content("Thread reply", thread_root_id="$thread789")
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$thread789"

    def test_build_message_content_reply(self):
        """Test building reply message."""
        content = _build_message_content("Reply", reply_to_id="$msg789")
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$msg789"

    def test_build_message_content_thread_reply(self):
        """Test building thread reply with reply-to."""
        content = _build_message_content(
            "Thread reply", thread_root_id="$thread999", reply_to_id="$msg999"
        )
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$thread999"
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$msg999"

    def test_build_edit_content_simple(self):
        """Test building simple edit content."""
        content = _build_edit_content("$original123", "Edited text")
        assert content["body"] == "* Edited text"
        assert content["m.new_content"]["body"] == "Edited text"
        assert content["m.relates_to"]["rel_type"] == "m.replace"
        assert content["m.relates_to"]["event_id"] == "$original123"

    def test_build_edit_content_with_formatted(self):
        """Test building edit with formatted body."""
        content = _build_edit_content("$original456", "Edited", formatted_body="<b>Edited</b>")
        assert content["formatted_body"] == "* <b>Edited</b>"
        assert content["m.new_content"]["formatted_body"] == "<b>Edited</b>"
        assert "format" in content
        assert "format" in content["m.new_content"]

    def test_build_edit_content_with_mentions(self):
        """Test building edit with mentions."""
        content = _build_edit_content(
            "$original789", "Edited @user", mentioned_user_ids=["@user:matrix.org"]
        )
        assert content["m.mentions"] == {"user_ids": ["@user:matrix.org"]}
        assert content["m.new_content"]["m.mentions"] == {"user_ids": ["@user:matrix.org"]}

    def test_get_room_users(self):
        """Test getting users from a room."""
        client = MagicMock(spec=AsyncClient)
        room = MagicMock(spec=MatrixRoom)
        room.users = {
            "@user1:matrix.org": None,
            "@user2:matrix.org": None,
            "@user3:matrix.org": None,
        }
        client.rooms = {"!room:matrix.org": room}

        users = _get_room_users(client, "!room:matrix.org")
        assert len(users) == 3
        assert "@user1:matrix.org" in users
        assert "@user2:matrix.org" in users
        assert "@user3:matrix.org" in users

    def test_get_room_users_not_found(self):
        """Test getting users from non-existent room."""
        client = MagicMock(spec=AsyncClient)
        client.rooms = {}
        users = _get_room_users(client, "!nonexistent:matrix.org")
        assert users == []


class TestMentionParsing:
    """Test mention parsing functionality."""

    def test_parse_mentions_single(self):
        """Test parsing single mention."""
        users = ["@alice:matrix.org", "@bob:matrix.org"]
        body, formatted_body, mentioned_user_ids = _parse_mentions("Hello @alice", users)
        assert body == "Hello @alice"
        assert mentioned_user_ids == ["@alice:matrix.org"]
        assert "@alice:matrix.org" in formatted_body

    def test_parse_mentions_multiple(self):
        """Test parsing multiple mentions."""
        users = ["@alice:matrix.org", "@bob:matrix.org", "@charlie:matrix.org"]
        body, formatted_body, mentioned_user_ids = _parse_mentions(
            "@alice and @bob please review", users
        )
        assert body == "@alice and @bob please review"
        assert mentioned_user_ids == ["@alice:matrix.org", "@bob:matrix.org"]
        assert "@alice:matrix.org" in formatted_body
        assert "@bob:matrix.org" in formatted_body

    def test_parse_mentions_none(self):
        """Test parsing with no mentions."""
        users = ["@alice:matrix.org", "@bob:matrix.org"]
        body, formatted_body, mentioned_user_ids = _parse_mentions("Hello world", users)
        assert body == "Hello world"
        assert mentioned_user_ids == []
        assert formatted_body is None

    def test_parse_mentions_invalid(self):
        """Test parsing with invalid mention."""
        users = ["@alice:matrix.org"]
        body, formatted_body, mentioned_user_ids = _parse_mentions("Hello @nonexistent", users)
        assert body == "Hello @nonexistent"
        assert mentioned_user_ids == []
        assert formatted_body is None


class TestCLIValidation:
    """Test CLI argument validation."""

    def test_validate_required_args_present(self):
        """Test validation when required args present."""
        ctx = MagicMock()
        ctx.command.name = "test"
        # Should not raise
        _validate_required_args(ctx, room="TestRoom")

    def test_validate_required_args_missing(self):
        """Test validation when required args missing."""
        import typer

        ctx = MagicMock()
        ctx.command.name = "test"

        with pytest.raises(typer.Exit), patch("matty.console.print") as mock_print:
            _validate_required_args(ctx, room=None)
            mock_print.assert_called()


class TestCLICommands:
    """Test CLI command execution."""

    def test_cli_help(self):
        """Test help command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Functional Matrix CLI client" in result.output

    def test_cli_rooms_no_creds(self):
        """Test rooms command without credentials."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", None, None)
            # Mock the async execution to avoid actual connection
            with patch("matty.asyncio.run") as mock_run:
                mock_run.side_effect = Exception("No credentials")
                result = runner.invoke(app, ["rooms"])
                # Should handle the exception
                assert result.exit_code == 1

    def test_cli_messages_no_room(self):
        """Test messages command without room argument."""
        result = runner.invoke(app, ["messages"])
        assert result.exit_code != 0

    def test_cli_send_no_message(self):
        """Test send command without message."""
        result = runner.invoke(app, ["send", "TestRoom"])
        assert result.exit_code != 0

    def test_cli_thread_start_no_handle(self):
        """Test thread-start command without handle."""
        result = runner.invoke(app, ["thread-start", "TestRoom"])
        assert result.exit_code != 0

    def test_cli_react_no_emoji(self):
        """Test react command without emoji."""
        result = runner.invoke(app, ["react", "TestRoom", "m1"])
        assert result.exit_code != 0

    def test_cli_edit_no_content(self):
        """Test edit command without new content."""
        result = runner.invoke(app, ["edit", "TestRoom", "m1"])
        assert result.exit_code != 0


class TestAsyncCommandExecution:
    """Test async command execution functions."""

    @pytest.mark.asyncio
    async def test_execute_rooms_command_success(self, capsys):
        """Test successful rooms command execution."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True):
                room = MagicMock(spec=MatrixRoom)
                room.room_id = "!room:matrix.org"
                room.display_name = "Test Room"
                room.member_count = 5
                room.topic = "Test Topic"
                room.users = {f"@user{i}:matrix.org": None for i in range(5)}

                client.rooms = {"!room:matrix.org": room}
                client.close = AsyncMock()

                await _execute_rooms_command("user", "pass", OutputFormat.simple)

        captured = capsys.readouterr()
        assert "Test Room" in captured.out

    @pytest.mark.asyncio
    async def test_execute_rooms_command_login_fail(self, capsys):
        """Test rooms command with login failure."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=False):
                client.close = AsyncMock()

                await _execute_rooms_command("user", "pass", OutputFormat.simple)

        captured = capsys.readouterr()
        assert captured.out == ""

    @pytest.mark.asyncio
    async def test_execute_messages_command_room_not_found(self, capsys):
        """Test messages command when room not found."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True):
                with patch("matty._sync_client", return_value=None):
                    with patch("matty._find_room", return_value=None):
                        client.close = AsyncMock()

                        await _execute_messages_command(
                            "NonExistent", 10, "user", "pass", OutputFormat.simple
                        )

        captured = capsys.readouterr()
        assert "not found" in captured.out.lower()

    @pytest.mark.asyncio
    async def test_execute_send_command_with_mentions(self):
        """Test send command with mentions."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True):
                with patch("matty._sync_client", return_value=None):
                    with patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")):
                        with patch("matty._send_message", return_value=True) as mock_send:
                            client.close = AsyncMock()

                            await _execute_send_command("Test Room", "@alice hello", "user", "pass")

                            # Verify _send_message was called
                            mock_send.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_users_command_json(self, capsys):
        """Test users command with JSON output."""
        with patch("matty._create_client") as mock_create:
            client = MagicMock(spec=AsyncClient)
            mock_create.return_value = client

            with patch("matty._login", return_value=True):
                with patch("matty._sync_client", return_value=None):
                    room = MagicMock(spec=MatrixRoom)
                    room.room_id = "!room:matrix.org"
                    room.display_name = "Test Room"
                    room.topic = "Test topic"
                    room.member_count = 2
                    room.users = {"@alice:matrix.org": None, "@bob:matrix.org": None}

                    client.rooms = {"!room:matrix.org": room}

                    with patch("matty._find_room", return_value=("!room:matrix.org", "Test Room")):
                        client.close = AsyncMock()

                        await _execute_users_command("Test Room", "user", "pass", OutputFormat.json)

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["room"] == "Test Room"
        assert len(data["users"]) == 2


class TestErrorHandling:
    """Test error handling scenarios."""

    @pytest.mark.asyncio
    async def test_login_with_error_response(self):
        """Test login with error response."""
        client = MagicMock(spec=AsyncClient)
        error = ErrorResponse("Invalid credentials", "M_FORBIDDEN")
        client.login = AsyncMock(return_value=error)

        result = await _login(client, "wrong_pass")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_message_exception(self):
        """Test send message with exception."""
        client = MagicMock(spec=AsyncClient)
        client.room_send = AsyncMock(side_effect=Exception("Network error"))

        result = await _send_message(client, "!room:matrix.org", "Test")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_messages_error_response(self):
        """Test get messages with error response."""
        client = MagicMock(spec=AsyncClient)
        error = ErrorResponse("Forbidden", "M_FORBIDDEN")
        client.room_messages = AsyncMock(return_value=error)

        messages = await _get_messages(client, "!room:matrix.org", 10)
        assert messages == []

    @pytest.mark.asyncio
    async def test_sync_client_error(self):
        """Test sync client with error."""
        client = MagicMock(spec=AsyncClient)
        error = ErrorResponse("Sync failed", "M_UNKNOWN")
        client.sync = AsyncMock(return_value=error)

        # Should handle error gracefully
        await _sync_client(client)

    @pytest.mark.asyncio
    async def test_find_room_partial_match(self):
        """Test finding room with partial name match doesn't work."""
        client = MagicMock(spec=AsyncClient)

        room = MagicMock(spec=MatrixRoom)
        room.room_id = "!room:matrix.org"
        room.display_name = "Test Room"
        room.users = {"@user1:matrix.org": None}
        room.topic = None
        room.member_count = 1

        client.rooms = {"!room:matrix.org": room}

        # Partial match should not work
        result = await _find_room(client, "Test")
        assert result is None

        # Exact match (case insensitive) should work
        result = await _find_room(client, "test room")
        assert result == ("!room:matrix.org", "Test Room")


class TestThreadHandling:
    """Test thread handling functionality."""

    @pytest.mark.asyncio
    async def test_get_threads_empty(self):
        """Test getting threads from room with no threads."""
        client = MagicMock(spec=AsyncClient)

        mock_response = MagicMock()
        mock_response.chunk = []

        client.room_messages = AsyncMock(return_value=mock_response)

        threads = await _get_threads(client, "!room:matrix.org")
        assert threads == []

    @pytest.mark.asyncio
    async def test_get_thread_messages_with_deleted_root(self):
        """Test getting thread messages when root is deleted."""
        from nio import RoomMessageText

        client = MagicMock(spec=AsyncClient)

        # Create mock events - only replies, no root
        reply1 = MagicMock(spec=RoomMessageText)
        reply1.sender = "@user:matrix.org"
        reply1.body = "Reply 1"
        reply1.server_timestamp = 1704110500000
        reply1.event_id = "$reply1"
        reply1.source = {
            "content": {
                "body": "Reply 1",
                "msgtype": "m.text",
                "m.relates_to": {
                    "rel_type": "m.thread",
                    "event_id": "$missing_root",
                },
            }
        }

        mock_response = MagicMock()
        mock_response.chunk = [reply1]

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._get_or_create_handle", return_value="m1"):
            messages = await _get_thread_messages(client, "!room:matrix.org", "$missing_root")

        # Should have placeholder + reply
        assert len(messages) == 2
        assert messages[0].sender == "[system]"
        assert "not available" in messages[0].content
        assert messages[1].content == "Reply 1"

    @pytest.mark.asyncio
    async def test_get_message_by_handle_not_found(self):
        """Test getting message by handle when not found."""
        client = MagicMock(spec=AsyncClient)

        mock_response = MagicMock()
        mock_response.chunk = []

        client.room_messages = AsyncMock(return_value=mock_response)

        with patch("matty._lookup_mapping", return_value=None):
            msg = await _get_message_by_handle(client, "!room:matrix.org", "m999")
            assert msg is None


class TestConfigLoading:
    """Test configuration loading."""

    def test_load_config_with_env_vars(self, monkeypatch):
        """Test loading config from environment variables."""
        # Use real server from .env for testing
        monkeypatch.setenv("MATRIX_HOMESERVER", "https://m-test.mindroom.chat")
        monkeypatch.setenv("MATRIX_USERNAME", "mindroom_user")
        monkeypatch.setenv("MATRIX_PASSWORD", "user_secure_password")
        monkeypatch.setenv("MATRIX_SSL_VERIFY", "false")

        config = _load_config()
        assert config.homeserver == "https://m-test.mindroom.chat"
        assert config.username == "mindroom_user"
        assert config.password == "user_secure_password"
        assert config.ssl_verify is False

    def test_load_config_defaults(self, monkeypatch):
        """Test loading config with defaults."""
        # Clear any existing env vars
        monkeypatch.delenv("MATRIX_HOMESERVER", raising=False)
        monkeypatch.delenv("MATRIX_USERNAME", raising=False)
        monkeypatch.delenv("MATRIX_PASSWORD", raising=False)
        monkeypatch.delenv("MATRIX_SSL_VERIFY", raising=False)

        # Mock dotenv.load_dotenv to not load .env file
        with patch("matty.load_dotenv"):
            config = _load_config()
            assert config.homeserver == "https://matrix.org"
            assert config.username is None
            assert config.password is None
            assert config.ssl_verify is True

    def test_load_config_ssl_verify_false(self, monkeypatch):
        """Test loading config with SSL verify disabled."""
        monkeypatch.setenv("MATRIX_SSL_VERIFY", "false")

        config = _load_config()
        assert config.ssl_verify is False


class TestClientCreation:
    """Test Matrix client creation."""

    @pytest.mark.asyncio
    async def test_create_client_with_ssl_verify(self):
        """Test creating client with SSL verification enabled."""
        config = Config(
            "https://m-test.mindroom.chat", "mindroom_user", "user_secure_password", ssl_verify=True
        )

        with patch("matty.AsyncClient") as mock_client_class:
            await _create_client(config)

            # Verify AsyncClient was called with correct args
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args
            assert call_args[0][0] == "https://m-test.mindroom.chat"
            assert call_args[0][1] == "mindroom_user"
            assert call_args[1]["ssl"] is True

    @pytest.mark.asyncio
    async def test_create_client_without_ssl_verify(self):
        """Test creating client with SSL verification disabled."""
        config = Config(
            "https://m-test.mindroom.chat",
            "mindroom_user",
            "user_secure_password",
            ssl_verify=False,
        )

        with patch("matty.AsyncClient") as mock_client_class:
            await _create_client(config)

            # Verify AsyncClient was called with SSL disabled
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args
            assert call_args[0][0] == "https://m-test.mindroom.chat"
            assert call_args[0][1] == "mindroom_user"
            assert call_args[1]["ssl"] is False


class TestPydanticModels:
    """Test Pydantic model validation."""

    def test_thread_id_mapping_validation(self):
        """Test ThreadIdMapping model validation."""
        mapping = ThreadIdMapping()
        assert mapping.counter == 0
        assert mapping.id_to_matrix == {}
        assert mapping.matrix_to_id == {}

        # Test with data
        mapping = ThreadIdMapping(
            counter=5,
            id_to_matrix={1: "$event1", 2: "$event2"},
            matrix_to_id={"$event1": 1, "$event2": 2},
        )
        assert mapping.counter == 5
        assert mapping.id_to_matrix[1] == "$event1"

    def test_thread_id_mapping_key_conversion(self):
        """Test ThreadIdMapping converts string keys to int."""
        data = {
            "counter": 3,
            "id_to_matrix": {"1": "$event1", "2": "$event2"},
            "matrix_to_id": {"$event1": 1, "$event2": 2},
        }
        mapping = ThreadIdMapping(**data)
        assert mapping.id_to_matrix[1] == "$event1"
        assert mapping.id_to_matrix[2] == "$event2"

    def test_message_handle_mapping(self):
        """Test MessageHandleMapping model."""
        mapping = MessageHandleMapping()
        assert mapping.handle_counter == {}
        assert mapping.room_handles == {}
        assert mapping.room_handle_to_event == {}

        # Test with data
        mapping = MessageHandleMapping(
            handle_counter={"!room": 5},
            room_handles={"!room": {"$event": "m1"}},
            room_handle_to_event={"!room": {"m1": "$event"}},
        )
        assert mapping.handle_counter["!room"] == 5

    def test_server_state(self):
        """Test ServerState model."""
        state = ServerState()
        assert isinstance(state.thread_ids, ThreadIdMapping)
        assert isinstance(state.message_handles, MessageHandleMapping)
