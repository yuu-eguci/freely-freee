"""対象月入力の共通処理を検証するテストです。"""

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.actions import bulk_attendance, bulk_attendance_reset
from app.actions.target_month_input import (
    TARGET_MONTH_PROMPT,
    parse_target_month,
    parse_target_month_value,
)
from app.exit_codes import EXIT_CODE_MENU_ERROR


def _parse_with_output(raw: str) -> "tuple[tuple[int, int] | None, str]":
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        result = parse_target_month_value(raw)
    return result, buffer.getvalue()


class ParseTargetMonthValueTests(unittest.TestCase):
    def test_accepts_hyphenated_format(self) -> None:
        self.assertEqual(_parse_with_output("2026-09"), ((2026, 9), ""))

    def test_accepts_compact_format(self) -> None:
        self.assertEqual(_parse_with_output("202609"), ((2026, 9), ""))

    def test_accepts_boundary_months(self) -> None:
        for raw, expected in (
            ("2026-01", (2026, 1)),
            ("202601", (2026, 1)),
            ("2026-12", (2026, 12)),
            ("202612", (2026, 12)),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(_parse_with_output(raw), (expected, ""))

    def test_rejects_empty_input(self) -> None:
        result, output = _parse_with_output("")
        self.assertIsNone(result)
        self.assertIn("[エラー] 入力が空です。", output)

    def test_rejects_invalid_formats(self) -> None:
        for raw in ("2026/09", "2026-9", "20269", "2026090", "26-09", "2026-09-01", "2026_09", "2026--09", "abcdef"):
            with self.subTest(raw=raw):
                result, output = _parse_with_output(raw)
                self.assertIsNone(result)
                self.assertIn(f"[エラー] フォーマットが不正です: {raw!r}", output)
                self.assertIn("(例: 2026-03 または 202603)", output)

    def test_rejects_fullwidth_digits(self) -> None:
        # 全角数字の 2026-09 と 202609 です。
        for raw in ("\uff12\uff10\uff12\uff16-\uff10\uff19", "\uff12\uff10\uff12\uff16\uff10\uff19"):
            with self.subTest(raw=raw):
                result, output = _parse_with_output(raw)
                self.assertIsNone(result)
                self.assertIn(f"[エラー] フォーマットが不正です: {raw!r}", output)

    def test_rejects_nonexistent_months(self) -> None:
        for raw in ("2026-00", "202600", "2026-13", "202613", "0000-01", "000001"):
            with self.subTest(raw=raw):
                result, output = _parse_with_output(raw)
                self.assertIsNone(result)
                self.assertIn(f"[エラー] 存在しない年月です: {raw!r}", output)


class ParseTargetMonthTests(unittest.TestCase):
    def test_uses_prompt_and_strips_input(self) -> None:
        with patch("builtins.input", return_value="  202609  ") as mocked_input:
            result = parse_target_month()

        self.assertEqual(result, (2026, 9))
        mocked_input.assert_called_once_with("対象月を入力してね (yyyy-mm yyyymm どっちか): ")
        self.assertEqual(TARGET_MONTH_PROMPT, "対象月を入力してね (yyyy-mm yyyymm どっちか): ")


class HandlerTargetMonthTests(unittest.TestCase):
    def test_handlers_stop_before_api_calls_on_invalid_month(self) -> None:
        for module in (bulk_attendance, bulk_attendance_reset):
            with self.subTest(module=module.__name__):
                with (
                    patch("builtins.input", return_value="2026/09") as mocked_input,
                    patch.object(module, "HrApiClient") as mocked_client,
                    redirect_stdout(io.StringIO()),
                ):
                    exit_code = module.handler(context=None)  # type: ignore[arg-type]

                self.assertEqual(exit_code, EXIT_CODE_MENU_ERROR)
                mocked_input.assert_called_once_with(TARGET_MONTH_PROMPT)
                mocked_client.assert_not_called()

    def test_reset_handler_passes_compact_month(self) -> None:
        with (
            patch("builtins.input", return_value="202609"),
            patch.object(bulk_attendance_reset, "HrApiClient"),
            patch.object(bulk_attendance_reset, "resolve_current_user_context"),
            patch.object(bulk_attendance_reset, "_generate_dates", side_effect=RuntimeError("stop")) as mocked_dates,
            self.assertRaises(RuntimeError),
        ):
            bulk_attendance_reset.handler(context=_DummyContext())  # type: ignore[arg-type]

        mocked_dates.assert_called_once_with(2026, 9)

    def test_bulk_attendance_passes_compact_month(self) -> None:
        with (
            patch("builtins.input", side_effect=["202609", "", "", ""]),
            patch.object(bulk_attendance, "HrApiClient"),
            patch.object(bulk_attendance, "resolve_current_user_context"),
            patch.object(bulk_attendance, "_execute_bulk_attendance", return_value=0) as mocked_execute,
        ):
            exit_code = bulk_attendance.handler(context=_DummyContext())  # type: ignore[arg-type]

        self.assertEqual(exit_code, 0)
        self.assertEqual(mocked_execute.call_args.kwargs["year"], 2026)
        self.assertEqual(mocked_execute.call_args.kwargs["month"], 9)


class _DummyConfig:
    target_company_id = 1


class _DummyContext:
    config = _DummyConfig()
    api_client = None


if __name__ == "__main__":
    unittest.main()
