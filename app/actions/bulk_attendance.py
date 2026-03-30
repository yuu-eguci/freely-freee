"""指定の月の平日に一括で勤怠を登録するアクションです。"""

import calendar
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from app.actions.bulk_attendance_common import (
    BULK_ATTENDANCE_ALLOWED_PAID_HOLIDAY_STATUSES,
    BULK_ATTENDANCE_API_WAIT_SECONDS,
    BULK_ATTENDANCE_BREAK_END_TIME,
    BULK_ATTENDANCE_BREAK_START_TIME,
    BULK_ATTENDANCE_PAID_HOLIDAYS_PAGE_LIMIT,
    BULK_ATTENDANCE_WORK_END_MINUTES,
    BULK_ATTENDANCE_WORK_START_MINUTES,
)
from app.clients.hr_api_client import HrApiClient
from app.context import AppContext
from app.errors import ActionExecutionError, ApiResponseError
from app.exit_codes import EXIT_CODE_APP_ERROR, EXIT_CODE_MENU_ERROR, EXIT_CODE_OK

_PROCESS_RESULT = Literal["success", "skipped", "error"]
_PAID_HOLIDAY_KIND = Literal["none", "full", "half", "half_fallback"]
_TARGET_IDS_RESOLVER = Callable[[HrApiClient], "tuple[int, int] | None"]


@dataclass(frozen=True)
class _PaidHolidayDecision:
    kind: _PAID_HOLIDAY_KIND
    request_id: "int | None" = None
    half_start_at: "str | None" = None
    half_end_at: "str | None" = None
    work_start_minutes: "int | None" = None
    work_end_minutes: "int | None" = None
    paid_minutes: "int | None" = None
    fallback_reason: "str | None" = None
    fallback_detail: "str | None" = None


def handler(context: AppContext) -> int:
    """指定の月の平日に一括で勤怠を登録します。"""

    return _run_bulk_attendance(context, target_ids_resolver=_resolve_user_ids)


def handler_by_employee_id(context: AppContext) -> int:
    """指定の月の平日に従業員ID指定で一括勤怠登録します。"""

    return _run_bulk_attendance(context, target_ids_resolver=_resolve_ids_by_input_employee_id)


def _run_bulk_attendance(context: AppContext, *, target_ids_resolver: _TARGET_IDS_RESOLVER) -> int:
    result = _parse_target_month()
    if result is None:
        return EXIT_CODE_MENU_ERROR
    year, month = result

    work_hours = _parse_work_hours()
    if work_hours is None:
        return EXIT_CODE_MENU_ERROR
    work_start_minutes, work_end_minutes = work_hours

    hr_client = HrApiClient(context.api_client)
    target_ids = target_ids_resolver(hr_client)
    if target_ids is None:
        return EXIT_CODE_MENU_ERROR
    company_id, employee_id = target_ids

    return _execute_bulk_attendance(
        hr_client=hr_client,
        company_id=company_id,
        employee_id=employee_id,
        year=year,
        month=month,
        work_start_minutes=work_start_minutes,
        work_end_minutes=work_end_minutes,
    )


def _execute_bulk_attendance(
    *,
    hr_client: HrApiClient,
    company_id: int,
    employee_id: int,
    year: int,
    month: int,
    work_start_minutes: int,
    work_end_minutes: int,
) -> int:
    attendance_tag_id = _resolve_attendance_tag_id(hr_client, employee_id, company_id)

    paid_holidays_by_date = _load_paid_holidays_by_date(hr_client, company_id, year, month)

    dates = _generate_dates(year, month)
    print(f"\n対象月: {year:04d}-{month:02d} ({len(dates)}日間)\n")

    success_count = 0
    skip_count = 0
    for date in dates:
        proc_result = _process_date(
            hr_client,
            employee_id,
            company_id,
            attendance_tag_id,
            date,
            paid_holidays_by_date.get(date, []),
            work_start_minutes,
            work_end_minutes,
        )
        if proc_result == "success":
            success_count += 1
        elif proc_result == "skipped":
            skip_count += 1
        elif proc_result == "error":
            _print_summary(success_count, skip_count, error_date=date)
            return EXIT_CODE_APP_ERROR
        time.sleep(BULK_ATTENDANCE_API_WAIT_SECONDS)

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


