"""Local web interface for employee-id monthly attendance registration."""

import argparse
import os
import re
import sys
import threading
import traceback
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qs, urlparse

from app.actions.bulk_attendance import run_by_employee_id_for_web
from app.auth.oauth_service import (
    build_authorize_url,
    refresh_access_token,
    require_access_token,
)
from app.auth.token_store import load_refresh_token, save_tokens
from app.clients.freee_api_client import FreeeApiClient
from app.config import ConfigError, load_config
from app.context import AppContext
from app.errors import ActionExecutionError, ApiClientError, OAuthTokenError, TokenStoreError
from app.exit_codes import EXIT_CODE_APP_ERROR, EXIT_CODE_MENU_ERROR, EXIT_CODE_OK
from app.logging.tee_logger import (
    LOG_RETENTION_DAYS,
    LogSink,
    TeeStream,
    build_log_file_path,
    cleanup_old_log_dirs,
    format_run_timestamp,
)

_RUNNING_LOCK = threading.Lock()
_MONTH_PATTERN = re.compile(r"\d{4}-\d{2}")
_WAITING_MESSAGE = (
    "まあ仕様上はいくらでも連続処理できるんだけど、内部的に Freee API を呼んでおり、"
    "あんまりたくさん API コールするのも Freee に申し訳ないので処理終わるの待ってね"
)


@dataclass(frozen=True)
class WebFormState:
    target_month: str
    start_hour: str
    end_hour: str
    employee_id: str
    include_attendance_tag: bool


@dataclass(frozen=True)
class WebFormInput:
    target_month: str
    start_hour: int
    end_hour: int
    employee_id: int
    include_attendance_tag: bool


@dataclass(frozen=True)
class SubmissionResult:
    success: bool
    title: str
    messages: tuple[str, ...]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="freee monthly attendance web ui")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def _default_form_state() -> WebFormState:
    return WebFormState(
        target_month=datetime.now().strftime("%Y-%m"),
        start_hour="9",
        end_hour="19",
        employee_id="",
        include_attendance_tag=False,
    )


