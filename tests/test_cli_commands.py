"""Additional tests to improve coverage to >90%."""

from unittest.mock import patch

from typer.testing import CliRunner

from matty import (
    Config,
    app,
)

runner = CliRunner()


class TestCLICommands:
    """Test CLI command execution."""

    def test_cli_help(self):
        """Test help command."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Functional Matrix CLI client" in result.output

    def test_cli_rooms_no_creds(self):
        """Test rooms command without credentials."""
        with patch("matty._load_config") as mock_load:
            mock_load.return_value = Config("https://matrix.org", None, None)
            # Mock the async execution to avoid actual connection
            with patch("matty.asyncio.run") as mock_run:
                mock_run.side_effect = Exception("No credentials")
                result = runner.invoke(app, ["rooms"])
                # Should handle the exception
                assert result.exit_code == 1

    def test_cli_messages_no_room(self):
        """Test messages command without room argument."""
        result = runner.invoke(app, ["messages"])
        assert result.exit_code != 0

    def test_cli_send_no_message(self):
        """Test send command without message."""
        result = runner.invoke(app, ["send", "TestRoom"])
        assert result.exit_code != 0

    def test_cli_thread_start_no_handle(self):
        """Test thread-start command without handle."""
        result = runner.invoke(app, ["thread-start", "TestRoom"])
        assert result.exit_code != 0

    def test_cli_react_no_emoji(self):
        """Test react command without emoji."""
        result = runner.invoke(app, ["react", "TestRoom", "m1"])
        assert result.exit_code != 0

    def test_cli_edit_no_content(self):
        """Test edit command without new content."""
        result = runner.invoke(app, ["edit", "TestRoom", "m1"])
        assert result.exit_code != 0
