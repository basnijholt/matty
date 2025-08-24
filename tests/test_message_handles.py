"""Additional tests to improve coverage to >90%."""

from unittest.mock import patch

from typer.testing import CliRunner

from matty import (
    ServerState,
    _get_event_id_from_handle,
    _get_or_create_handle,
)

runner = CliRunner()


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
