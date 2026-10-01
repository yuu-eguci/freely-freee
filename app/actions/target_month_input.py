"""月次一括勤怠アクションで共有する対象月入力の処理です。"""

import re
from datetime import datetime

TARGET_MONTH_PROMPT = "対象月を入力してね (yyyy-mm yyyymm どっちか): "

# yyyy-mm と yyyymm の両方を受け付けます。全角数字は受け付けません。
_TARGET_MONTH_PATTERN = re.compile(r"(\d{4})-?(\d{2})", re.ASCII)


def parse_target_month() -> "tuple[int, int] | None":
    """input() で対象月を受け取り、(year, month) を返します。不正入力時は None を返します。"""

    raw = input(TARGET_MONTH_PROMPT).strip()
    return parse_target_month_value(raw)


def parse_target_month_value(raw: str) -> "tuple[int, int] | None":
    """yyyy-mm または yyyymm 形式の文字列を (year, month) へ変換します。"""

    if not raw:
        print("[エラー] 入力が空です。")
        return None
    match = _TARGET_MONTH_PATTERN.fullmatch(raw)
    if match is None:
        print(f"[エラー] フォーマットが不正です: {raw!r}  (例: 2026-03 または 202603)")
        return None
    try:
        dt = datetime(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        print(f"[エラー] 存在しない年月です: {raw!r}")
        return None
    return dt.year, dt.month
