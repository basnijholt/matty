"""Authentication command and helper tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import httpx
import pytest
from typer.testing import CliRunner

from matty import Config
from matty.auth import (
    LoginResult,
    SSOProvider,
    build_sso_redirect_url,
    login_with_token,
    parse_sso_providers,
)
from matty.cli import _authenticate_client, _load_config, app

if TYPE_CHECKING:
    from pathlib import Path


runner = CliRunner()


def _clear_matrix_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "MATRIX_HOMESERVER",
        "MATRIX_USERNAME",
        "MATRIX_PASSWORD",
        "MATRIX_SSL_VERIFY",
        "MATRIX_USER_ID",
        "MATRIX_DEVICE_ID",
        "MATRIX_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def test_auth_help_lists_all_auth_modes() -> None:
    result = runner.invoke(app, ["auth", "--help"])

    assert result.exit_code == 0
    assert "token" in result.output
    assert "password" in result.output
    assert "sso-url" in result.output
    assert "providers" in result.output
    assert "sso" in result.output
    assert "login-token" in result.output
    assert "logout" in result.output


def test_auth_token_writes_stored_access_token_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"

    result = runner.invoke(
        app,
        [
            "auth",
            "token",
            "https://matrix.example.com/",
            "@alice:example.com",
            "test-token",
            "--device-id",
            "TESTDEVICE",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["homeserver"] == "https://matrix.example.com"
    assert saved["user_id"] == "@alice:example.com"
    assert saved["device_id"] == "TESTDEVICE"
    assert saved["access_token"] == "test-token"
    assert "password" not in saved


def test_auth_logout_removes_stored_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text('{"homeserver": "https://matrix.example.com"}\n', encoding="utf-8")

    result = runner.invoke(app, ["auth", "logout", "--config", str(config_path)])

    assert result.exit_code == 0
    assert not config_path.exists()
    assert "Removed Matty credentials" in result.output


def test_load_config_reads_stored_access_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear_matrix_env(monkeypatch)
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "homeserver": "https://matrix.example.com",
                "user_id": "@alice:example.com",
                "device_id": "TESTDEVICE",
                "access_token": "test-token",
                "ssl_verify": False,
            }
        ),
        encoding="utf-8",
    )

    config = _load_config(config_path)

    assert config.homeserver == "https://matrix.example.com"
    assert config.user_id == "@alice:example.com"
    assert config.device_id == "TESTDEVICE"
    assert config.access_token == "test-token"
    assert config.ssl_verify is False


def test_environment_overrides_stored_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "homeserver": "https://stored.example.com",
                "user_id": "@stored:example.com",
                "device_id": "STORED",
                "access_token": "stored-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MATRIX_HOMESERVER", "https://env.example.com")
    monkeypatch.setenv("MATRIX_USER_ID", "@env:example.com")
    monkeypatch.setenv("MATRIX_DEVICE_ID", "ENVDEVICE")
    monkeypatch.setenv("MATRIX_ACCESS_TOKEN", "env-token")

    config = _load_config(config_path)

    assert config.homeserver == "https://env.example.com"
    assert config.user_id == "@env:example.com"
    assert config.device_id == "ENVDEVICE"
    assert config.access_token == "env-token"


def test_authenticate_client_restores_access_token() -> None:
    client = MagicMock()
    config = Config(
        homeserver="https://matrix.example.com",
        user_id="@alice:example.com",
        device_id="TESTDEVICE",
        access_token="test-token",
    )

    assert _authenticate_client(client, config) is True

    client.restore_login.assert_called_once_with(
        user_id="@alice:example.com",
        device_id="TESTDEVICE",
        access_token="test-token",
    )


def test_build_sso_redirect_url_includes_redirect_url() -> None:
    url = build_sso_redirect_url(
        homeserver="https://matrix.example.com",
        redirect_url="http://127.0.0.1:8767/callback",
    )

    assert url == (
        "https://matrix.example.com/_matrix/client/v3/login/sso/redirect?"
        "redirectUrl=http%3A%2F%2F127.0.0.1%3A8767%2Fcallback"
    )


def test_parse_sso_providers_reads_matrix_login_flows() -> None:
    providers = parse_sso_providers(
        {
            "flows": [
                {"type": "m.login.password"},
                {
                    "type": "m.login.sso",
                    "identity_providers": [
                        {"id": "google", "name": "Google", "brand": "google"},
                        {"id": "github", "name": "GitHub", "brand": "github"},
                    ],
                },
            ],
        }
    )

    assert providers == [
        SSOProvider(id="google", name="Google", brand="google"),
        SSOProvider(id="github", name="GitHub", brand="github"),
    ]


@pytest.mark.asyncio
async def test_login_with_token_fetches_user_id_when_login_response_omits_it() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/_matrix/client/v3/login":
            return httpx.Response(
                200,
                json={
                    "access_token": "test-access-token",
                    "device_id": "TESTDEVICE",
                },
            )
        if request.url.path == "/_matrix/client/v3/account/whoami":
            assert request.headers["authorization"] == "Bearer test-access-token"
            return httpx.Response(200, json={"user_id": "@alice:example.com"})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await login_with_token(
            homeserver="https://matrix.example.com",
            login_token="test-login-token",
            http_client=http_client,
        )

    assert result == LoginResult(
        homeserver="https://matrix.example.com",
        user_id="@alice:example.com",
        device_id="TESTDEVICE",
        access_token="test-access-token",
    )
    assert requests == [
        ("POST", "/_matrix/client/v3/login"),
        ("GET", "/_matrix/client/v3/account/whoami"),
    ]
