"""Additional tests to improve coverage to >90%."""

from typer.testing import CliRunner

from matty import (
    ServerState,
    _resolve_thread_id,
)

runner = CliRunner()


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
