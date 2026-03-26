"""OAuth flows for freee token acquisition and refresh."""

import secrets
from typing import Any
from urllib.parse import urlencode

import requests
from requests import Response

from app.config import AppConfig
from app.errors import OAuthTokenError

AUTHORIZE_URL = "https://accounts.secure.freee.co.jp/public_api/authorize"
TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"
REQUEST_TIMEOUT_SECONDS = 30


def build_authorize_url(config: AppConfig) -> tuple[str, str]:
    """Build the authorize URL and generated state."""

    state = secrets.token_urlsafe(32)
    params = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "state": state,
            "prompt": "select_company",
        }
    )
    return f"{AUTHORIZE_URL}?{params}", state


def parse_token_response(response: Response) -> dict[str, Any]:
    """Validate a token endpoint response."""

    try:
        payload = response.json()
    except ValueError as exc:
        raise OAuthTokenError(
            f"Token endpoint returned non-JSON response (status={response.status_code})"
        ) from exc

    if not isinstance(payload, dict):
        raise OAuthTokenError("Token endpoint returned a non-object JSON response")

    if response.status_code >= 400:
        error = payload.get("error")
        description = payload.get("error_description")
        message = payload.get("message")
        details = [part for part in [error, description, message] if isinstance(part, str) and part]
        detail_text = ", ".join(details) if details else "No detailed error message"
        raise OAuthTokenError(
            f"Token endpoint error (status={response.status_code}): {detail_text}"
        )

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthTokenError("Token endpoint response missing access_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise OAuthTokenError("Token endpoint response missing refresh_token")

    return payload


def post_token(payload: dict[str, str]) -> dict[str, Any]:
    """Send a token endpoint request and validate the response."""

    try:
        response = requests.post(TOKEN_URL, data=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.Timeout as exc:
        raise OAuthTokenError("Token endpoint request timed out") from exc
    except requests.ConnectionError as exc:
        raise OAuthTokenError("Could not connect to token endpoint") from exc
    except requests.RequestException as exc:
        raise OAuthTokenError(f"Token endpoint request failed: {exc}") from exc

    return parse_token_response(response)


def exchange_auth_code(config: AppConfig, auth_code: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens."""

    if not auth_code.strip():
        raise OAuthTokenError("Received an empty authorization code")
    return post_token(
        {
            "grant_type": "authorization_code",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": auth_code.strip(),
            "redirect_uri": config.redirect_uri,
        }
    )


def refresh_access_token(config: AppConfig, refresh_token: str) -> dict[str, Any]:
    """Refresh an access token using a refresh token."""

    if not refresh_token.strip():
        raise OAuthTokenError("Refresh token is empty")
    return post_token(
        {
            "grant_type": "refresh_token",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "refresh_token": refresh_token.strip(),
        }
    )


def require_access_token(token_payload: dict[str, Any]) -> str:
    """Extract the access token from a token response payload."""

    access_token = token_payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise OAuthTokenError("Token endpoint response missing access_token")
    return access_token
