"""bulk_attendance の有給判定ロジックを検証するテストです。"""

import unittest
from unittest.mock import patch

from app.actions.bulk_attendance import (
    _HALF_FALLBACK_REASON_MESSAGES,
    _build_half_decision,
    _decide_paid_holiday,
    _fetch_paid_holidays_for_month,
    _load_paid_holidays_by_date,
    _parse_include_attendance_tag,
    _process_date,
)
from app.actions.bulk_attendance_common import (
    BULK_ATTENDANCE_WORK_END_MINUTES,
    BULK_ATTENDANCE_WORK_START_MINUTES,
)
from app.clients.freee_api_client import ApiResponse
from app.errors import ActionExecutionError


class _FakeHrApiClient:
    def __init__(self, responses: list[ApiResponse]) -> None:
        self._responses = responses
        self.calls: list[dict[str, int | str]] = []

    def get_paid_holidays(
        self,
        company_id: int,
        *,
        applicant_id: int,
        start_target_date: str,
        end_target_date: str,
        limit: int,
        offset: int,
    ) -> ApiResponse:
        self.calls.append(
            {
                "company_id": company_id,
                "applicant_id": applicant_id,
                "start_target_date": start_target_date,
                "end_target_date": end_target_date,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._responses.pop(0)


class _FakeHrApiClientForProcessDate:
    def __init__(
        self,
        *,
        day_pattern: str = "normal_day",
        use_default_work_pattern: bool = True,
    ) -> None:
        self.day_pattern = day_pattern
        self.use_default_work_pattern = use_default_work_pattern
        self.put_work_record_calls: list[dict] = []
        self.put_attendance_tags_calls: list[dict] = []

    def get_work_record(self, employee_id: int, date: str, company_id: int) -> ApiResponse:
        return ApiResponse(
            status_code=200,
            headers={},
            body={
                "day_pattern": self.day_pattern,
                "use_default_work_pattern": self.use_default_work_pattern,
            },
        )

    def put_work_record(self, employee_id: int, date: str, body: dict) -> ApiResponse:
        self.put_work_record_calls.append(
            {"employee_id": employee_id, "date": date, "body": body}
        )
        return ApiResponse(status_code=200, headers={}, body={})

    def put_attendance_tags(self, employee_id: int, date: str, body: dict) -> ApiResponse:
        self.put_attendance_tags_calls.append(
            {"employee_id": employee_id, "date": date, "body": body}
        )
        return ApiResponse(status_code=200, headers={}, body={})


class BulkAttendancePaidHolidayTests(unittest.TestCase):
    def test_parse_include_attendance_tag_defaults_false_on_enter(self) -> None:
        with patch("builtins.input", return_value=""):
            include_attendance_tag = _parse_include_attendance_tag()

        self.assertFalse(include_attendance_tag)

    def test_parse_include_attendance_tag_accepts_yes(self) -> None:
        with patch("builtins.input", return_value="yes"):
            include_attendance_tag = _parse_include_attendance_tag()

        self.assertTrue(include_attendance_tag)

    def test_parse_include_attendance_tag_accepts_no(self) -> None:
        with patch("builtins.input", return_value="n"):
            include_attendance_tag = _parse_include_attendance_tag()

        self.assertFalse(include_attendance_tag)

    def test_parse_include_attendance_tag_rejects_invalid(self) -> None:
        with patch("builtins.input", return_value="maybe"):
            include_attendance_tag = _parse_include_attendance_tag()

        self.assertIsNone(include_attendance_tag)

    def test_build_half_decision_morning_half(self) -> None:
        decision = _build_half_decision(
            {
                "id": 1,
                "start_at": "09:00",
                "end_at": "14:00",
            },
            BULK_ATTENDANCE_WORK_START_MINUTES,
            BULK_ATTENDANCE_WORK_END_MINUTES,
        )

        self.assertEqual("half", decision.kind)
        self.assertEqual(14 * 60, decision.work_start_minutes)
        self.assertEqual(BULK_ATTENDANCE_WORK_END_MINUTES, decision.work_end_minutes)
        self.assertEqual(300, decision.paid_minutes)

    def test_build_half_decision_with_custom_work_hours(self) -> None:
        decision = _build_half_decision(
            {
                "id": 101,
                "start_at": "08:00",
                "end_at": "12:00",
            },
            8 * 60,
            17 * 60,
        )

        self.assertEqual("half", decision.kind)
        self.assertEqual(12 * 60, decision.work_start_minutes)
        self.assertEqual(17 * 60, decision.work_end_minutes)
        self.assertEqual(240, decision.paid_minutes)

    def test_build_half_decision_center_split_fallback(self) -> None:
        decision = _build_half_decision(
            {
                "id": 2,
                "start_at": "10:00",
                "end_at": "15:00",
            },
            BULK_ATTENDANCE_WORK_START_MINUTES,
            BULK_ATTENDANCE_WORK_END_MINUTES,
        )

        self.assertEqual("half_fallback", decision.kind)
        self.assertEqual("center_split", decision.fallback_reason)

    def test_half_fallback_reason_messages(self) -> None:
        self.assertEqual(
            {
                "multiple_half_requests": "同じ日に半休申請が複数あるぞ",
                "missing_half_time": "半休申請の開始時刻または終了時刻の設定がなくてよくわからん",
                "invalid_half_time": "半休申請の開始時刻または終了時刻の形式がおかしそう",
                "invalid_half_range": "半休申請の開始時刻が終了時刻以降になっていそう",
                "outside_work_range": "半休申請の時間が指定された勤務時間の範囲外にありそう",
                "center_split": "半休申請が勤務時間の中央にあって勤務時間がふたつに分かれちゃってる",
                "invalid_half_duration": "半休なのに勤務時間が全部潰されちゃってる",
            },
            _HALF_FALLBACK_REASON_MESSAGES,
        )

    def test_decide_paid_holiday_rejects_unsupported_status(self) -> None:
        decision = _decide_paid_holiday(
            "2026-03-01",
            [
                {
                    "id": 10,
                    "target_date": "2026-03-01",
                    "holiday_type": "full",
                    "status": "rejected",
                    "revoke_status": None,
                }
            ],
            BULK_ATTENDANCE_WORK_START_MINUTES,
            BULK_ATTENDANCE_WORK_END_MINUTES,
        )

        self.assertEqual("none", decision.kind)

    def test_decide_paid_holiday_prefers_latest_full(self) -> None:
        decision = _decide_paid_holiday(
            "2026-03-01",
            [
                {
                    "id": 11,
                    "holiday_type": "full",
                    "status": "approved",
                    "revoke_status": None,
                    "issue_date": "2026-03-01",
                },
                {
                    "id": 12,
                    "holiday_type": "full",
                    "status": "approved",
                    "revoke_status": None,
                    "issue_date": "2026-03-03",
                },
            ],
            BULK_ATTENDANCE_WORK_START_MINUTES,
            BULK_ATTENDANCE_WORK_END_MINUTES,
        )

        self.assertEqual("full", decision.kind)
        self.assertEqual(12, decision.request_id)

    def test_fetch_paid_holidays_pagination_incomplete_raises(self) -> None:
        fake_client = _FakeHrApiClient(
            responses=[
                ApiResponse(
                    status_code=200,
                    headers={},
                    body={
                        "paid_holidays": [{"id": 1, "target_date": "2026-03-01"}],
                        "total_count": 2,
                    },
                ),
                ApiResponse(
                    status_code=200,
                    headers={},
                    body={
                        "paid_holidays": [],
                        "total_count": 2,
                    },
                ),
            ]
        )

        with self.assertRaises(ActionExecutionError):
            _fetch_paid_holidays_for_month(
                fake_client,
                company_id=123,
                applicant_id=456,
                start_target_date="2026-03-01",
                end_target_date="2026-03-31",
            )

        self.assertEqual([0, 100], [call["offset"] for call in fake_client.calls])
        self.assertEqual([456, 456], [call["applicant_id"] for call in fake_client.calls])

    def test_load_paid_holidays_by_date_logs_range_and_target_dates(self) -> None:
        fake_client = _FakeHrApiClient(
            responses=[
                ApiResponse(
                    status_code=200,
                    headers={},
                    body={
                        "paid_holidays": [
                            {
                                "id": 1,
                                "target_date": "2026-03-01",
                            },
                            {
                                "id": 2,
                                "target_date": "2026-03-15",
                            },
                        ],
                        "total_count": 2,
                    },
                )
            ]
        )

        with patch("builtins.print") as mock_print:
            by_date = _load_paid_holidays_by_date(
                fake_client,
                company_id=123,
                applicant_id=456,
                year=2026,
                month=3,
            )

        self.assertEqual({"2026-03-01", "2026-03-15"}, set(by_date))
        logged_lines = [call.args[0] for call in mock_print.call_args_list]
        self.assertIn(
            "[INFO] paid_holidays取得条件 company_id=123 applicant_id=456 range=2026-03-01..2026-03-31",
            logged_lines,
        )
        self.assertIn(
            "[INFO] paid_holidays取得結果 valid_count=2 invalid_target_date_count=0 target_dates=2026-03-01,2026-03-15",
            logged_lines,
        )

    def test_load_paid_holidays_by_date_logs_invalid_target_date_count(self) -> None:
        fake_client = _FakeHrApiClient(
            responses=[
                ApiResponse(
                    status_code=200,
                    headers={},
                    body={
                        "paid_holidays": [
                            {
                                "id": 1,
                                "target_date": "2026-03-01",
                            },
                            {
                                "id": 2,
                                "target_date": 123,
                            },
                        ],
                        "total_count": 2,
                    },
                )
            ]
        )

        with patch("builtins.print") as mock_print:
            by_date = _load_paid_holidays_by_date(
                fake_client,
                company_id=123,
                applicant_id=456,
                year=2026,
                month=3,
            )

        self.assertEqual({"2026-03-01"}, set(by_date))
        logged_lines = [call.args[0] for call in mock_print.call_args_list]
        self.assertIn(
            "[INFO] paid_holidays取得結果 valid_count=1 invalid_target_date_count=1 target_dates=2026-03-01",
            logged_lines,
        )

    def test_process_date_full_paid_holiday_skips_attendance_tag(self) -> None:
        fake_client = _FakeHrApiClientForProcessDate()

        result = _process_date(
            fake_client,
            employee_id=100,
            company_id=200,
            attendance_tag_id=300,
            date="2026-03-10",
            paid_holidays_for_date=[
                {
                    "id": 21,
                    "holiday_type": "full",
                    "status": "approved",
                    "revoke_status": None,
                    "issue_date": "2026-03-01",
                }
            ],
            work_start_minutes=BULK_ATTENDANCE_WORK_START_MINUTES,
            work_end_minutes=BULK_ATTENDANCE_WORK_END_MINUTES,
            include_attendance_tag=True,
        )

        self.assertEqual("success", result)
        self.assertEqual(1, len(fake_client.put_work_record_calls))
        self.assertEqual(0, len(fake_client.put_attendance_tags_calls))

    def test_process_date_half_paid_holiday_keeps_attendance_tag(self) -> None:
        fake_client = _FakeHrApiClientForProcessDate()

        result = _process_date(
            fake_client,
            employee_id=100,
            company_id=200,
            attendance_tag_id=300,
            date="2026-03-11",
            paid_holidays_for_date=[
                {
                    "id": 22,
                    "holiday_type": "half",
                    "status": "approved",
                    "revoke_status": None,
                    "start_at": "09:00",
                    "end_at": "14:00",
                }
            ],
            work_start_minutes=BULK_ATTENDANCE_WORK_START_MINUTES,
            work_end_minutes=BULK_ATTENDANCE_WORK_END_MINUTES,
            include_attendance_tag=True,
        )

        self.assertEqual("success", result)
        self.assertEqual(1, len(fake_client.put_work_record_calls))
        self.assertEqual(1, len(fake_client.put_attendance_tags_calls))

    def test_process_date_half_fallback_logs_japanese_reason_and_guidance(self) -> None:
        fake_client = _FakeHrApiClientForProcessDate()

        with patch("builtins.print") as mock_print:
            result = _process_date(
                fake_client,
                employee_id=100,
                company_id=200,
                attendance_tag_id=None,
                date="2026-07-21",
                paid_holidays_for_date=[
                    {
                        "id": 18710761,
                        "holiday_type": "half",
                        "status": "approved",
                        "revoke_status": None,
                        "start_at": "14:00",
                        "end_at": "18:00",
                    }
                ],
                work_start_minutes=BULK_ATTENDANCE_WORK_START_MINUTES,
                work_end_minutes=BULK_ATTENDANCE_WORK_END_MINUTES,
                include_attendance_tag=False,
            )

        self.assertEqual("success", result)
        logged_lines = [call.args[0] for call in mock_print.call_args_list]
        self.assertIn(
            "[WARN] 2026-07-21 reason=half_fallback "
            "detail=reason=center_split,request_id=18710761,start_at=14:00,end_at=18:00",
            logged_lines,
        )
        self.assertIn(
            "[OK]   2026-07-21 09:00-19:00(half_fallback) 勤怠登録したよ "
            "(出社タグなし) 半休を自動反映できなかったよ "
            "(理由: 半休申請が勤務時間の中央にあって勤務時間がふたつに分かれちゃってる)。"
            "指定された勤務時間どおりに登録したので、 freee のサイトで確認・修正してね",
            logged_lines,
        )
        payload = fake_client.put_work_record_calls[0]["body"]
        self.assertNotIn("paid_holidays", payload)

    def test_process_date_normal_day_ignores_use_default_work_pattern_false(self) -> None:
        fake_client = _FakeHrApiClientForProcessDate(
            day_pattern="normal_day",
            use_default_work_pattern=False,
        )

        result = _process_date(
            fake_client,
            employee_id=100,
            company_id=200,
            attendance_tag_id=300,
            date="2026-03-12",
            paid_holidays_for_date=[],
            work_start_minutes=BULK_ATTENDANCE_WORK_START_MINUTES,
            work_end_minutes=BULK_ATTENDANCE_WORK_END_MINUTES,
            include_attendance_tag=True,
        )

        self.assertEqual("success", result)
        self.assertEqual(1, len(fake_client.put_work_record_calls))
        self.assertEqual(1, len(fake_client.put_attendance_tags_calls))
        payload = fake_client.put_work_record_calls[0]["body"]
        self.assertEqual(1, len(payload["break_records"]))

    def test_process_date_custom_hours_without_lunch_window_omits_break_records(self) -> None:
        fake_client = _FakeHrApiClientForProcessDate()

        result = _process_date(
            fake_client,
            employee_id=100,
            company_id=200,
            attendance_tag_id=300,
            date="2026-03-14",
            paid_holidays_for_date=[],
            work_start_minutes=13 * 60,
            work_end_minutes=18 * 60,
            include_attendance_tag=True,
        )

        self.assertEqual("success", result)
        payload = fake_client.put_work_record_calls[0]["body"]
        self.assertEqual([], payload["break_records"])

    def test_process_date_non_normal_day_skips_regardless_of_use_default_work_pattern(self) -> None:
        for day_pattern in ("holiday", "legal_holiday"):
            for use_default_work_pattern in (True, False):
                with self.subTest(
                    day_pattern=day_pattern,
                    use_default_work_pattern=use_default_work_pattern,
                ):
                    fake_client = _FakeHrApiClientForProcessDate(
                        day_pattern=day_pattern,
                        use_default_work_pattern=use_default_work_pattern,
                    )

                    result = _process_date(
                        fake_client,
                        employee_id=100,
                        company_id=200,
                        attendance_tag_id=300,
                        date="2026-03-13",
                        paid_holidays_for_date=[],
                        work_start_minutes=BULK_ATTENDANCE_WORK_START_MINUTES,
                        work_end_minutes=BULK_ATTENDANCE_WORK_END_MINUTES,
                        include_attendance_tag=True,
                    )

                    self.assertEqual("skipped", result)
                    self.assertEqual(0, len(fake_client.put_work_record_calls))
                    self.assertEqual(0, len(fake_client.put_attendance_tags_calls))

    def test_process_date_skips_attendance_tag_when_disabled(self) -> None:
        fake_client = _FakeHrApiClientForProcessDate()

        result = _process_date(
            fake_client,
            employee_id=100,
            company_id=200,
            attendance_tag_id=300,
            date="2026-03-15",
            paid_holidays_for_date=[],
            work_start_minutes=BULK_ATTENDANCE_WORK_START_MINUTES,
            work_end_minutes=BULK_ATTENDANCE_WORK_END_MINUTES,
            include_attendance_tag=False,
        )

        self.assertEqual("success", result)
        self.assertEqual(1, len(fake_client.put_work_record_calls))
        self.assertEqual(0, len(fake_client.put_attendance_tags_calls))


if __name__ == "__main__":
    unittest.main()
