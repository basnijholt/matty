"""Additional tests to improve coverage to >90%."""

from unittest.mock import patch

from typer.testing import CliRunner

from matty import (
    _load_config,
)

runner = CliRunner()


class TestConfigLoading:
    """Test configuration loading."""

    def test_load_config_with_env_vars(self, monkeypatch):
        """Test loading config from environment variables."""
        # Use real server from .env for testing
        monkeypatch.setenv("MATRIX_HOMESERVER", "https://m-test.mindroom.chat")
        monkeypatch.setenv("MATRIX_USERNAME", "mindroom_user")
        monkeypatch.setenv("MATRIX_PASSWORD", "user_secure_password")
        monkeypatch.setenv("MATRIX_SSL_VERIFY", "false")

        config = _load_config()
        assert config.homeserver == "https://m-test.mindroom.chat"
        assert config.username == "mindroom_user"
        assert config.password == "user_secure_password"
        assert config.ssl_verify is False

    def test_load_config_defaults(self, monkeypatch):
        """Test loading config with defaults."""
        # Clear any existing env vars
        monkeypatch.delenv("MATRIX_HOMESERVER", raising=False)
        monkeypatch.delenv("MATRIX_USERNAME", raising=False)
        monkeypatch.delenv("MATRIX_PASSWORD", raising=False)
        monkeypatch.delenv("MATRIX_SSL_VERIFY", raising=False)

        # Mock dotenv.load_dotenv to not load .env file
        with patch("matty.load_dotenv"):
            config = _load_config()
            assert config.homeserver == "https://matrix.org"
            assert config.username is None
            assert config.password is None
            assert config.ssl_verify is True

    def test_load_config_ssl_verify_false(self, monkeypatch):
        """Test loading config with SSL verify disabled."""
        monkeypatch.setenv("MATRIX_SSL_VERIFY", "false")

        config = _load_config()
        assert config.ssl_verify is False
