"""Fixed tests for matty module to increase code coverage."""

from datetime import UTC, datetime
from unittest.mock import patch

from typer.testing import CliRunner

from matty import (
    Message,
    Room,
    _load_config,
)

runner = CliRunner()


class TestDataclasses:
    """Test dataclass functionality."""

    def test_room_dataclass(self):
        """Test Room dataclass."""
        room = Room(
            room_id="!test:matrix.org",
            name="Test Room",
            member_count=10,
            topic="Test topic",
        )
        assert room.room_id == "!test:matrix.org"
        assert room.name == "Test Room"
        assert room.member_count == 10
        assert room.topic == "Test topic"

    def test_room_dataclass_defaults(self):
        """Test Room dataclass with defaults."""
        room = Room(room_id="!test:matrix.org", name="Test", member_count=0)
        assert room.member_count == 0
        assert room.topic is None

    def test_message_with_thread(self):
        """Test Message dataclass with thread information."""
        msg = Message(
            sender="@user:matrix.org",
            content="Thread message",
            timestamp=datetime.now(UTC),
            room_id="!room:matrix.org",
            event_id="$event123",
            thread_root_id="$thread123",
            reply_to_id="$reply123",
        )
        assert msg.thread_root_id == "$thread123"
        assert msg.reply_to_id == "$reply123"
        assert msg.is_thread_root is False

    def test_config_from_env(self):
        """Test Config loading from environment variables."""
        with patch.dict(
            "os.environ",
            {
                "MATRIX_HOMESERVER": "https://custom.server",
                "MATRIX_USERNAME": "testuser",
                "MATRIX_PASSWORD": "testpass",
                "MATRIX_SSL_VERIFY": "false",
            },
        ):
            config = _load_config()
            assert config.homeserver == "https://custom.server"
            assert config.username == "testuser"
            assert config.password == "testpass"
            assert config.ssl_verify is False
