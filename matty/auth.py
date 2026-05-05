"""Matrix authentication helpers for Matty."""

from __future__ import annotations

from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx
from nio import AsyncClient, LoginResponse

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True)
class SSOProvider:
    """Matrix SSO identity provider."""

    id: str
    name: str | None = None
    brand: str | None = None


@dataclass(frozen=True)
class LoginResult:
    """Successful Matrix login details."""

    homeserver: str
    user_id: str
    device_id: str | None
    access_token: str
    ssl_verify: bool = True


def build_sso_redirect_url(*, homeserver: str, redirect_url: str, idp_id: str | None = None) -> str:
    """Build a Matrix SSO redirect URL for a local callback."""
    base = homeserver.rstrip("/")
    provider = f"/{quote(idp_id, safe='')}" if idp_id else ""
    query = urlencode({"redirectUrl": redirect_url})
    return f"{base}/_matrix/client/v3/login/sso/redirect{provider}?{query}"


def parse_sso_providers(login_response: dict[str, Any]) -> list[SSOProvider]:
    """Parse advertised Matrix SSO providers from a login response."""
    providers: list[SSOProvider] = []
    for flow in login_response.get("flows", []):
        if not isinstance(flow, dict) or flow.get("type") != "m.login.sso":
            continue
        providers.extend(
            SSOProvider(
                id=provider["id"],
                name=provider.get("name") if isinstance(provider.get("name"), str) else None,
                brand=provider.get("brand") if isinstance(provider.get("brand"), str) else None,
            )
            for provider in flow.get("identity_providers", [])
            if isinstance(provider, dict) and isinstance(provider.get("id"), str)
        )
    return providers


def fetch_sso_providers(*, homeserver: str, ssl_verify: bool = True) -> list[SSOProvider]:
    """Fetch advertised Matrix SSO providers for a homeserver."""
    response = httpx.get(
        f"{homeserver.rstrip('/')}/_matrix/client/v3/login",
        timeout=10,
        verify=ssl_verify,
    )
    _raise_for_redirect(response)
    response.raise_for_status()
    return parse_sso_providers(_response_json_object(response, context="Matrix login response"))


def resolve_sso_provider_id(idp_id: str, providers: Iterable[SSOProvider]) -> str:
    """Resolve a Matrix SSO provider id, name, or brand to its advertised id."""
    provider_list = list(providers)
    for provider in provider_list:
        if idp_id == provider.id:
            return provider.id

    normalized = idp_id.casefold()
    matches = [
        provider
        for provider in provider_list
        if normalized
        in {alias.casefold() for alias in (provider.id, provider.name, provider.brand) if alias}
    ]
    if not matches:
        available = ", ".join(_provider_alias_label(provider) for provider in provider_list)
        msg = f"Matrix SSO provider {idp_id!r} is not advertised by this homeserver"
        if available:
            msg = f"{msg}. Available providers: {available}"
        raise ValueError(msg)
    if len(matches) > 1:
        available = ", ".join(_provider_alias_label(provider) for provider in matches)
        msg = f"Matrix SSO provider {idp_id!r} is ambiguous. Matching providers: {available}"
        raise ValueError(msg)
    return matches[0].id


def extract_login_token(query: str) -> str:
    """Extract the Matrix SSO login token from a callback query string."""
    values = parse_qs(query, keep_blank_values=False)
    token = values.get("loginToken", [None])[0]
    if not token:
        msg = "Matrix SSO callback did not include loginToken"
        raise ValueError(msg)
    return token


class SSOCallbackServer:
    """Single-request local HTTP callback server for Matrix SSO."""

    def __init__(self, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self.token: str | None = None
        self.error: Exception | None = None
        owner = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                try:
                    owner.token = extract_login_token(urlsplit(self.path).query)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"Matty login complete. You can close this tab.")
                except Exception as exc:
                    owner.error = exc
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Matty login failed. Return to the terminal.")

            def log_message(self, format: str, *_args: object) -> None:
                del format, _args

        self._server = HTTPServer((host, port), CallbackHandler)
        self.redirect_url = f"http://{host}:{self._server.server_port}/callback"

    def wait_for_token(self) -> str:
        """Wait for one callback request and return its login token."""
        try:
            self._server.handle_request()
        finally:
            self.close()
        if self.error is not None:
            raise self.error
        if self.token is None:
            msg = "Matrix SSO callback did not complete"
            raise RuntimeError(msg)
        return self.token

    def close(self) -> None:
        """Close the callback server socket."""
        self._server.server_close()


