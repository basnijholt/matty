"""Additional tests to improve coverage to >90%."""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from matty import (
    _validate_required_args,
)

runner = CliRunner()


class TestCLIValidation:
    """Test CLI argument validation."""

    def test_validate_required_args_present(self):
        """Test validation when required args present."""
        ctx = MagicMock()
        ctx.command.name = "test"
        # Should not raise
        _validate_required_args(ctx, room="TestRoom")

    def test_validate_required_args_missing(self):
        """Test validation when required args missing."""
        import typer

        ctx = MagicMock()
        ctx.command.name = "test"

        with pytest.raises(typer.Exit), patch("matty.console.print") as mock_print:
            _validate_required_args(ctx, room=None)
            mock_print.assert_called()
