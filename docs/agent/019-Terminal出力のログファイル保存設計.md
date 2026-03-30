# 019 Terminal出力のログファイル保存設計

## 要望

- このツールを同僚にも使ってもらえるようにしたい。
- エラー時に「このフォルダのログファイルを送って」と案内できるようにしたい。
- そのため、実行時に Terminal に出る内容を、同じ内容のログファイルにも保存したい。
- いつ実行したログか分かるように、実行時刻を残したい。

## 設計方針（既存動作を壊さない）

- 既存の `print()` 挙動は変えず、`main.py` の入口で `stdout/stderr` を「Terminal + ファイル」の二重出力に差し替える。
- 既存の終了コード運用（`0 / 1 / 2 / 130`）はそのまま維持する。
- 既存の `app/bootstrap.py` 側ロジックには手を入れず、ログ機能は薄い共通部品として追加する。

## 詳細設計

### 1. ログ出力先ディレクトリ/ファイル命名規則

- ルート: `./logs/`
- 日付ディレクトリ: `./logs/YYYYMMDD/`
- ログファイル名: `freee-cli_YYYYMMDD_HHMMSS_pid<プロセスID>.log`
- 例: `logs/20260330/freee-cli_20260330_153045_pid12345.log`
- 時刻はローカル時刻（実行環境のタイムゾーン）で作る。
- 実装時は起動直後に `mkdir(parents=True, exist_ok=True)` で作成する。

### 2. Terminal + ファイルへ同時出力する方式

- `app/logging/tee_logger.py`（新規想定）に `TeeStream` を用意する。
- `TeeStream` は `write()` / `flush()` / `isatty()` を持ち、書き込み先を「元の Terminal ストリーム」と「ログファイル」の2つに流す。
- `main.py` で実行開始時に:
1. ログファイルを開く
2. 元の `sys.stdout` / `sys.stderr` を退避
3. `sys.stdout = TeeStream(original_stdout, log_file)`
4. `sys.stderr = TeeStream(original_stderr, log_file)`
- これで既存の `print()` 呼び出しは変更なしで二重出力される。
- 実行終了時は `finally` で `flush` とクローズを行い、`sys.stdout/stderr` を元に戻す。

### 3. stdout/stderr と例外時の扱い

- `stdout` と `stderr` は分離したまま扱う（色分けや既存運用に影響を出さない）。
- どちらも同一ログファイルへ保存する（時系列で追えるようにする）。
- ハンドリング済み例外（既存の `run()` が終了コードを返すケース）:
  - 既存どおり `bootstrap.py` が `stderr` に出した内容をそのままログに残す。
- 未ハンドル例外:
  - `main.py` 側で `traceback.print_exc(file=sys.stderr)` を出す。
  - その後 `EXIT_CODE_APP_ERROR (1)` で終了する。
- `KeyboardInterrupt` は既存方針優先で `130` を維持し、中断メッセージもログに残す。

### 4. 実行開始・終了時刻、終了コードの記録方針

- ログ冒頭に開始行を必ず出力:
  - 例: `[RUN START] 2026-03-30 15:30:45 +0900`
- ログ末尾に終了行を必ず出力:
  - 例: `[RUN END] 2026-03-30 15:31:12 +0900`
  - 例: `[EXIT CODE] 1`
- 実装は `main.py` で以下の順:
1. `start_at = now`
2. `run()` 実行して `exit_code` 受け取り
3. `finally` で `end_at` と `exit_code` を出力
- 例外で `run()` が値を返せなかった場合も、`exit_code=1` を補完して記録する。

### 5. 同僚に渡すための運用メッセージ

- 実行の最後に、Terminal とログ両方へ次を出す:
  - `ログ保存先: <絶対パス>`
  - `不具合調査を頼むときは、この .log ファイルをそのまま送ってね`
- 同僚への案内は「フォルダ」より「ファイル単位」を基本にする（送付ミス防止）。
- もし複数回実行した場合は「対象時刻のファイル名（YYYYMMDD_HHMMSS）」を指定してもらう運用にする。

### 6. 変更対象（実装フェーズ想定）

- `main.py`（起動時のログ初期化、開始/終了行、終了コード記録）
- `app/logging/tee_logger.py`（新規: 二重出力ストリーム）
- `tests/` 配下のログ機能テスト（新規）

### 7. テスト観点

- ログファイル作成:
  - 実行ごとに `logs/YYYYMMDD/` に1ファイル作成される。
  - ファイル名に `YYYYMMDD_HHMMSS` と `pid` が含まれる。
- 同時出力:
  - `stdout` 出力が Terminal とファイルで同一内容になる。
  - `stderr` 出力も Terminal とファイルで同一内容になる。
- 例外/終了コード:
  - 正常終了で `[EXIT CODE] 0` が出る。
  - `MenuInputError` など既存エラー系で既存終了コード（`1/2/130`）が維持される。
  - 未ハンドル例外時に `traceback` と `[EXIT CODE] 1` が残る。
- 時刻記録:
  - `[RUN START]` と `[RUN END]` が両方ある。
  - `RUN END >= RUN START` になっている。
- 既存回帰:
  - 既存機能の標準出力メッセージ（例: トークン更新メッセージ、メニュー表示）が改変されていない。

## オーナーメモ

- 使い方が簡単で、トラブル時にログ回収しやすい形が理想。
- 既存の表示体験（Terminal 出力）は壊さない。