def _parse_work_hours() -> "tuple[int, int] | None":
    default_start_hour = BULK_ATTENDANCE_WORK_START_MINUTES // 60
    default_end_hour = BULK_ATTENDANCE_WORK_END_MINUTES // 60

    start_raw = input(
        f"出勤何時にする? ( 0-23 の整数。Enter で {default_start_hour} ): "
    ).strip()
    end_raw = input(
        f"退勤何時にする? ( 0-23 の整数。Enter で {default_end_hour} ): "
    ).strip()

    start_hour = _parse_hour_input(start_raw, "出勤", default_start_hour)
    if start_hour is None:
        return None
    end_hour = _parse_hour_input(end_raw, "退勤", default_end_hour)
    if end_hour is None:
        return None

    if start_hour >= end_hour:
        print(
            "[エラー] 出勤時刻は退勤時刻より前にしてね "
            f"( start={start_hour:02d}, end={end_hour:02d} )"
        )
        return None
    return start_hour * 60, end_hour * 60


def _parse_hour_input(raw: str, label: str, default_hour: int) -> "int | None":
    if not raw:
        return default_hour
    if not re.fullmatch(r"\d{1,2}", raw):
        print(f"[エラー] {label}時刻は 0-23 の整数で入力してね: {raw!r}")
        return None
    hour = int(raw)
    if not (0 <= hour <= 23):
        print(f"[エラー] {label}時刻は 0-23 の整数で入力してね: {raw!r}")
        return None
    return hour


def _resolve_user_ids(hr_client: HrApiClient) -> "tuple[int, int]":
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


def _resolve_ids_by_input_employee_id(hr_client: HrApiClient) -> "tuple[int, int] | None":
    company_id = _resolve_company_id(hr_client)
    employee_id = _parse_employee_id()
    if employee_id is None:
        return None
    return company_id, employee_id


def _resolve_company_id(hr_client: HrApiClient) -> int:
    company = _resolve_first_company(hr_client)
    company_id = company.get("id")
    if company_id is None:
        raise ActionExecutionError("GET /users/me: company_id が取得できませんでした。")
    return int(company_id)


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


def _parse_employee_id() -> "int | None":
    raw = input(
        "対象の従業員IDを入力してね "
        "(数字のみ。よくわからんかったら Ctrl + C でいったん終わって、やり直してね): "
    ).strip()
    if not raw:
        print("[エラー] 従業員IDは空で入力できないよ")
        return None
    if not re.fullmatch(r"\d+", raw):
        print(f"[エラー] 従業員IDは数字だけで入力してね: {raw!r}")
        return None
    employee_id = int(raw)
    if employee_id < 1:
        print(f"[エラー] 従業員IDは 1 以上の整数で入力してね: {raw!r}")
        return None
    return employee_id


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


def _load_paid_holidays_by_date(
    hr_client: HrApiClient,
    company_id: int,
    year: int,
    month: int,
) -> "dict[str, list[dict[str, Any]]]":
    start_date, end_date = _month_date_range(year, month)
    paid_holidays = _fetch_paid_holidays_for_month(
        hr_client,
        company_id=company_id,
        start_target_date=start_date,
        end_target_date=end_date,
    )
    by_date: dict[str, list[dict[str, Any]]] = {}
    for paid_holiday in paid_holidays:
        target_date = paid_holiday.get("target_date")
        if not isinstance(target_date, str):
            continue
        by_date.setdefault(target_date, []).append(paid_holiday)
    return by_date


def _month_date_range(year: int, month: int) -> "tuple[str, str]":
    _, last_day = calendar.monthrange(year, month)
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"
    return start_date, end_date