async def login_with_password(
    *,
    homeserver: str,
    user: str,
    password: str,
    device_name: str = "matty",
    ssl_verify: bool = True,
) -> LoginResult:
    """Login using Matrix password auth and return a stored-token result."""
    client = AsyncClient(homeserver.rstrip("/"), user, ssl=ssl_verify)
    try:
        response = await client.login(password=password, device_name=device_name)
    finally:
        await client.close()
    if isinstance(response, LoginResponse):
        return LoginResult(
            homeserver=homeserver.rstrip("/"),
            user_id=response.user_id,
            device_id=response.device_id,
            access_token=response.access_token,
            ssl_verify=ssl_verify,
        )
    msg = f"Matrix password login failed: {response}"
    raise RuntimeError(msg)


async def login_with_token(
    *,
    homeserver: str,
    login_token: str,
    device_name: str = "matty",
    ssl_verify: bool = True,
    http_client: httpx.AsyncClient | None = None,
) -> LoginResult:
    """Exchange a Matrix SSO loginToken for an access token."""
    normalized_homeserver = homeserver.rstrip("/")
    if http_client is not None:
        return await _login_with_token_http(
            http_client=http_client,
            homeserver=normalized_homeserver,
            login_token=login_token,
            device_name=device_name,
            ssl_verify=ssl_verify,
        )

    async with httpx.AsyncClient(timeout=10, verify=ssl_verify) as client:
        return await _login_with_token_http(
            http_client=client,
            homeserver=normalized_homeserver,
            login_token=login_token,
            device_name=device_name,
            ssl_verify=ssl_verify,
        )


async def _login_with_token_http(
    *,
    http_client: httpx.AsyncClient,
    homeserver: str,
    login_token: str,
    device_name: str,
    ssl_verify: bool,
) -> LoginResult:
    response = await http_client.post(
        f"{homeserver}/_matrix/client/v3/login",
        json={
            "type": "m.login.token",
            "token": login_token,
            "initial_device_display_name": device_name,
        },
    )
    _raise_for_redirect(response)
    response.raise_for_status()
    data = _response_json_object(response, context="Matrix token login response")

    access_token = _required_string(data, "access_token", context="Matrix token login response")
    device_id = data.get("device_id")
    user_id = data.get("user_id")
    if not isinstance(user_id, str):
        user_id = await _fetch_user_id(
            http_client=http_client,
            homeserver=homeserver,
            access_token=access_token,
        )

    return LoginResult(
        homeserver=homeserver,
        user_id=user_id,
        device_id=device_id if isinstance(device_id, str) else None,
        access_token=access_token,
        ssl_verify=ssl_verify,
    )


async def _fetch_user_id(
    *,
    http_client: httpx.AsyncClient,
    homeserver: str,
    access_token: str,
) -> str:
    response = await http_client.get(
        f"{homeserver}/_matrix/client/v3/account/whoami",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_redirect(response)
    response.raise_for_status()
    data = _response_json_object(response, context="Matrix whoami response")
    return _required_string(data, "user_id", context="Matrix whoami response")


def _raise_for_redirect(response: httpx.Response) -> None:
    if not response.is_redirect:
        return
    location = response.headers.get("location")
    msg = "Matrix API request was redirected before authentication completed."
    if location:
        msg = f"{msg} Redirect location: {location}"
    raise RuntimeError(msg)


def _response_json_object(response: httpx.Response, *, context: str) -> dict[str, Any]:
    data = response.json()
    if isinstance(data, dict):
        return data
    msg = f"{context} was not a JSON object"
    raise RuntimeError(msg)


def _required_string(data: dict[str, Any], key: str, *, context: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    msg = f"{context} did not include required string field {key!r}"
    raise RuntimeError(msg)


def _provider_alias_label(provider: SSOProvider) -> str:
    aliases = list(
        dict.fromkeys(
            alias for alias in (provider.name, provider.brand) if alias and alias != provider.id
        )
    )
    if not aliases:
        return provider.id
    return f"{provider.id} ({'/'.join(aliases)})"
