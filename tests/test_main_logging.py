"""main.py のログ出力機能を検証するテストです。"""

import argparse
import io
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import main
from app.exit_codes import EXIT_CODE_CANCELLED, EXIT_CODE_OK
from app.logging.tee_logger import LogSink, TeeStream, cleanup_old_log_dirs


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class _FailingLogStream(io.StringIO):
    def write(self, _: str) -> int:
        raise OSError("disk full")


class MainLoggingTests(unittest.TestCase):
    def test_main_writes_terminal_output_and_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_root = Path(tmp_dir) / "logs"

            def _fake_run(*, auth_code: str | None) -> int:
                del auth_code
                print("stdout-message")
                print("\x1b[31mansi-stderr\x1b[0m", file=sys.stderr)
                return EXIT_CODE_OK

            with (
                patch("main.parse_args", return_value=argparse.Namespace(auth_code=None)),
                patch("main.run", side_effect=_fake_run),
                patch("main._resolve_logs_root", return_value=logs_root),
                patch("sys.stdout", new_callable=io.StringIO) as stdout_capture,
                patch("sys.stderr", new_callable=io.StringIO) as stderr_capture,
            ):
                exit_code = main.main()

            self.assertEqual(EXIT_CODE_OK, exit_code)
            terminal_stdout = stdout_capture.getvalue()
            terminal_stderr = stderr_capture.getvalue()
            self.assertIn("[RUN START]", terminal_stdout)
            self.assertIn("[RUN END]", terminal_stdout)
            self.assertIn("[EXIT CODE] 0", terminal_stdout)
            self.assertIn("stdout-message", terminal_stdout)
            self.assertIn("ansi-stderr", terminal_stderr)

            log_files = sorted(logs_root.glob("*/*.log"))
            self.assertEqual(1, len(log_files))
            log_content = log_files[0].read_text(encoding="utf-8")
            self.assertIn("[RUN START]", log_content)
            self.assertIn("[RUN END]", log_content)
            self.assertIn("[EXIT CODE] 0", log_content)
            self.assertIn("stdout-message", log_content)
            self.assertIn("\x1b[31mansi-stderr\x1b[0m", log_content)
            self.assertIn(f"ログ保存先: {log_files[0].resolve()}", terminal_stdout)

    def test_main_handles_keyboard_interrupt_with_exit_code_130(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_root = Path(tmp_dir) / "logs"

            def _interrupt_run(*, auth_code: str | None) -> int:
                del auth_code
                raise KeyboardInterrupt

            with (
                patch("main.parse_args", return_value=argparse.Namespace(auth_code=None)),
                patch("main.run", side_effect=_interrupt_run),
                patch("main._resolve_logs_root", return_value=logs_root),
                patch("sys.stdout", new_callable=io.StringIO) as stdout_capture,
                patch("sys.stderr", new_callable=io.StringIO) as stderr_capture,
            ):
                exit_code = main.main()

            self.assertEqual(EXIT_CODE_CANCELLED, exit_code)
            self.assertIn("[MENU CANCELLED] KeyboardInterrupt", stderr_capture.getvalue())
            self.assertIn("[EXIT CODE] 130", stdout_capture.getvalue())

            log_files = sorted(logs_root.glob("*/*.log"))
            self.assertEqual(1, len(log_files))
            log_content = log_files[0].read_text(encoding="utf-8")
            self.assertIn("[MENU CANCELLED] KeyboardInterrupt", log_content)
            self.assertIn("[EXIT CODE] 130", log_content)

    def test_main_continues_when_log_file_creation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_root = Path(tmp_dir) / "logs"

            def _fake_run(*, auth_code: str | None) -> int:
                del auth_code
                print("still-running")
                return EXIT_CODE_OK

            with (
                patch("main.parse_args", return_value=argparse.Namespace(auth_code=None)),
                patch("main.run", side_effect=_fake_run),
                patch("main._resolve_logs_root", return_value=logs_root),
                patch("main._open_log_file", side_effect=OSError("disk full")),
                patch("sys.stdout", new_callable=io.StringIO) as stdout_capture,
                patch("sys.stderr", new_callable=io.StringIO) as stderr_capture,
            ):
                exit_code = main.main()

            self.assertEqual(EXIT_CODE_OK, exit_code)
            self.assertIn("[LOG WARNING] ログファイルの準備に失敗したため", stderr_capture.getvalue())
            self.assertIn("ログファイルの作成に失敗したよ", stdout_capture.getvalue())
            self.assertEqual([], list(logs_root.glob("*/*.log")))

    def test_cleanup_old_log_dirs_removes_only_expired_date_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_root = Path(tmp_dir) / "logs"
            old_dir = logs_root / "20260201"
            keep_dir = logs_root / "20260320"
            invalid_dir = logs_root / "keep_me"
            old_dir.mkdir(parents=True)
            keep_dir.mkdir(parents=True)
            invalid_dir.mkdir(parents=True)
            (old_dir / "old.log").write_text("x", encoding="utf-8")
            (keep_dir / "new.log").write_text("y", encoding="utf-8")

            cleanup_old_log_dirs(
                logs_root,
                now=datetime(2026, 3, 30, tzinfo=UTC),
            )

            self.assertFalse(old_dir.exists())
            self.assertTrue(keep_dir.exists())
            self.assertTrue(invalid_dir.exists())

    def test_teestream_keeps_terminal_output_when_log_write_fails(self) -> None:
        original_stream = _TtyStringIO()
        warning_stream = io.StringIO()
        sink = LogSink(log_stream=_FailingLogStream(), warning_stream=warning_stream)
        stream = TeeStream(original_stream=original_stream, log_sink=sink)

        stream.write("abc")
        stream.write("def")
        stream.flush()

        self.assertEqual("abcdef", original_stream.getvalue())
        self.assertTrue(stream.isatty())
        self.assertEqual(1, warning_stream.getvalue().count("[LOG WARNING]"))


if __name__ == "__main__":
    unittest.main()