def _fetch_paid_holidays_for_month(
    hr_client: HrApiClient,
    *,
    company_id: int,
    start_target_date: str,
    end_target_date: str,
) -> "list[dict[str, Any]]":
    paid_holidays: list[dict[str, Any]] = []
    offset = 0
    total_count: int | None = None

    while True:
        resp = hr_client.get_paid_holidays(
            company_id,
            start_target_date=start_target_date,
            end_target_date=end_target_date,
            limit=BULK_ATTENDANCE_PAID_HOLIDAYS_PAGE_LIMIT,
            offset=offset,
        )
        body = resp.body
        if not isinstance(body, dict):
            raise ActionExecutionError("GET /approval_requests/paid_holidays: 予期しないレスポンス形式です。")

        page_items = body.get("paid_holidays")
        raw_total_count = body.get("total_count")

        if not isinstance(page_items, list):
            raise ActionExecutionError("GET /approval_requests/paid_holidays: paid_holidays が配列ではありません。")
        if not isinstance(raw_total_count, int):
            raise ActionExecutionError("GET /approval_requests/paid_holidays: total_count が数値ではありません。")

        total_count = raw_total_count if total_count is None else total_count
        paid_holidays.extend(item for item in page_items if isinstance(item, dict))

        if len(paid_holidays) >= total_count:
            break

        if not page_items:
            raise ActionExecutionError(
                "GET /approval_requests/paid_holidays: total_count 未達のまま 0 件応答が返りました。処理を中断します。"
            )

        offset += BULK_ATTENDANCE_PAID_HOLIDAYS_PAGE_LIMIT

    return paid_holidays


def _process_date(
    hr_client: HrApiClient,
    employee_id: int,
    company_id: int,
    attendance_tag_id: int,
    date: str,
    paid_holidays_for_date: "list[dict[str, Any]]",
    work_start_minutes: int,
    work_end_minutes: int,
) -> _PROCESS_RESULT:
    """1 日分の勤怠登録 + タグ付与を行い、 'success' / 'skipped' / 'error' を返します。"""

    try:
        resp = hr_client.get_work_record(employee_id, date, company_id)
    except ApiResponseError as exc:
        _print_api_error(date, "get_work_record", exc)
        return "error"

    body = resp.body
    day_pattern = body.get("day_pattern") if isinstance(body, dict) else None

    if day_pattern != "normal_day":
        print(
            f"[SKIP] {date} reason=day_pattern_not_normal_day "
            f"detail=day_pattern={_to_log_value(day_pattern)}"
        )
        return "skipped"

    decision = _decide_paid_holiday(
        date,
        paid_holidays_for_date,
        work_start_minutes,
        work_end_minutes,
    )
    if decision.kind == "half_fallback":
        _print_half_fallback(date, decision)

    work_payload = _build_work_record_payload(
        company_id,
        date,
        decision,
        work_start_minutes,
        work_end_minutes,
    )
    try:
        hr_client.put_work_record(employee_id, date, work_payload)
    except ApiResponseError as exc:
        _print_api_error(date, "put_work_record", exc)
        return "error"

    work_label = _work_result_label(decision, work_start_minutes, work_end_minutes)

    if decision.kind == "full":
        print(f"[OK]   {date} {work_label} 勤怠登録済み (出社タグなし)")
        return "success"

    tag_payload = _build_attendance_tag_payload(company_id, attendance_tag_id)
    try:
        hr_client.put_attendance_tags(employee_id, date, tag_payload)
    except ApiResponseError as exc:
        print(f"[OK]   {date} {work_label} 勤怠登録済み")
        _print_api_error(date, "put_attendance_tags", exc)
        return "error"

    print(f"[OK]   {date} {work_label} 出社タグ付与済み")
    return "success"


