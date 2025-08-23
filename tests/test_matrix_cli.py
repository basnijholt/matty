"""Tests for matty module."""

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from matty import (
    Config,
    Message,
    OutputFormat,
    _get_or_create_id,
    _load_id_mappings,
    _resolve_id,
    _save_id_mappings,
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
    # Use temporary file for testing
    test_file = tmp_path / "test_ids.json"
    monkeypatch.setattr("matty.ID_MAP_FILE", test_file)

    # Reset global state
    import matty

    matty._id_counter = 0
    matty._id_to_matrix = {}
    matty._matrix_to_id = {}

    # Test creating new ID
    matrix_id = "$test123:matrix.org"
    simple_id = _get_or_create_id(matrix_id)
    assert simple_id == 1
    assert matty._id_to_matrix[1] == matrix_id
    assert matty._matrix_to_id[matrix_id] == 1

    # Test getting existing ID
    same_id = _get_or_create_id(matrix_id)
    assert same_id == 1

    # Test saving and loading
    _save_id_mappings()
    assert test_file.exists()

    # Reset and load
    matty._id_counter = 0
    matty._id_to_matrix = {}
    matty._matrix_to_id = {}

    _load_id_mappings()
    assert matty._id_counter == 1
    assert matty._id_to_matrix[1] == matrix_id
    assert matty._matrix_to_id[matrix_id] == 1


def test_resolve_id():
    """Test ID resolution."""
    import matty

    # Setup test data
    matty._id_to_matrix = {1: "$test:matrix.org", 2: "!room:matrix.org"}
    matty._matrix_to_id = {"$test:matrix.org": 1, "!room:matrix.org": 2}

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

    result = await _login(client, "user", "wrong_password")
    assert result is False


@pytest.mark.asyncio
async def test_send_message_success():
    """Test successful message sending."""
    from unittest.mock import AsyncMock

    from nio import AsyncClient

    from matty import _send_message

    client = MagicMock(spec=AsyncClient)
    client.room_send = AsyncMock(return_value=None)
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

    from nio import AsyncClient

    from matty import _send_message

    client = MagicMock(spec=AsyncClient)
    client.room_send = AsyncMock(return_value=None)
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
