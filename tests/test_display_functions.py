"""Additional tests to improve coverage to >90%."""

import json
from datetime import UTC, datetime

from typer.testing import CliRunner

from matty import (
    Message,
    Room,
    _display_messages_json,
    _display_messages_rich,
    _display_messages_simple,
    _display_rooms_json,
    _display_rooms_rich,
    _display_rooms_simple,
    _display_users_json,
    _display_users_rich,
    _display_users_simple,
)

runner = CliRunner()


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
