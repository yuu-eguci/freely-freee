import argparse
import os
import sys
import traceback
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import TextIO

from app.bootstrap import run
from app.exit_codes import EXIT_CODE_APP_ERROR, EXIT_CODE_CANCELLED
from app.logging.tee_logger import (
    LOG_RETENTION_DAYS,
    LogSink,
    TeeStream,
    build_log_file_path,
    cleanup_old_log_dirs,
    format_run_timestamp,
)


def parse_args() -> argparse.Namespace:
    """コマンドライン引数を解析します。"""

    parser = argparse.ArgumentParser(description="freee OAuth token bootstrap utility")
    parser.add_argument(
        "--auth-code",
        default=None,
        help="Authorization code obtained from the browser flow",
    )
    return parser.parse_args()


def _resolve_logs_root() -> Path:
    return Path(__file__).resolve().parent / "logs"


def _open_log_file(log_path: Path) -> TextIO:
    return log_path.open("w", encoding="utf-8")


def main() -> int:
    args = parse_args()

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    started_at = datetime.now().astimezone()
    logs_root = _resolve_logs_root()
    log_path: Path | None = None
    log_sink: LogSink | None = None
    log_creation_failed = False
    exit_code: int | None = None

    try:
        cleanup_old_log_dirs(
            logs_root,
            now=started_at,
            retain_days=LOG_RETENTION_DAYS,
            warning_stream=original_stderr,
        )
        log_path = build_log_file_path(logs_root, started_at, pid=os.getpid())
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_stream = _open_log_file(log_path)
        log_sink = LogSink(log_stream=log_stream, warning_stream=original_stderr)
        sys.stdout = TeeStream(original_stream=original_stdout, log_sink=log_sink)
        sys.stderr = TeeStream(original_stream=original_stderr, log_sink=log_sink)
    except OSError as exc:
        log_path = None
        log_creation_failed = True
        print(
            "[LOG WARNING] ログファイルの準備に失敗したため、Terminal出力のみで継続するよ: "
            f"{exc}",
            file=original_stderr,
        )

    try:
        print(f"[RUN START] {format_run_timestamp(started_at)}")
        exit_code = run(auth_code=args.auth_code)
    except KeyboardInterrupt:
        print("[MENU CANCELLED] KeyboardInterrupt", file=sys.stderr)
        exit_code = EXIT_CODE_CANCELLED
    except Exception:
        traceback.print_exc(file=sys.stderr)
        exit_code = EXIT_CODE_APP_ERROR
    finally:
        if exit_code is None:
            exit_code = EXIT_CODE_APP_ERROR

        ended_at = datetime.now().astimezone()
        try:
            print(f"[RUN END] {format_run_timestamp(ended_at)}")
            print(f"[EXIT CODE] {exit_code}")
            if log_path is not None:
                print(f"ログ保存先: {log_path.resolve()}")
                print("不具合調査を頼むときは、この .log ファイルをそのまま送ってね")
            elif log_creation_failed:
                print("ログファイルの作成に失敗したよ")
        except Exception as exc:
            print(
                "[LOG WARNING] 終了情報の出力に失敗したため、Terminalへフォールバックするよ: "
                f"{exc}",
                file=original_stderr,
            )
            print(f"[RUN END] {format_run_timestamp(ended_at)}", file=original_stderr)
            print(f"[EXIT CODE] {exit_code}", file=original_stderr)
            if log_path is not None:
                print(f"ログ保存先: {log_path.resolve()}", file=original_stderr)
                print(
                    "不具合調査を頼むときは、この .log ファイルをそのまま送ってね",
                    file=original_stderr,
                )
            elif log_creation_failed:
                print("ログファイルの作成に失敗したよ", file=original_stderr)
        finally:
            with suppress(Exception):
                sys.stdout.flush()
            with suppress(Exception):
                sys.stderr.flush()
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            if log_sink is not None:
                log_sink.close()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
