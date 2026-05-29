"""hr_user_context の共通 user 情報解決を検証するテストです。"""

import unittest

from app.actions.hr_user_context import resolve_current_company_and_employee_id
from app.clients.freee_api_client import ApiResponse
from app.errors import ActionExecutionError


class _FakeHrApiClientForCurrentUser:
    def __init__(self, body: dict) -> None:
        self.body = body
        self.call_count = 0

    def get_current_user(self) -> ApiResponse:
        self.call_count += 1
        return ApiResponse(status_code=200, headers={}, body=self.body)


class HrUserContextTests(unittest.TestCase):
    def test_resolve_current_company_and_employee_id_uses_target_company(self) -> None:
        fake_client = _FakeHrApiClientForCurrentUser(
            body={
                "companies": [
                    {
                        "id": 987,
                        "employee_id": 9999,
                    },
                    {
                        "id": 654,
                        "employee_id": 1111,
                    },
                ]
            }
        )

        resolved = resolve_current_company_and_employee_id(
            fake_client,
            target_company_id=654,
        )

        self.assertEqual((654, 1111), resolved)
        self.assertEqual(1, fake_client.call_count)

    def test_resolve_current_company_and_employee_id_accepts_string_company_id(self) -> None:
        fake_client = _FakeHrApiClientForCurrentUser(
            body={
                "companies": [
                    {
                        "id": "654",
                        "employee_id": "1111",
                    }
                ]
            }
        )

        resolved = resolve_current_company_and_employee_id(
            fake_client,
            target_company_id=654,
        )

        self.assertEqual((654, 1111), resolved)
        self.assertEqual(1, fake_client.call_count)

    def test_resolve_current_company_and_employee_id_rejects_missing_target_company(self) -> None:
        fake_client = _FakeHrApiClientForCurrentUser(
            body={
                "companies": [
                    {
                        "id": 987,
                        "employee_id": 9999,
                    }
                ]
            }
        )

        with self.assertRaises(ActionExecutionError) as exc:
            resolve_current_company_and_employee_id(
                fake_client,
                target_company_id=654,
            )

        self.assertEqual(
            "GET /users/me: TARGET_COMPANY_ID=654 に一致する company が見つかりませんでした。",
            str(exc.exception),
        )


if __name__ == "__main__":
    unittest.main()
