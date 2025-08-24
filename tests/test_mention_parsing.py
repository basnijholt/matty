"""Additional tests to improve coverage to >90%."""

from typer.testing import CliRunner

from matty import (
    _parse_mentions,
)

runner = CliRunner()


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
