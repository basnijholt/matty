"""Additional tests to improve coverage to >90%."""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from matty import (
    Config,
    _create_client,
)

runner = CliRunner()


class TestClientCreation:
    """Test Matrix client creation."""

    @pytest.mark.asyncio
    async def test_create_client_with_ssl_verify(self):
        """Test creating client with SSL verification enabled."""
        config = Config(
            "https://m-test.mindroom.chat", "mindroom_user", "user_secure_password", ssl_verify=True
        )

        with patch("matty.AsyncClient") as mock_client_class:
            await _create_client(config)

            # Verify AsyncClient was called with correct args
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args
            assert call_args[0][0] == "https://m-test.mindroom.chat"
            assert call_args[0][1] == "mindroom_user"
            assert call_args[1]["ssl"] is True

    @pytest.mark.asyncio
    async def test_create_client_without_ssl_verify(self):
        """Test creating client with SSL verification disabled."""
        config = Config(
            "https://m-test.mindroom.chat",
            "mindroom_user",
            "user_secure_password",
            ssl_verify=False,
        )

        with patch("matty.AsyncClient") as mock_client_class:
            await _create_client(config)

            # Verify AsyncClient was called with SSL disabled
            mock_client_class.assert_called_once()
            call_args = mock_client_class.call_args
            assert call_args[0][0] == "https://m-test.mindroom.chat"
            assert call_args[0][1] == "mindroom_user"
            assert call_args[1]["ssl"] is False
