"""Additional tests to improve coverage to >90%."""

from unittest.mock import AsyncMock, patch

import pytest
from nio import AsyncClientConfig, SyncError
from typer.testing import CliRunner

from matty import (
    Config,
    _create_client,
)
from matty.cli import (
    _CLI_SYNC_FILTER,
    _DEFAULT_MAX_TIMEOUTS,
    MatrixSyncError,
    _build_client_config,
    _sync_client,
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

    @pytest.mark.asyncio
    async def test_create_client_bounds_nio_timeout_retries(self) -> None:
        """One-shot CLI clients cap nio's retry loop to avoid endless sleeps."""
        config = Config("https://m-test.mindroom.chat", "u", "p")

        with patch("matty.AsyncClient") as mock_client_class:
            await _create_client(config)

            passed_config = mock_client_class.call_args.kwargs["config"]
            assert isinstance(passed_config, AsyncClientConfig)
            assert passed_config.max_timeouts == _DEFAULT_MAX_TIMEOUTS
            assert passed_config.max_timeouts is not None
            assert passed_config.max_timeouts >= 1


def test_build_client_config_bounds_timeout_retries() -> None:
    cfg = _build_client_config()

    assert isinstance(cfg, AsyncClientConfig)
    assert cfg.max_timeouts is not None
    assert cfg.max_timeouts >= 1
    assert cfg.request_timeout > 0


class TestSyncClient:
    """Test :func:`_sync_client` behavior around errors and filters."""

    @pytest.mark.asyncio
    async def test_sync_uses_slim_cli_filter(self) -> None:
        client = AsyncMock()
        # A plain object won't match isinstance(_, SyncError).
        client.sync = AsyncMock(return_value=object())

        await _sync_client(client, timeout=123)

        call = client.sync.await_args
        assert call.kwargs["timeout"] == 123
        assert call.kwargs["sync_filter"] == _CLI_SYNC_FILTER
        # Lazy-load members keeps initial /sync cheap on large accounts.
        room = _CLI_SYNC_FILTER["room"]
        assert isinstance(room, dict)
        assert room["state"]["lazy_load_members"] is True
        assert room["timeline"]["lazy_load_members"] is True

    @pytest.mark.asyncio
    async def test_sync_raises_matrix_sync_error_on_sync_error_response(self) -> None:
        client = AsyncMock()
        err = SyncError.from_dict({"errcode": "M_UNKNOWN", "error": "boom"})
        client.sync = AsyncMock(return_value=err)

        with pytest.raises(MatrixSyncError, match="boom"):
            await _sync_client(client)

    @pytest.mark.asyncio
    async def test_sync_raises_matrix_sync_error_when_response_has_no_message(self) -> None:
        client = AsyncMock()
        # Simulate the historic nio "next_batch is a required property" path:
        # schema validation fails, so nio returns a SyncError with no message.
        err = SyncError.from_dict({})
        client.sync = AsyncMock(return_value=err)

        with pytest.raises(MatrixSyncError, match="Matrix /sync failed"):
            await _sync_client(client)
