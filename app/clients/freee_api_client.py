"""Minimal freee API client scaffold for future actions."""

from dataclasses import dataclass
from typing import Any

import requests

from app.errors import ApiAuthenticationError, ApiConnectionError, ApiResponseError

DEFAULT_TIMEOUT_SECONDS = 30
BASE_URL = "https://api.freee.co.jp"


@dataclass(frozen=True)
class ApiResponse:
    """Normalized API response wrapper."""

    status_code: int
    headers: dict[str, str]
    body: "dict[str, Any] | list[Any] | None"


class FreeeApiClient:
    """Thin HTTP client shared by future freee API actions."""

    def __init__(self, access_token: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._access_token = access_token
        self._timeout_seconds = timeout_seconds

    def get(self, path: str, *, params: "dict[str, Any] | None" = None) -> ApiResponse:
        """Perform a GET request."""

        return self._request("GET", path, params=params)

    def post(self, path: str, *, json_body: "dict[str, Any] | None" = None) -> ApiResponse:
        """Perform a POST request."""

        return self._request("POST", path, json=json_body)

    def _request(self, method: str, path: str, **kwargs: Any) -> ApiResponse:
        url = f"{BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=self._timeout_seconds,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise ApiConnectionError(f"Request timed out: {method} {path}") from exc
        except requests.ConnectionError as exc:
            raise ApiConnectionError(f"Could not connect to API: {method} {path}") from exc
        except requests.RequestException as exc:
            raise ApiConnectionError(f"API request failed: {method} {path}: {exc}") from exc

        if response.status_code in (401, 403):
            raise ApiAuthenticationError(
                f"API authentication failed (status={response.status_code}): {method} {path}"
            )
        if response.status_code >= 400:
            raise ApiResponseError(
                f"API request failed (status={response.status_code}): {method} {path}"
            )

        body = _parse_response_body(response)
        return ApiResponse(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
        )


def _parse_response_body(response: requests.Response) -> "dict[str, Any] | list[Any] | None":
    if response.status_code == 204 or not response.content:
        return None
    try:
        body = response.json()
    except ValueError as exc:
        raise ApiResponseError(
            f"API returned non-JSON response (status={response.status_code})"
        ) from exc
    if isinstance(body, (dict, list)):
        return body
    raise ApiResponseError("API returned unsupported JSON body type")
