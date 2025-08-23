"""Pytest configuration and fixtures."""

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def env_setup(monkeypatch, tmp_path):
    """Set up environment variables for tests."""
    # Use test server configuration
    monkeypatch.setenv("MATRIX_HOMESERVER", "https://test.matrix.org")
    monkeypatch.setenv("MATRIX_USERNAME", "test_user")
    monkeypatch.setenv("MATRIX_PASSWORD", "test_password")
    monkeypatch.setenv("MATRIX_SSL_VERIFY", "false")

    # Use temporary directory for ID mappings
    test_id_file = tmp_path / "test_matrix_ids.json"
    monkeypatch.setattr("matrix_cli.ID_MAP_FILE", test_id_file)

    yield


@pytest.fixture
def mock_client():
    """Create a mock Matrix client."""
    from unittest.mock import MagicMock

    from nio import AsyncClient

    client = MagicMock(spec=AsyncClient)
    client.homeserver = "https://test.matrix.org"
    client.user_id = "@test_user:test.matrix.org"
    client.device_id = "TEST_DEVICE"
    client.rooms = {}

    return client