def _decide_paid_holiday(
    date: str,
    paid_holidays_for_date: "list[dict[str, Any]]",
    work_start_minutes: int,
    work_end_minutes: int,
) -> _PaidHolidayDecision:
    supported_requests = _filter_supported_paid_holidays(date, paid_holidays_for_date)
    if not supported_requests:
        return _PaidHolidayDecision(kind="none")

    full_requests = [item for item in supported_requests if item.get("holiday_type") == "full"]
    if full_requests:
        selected_full = _select_full_paid_holiday(date, full_requests)
        return _PaidHolidayDecision(kind="full", request_id=_as_int(selected_full.get("id")))

    half_requests = [item for item in supported_requests if item.get("holiday_type") == "half"]
    if len(half_requests) > 1:
        ids = [str(_as_int(item.get("id"))) for item in half_requests]
        return _PaidHolidayDecision(
            kind="half_fallback",
            fallback_reason="multiple_half_requests",
            fallback_detail=f"request_ids={','.join(ids)}",
        )
    if not half_requests:
        return _PaidHolidayDecision(kind="none")

    return _build_half_decision(half_requests[0], work_start_minutes, work_end_minutes)


def _filter_supported_paid_holidays(
    date: str, paid_holidays_for_date: "list[dict[str, Any]]"
) -> "list[dict[str, Any]]":
    supported: list[dict[str, Any]] = []

    for item in paid_holidays_for_date:
        request_id = _as_int(item.get("id"))
        status = item.get("status")
        revoke_status = item.get("revoke_status")
        holiday_type = item.get("holiday_type")

        if revoke_status is not None:
            print(
                f"[INFO] {date} paid_holiday除外 id={_to_log_value(request_id)} "
                f"reason=revoke_status_not_null detail=revoke_status={_to_log_value(revoke_status)}"
            )
            continue
        if status not in BULK_ATTENDANCE_ALLOWED_PAID_HOLIDAY_STATUSES:
            print(
                f"[INFO] {date} paid_holiday除外 id={_to_log_value(request_id)} "
                f"reason=status_not_supported detail=status={_to_log_value(status)}"
            )
            continue
        if holiday_type not in ("full", "half"):
            print(
                f"[INFO] {date} paid_holiday除外 id={_to_log_value(request_id)} "
                f"reason=holiday_type_not_supported detail=holiday_type={_to_log_value(holiday_type)}"
            )
            continue
        supported.append(item)

    return supported


def _select_full_paid_holiday(date: str, full_requests: "list[dict[str, Any]]") -> "dict[str, Any]":
    if len(full_requests) == 1:
        return full_requests[0]

    selected = sorted(full_requests, key=_full_priority, reverse=True)[0]
    all_ids = [_to_log_value(_as_int(item.get("id"))) for item in full_requests]
    selected_id = _to_log_value(_as_int(selected.get("id")))
    print(
        f"[WARN] {date} reason=multiple_full_requests "
        f"detail=request_ids={','.join(all_ids)},selected={selected_id}"
    )
    return selected


def _full_priority(item: "dict[str, Any]") -> "tuple[int, int]":
    issue_date = item.get("issue_date")
    issue_date_value = 0
    if isinstance(issue_date, str):
        try:
            issue_date_value = int(datetime.strptime(issue_date, "%Y-%m-%d").strftime("%Y%m%d"))
        except ValueError:
            issue_date_value = 0
    item_id = _as_int(item.get("id")) or -1
    return issue_date_value, item_id


