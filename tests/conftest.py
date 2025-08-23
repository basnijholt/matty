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

    # Use temporary directory for state files
    test_state_dir = tmp_path / ".config" / "matty" / "state"
    test_state_dir.mkdir(parents=True, exist_ok=True)

    # Patch the state file path to use test directory
    def _get_test_state_file(server=None):
        from urllib.parse import urlparse

        if server is None:
            server = "https://test.matrix.org"

        if server.startswith(("http://", "https://")):
            domain = urlparse(server).netloc
        else:
            domain = server

        return test_state_dir / f"{domain}.json"

    monkeypatch.setattr("matty._get_state_file", _get_test_state_file)

    # Clear the state for tests
    monkeypatch.setattr("matty._state", None)

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
