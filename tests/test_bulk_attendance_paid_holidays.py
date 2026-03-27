"""bulk_attendance の有給判定ロジックを検証するテストです。"""

import unittest

from app.actions.bulk_attendance import (
    _build_half_decision,
    _decide_paid_holiday,
    _fetch_paid_holidays_for_month,
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
        start_target_date: str,
        end_target_date: str,
        limit: int,
        offset: int,
    ) -> ApiResponse:
        self.calls.append(
            {
                "company_id": company_id,
                "start_target_date": start_target_date,
                "end_target_date": end_target_date,
                "limit": limit,
                "offset": offset,
            }
        )
        return self._responses.pop(0)


class BulkAttendancePaidHolidayTests(unittest.TestCase):
    def test_build_half_decision_morning_half(self) -> None:
        decision = _build_half_decision(
            {
                "id": 1,
                "start_at": "09:00",
                "end_at": "14:00",
            }
        )

        self.assertEqual("half", decision.kind)
        self.assertEqual(14 * 60, decision.work_start_minutes)
        self.assertEqual(19 * 60, decision.work_end_minutes)
        self.assertEqual(300, decision.paid_minutes)

    def test_build_half_decision_center_split_fallback(self) -> None:
        decision = _build_half_decision(
            {
                "id": 2,
                "start_at": "10:00",
                "end_at": "15:00",
            }
        )

        self.assertEqual("half_fallback", decision.kind)
        self.assertEqual("center_split", decision.fallback_reason)

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
                start_target_date="2026-03-01",
                end_target_date="2026-03-31",
            )

        self.assertEqual([0, 100], [call["offset"] for call in fake_client.calls])


if __name__ == "__main__":
    unittest.main()
