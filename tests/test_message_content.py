"""More tests to reach >90% coverage."""

from matty import (
    _build_message_content,
)


class TestMessageContent:
    """Test message content building with various options."""

    def test_build_message_with_all_options(self):
        """Test building message with all relations."""
        content = _build_message_content(
            "Test message",
            formatted_body="<b>Test message</b>",
            mentioned_user_ids=["@user:matrix.org"],
            thread_root_id="$thread123",
            reply_to_id="$reply456",
        )

        assert content["body"] == "Test message"
        assert content["formatted_body"] == "<b>Test message</b>"
        assert content["format"] == "org.matrix.custom.html"
        assert content["m.mentions"]["user_ids"] == ["@user:matrix.org"]
        assert content["m.relates_to"]["rel_type"] == "m.thread"
        assert content["m.relates_to"]["event_id"] == "$thread123"
        assert content["m.relates_to"]["m.in_reply_to"]["event_id"] == "$reply456"
