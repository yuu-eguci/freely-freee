"""指定月の平日に一括で勤怠を登録するアクションです。"""

import calendar
import re
import time
from datetime import datetime
from typing import Literal

from app.clients.hr_api_client import HrApiClient
from app.context import AppContext
from app.errors import ActionExecutionError, ApiResponseError
from app.exit_codes import EXIT_CODE_APP_ERROR, EXIT_CODE_MENU_ERROR, EXIT_CODE_OK

_ProcessResult = Literal["success", "skipped", "error"]


def handler(context: AppContext) -> int:
    """指定月の平日に一括で勤怠を登録します。"""

    # 1. yyyy-mm を input() で受け取ってパース
    result = _parse_target_month()
    if result is None:
        return EXIT_CODE_MENU_ERROR
    year, month = result

    # 2. API クライアント準備
    hr_client = HrApiClient(context.api_client)

    # 3. company_id, employee_id 取得
    company_id, employee_id = _resolve_user_ids(hr_client)

    # 4. 出社タグ id 取得
    attendance_tag_id = _resolve_attendance_tag_id(hr_client, employee_id, company_id)

    # 5. 日付リスト生成
    dates = _generate_dates(year, month)
    print(f"\n対象月: {year:04d}-{month:02d} ({len(dates)}日間)\n")

    # 6. 日付ループ
    success_count = 0
    skip_count = 0
    for date in dates:
        proc_result = _process_date(hr_client, employee_id, company_id, attendance_tag_id, date)
        if proc_result == "success":
            success_count += 1
        elif proc_result == "skipped":
            skip_count += 1
        elif proc_result == "error":
            _print_summary(success_count, skip_count, error_date=date)
            return EXIT_CODE_APP_ERROR
        time.sleep(0.5)  # 外部サービスへの配慮

    # 7. 完了
    _print_summary(success_count, skip_count)
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


def _resolve_user_ids(hr_client: HrApiClient) -> "tuple[int, int]":
    """GET /users/me から company_id と employee_id を取得します。"""

    resp = hr_client.get_current_user()
    body = resp.body
    if not isinstance(body, dict):
        raise ActionExecutionError("GET /users/me: 予期しないレスポンス形式です。")
    companies = body.get("companies", [])
    if not companies:
        raise ActionExecutionError("GET /users/me: companies が空です。freee の権限設定を確認してください。")
    first = companies[0]
    company_id = first.get("id")
    employee_id = first.get("employee_id")
    if company_id is None:
        raise ActionExecutionError("GET /users/me: company_id が取得できませんでした。")
    if employee_id is None:
        raise ActionExecutionError(
            "GET /users/me: employee_id が取得できませんでした。freee の権限設定を確認してください。"
        )
    return int(company_id), int(employee_id)


def _resolve_attendance_tag_id(
    hr_client: HrApiClient, employee_id: int, company_id: int
) -> int:
    """勤怠タグ一覧から「出社」を含むタグの id を返します。"""

    resp = hr_client.get_attendance_tags(employee_id, company_id)
    body = resp.body
    if not isinstance(body, dict):
        raise ActionExecutionError("GET /attendance_tags: 予期しないレスポンス形式です。")
    tags = body.get("employee_attendance_tags", [])
    matched = [t for t in tags if "出社" in t.get("name", "")]
    if not matched:
        raise ActionExecutionError(
            "勤怠タグに「出社」を含む名前のタグが見つかりませんでした。freee の勤怠タグ設定を確認してください。"
        )
    if len(matched) > 1:
        names = [t.get("name") for t in matched]
        print(f"[INFO] 「出社」タグが複数見つかりました: {names}  -> 先頭の {names[0]!r} を使います。")
    return int(matched[0]["id"])


def _generate_dates(year: int, month: int) -> "list[str]":
    """対象月の 1 日から末日までの日付リストを yyyy-mm-dd 形式で返します。"""

    _, last_day = calendar.monthrange(year, month)
    return [f"{year:04d}-{month:02d}-{day:02d}" for day in range(1, last_day + 1)]


def _process_date(
    hr_client: HrApiClient,
    employee_id: int,
    company_id: int,
    attendance_tag_id: int,
    date: str,
) -> _ProcessResult:
    """1 日分の勤怠登録 + タグ付与を行い、 'success' / 'skipped' / 'error' を返します。"""

    # 6a. day_pattern を確認
    try:
        resp = hr_client.get_work_record(employee_id, date, company_id)
    except ApiResponseError as exc:
        _print_api_error(date, "勤怠レコード取得失敗", exc)
        return "error"

    body = resp.body
    day_pattern = body.get("day_pattern") if isinstance(body, dict) else None
    use_default_work_pattern = (
        body.get("use_default_work_pattern") if isinstance(body, dict) else None
    )

    # 6b. day_pattern が normal_day でなければスキップ
    if day_pattern != "normal_day":
        print(
            f"[SKIP] {date} reason=day_pattern_not_normal_day "
            f"detail=day_pattern={_to_log_value(day_pattern)}"
        )
        return "skipped"

    # 6c. use_default_work_pattern が true でなければスキップ
    if use_default_work_pattern is not True:
        print(
            f"[SKIP] {date} reason=use_default_work_pattern_false "
            f"detail=use_default_work_pattern={_to_log_value(use_default_work_pattern)}"
        )
        return "skipped"

    # 6d. 勤怠レコード更新
    work_payload = _build_work_record_payload(company_id, date)
    try:
        hr_client.put_work_record(employee_id, date, work_payload)
    except ApiResponseError as exc:
        _print_api_error(date, None, exc)
        return "error"

    # 6f. 勤怠タグ更新
    tag_payload = _build_attendance_tag_payload(company_id, attendance_tag_id)
    try:
        hr_client.put_attendance_tags(employee_id, date, tag_payload)
    except ApiResponseError as exc:
        # 勤怠登録は成功したがタグ付与で失敗した場合
        print(f"[OK]   {date} 09:00-19:00 勤怠登録済み")
        _print_api_error(date, "タグ付与失敗", exc)
        return "error"

    # 6h. 成功ログ
    print(f"[OK]   {date} 09:00-19:00 出社タグ付与済み")
    return "success"


def _to_log_value(value: object) -> str:
    """ログ向けに値を文字列へ整形します。"""

    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


def _build_work_record_payload(company_id: int, date: str) -> dict:
    """勤怠レコード更新用の payload を構築します。"""

    return {
        "company_id": company_id,
        "break_records": [
            {
                "clock_in_at": f"{date} 11:30:00",
                "clock_out_at": f"{date} 12:30:00",
            }
        ],
        "work_record_segments": [
            {
                "clock_in_at": f"{date} 09:00:00",
                "clock_out_at": f"{date} 19:00:00",
            }
        ],
    }


def _build_attendance_tag_payload(company_id: int, attendance_tag_id: int) -> dict:
    """勤怠タグ更新用の payload を構築します。"""

    return {
        "company_id": company_id,
        "employee_attendance_tags": [
            {
                "attendance_tag_id": attendance_tag_id,
                "amount": 1,
            }
        ],
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


def _print_summary(
    success_count: int,
    skip_count: int,
    error_date: "str | None" = None,
) -> None:
    """処理結果のサマリーを出力します。"""

    error_count = 1 if error_date else 0
    if error_date:
        print(
            f"\n中断: {success_count}日登録 / {skip_count}日スキップ / {error_count}日エラー"
            f" ({error_date} で中断)"
        )
    else:
        print(f"\n完了: {success_count}日登録 / {skip_count}日スキップ / {error_count}日エラー")
