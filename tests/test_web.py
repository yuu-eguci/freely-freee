"""web.py のフォーム処理と送信処理を検証するテストです。"""

import unittest
from unittest.mock import patch

import web
from app.errors import ActionExecutionError, OAuthTokenError
from app.exit_codes import EXIT_CODE_OK


class WebTests(unittest.TestCase):
    def test_parse_form_submission_accepts_valid_input(self) -> None:
        form_input, state, errors = web.parse_form_submission(
            {
                "target_month": ["2026-03"],
                "start_hour": ["9"],
                "end_hour": ["19"],
                "employee_id": ["123"],
                "include_attendance_tag": ["on"],
            }
        )

        self.assertEqual((), errors)
        self.assertIsNotNone(form_input)
        assert form_input is not None
        self.assertEqual("2026-03", form_input.target_month)
        self.assertEqual(9, form_input.start_hour)
        self.assertEqual(19, form_input.end_hour)
        self.assertEqual(123, form_input.employee_id)
        self.assertTrue(form_input.include_attendance_tag)
        self.assertEqual("123", state.employee_id)

    def test_parse_form_submission_rejects_invalid_values(self) -> None:
        form_input, _, errors = web.parse_form_submission(
            {
                "target_month": ["2026-13"],
                "start_hour": ["20"],
                "end_hour": ["8"],
                "employee_id": ["abc"],
            }
        )

        self.assertIsNone(form_input)
        self.assertIn("対象月が不正です。実在する年月を入力してね。", errors)
        self.assertIn("出勤時刻は退勤時刻より前にしてね。", errors)
        self.assertIn("従業員IDは数字で入力してね。", errors)

    def test_parse_form_submission_defaults_include_attendance_tag_to_false(self) -> None:
        form_input, _, errors = web.parse_form_submission(
            {
                "target_month": ["2026-03"],
                "start_hour": ["9"],
                "end_hour": ["19"],
                "employee_id": ["1"],
            }
        )

        self.assertEqual((), errors)
        self.assertIsNotNone(form_input)
        assert form_input is not None
        self.assertFalse(form_input.include_attendance_tag)

    def test_run_submission_returns_token_error_result(self) -> None:
        form_input = web.WebFormInput(
            target_month="2026-03",
            start_hour=9,
            end_hour=19,
            employee_id=1,
            include_attendance_tag=False,
        )

        with (
            patch("web.load_config", return_value=object()),
            patch("web.load_refresh_token", return_value="refresh"),
            patch("web.refresh_access_token", side_effect=OAuthTokenError("token failed")),
            patch("web.build_authorize_url", return_value=("https://example.com/auth", "state-1")),
        ):
            result = web.run_submission(form_input)

        self.assertFalse(result.success)
        self.assertEqual("トークン更新に失敗したよ", result.title)
        self.assertIn("authorize_url: https://example.com/auth", result.messages)
        self.assertIn("state: state-1", result.messages)

    def test_run_submission_returns_failure_when_action_raises(self) -> None:
        form_input = web.WebFormInput(
            target_month="2026-03",
            start_hour=9,
            end_hour=19,
            employee_id=1,
            include_attendance_tag=False,
        )

        with (
            patch("web.load_config", return_value=object()),
            patch("web.load_refresh_token", return_value="refresh"),
            patch(
                "web.refresh_access_token",
                return_value={"access_token": "access", "refresh_token": "refresh-next"},
            ),
            patch("web.save_tokens"),
            patch("web.require_access_token", return_value="access"),
            patch(
                "web.run_by_employee_id_for_web",
                side_effect=ActionExecutionError("users/me failed"),
            ),
        ):
            result = web.run_submission(form_input)

        self.assertFalse(result.success)
        self.assertEqual("処理失敗", result.title)
        self.assertIn("freee API 呼び出し中にエラーが発生しました: users/me failed", result.messages)

    def test_run_submission_success(self) -> None:
        form_input = web.WebFormInput(
            target_month="2026-03",
            start_hour=9,
            end_hour=19,
            employee_id=55,
            include_attendance_tag=True,
        )

        with (
            patch("web.load_config", return_value=object()),
            patch("web.load_refresh_token", return_value="refresh"),
            patch(
                "web.refresh_access_token",
                return_value={"access_token": "access", "refresh_token": "refresh-next"},
            ),
            patch("web.save_tokens"),
            patch("web.require_access_token", return_value="access"),
            patch("web.run_by_employee_id_for_web", return_value=EXIT_CODE_OK) as run_action,
        ):
            result = web.run_submission(form_input)

        self.assertTrue(result.success)
        self.assertEqual("処理完了", result.title)
        run_action.assert_called_once()


if __name__ == "__main__":
    unittest.main()