def _first(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    if not values:
        return default
    return values[0].strip()


def parse_form_submission(params: dict[str, list[str]]) -> tuple[WebFormInput | None, WebFormState, tuple[str, ...]]:
    default = _default_form_state()
    include_attendance_tag = _first(params, "include_attendance_tag").lower() in {
        "on",
        "1",
        "true",
        "yes",
        "y",
    }
    state = WebFormState(
        target_month=_first(params, "target_month", default.target_month),
        start_hour=_first(params, "start_hour", default.start_hour),
        end_hour=_first(params, "end_hour", default.end_hour),
        employee_id=_first(params, "employee_id", default.employee_id),
        include_attendance_tag=include_attendance_tag,
    )

    errors: list[str] = []
    if not _MONTH_PATTERN.fullmatch(state.target_month):
        errors.append("対象月は yyyy-mm 形式で入力してね。")
    else:
        try:
            datetime.strptime(state.target_month, "%Y-%m")
        except ValueError:
            errors.append("対象月が不正です。実在する年月を入力してね。")

    start_hour = _parse_hour(state.start_hour, "出勤", errors)
    end_hour = _parse_hour(state.end_hour, "退勤", errors)
    if start_hour is not None and end_hour is not None and start_hour >= end_hour:
        errors.append("出勤時刻は退勤時刻より前にしてね。")

    employee_id = _parse_employee_id(state.employee_id, errors)
    if errors:
        return None, state, tuple(errors)

    assert start_hour is not None
    assert end_hour is not None
    assert employee_id is not None
    return (
        WebFormInput(
            target_month=state.target_month,
            start_hour=start_hour,
            end_hour=end_hour,
            employee_id=employee_id,
            include_attendance_tag=state.include_attendance_tag,
        ),
        state,
        (),
    )


def _parse_hour(raw: str, label: str, errors: list[str]) -> int | None:
    if not raw:
        errors.append(f"{label}時刻は 0-23 の整数で入力してね。")
        return None
    if not re.fullmatch(r"\d{1,2}", raw):
        errors.append(f"{label}時刻は 0-23 の整数で入力してね。")
        return None
    value = int(raw)
    if not (0 <= value <= 23):
        errors.append(f"{label}時刻は 0-23 の整数で入力してね。")
        return None
    return value


def _parse_employee_id(raw: str, errors: list[str]) -> int | None:
    if not raw:
        errors.append("従業員IDは必須です。")
        return None
    if not re.fullmatch(r"\d+", raw):
        errors.append("従業員IDは数字で入力してね。")
        return None
    value = int(raw)
    if value < 1:
        errors.append("従業員IDは 1 以上の整数で入力してね。")
        return None
    return value


def run_submission(form_input: WebFormInput) -> SubmissionResult:
    try:
        config = load_config()
    except ConfigError as exc:
        return SubmissionResult(False, "設定エラー", (str(exc),))

    try:
        refresh_token = load_refresh_token()
        token_payload = refresh_access_token(config, refresh_token)
        save_tokens(token_payload)
        access_token = require_access_token(token_payload)
    except (OAuthTokenError, TokenStoreError) as exc:
        authorize_url, state = build_authorize_url(config)
        return SubmissionResult(
            False,
            "トークン更新に失敗したよ",
            (
                str(exc),
                "認可コードを再取得してから、従来どおり main.py で token.json を更新してね。",
                f"authorize_url: {authorize_url}",
                f"state: {state}",
            ),
        )

    context = AppContext(
        config=config,
        access_token=access_token,
        api_client=FreeeApiClient(access_token),
        debug_mode=False,
    )

    try:
        exit_code = run_by_employee_id_for_web(
            context,
            target_month=form_input.target_month,
            start_hour=form_input.start_hour,
            end_hour=form_input.end_hour,
            employee_id=form_input.employee_id,
            include_attendance_tag=form_input.include_attendance_tag,
        )
    except (ActionExecutionError, ApiClientError) as exc:
        return SubmissionResult(
            False,
            "処理失敗",
            (
                f"freee API 呼び出し中にエラーが発生しました: {exc}",
                "Terminal と logs/ 配下の最新ログを確認してね。",
            ),
        )
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return SubmissionResult(
            False,
            "処理失敗",
            (
                "予期しないエラーが発生しました。",
                "Terminal と logs/ 配下の最新ログを確認してね。",
            ),
        )

    if exit_code == EXIT_CODE_OK:
        return SubmissionResult(
            True,
            "処理完了",
            (
                "従業員ID指定の勤怠登録が完了しました。",
                "詳細は Terminal と logs/ 配下の実行ログを確認してね。",
            ),
        )

    if exit_code == EXIT_CODE_MENU_ERROR:
        return SubmissionResult(
            False,
            "入力エラー",
            ("入力値が不正なため処理を中断しました。入力内容を見直して再送してね。",),
        )

    return SubmissionResult(
        False,
        "処理失敗",
        (
            "freee API 呼び出し中にエラーが発生しました。",
            "logs 配下の最新ログファイルをそのまま送って確認してもらってね。",
        ),
    )


def _resolve_logs_root() -> Path:
    return Path(__file__).resolve().parent / "logs"


def _open_log_file(log_path: Path) -> TextIO:
    return log_path.open("w", encoding="utf-8")


def render_page(
    *,
    state: WebFormState,
    errors: tuple[str, ...] = (),
    result: SubmissionResult | None = None,
) -> bytes:
    errors_html = "".join(f"<li>{escape(item)}</li>" for item in errors)
    result_html = ""
    if result is not None:
        css_class = "ok" if result.success else "ng"
        messages_html = "".join(f"<li>{escape(item)}</li>" for item in result.messages)
        result_html = (
            f"<section class=\"result {css_class}\">"
            f"<h2>{escape(result.title)}</h2>"
            f"<ul>{messages_html}</ul>"
            "</section>"
        )

    checked = " checked" if state.include_attendance_tag else ""
    html = f"""<!doctype html>
<html lang=\"ja\">
<head>
  <meta charset=\"utf-8\">
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
  <title>freely-freee web</title>
  <style>
    body {{
      font-family: 'Hiragino Sans', 'Noto Sans JP', sans-serif;
      margin: 0;
      background: #f5f7fb;
      color: #1f2937;
    }}
    .wrap {{
      max-width: 760px;
      margin: 24px auto;
      background: #fff;
      padding: 24px;
      border-radius: 12px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
    }}
    h1 {{ margin-top: 0; }}
    .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    label {{ display: flex; flex-direction: column; font-size: 14px; gap: 4px; }}
    input[type=text], input[type=number], input[type=month] {{
      padding: 10px;
      border: 1px solid #cbd5e1;
      border-radius: 8px;
      font-size: 16px;
    }}
    .full {{ grid-column: 1 / -1; }}
    .check {{ display: flex; align-items: center; gap: 8px; }}
    button {{
      margin-top: 12px;
      padding: 10px 16px;
      border: 0;
      border-radius: 8px;
      background: #0f766e;
      color: #fff;
      font-size: 16px;
      cursor: pointer;
    }}
    .errors {{
      background: #fef2f2;
      border: 1px solid #fecaca;
      padding: 10px 12px;
      border-radius: 8px;
      margin-bottom: 12px;
    }}
    .result {{ margin-top: 16px; padding: 12px; border-radius: 8px; }}
    .result.ok {{ background: #ecfdf5; border: 1px solid #a7f3d0; }}
    .result.ng {{ background: #fff7ed; border: 1px solid #fed7aa; }}
    .loading {{
      display: none;
      margin-top: 16px;
      padding: 12px;
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
    }}
    .loading.show {{ display: block; }}
    .spinner {{
      width: 24px;
      height: 24px;
      border: 4px solid #93c5fd;
      border-top-color: #1d4ed8;
      border-radius: 50%;
      animation: spin 1s linear infinite;
      margin-bottom: 8px;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    @media (max-width: 640px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main class=\"wrap\">
    <h1>従業員ID指定の勤怠登録</h1>
    <p>token.json 更新は従来どおりのフローで処理し、その後に月次勤怠登録を実行します。</p>
    <p><code>docker compose run --rm --service-ports app pipenv run python web.py</code></p>
    {('<section class="errors"><ul>' + errors_html + '</ul></section>') if errors else ''}
    <form id=\"bulk-form\" method=\"post\" action=\"/submit\">
      <div class=\"grid\">
        <label>対象月
          <input name=\"target_month\" type=\"month\" value=\"{escape(state.target_month)}\" required>
        </label>
        <label>従業員ID
          <input
            name=\"employee_id\"
            type=\"number\"
            min=\"1\"
            step=\"1\"
            value=\"{escape(state.employee_id)}\"
            required
          >
        </label>
        <label>出勤何時
          <input name=\"start_hour\" type=\"number\" min=\"0\" max=\"23\" value=\"{escape(state.start_hour)}\" required>
        </label>
        <label>退勤何時
          <input name=\"end_hour\" type=\"number\" min=\"0\" max=\"23\" value=\"{escape(state.end_hour)}\" required>
        </label>
        <label class=\"full check\">
          <input name=\"include_attendance_tag\" type=\"checkbox\"{checked}>
          出社タグを付与する
        </label>
      </div>
      <button id=\"submit-btn\" type=\"submit\">送信</button>
      <section id=\"loading\" class=\"loading\">
        <div class=\"spinner\"></div>
        <p>{escape(_WAITING_MESSAGE)}</p>
      </section>
    </form>
    {result_html}
  </main>
  <script>
    const form = document.getElementById('bulk-form');
    const loading = document.getElementById('loading');
    const submitBtn = document.getElementById('submit-btn');
    form.addEventListener('submit', () => {{
      loading.classList.add('show');
      submitBtn.disabled = true;
    }});
  </script>
</body>
</html>
"""
    return html.encode("utf-8")


class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_html(render_page(state=_default_form_state()))

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/submit":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        params = self._read_form_params()
        form_input, state, errors = parse_form_submission(params)
        if errors:
            self._send_html(render_page(state=state, errors=errors), status=HTTPStatus.BAD_REQUEST)
            return

        if form_input is None:
            self._send_html(
                render_page(
                    state=state,
                    errors=("入力値の解釈に失敗しました。もう一度入力してね。",),
                ),
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        if not _RUNNING_LOCK.acquire(blocking=False):
            self._send_html(
                render_page(
                    state=state,
                    errors=(
                        "いま別の処理を実行中です。完了してからもう一度送信してね。",
                    ),
                ),
                status=HTTPStatus.CONFLICT,
            )
            return

        try:
            result = run_submission(form_input)
        finally:
            _RUNNING_LOCK.release()

        if result.success:
            status = HTTPStatus.OK
        elif result.title == "入力エラー":
            status = HTTPStatus.BAD_REQUEST
        else:
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        self._send_html(render_page(state=state, result=result), status=status)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_form_params(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        return parse_qs(body, keep_blank_values=True)

    def _send_html(self, body: bytes, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    args = parse_args()

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    started_at = datetime.now().astimezone()
    logs_root = _resolve_logs_root()
    log_path: Path | None = None
    log_sink: LogSink | None = None
    log_creation_failed = False

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

    print(f"[RUN START] {format_run_timestamp(started_at)}")
    if log_path is not None:
        print(f"ログ保存先: {log_path.resolve()}")
    server: ThreadingHTTPServer | None = None
    exit_code = EXIT_CODE_OK
    try:
        server = ThreadingHTTPServer((args.host, args.port), WebHandler)
        print(f"Web UI started: http://127.0.0.1:{args.port}")
        print("Ctrl+C で停止できます。")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb UI を停止しました。")
    except OSError as exc:
        print(f"[SERVER ERROR] Web UI の起動に失敗しました: {exc}", file=sys.stderr)
        exit_code = EXIT_CODE_APP_ERROR
    except Exception:
        traceback.print_exc(file=sys.stderr)
        exit_code = EXIT_CODE_APP_ERROR
    finally:
        if server is not None:
            server.server_close()
        ended_at = datetime.now().astimezone()
        try:
            print(f"[RUN END] {format_run_timestamp(ended_at)}")
            print(f"[EXIT CODE] {exit_code}")
            if log_path is not None:
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
