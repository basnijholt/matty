"""Additional tests to improve coverage to >90%."""

from typer.testing import CliRunner

from matty import (
    MessageHandleMapping,
    ServerState,
    ThreadIdMapping,
)

runner = CliRunner()


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