def _build_half_decision(
    item: "dict[str, Any]",
    work_start_minutes: int,
    work_end_minutes: int,
) -> _PaidHolidayDecision:
    request_id = _as_int(item.get("id"))
    start_at = item.get("start_at")
    end_at = item.get("end_at")

    if not isinstance(start_at, str) or not isinstance(end_at, str):
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at if isinstance(start_at, str) else None,
            end_at=end_at if isinstance(end_at, str) else None,
            reason="missing_half_time",
        )

    start_minutes = _parse_hhmm_to_minutes(start_at)
    end_minutes = _parse_hhmm_to_minutes(end_at)
    if start_minutes is None or end_minutes is None:
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at,
            end_at=end_at,
            reason="invalid_half_time",
        )
    if start_minutes >= end_minutes:
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at,
            end_at=end_at,
            reason="invalid_half_range",
        )
    if start_minutes < work_start_minutes or end_minutes > work_end_minutes:
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at,
            end_at=end_at,
            reason="outside_work_range",
        )

    is_center_split = (
        start_minutes > work_start_minutes
        and end_minutes < work_end_minutes
        and start_minutes < end_minutes
    )
    if is_center_split:
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at,
            end_at=end_at,
            reason="center_split",
        )

    if start_minutes == work_start_minutes:
        paid_minutes = end_minutes - work_start_minutes
        decision_work_start_minutes = end_minutes
        decision_work_end_minutes = work_end_minutes
    elif end_minutes == work_end_minutes:
        paid_minutes = work_end_minutes - start_minutes
        decision_work_start_minutes = work_start_minutes
        decision_work_end_minutes = start_minutes
    else:
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at,
            end_at=end_at,
            reason="edge_not_aligned",
        )

    if decision_work_start_minutes >= decision_work_end_minutes or paid_minutes <= 0:
        return _half_fallback_decision(
            request_id=request_id,
            start_at=start_at,
            end_at=end_at,
            reason="invalid_half_duration",
        )

    return _PaidHolidayDecision(
        kind="half",
        request_id=request_id,
        half_start_at=start_at,
        half_end_at=end_at,
        work_start_minutes=decision_work_start_minutes,
        work_end_minutes=decision_work_end_minutes,
        paid_minutes=paid_minutes,
    )


def _half_fallback_decision(
    *,
    request_id: "int | None",
    start_at: "str | None",
    end_at: "str | None",
    reason: str,
) -> _PaidHolidayDecision:
    detail = (
        f"request_id={_to_log_value(request_id)},start_at={_to_log_value(start_at)},"
        f"end_at={_to_log_value(end_at)}"
    )
    return _PaidHolidayDecision(
        kind="half_fallback",
        request_id=request_id,
        half_start_at=start_at,
        half_end_at=end_at,
        fallback_reason=reason,
        fallback_detail=detail,
    )


def _print_half_fallback(date: str, decision: _PaidHolidayDecision) -> None:
    detail_parts = []
    if decision.fallback_reason:
        detail_parts.append(f"reason={decision.fallback_reason}")
    if decision.fallback_detail:
        detail_parts.append(decision.fallback_detail)
    detail = ",".join(detail_parts) if detail_parts else "detail=unknown"
    print(f"[WARN] {date} reason=half_fallback detail={detail}")


def _build_work_record_payload(
    company_id: int,
    date: str,
    decision: _PaidHolidayDecision,
    work_start_minutes: int,
    work_end_minutes: int,
) -> dict[str, Any]:
    if work_start_minutes >= work_end_minutes:
        raise ActionExecutionError(
            "就業時刻の範囲が不正です。start は end より前である必要があります。"
        )

    if decision.kind == "full":
        return _build_full_paid_holiday_payload(company_id)
    if decision.kind == "half":
        if (
            decision.work_start_minutes is None
            or decision.work_end_minutes is None
            or decision.paid_minutes is None
        ):
            raise ActionExecutionError("half 有給 payload の構築に必要な値が不足しています。")
        return _build_half_paid_holiday_payload(
            company_id=company_id,
            date=date,
            work_start_minutes=decision.work_start_minutes,
            work_end_minutes=decision.work_end_minutes,
            paid_minutes=decision.paid_minutes,
        )
    return _build_default_work_record_payload(
        company_id,
        date,
        work_start_minutes,
        work_end_minutes,
    )


