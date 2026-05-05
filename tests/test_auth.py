"""Authentication command and helper tests."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from nio import LoginResponse
from typer.testing import CliRunner

from matty import Config
from matty.auth import (
    LoginResult,
    SSOCallbackServer,
    SSOProvider,
    build_sso_redirect_url,
    extract_login_token,
    fetch_sso_providers,
    login_with_password,
    login_with_token,
    parse_sso_providers,
    resolve_sso_provider_id,
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


def test_auth_logout_is_idempotent(tmp_path: Path) -> None:
    config_path = tmp_path / "missing.json"

    result = runner.invoke(app, ["auth", "logout", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "No Matty credentials found" in result.output


def test_config_path_prints_default_path() -> None:
    result = runner.invoke(app, ["config-path"])

    assert result.exit_code == 0
    assert result.output.strip().endswith(".config/matty/config.json")


def test_auth_sso_url_opens_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("matty.cli.webbrowser.open", opened.append)
    monkeypatch.setattr(
        "matty.cli.fetch_sso_providers",
        lambda **_kwargs: [SSOProvider(id="Ov23li6wDSuBsiVjYWar", name="GitHub", brand="github")],
    )

    result = runner.invoke(
        app,
        [
            "auth",
            "sso-url",
            "https://matrix.example.com",
            "http://127.0.0.1:8767/callback",
            "--idp-id",
            "github",
            "--open",
        ],
    )

    assert result.exit_code == 0
    assert (
        "https://matrix.example.com/_matrix/client/v3/login/sso/redirect/"
        "Ov23li6wDSuBsiVjYWar?" in result.output
    )
    assert opened == [result.output.strip()]


def test_auth_providers_lists_provider_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_fetch_sso_providers(*, homeserver: str, ssl_verify: bool = True) -> list[SSOProvider]:
        assert homeserver == "https://matrix.example.com"
        assert ssl_verify is False
        return [
            SSOProvider(id="google", name="Google", brand="google"),
            SSOProvider(id="github", name="GitHub", brand="github"),
        ]

    monkeypatch.setattr("matty.cli.fetch_sso_providers", fake_fetch_sso_providers)

    result = runner.invoke(
        app,
        ["auth", "providers", "https://matrix.example.com", "--no-ssl-verify"],
    )

    assert result.exit_code == 0
    assert "google\tGoogle" in result.output
    assert "github\tGitHub" in result.output


def test_auth_providers_reports_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("matty.cli.fetch_sso_providers", lambda **_kwargs: [])

    result = runner.invoke(app, ["auth", "providers", "https://matrix.example.com"])

    assert result.exit_code == 0
    assert "No Matrix SSO providers" in result.output


def test_auth_password_saves_login_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"

    async def fake_login_with_password(**kwargs) -> LoginResult:
        assert kwargs["homeserver"] == "https://matrix.example.com"
        assert kwargs["user"] == "@alice:example.com"
        assert kwargs["password"] == "secret"
        assert kwargs["device_name"] == "matty"
        assert kwargs["ssl_verify"] is False
        return LoginResult(
            homeserver="https://matrix.example.com",
            user_id="@alice:example.com",
            device_id="TESTDEVICE",
            access_token="test-token",
            ssl_verify=False,
        )

    monkeypatch.setattr("matty.cli.login_with_password", fake_login_with_password)

    result = runner.invoke(
        app,
        [
            "auth",
            "password",
            "https://matrix.example.com",
            "@alice:example.com",
            "--password",
            "secret",
            "--no-ssl-verify",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["user_id"] == "@alice:example.com"
    assert saved["device_id"] == "TESTDEVICE"
    assert saved["access_token"] == "test-token"
    assert saved["ssl_verify"] is False


def test_auth_login_token_saves_login_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.json"

    async def fake_login_with_token(**kwargs) -> LoginResult:
        assert kwargs["login_token"] == "single-use-token"
        return LoginResult(
            homeserver="https://matrix.example.com",
            user_id="@alice:example.com",
            device_id="TESTDEVICE",
            access_token="test-token",
        )

    monkeypatch.setattr("matty.cli.login_with_token", fake_login_with_token)

    result = runner.invoke(
        app,
        [
            "auth",
            "login-token",
            "https://matrix.example.com",
            "single-use-token",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "test-token"


def test_auth_sso_waits_for_callback_and_saves_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.json"
    closed: list[bool] = []
    opened: list[str] = []

    class FakeCallback:
        redirect_url = "http://127.0.0.1:8767/callback"

        def __init__(self, *, host: str, port: int) -> None:
            assert host == "127.0.0.1"
            assert port == 0

        def wait_for_token(self) -> str:
            self.close()
            return "sso-login-token"

        def close(self) -> None:
            closed.append(True)

    async def fake_login_with_token(**kwargs) -> LoginResult:
        assert kwargs["login_token"] == "sso-login-token"
        return LoginResult(
            homeserver="https://matrix.example.com",
            user_id="@alice:example.com",
            device_id="TESTDEVICE",
            access_token="test-token",
        )

    monkeypatch.setattr("matty.cli.SSOCallbackServer", FakeCallback)
    monkeypatch.setattr("matty.cli.login_with_token", fake_login_with_token)
    monkeypatch.setattr("matty.cli.webbrowser.open", opened.append)

    result = runner.invoke(
        app,
        ["auth", "sso", "https://matrix.example.com", "--config", str(config_path)],
    )

    assert result.exit_code == 0
    assert opened
    assert closed == [True, True]
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["access_token"] == "test-token"


def test_auth_sso_resolves_provider_name_to_advertised_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.json"
    opened: list[str] = []

    class FakeCallback:
        redirect_url = "http://127.0.0.1:8767/callback"

        def __init__(self, *, host: str, port: int) -> None:
            assert host == "127.0.0.1"
            assert port == 0

        def wait_for_token(self) -> str:
            return "sso-login-token"

        def close(self) -> None:
            pass

    async def fake_login_with_token(**_kwargs) -> LoginResult:
        return LoginResult(
            homeserver="https://mindroom.chat",
            user_id="@alice:mindroom.chat",
            device_id="TESTDEVICE",
            access_token="test-token",
        )

    def fake_fetch_sso_providers(**_kwargs) -> list[SSOProvider]:
        return [
            SSOProvider(id="Ov23li6wDSuBsiVjYWar", name="github", brand="github"),
        ]

    monkeypatch.setattr("matty.cli.SSOCallbackServer", FakeCallback)
    monkeypatch.setattr("matty.cli.login_with_token", fake_login_with_token)
    monkeypatch.setattr("matty.cli.fetch_sso_providers", fake_fetch_sso_providers)
    monkeypatch.setattr("matty.cli.webbrowser.open", opened.append)

    result = runner.invoke(
        app,
        [
            "auth",
            "sso",
            "https://mindroom.chat",
            "--idp-id",
            "github",
            "--config",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert opened == [
        (
            "https://mindroom.chat/_matrix/client/v3/login/sso/redirect/"
            "Ov23li6wDSuBsiVjYWar?redirectUrl=http%3A%2F%2F127.0.0.1%3A8767%2Fcallback"
        )
    ]


def test_auth_sso_rejects_unknown_advertised_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "matty.cli.fetch_sso_providers",
        lambda **_kwargs: [SSOProvider(id="Ov23li6wDSuBsiVjYWar", name="github", brand="github")],
    )

    result = runner.invoke(
        app,
        [
            "auth",
            "sso",
            "https://mindroom.chat",
            "--idp-id",
            "gitlab",
        ],
    )

    assert result.exit_code != 0
    assert "gitlab" in result.output
    assert "Available providers" in result.output


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


def test_extract_login_token_from_callback_query() -> None:
    assert extract_login_token("loginToken=abc123&state=ignored") == "abc123"


def test_extract_login_token_requires_token() -> None:
    with pytest.raises(ValueError, match="loginToken"):
        extract_login_token("state=ignored")


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


def test_resolve_sso_provider_id_accepts_name_or_brand_alias() -> None:
    providers = [
        SSOProvider(
            id="974295579207-8d3ippmssoiaibuu04id02sb66rgi1h3.apps.googleusercontent.com",
            name="google",
            brand="google",
        ),
        SSOProvider(id="Ov23li6wDSuBsiVjYWar", name="github", brand="github"),
    ]

    assert resolve_sso_provider_id("github", providers) == "Ov23li6wDSuBsiVjYWar"
    assert resolve_sso_provider_id("GOOGLE", providers) == (
        "974295579207-8d3ippmssoiaibuu04id02sb66rgi1h3.apps.googleusercontent.com"
    )


def test_resolve_sso_provider_id_reports_ambiguous_alias() -> None:
    providers = [
        SSOProvider(id="one", name="GitHub"),
        SSOProvider(id="two", brand="github"),
    ]

    with pytest.raises(ValueError, match="ambiguous"):
        resolve_sso_provider_id("github", providers)


def test_fetch_sso_providers_reads_login_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, *, timeout: int, verify: bool) -> httpx.Response:
        assert url == "https://matrix.example.com/_matrix/client/v3/login"
        assert timeout == 10
        assert verify is False
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "flows": [
                    {
                        "type": "m.login.sso",
                        "identity_providers": [{"id": "github", "name": "GitHub"}],
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    assert fetch_sso_providers(homeserver="https://matrix.example.com/", ssl_verify=False) == [
        SSOProvider(id="github", name="GitHub")
    ]


def test_sso_callback_server_receives_login_token() -> None:
    callback = SSOCallbackServer()

    def open_callback() -> None:
        with urllib.request.urlopen(f"{callback.redirect_url}?loginToken=abc123", timeout=10):
            pass

    thread = threading.Thread(target=open_callback)
    thread.start()
    try:
        assert callback.wait_for_token() == "abc123"
    finally:
        thread.join(timeout=10)


def test_sso_callback_server_reports_missing_login_token() -> None:
    callback = SSOCallbackServer()

    def open_callback() -> None:
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"{callback.redirect_url}?state=missing", timeout=10)

    thread = threading.Thread(target=open_callback)
    thread.start()
    try:
        with pytest.raises(ValueError, match="loginToken"):
            callback.wait_for_token()
    finally:
        thread.join(timeout=10)


@pytest.mark.asyncio
async def test_login_with_password_returns_login_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.login.return_value = LoginResponse("@alice:example.com", "TESTDEVICE", "test-token")

    class FakeAsyncClient:
        def __new__(cls, *args, **kwargs):
            assert args == ("https://matrix.example.com", "@alice:example.com")
            assert kwargs == {"ssl": False}
            return client

    monkeypatch.setattr("matty.auth.AsyncClient", FakeAsyncClient)

    result = await login_with_password(
        homeserver="https://matrix.example.com/",
        user="@alice:example.com",
        password="secret",
        ssl_verify=False,
    )

    assert result == LoginResult(
        homeserver="https://matrix.example.com",
        user_id="@alice:example.com",
        device_id="TESTDEVICE",
        access_token="test-token",
        ssl_verify=False,
    )
    client.login.assert_awaited_once_with(password="secret", device_name="matty")
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_with_password_reports_login_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AsyncMock()
    client.login.return_value = object()

    class FakeAsyncClient:
        def __new__(cls, *_args, **_kwargs):
            return client

    monkeypatch.setattr("matty.auth.AsyncClient", FakeAsyncClient)

    with pytest.raises(RuntimeError, match="password login failed"):
        await login_with_password(
            homeserver="https://matrix.example.com",
            user="@alice:example.com",
            password="secret",
        )
    client.close.assert_awaited_once()


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


@pytest.mark.asyncio
async def test_login_with_token_uses_user_id_from_login_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/_matrix/client/v3/login"
        return httpx.Response(
            200,
            json={
                "access_token": "test-access-token",
                "device_id": "TESTDEVICE",
                "user_id": "@alice:example.com",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        result = await login_with_token(
            homeserver="https://matrix.example.com",
            login_token="test-login-token",
            http_client=http_client,
        )

    assert result.user_id == "@alice:example.com"
    assert result.device_id == "TESTDEVICE"


@pytest.mark.asyncio
async def test_login_with_token_reports_redirected_matrix_api() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                302, headers={"location": "https://gateway.example.com"}
            )
        )
    ) as http_client:
        with pytest.raises(RuntimeError, match="Redirect location"):
            await login_with_token(
                homeserver="https://matrix.example.com",
                login_token="test-login-token",
                http_client=http_client,
            )


@pytest.mark.asyncio
async def test_login_with_token_requires_access_token() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={}))
    ) as http_client:
        with pytest.raises(RuntimeError, match="access_token"):
            await login_with_token(
                homeserver="https://matrix.example.com",
                login_token="test-login-token",
                http_client=http_client,
            )


@pytest.mark.asyncio
async def test_login_with_token_requires_json_object() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=[]))
    ) as http_client:
        with pytest.raises(RuntimeError, match="JSON object"):
            await login_with_token(
                homeserver="https://matrix.example.com",
                login_token="test-login-token",
                http_client=http_client,
            )
