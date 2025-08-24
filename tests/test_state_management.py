"""Additional tests to improve coverage to >90%."""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from matty import (
    ServerState,
    _get_state_file,
    _load_state,
    _lookup_mapping,
    _save_state,
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
