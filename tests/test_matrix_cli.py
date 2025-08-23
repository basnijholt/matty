"""Tests for matty module."""

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from matty import (
    Config,
    Message,
    OutputFormat,
    _get_or_create_id,
    _resolve_id,
    app,
)

runner = CliRunner()


def test_config_defaults():
    """Test Config dataclass defaults."""
    config = Config()
    assert config.homeserver == "https://matrix.org"
    assert config.username is None
    assert config.password is None
    assert config.ssl_verify is True


def test_message_dataclass():
    """Test Message dataclass."""
    from datetime import UTC, datetime

    msg = Message(
        sender="@user:matrix.org",
        content="Test message",
        timestamp=datetime.now(UTC),
        room_id="!room:matrix.org",
        event_id="$event123",
    )
    assert msg.sender == "@user:matrix.org"
    assert msg.content == "Test message"
    assert msg.thread_root_id is None
    assert msg.reply_to_id is None
    assert msg.is_thread_root is False


def test_output_format_enum():
    """Test OutputFormat enum."""
    assert OutputFormat.rich == "rich"
    assert OutputFormat.simple == "simple"
    assert OutputFormat.json == "json"


def test_id_mapping_functions(tmp_path, monkeypatch):
    """Test ID mapping functions."""
    import matty

    # Use temporary state directory for testing
    test_state_dir = tmp_path / ".config" / "matty" / "state"
    test_state_dir.mkdir(parents=True, exist_ok=True)

    # Patch the state file path to use test directory
    def _get_test_state_file(server=None):  # noqa: ARG001
        return test_state_dir / "test.matrix.org.json"

    monkeypatch.setattr("matty._get_state_file", _get_test_state_file)
    monkeypatch.setattr("matty._state_cache", {})

    # Test creating new ID
    matrix_id = "$test123:matrix.org"
    simple_id = _get_or_create_id(matrix_id)
    assert simple_id == 1

    # Test getting existing ID
    same_id = _get_or_create_id(matrix_id)
    assert same_id == 1

    # Verify the state was saved
    state_file = test_state_dir / "test.matrix.org.json"
    assert state_file.exists()

    # Clear cache and test that ID persists
    matty._state_cache = {}
    loaded_id = _get_or_create_id(matrix_id)
    assert loaded_id == 1


def test_resolve_id(tmp_path, monkeypatch):
    """Test ID resolution."""

    # Use temporary state directory for testing
    test_state_dir = tmp_path / ".config" / "matty" / "state"
    test_state_dir.mkdir(parents=True, exist_ok=True)

    def _get_test_state_file(server=None):  # noqa: ARG001
        return test_state_dir / "test.matrix.org.json"

    monkeypatch.setattr("matty._get_state_file", _get_test_state_file)
    monkeypatch.setattr("matty._state_cache", {})

    # Setup test data by creating IDs
    _get_or_create_id("$test:matrix.org")  # Will be ID 1
    _get_or_create_id("!room:matrix.org")  # Will be ID 2

    # Test simple ID resolution (just numbers)
    assert _resolve_id("1") == "$test:matrix.org"
    assert _resolve_id("2") == "!room:matrix.org"

    # Test Matrix ID passthrough
    assert _resolve_id("$event:matrix.org") == "$event:matrix.org"
    assert _resolve_id("!room:matrix.org") == "!room:matrix.org"

    # Test invalid inputs
    assert _resolve_id("invalid") is None
    assert _resolve_id("999") is None


def test_cli_help():
    """Test CLI help command."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Functional Matrix CLI client" in result.output


def test_rooms_command_help():
    """Test rooms command help."""
    result = runner.invoke(app, ["rooms", "--help"])
    assert result.exit_code == 0
    assert "List all joined rooms" in result.output


def test_messages_command_help():
    """Test messages command help."""
    result = runner.invoke(app, ["messages", "--help"])
    assert result.exit_code == 0
    assert "messages" in result.output.lower()


@pytest.mark.asyncio
async def test_login_failure():
    """Test login failure handling."""
    from nio import AsyncClient, LoginError

    from matty import _login

    client = MagicMock(spec=AsyncClient)
    client.login = MagicMock(side_effect=LoginError("Invalid password"))

    result = await _login(client, "wrong_password")
    assert result is False


@pytest.mark.asyncio
async def test_send_message_success():
    """Test successful message sending."""
    from unittest.mock import AsyncMock

    from nio import AsyncClient, RoomSendResponse

    from matty import _send_message

    client = MagicMock(spec=AsyncClient)
    response = RoomSendResponse("$event123", "!room:matrix.org")
    client.room_send = AsyncMock(return_value=response)
    # Add rooms attribute for mention parsing
    client.rooms = {
        "!room:matrix.org": MagicMock(
            users={"@user1:matrix.org": {}, "@user2:matrix.org": {}}
        )
    }

    result = await _send_message(client, "!room:matrix.org", "Test message")
    assert result is True
    client.room_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_message_with_thread():
    """Test sending message in thread."""
    from unittest.mock import AsyncMock

    from nio import AsyncClient, RoomSendResponse

    from matty import _send_message

    client = MagicMock(spec=AsyncClient)
    response = RoomSendResponse("$event456", "!room:matrix.org")
    client.room_send = AsyncMock(return_value=response)
    # Add rooms attribute for mention parsing
    client.rooms = {
        "!room:matrix.org": MagicMock(
            users={"@user1:matrix.org": {}, "@user2:matrix.org": {}}
        )
    }

    result = await _send_message(
        client, "!room:matrix.org", "Thread reply", thread_root_id="$thread123"
    )
    assert result is True

    # Check that thread relation was added
    call_args = client.room_send.call_args
    content = call_args[1]["content"]
    assert "m.relates_to" in content
    assert content["m.relates_to"]["rel_type"] == "m.thread"
    assert content["m.relates_to"]["event_id"] == "$thread123"
