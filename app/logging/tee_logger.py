"""Utilities for teeing terminal output to a log file."""

import shutil
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

LOG_RETENTION_DAYS = 30


def format_run_timestamp(dt: datetime) -> str:
    """Format timestamp lines for run markers."""

    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def build_log_file_path(logs_root: Path, started_at: datetime, *, pid: int) -> Path:
    """Build the per-run log file path."""

    date_part = started_at.strftime("%Y%m%d")
    timestamp_part = started_at.strftime("%Y%m%d_%H%M%S")
    return logs_root / date_part / f"freee-cli_{timestamp_part}_pid{pid}.log"


def cleanup_old_log_dirs(
    logs_root: Path,
    *,
    now: datetime,
    retain_days: int = LOG_RETENTION_DAYS,
    warning_stream: TextIO | None = None,
) -> None:
    """Remove old date-based log directories in best-effort mode."""

    if not logs_root.exists():
        return

    cutoff_date = now.date() - timedelta(days=retain_days)
    for child in logs_root.iterdir():
        if not child.is_dir():
            continue
        try:
            child_date = datetime.strptime(child.name, "%Y%m%d").date()
        except ValueError:
            continue

        if child_date >= cutoff_date:
            continue

        try:
            shutil.rmtree(child)
        except OSError as exc:
            if warning_stream is not None:
                print(
                    "[LOG WARNING] 古いログディレクトリの削除に失敗したため、処理を継続するよ: "
                    f"{child} ({exc})",
                    file=warning_stream,
                )


class LogSink:
    """Shared writable log sink used by stdout/stderr tee streams."""

    def __init__(self, *, log_stream: TextIO, warning_stream: TextIO) -> None:
        self._log_stream: TextIO | None = log_stream
        self._warning_stream = warning_stream
        self._warning_emitted = False

    def write(self, text: str) -> None:
        if self._log_stream is None:
            return
        try:
            self._log_stream.write(text)
        except Exception as exc:  # pragma: no cover - defensive
            self._disable_log_output(exc)

    def flush(self) -> None:
        if self._log_stream is None:
            return
        try:
            self._log_stream.flush()
        except Exception as exc:  # pragma: no cover - defensive
            self._disable_log_output(exc)

    def close(self) -> None:
        if self._log_stream is None:
            return
        with suppress(Exception):
            self._log_stream.flush()
        with suppress(Exception):
            self._log_stream.close()
        self._log_stream = None

    def _disable_log_output(self, exc: Exception) -> None:
        if self._log_stream is not None:
            with suppress(Exception):
                self._log_stream.close()
            self._log_stream = None

        if self._warning_emitted:
            return

        self._warning_emitted = True
        print(
            "[LOG WARNING] ログファイルへの書き込みに失敗したため、Terminal出力のみ継続するよ: "
            f"{exc}",
            file=self._warning_stream,
        )
        with suppress(Exception):
            self._warning_stream.flush()


class TeeStream:
    """Write-through stream for terminal + shared log sink."""

    def __init__(self, *, original_stream: TextIO, log_sink: LogSink) -> None:
        self._original_stream = original_stream
        self._log_sink = log_sink

    def write(self, text: str) -> int:
        written = self._original_stream.write(text)
        self._log_sink.write(text)
        return written

    def flush(self) -> None:
        self._original_stream.flush()
        self._log_sink.flush()

    def isatty(self) -> bool:
        return self._original_stream.isatty()

    def __getattr__(self, name: str):
        return getattr(self._original_stream, name)
