"""freee 人事労務の current user 情報を解決する共通ヘルパーです。"""

from dataclasses import dataclass
from typing import Any

from app.clients.hr_api_client import HrApiClient
from app.errors import ActionExecutionError


@dataclass(frozen=True)
class HrUserContext:
    """GET /users/me の解決結果です。"""

    company_id: int
    employee_id: int
    user_id: int


def resolve_current_user_context(
    hr_client: HrApiClient,
    *,
    target_company_id: int,
) -> HrUserContext:
    """GET /users/me から current user 情報を取得します。"""

    resp = hr_client.get_current_user()
    body = resp.body
    if not isinstance(body, dict):
        raise ActionExecutionError("GET /users/me: 予期しないレスポンス形式です。")

    user_id = _as_int(body.get("id"))
    if user_id is None:
        raise ActionExecutionError("GET /users/me: user_id が取得できませんでした。freee の権限設定を確認してください。")

    company = _resolve_target_company(body, target_company_id)
    company_id = _require_int(
        company.get("id"),
        "GET /users/me: company_id が取得できませんでした。",
    )
    employee_id = _require_int(
        company.get("employee_id"),
        "GET /users/me: employee_id が取得できませんでした。freee の権限設定を確認してください。",
    )
    return HrUserContext(company_id=company_id, employee_id=employee_id, user_id=user_id)


def _resolve_target_company(body: dict[str, Any], target_company_id: int) -> "dict[str, Any]":
    companies = body.get("companies", [])
    if not companies:
        raise ActionExecutionError("GET /users/me: companies が空です。freee の権限設定を確認してください。")
    for company in companies:
        if not isinstance(company, dict):
            continue
        company_id = _as_int(company.get("id"))
        if company_id == target_company_id:
            return company

    raise ActionExecutionError(
        f"GET /users/me: TARGET_COMPANY_ID={target_company_id} に一致する company が見つかりませんでした。"
    )


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _require_int(value: object, message: str) -> int:
    resolved = _as_int(value)
    if resolved is None:
        raise ActionExecutionError(message)
    return resolved
