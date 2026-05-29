"""指定の月の勤怠を一括でリセットするアクションです。"""

import calendar
import re
import time
from datetime import datetime
from typing import Literal

from app.actions.bulk_attendance_common import BULK_ATTENDANCE_API_WAIT_SECONDS
from app.actions.hr_user_context import resolve_current_company_and_employee_id
from app.clients.hr_api_client import HrApiClient
from app.context import AppContext
from app.errors import ApiResponseError
from app.exit_codes import EXIT_CODE_APP_ERROR, EXIT_CODE_MENU_ERROR, EXIT_CODE_OK

_PROCESS_RESULT = Literal["success", "error"]


def handler(context: AppContext) -> int:
    """指定の月の勤怠を一括でリセットします。"""

    result = _parse_target_month()
    if result is None:
        return EXIT_CODE_MENU_ERROR
    year, month = result

    hr_client = HrApiClient(context.api_client)
    company_id, employee_id = resolve_current_company_and_employee_id(hr_client)

    dates = _generate_dates(year, month)
    print(f"\n対象月: {year:04d}-{month:02d} ({len(dates)}日間)\n")

    success_count = 0
    for date in dates:
        proc_result = _process_date(hr_client, employee_id, company_id, date)
        if proc_result == "success":
            success_count += 1
        elif proc_result == "error":
            _print_summary(success_count, error_date=date)
            return EXIT_CODE_APP_ERROR
        time.sleep(BULK_ATTENDANCE_API_WAIT_SECONDS)

    _print_summary(success_count)
    return EXIT_CODE_OK


def _parse_target_month() -> "tuple[int, int] | None":
    """input() で yyyy-mm を受け取り、(year, month) を返します。不正入力時は None を返します。"""

    raw = input("対象月を入力してね (yyyy-mm): ").strip()
    if not raw:
        print("[エラー] 入力が空です。")
        return None
    if not re.fullmatch(r"\d{4}-\d{2}", raw):
        print(f"[エラー] フォーマットが不正です: {raw!r}  (例: 2026-03)")
        return None
    try:
        dt = datetime.strptime(raw, "%Y-%m")
    except ValueError:
        print(f"[エラー] 存在しない年月です: {raw!r}")
        return None
    return dt.year, dt.month


def _generate_dates(year: int, month: int) -> "list[str]":
    """対象月の 1 日から末日までの日付リストを yyyy-mm-dd 形式で返します。"""

    _, last_day = calendar.monthrange(year, month)
    return [f"{year:04d}-{month:02d}-{day:02d}" for day in range(1, last_day + 1)]


def _process_date(
    hr_client: HrApiClient,
    employee_id: int,
    company_id: int,
    date: str,
) -> _PROCESS_RESULT:
    """1 日分の勤怠リセット + タグリセットを行い、結果を返します。"""

    work_payload = _build_work_record_reset_payload(company_id)
    try:
        hr_client.put_work_record(employee_id, date, work_payload)
    except ApiResponseError as exc:
        _print_api_error(date, "勤怠リセット失敗", exc)
        return "error"

    tag_payload = _build_attendance_tag_reset_payload(company_id)
    try:
        hr_client.put_attendance_tags(employee_id, date, tag_payload)
    except ApiResponseError as exc:
        print(f"[OK]   {date} 勤怠リセット済み")
        _print_api_error(date, "勤怠タグリセット失敗", exc)
        return "error"

    print(f"[OK]   {date} 勤怠/タグを空へ更新済み")
    return "success"


def _build_work_record_reset_payload(company_id: int) -> dict:
    """勤怠レコードを空にする payload を構築します。"""

    return {
        "company_id": company_id,
        "break_records": [],
        "work_record_segments": [],
    }


def _build_attendance_tag_reset_payload(company_id: int) -> dict:
    """勤怠タグを空にする payload を構築します。"""

    return {
        "company_id": company_id,
        "employee_attendance_tags": [],
    }


def _print_api_error(date: str, prefix: "str | None", exc: ApiResponseError) -> None:
    """API エラーのログを出力します。"""

    messages: list[str] = []
    body = exc.response_body
    if isinstance(body, dict):
        for err in body.get("errors", []):
            messages.extend(err.get("messages", []))

    detail = " / ".join(messages) if messages else str(exc)

    if prefix:
        print(f"[ERR]  {date} {prefix}: {detail}")
    else:
        print(f"[ERR]  {date} {detail}")


def _print_summary(success_count: int, error_date: "str | None" = None) -> None:
    """処理結果のサマリーを出力します。"""

    error_count = 1 if error_date else 0
    if error_date:
        print(f"\n中断: {success_count}日成功 / {error_count}日エラー ({error_date} で中断)")
    else:
        print(f"\n完了: {success_count}日成功 / {error_count}日エラー")
