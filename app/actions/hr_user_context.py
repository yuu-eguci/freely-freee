"""freee 人事労務の current user 情報を解決する共通ヘルパーです。"""

from typing import Any

from app.clients.hr_api_client import HrApiClient
from app.errors import ActionExecutionError


def resolve_current_company_and_employee_id(hr_client: HrApiClient) -> "tuple[int, int]":
    """GET /users/me から company_id と employee_id を取得します。"""

    company = _resolve_first_company(hr_client)
    company_id = company.get("id")
    employee_id = company.get("employee_id")
    if company_id is None:
        raise ActionExecutionError("GET /users/me: company_id が取得できませんでした。")
    if employee_id is None:
        raise ActionExecutionError(
            "GET /users/me: employee_id が取得できませんでした。freee の権限設定を確認してください。"
        )
    return int(company_id), int(employee_id)


def _resolve_first_company(hr_client: HrApiClient) -> "dict[str, Any]":
    resp = hr_client.get_current_user()
    body = resp.body
    if not isinstance(body, dict):
        raise ActionExecutionError("GET /users/me: 予期しないレスポンス形式です。")
    companies = body.get("companies", [])
    if not companies:
        raise ActionExecutionError("GET /users/me: companies が空です。freee の権限設定を確認してください。")
    first = companies[0]
    if not isinstance(first, dict):
        raise ActionExecutionError("GET /users/me: companies[0] の形式が不正です。")
    return first