def _build_default_work_record_payload(
    company_id: int,
    date: str,
    work_start_minutes: int,
    work_end_minutes: int,
) -> dict[str, Any]:
    break_start_minutes = _parse_hhmm_to_minutes(BULK_ATTENDANCE_BREAK_START_TIME[:5])
    break_end_minutes = _parse_hhmm_to_minutes(BULK_ATTENDANCE_BREAK_END_TIME[:5])
    if break_start_minutes is None or break_end_minutes is None:
        raise ActionExecutionError("休憩時刻の定数が不正です。")

    has_break = (
        work_start_minutes <= break_start_minutes and work_end_minutes >= break_end_minutes
    )
    break_records: list[dict[str, str]] = []
    if has_break:
        break_records = [
            {
                "clock_in_at": f"{date} {BULK_ATTENDANCE_BREAK_START_TIME}",
                "clock_out_at": f"{date} {BULK_ATTENDANCE_BREAK_END_TIME}",
            }
        ]
    else:
        print(
            f"[INFO] {date} reason=break_records_skipped "
            f"detail=work={_minutes_to_hhmm(work_start_minutes)}-{_minutes_to_hhmm(work_end_minutes)}"
        )

    return {
        "company_id": company_id,
        "break_records": break_records,
        "work_record_segments": [
            {
                "clock_in_at": f"{date} {_minutes_to_hhmmss(work_start_minutes)}",
                "clock_out_at": f"{date} {_minutes_to_hhmmss(work_end_minutes)}",
            }
        ],
    }


def _build_full_paid_holiday_payload(company_id: int) -> dict[str, Any]:
    return {
        "company_id": company_id,
        "paid_holidays": [
            {
                "type": "full",
            }
        ],
    }


def _build_half_paid_holiday_payload(
    *,
    company_id: int,
    date: str,
    work_start_minutes: int,
    work_end_minutes: int,
    paid_minutes: int,
) -> dict[str, Any]:
    return {
        "company_id": company_id,
        "work_record_segments": [
            {
                "clock_in_at": f"{date} {_minutes_to_hhmmss(work_start_minutes)}",
                "clock_out_at": f"{date} {_minutes_to_hhmmss(work_end_minutes)}",
            }
        ],
        "paid_holidays": [
            {
                "type": "half",
                "mins": paid_minutes,
            }
        ],
    }


def _work_result_label(
    decision: _PaidHolidayDecision,
    work_start_minutes: int,
    work_end_minutes: int,
) -> str:
    if decision.kind == "full":
        return "有給(full)"
    if decision.kind == "half":
        if decision.work_start_minutes is None or decision.work_end_minutes is None:
            return "半休(half)"
        start_at = _minutes_to_hhmm(decision.work_start_minutes)
        end_at = _minutes_to_hhmm(decision.work_end_minutes)
        return f"半休(勤務 {start_at}-{end_at})"
    if decision.kind == "half_fallback":
        start_at = _minutes_to_hhmm(work_start_minutes)
        end_at = _minutes_to_hhmm(work_end_minutes)
        return f"{start_at}-{end_at}(half_fallback)"
    start_at = _minutes_to_hhmm(work_start_minutes)
    end_at = _minutes_to_hhmm(work_end_minutes)
    return f"{start_at}-{end_at}"


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


def _parse_hhmm_to_minutes(value: str) -> "int | None":
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        return None
    hour, minute = value.split(":")
    hh = int(hour)
    mm = int(minute)
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 60 + mm


def _minutes_to_hhmm(minutes: int) -> str:
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}"


def _minutes_to_hhmmss(minutes: int) -> str:
    return f"{_minutes_to_hhmm(minutes)}:00"


def _as_int(value: object) -> "int | None":
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _to_log_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    return str(value)


def _print_api_error(date: str, step: str, exc: ApiResponseError) -> None:
    """API エラーのログを出力します。"""

    messages: list[str] = []
    body = exc.response_body
    if isinstance(body, dict):
        for err in body.get("errors", []):
            if isinstance(err, dict):
                raw_messages = err.get("messages", [])
                if isinstance(raw_messages, list):
                    messages.extend(str(message) for message in raw_messages)

    match = re.search(r"status=(\d+)", str(exc))
    status_text = match.group(1) if match else "unknown"
    detail = " / ".join(messages) if messages else str(exc)
    print(f"[ERR]  {date} step={step} status={status_text} message={detail}")


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
