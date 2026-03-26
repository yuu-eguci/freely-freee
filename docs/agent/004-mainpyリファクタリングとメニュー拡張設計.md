# 004 main.py リファクタリングとメニュー拡張設計

## このノートの位置づけ

- 本ノートは `003-アクセストークン取得後のコンソールメニュー設計` の次段として、`main.py` を今後の機能追加に耐えられる構造へ整理するための詳細設計です
- 今回は設計更新だけに集中し、コード実装はまだ行いません
- 目的は「メニュー項目を増やしても `main.py` が太らないこと」と「選択肢ごとに別 API を呼んでも責務が混ざらないこと」です

## 要望

- `main.py` が長くなってきたので、今後の機能追加に耐えられる構成へリファクタリングしたい
- 今後はメニュー選択肢をどんどん増やし、各選択肢ごとに別 API を呼び出したい
- そのため、選択肢追加と API 実装追加がしやすいコード構造を設計したい

## 今回やること

- 現在の `main.py` の責務を分解する設計を作る
- メニュー項目ごとに処理を独立して追加できる構造を設計する
- モジュール分割、責務分離、メニューアクション登録方式、エラーハンドリング、段階的移行方針まで具体化する

## 先に結論

- `main.py` は最終的に「起動入口」と「終了コードの返却」だけを担当する薄いファイルにする
- メニュー項目ごとの実処理は、`action_id` ごとに独立したアクションモジュールへ逃がす
- freee API 呼び出しはアクションの中に直書きせず、`client` 層に寄せる
- メニュー表示と選択制御は `menu` 層に閉じ込め、アクション実行の詳細を知らない状態にする
- 新しい選択肢を増やすときは、基本的に「アクションを 1 個追加して登録する」だけで済む形を目指す

## 現状の課題

### 1. `main.py` に責務が集まりすぎている

いまの `main.py` には、ざっくり次の責務が同居しています。

- 引数解析
- 環境変数ロード
- OAuth 認証 / リフレッシュ
- `token.json` の読み書き
- メニュー描画
- キー入力解釈
- アクション実行
- 例外から終了コードへの変換

この状態だと、たとえば「勤怠打刻 API を追加したい」となっただけで `main.py` を触る範囲が広くなり、レビューもしづらくなります。

### 2. メニューアクションが文字列分岐になっている

現状は `execute_menu_action(action: str, access_token: str)` の中で `if action == ...` を増やしていく形です。

この方式は最初は軽いのですが、選択肢が 5 件、10 件と増えたあたりで次の問題が出ます。

- 分岐が長くなる
- 各アクションに必要な引数が増えるとシグネチャが崩れる
- どのアクションが登録済みなのか見通しづらい
- 未登録や重複登録を検知しづらい

### 3. API 呼び出しの共通化ポイントがまだ曖昧

今後は「選択肢ごとに別 API を叩く」前提なので、アクションごとに `requests.get()` / `requests.post()` を直接書き始めると、認証ヘッダ、タイムアウト、レスポンス検証、エラー整形が各所に散ります。

ここを早めに揃えておかないと、あとで API ごとの癖が混ざって直しづらくなります。

## 設計方針

### 1. 層を 5 つに分ける

役割を次の 5 層に分けます。

1. `entrypoint` 層
   - 起動入口
   - 例外を終了コードへ変換
   - 他の層をつなぐだけ
2. `auth/token` 層
   - 認証、リフレッシュ、トークン保存、設定ロード
3. `menu` 層
   - メニュー描画、キー入力、選択確定
4. `action` 層
   - 選択された機能のユースケース実行
5. `client` 層
   - freee API との通信共通化

### 2. 依存方向を一方通行にする

依存は次の向きだけに揃えます。

`entrypoint -> auth/menu/action -> client`

逆向き依存は作りません。たとえば `client` が `menu` を知らない、`menu` が `client` を知らない、という形です。

### 3. メニュー追加は「登録」で完結させる

新しい選択肢を足すたびに中央の巨大 `if` 文を増やすのではなく、`action_id` と実行関数をレジストリへ登録する方式にします。

これで追加時の作業は次の流れに揃えられます。

1. 新しいアクションモジュールを作る
2. そのアクションをレジストリへ登録する
3. メニュー定義に 1 行追加する

## 詳細設計

### 想定ディレクトリ構成

```text
.
├── main.py
└── app/
    ├── __init__.py
    ├── bootstrap.py
    ├── config.py
    ├── exit_codes.py
    ├── errors.py
    ├── auth/
    │   ├── __init__.py
    │   ├── oauth_service.py
    │   └── token_store.py
    ├── menu/
    │   ├── __init__.py
    │   ├── controller.py
    │   ├── renderer.py
    │   ├── input_reader.py
    │   └── models.py
    ├── actions/
    │   ├── __init__.py
    │   ├── registry.py
    │   ├── context.py
    │   ├── base.py
    │   ├── print_access_token.py
    │   ├── punch_clock_in.py
    │   └── fetch_today_attendance.py
    └── clients/
        ├── __init__.py
        ├── freee_api_client.py
        └── attendance_client.py
```

ファイル名はたたき台ですが、責務の切り分けはこの粒度を基準にします。

### 各モジュールの責務

#### `main.py`

- 本当に薄くする
- やることは `bootstrap.run()` を呼んで `SystemExit(code)` へつなぐだけ
- 業務ロジックやメニュー定義は置かない

#### `app/bootstrap.py`

- アプリ全体の実行順を組み立てる
- ざっくり言うと orchestrator の役割
- 認証フロー完了後に `ActionContext` を組み立て、メニューを起動する
- 例外を捕まえる場所ではなく、基本は例外を上へ返す

#### `app/config.py`

- 環境変数読み込み
- `AppConfig` の構築
- 設定値の検証

#### `app/auth/oauth_service.py`

- 認可コード交換
- リフレッシュトークン更新
- authorize URL 生成
- OAuth レスポンス検証

#### `app/auth/token_store.py`

- `token.json` の読み書き
- ファイル存在確認
- JSON 構造検証

#### `app/menu/*`

- `controller.py`: メニュー表示ループ、選択決定
- `renderer.py`: 表示文字列と再描画だけを担当
- `input_reader.py`: `↑/↓/Enter/Ctrl+C/Ctrl+D` の解釈
- `models.py`: `MenuItem` など UI 用データ構造

ポイントは、`menu` 層では「何の API を叩くか」を知らないことです。知るのは `action_id` までに留めます。

#### `app/actions/*`

- 各メニュー機能の本体
- 1 アクション = 1 モジュールを基本にする
- `print_access_token.py` のような小さいものも、将来の統一感のためここへ置く

#### `app/actions/registry.py`

- `action_id` と実行関数の対応表を持つ
- 重複登録や未登録をここで検知する
- メニュー定義もここ、もしくは `menu` 用定義モジュールに寄せる

#### `app/clients/*`

- freee API との HTTP 通信を共通化する
- ベース URL、ヘッダ、タイムアウト、エラー整形をまとめる
- アクション側は「API をどう呼ぶか」ではなく「何をしたいか」を書ける状態にする

### データ構造

#### `MenuItem`

```python
@dataclass(frozen=True)
class MenuItem:
    label: str
    action_id: str
    description: str | None = None
    enabled: bool = True
```

- `label`: メニュー表示名
- `action_id`: 実行対象の識別子
- `description`: 将来ヘルプ表示を増やしたいときの余地
- `enabled`: 未実装機能を見せる/隠す判断に使える余地

#### `ActionContext`

```python
@dataclass(frozen=True)
class ActionContext:
    config: AppConfig
    access_token: str
    refresh_token: str | None
    api_client: FreeeApiClient
```

- アクション実行に必要な共通依存を 1 つに束ねる
- これで `execute_menu_action(action_id, access_token, config, timeout, ...)` みたいなシグネチャ崩壊を防ぐ
- 将来 `company_id` や `employee_id` を持たせる余地もある

#### `ActionDefinition`

```python
from collections.abc import Callable

ActionHandler = Callable[[ActionContext], int]

@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    menu_label: str
    handler: ActionHandler
    description: str | None = None
```

- メニュー表示に必要な情報と実行ハンドラをまとめる
- レジストリの最小単位になる

### メニューアクション登録方式

今回の肝です。結論としては「静的レジストリ方式」を採用します。

#### 採用方式

```python
ACTIONS = (
    ActionDefinition(
        action_id="print_access_token",
        menu_label="あ、いや、アクセストークン取得までいけるか見たかっただけ",
        handler=print_access_token_action,
    ),
    ActionDefinition(
        action_id="punch_clock_in",
        menu_label="出勤打刻をする",
        handler=punch_clock_in_action,
    ),
)
```

#### この方式にする理由

- いまの規模なら、動的 import やプラグイン機構まではいらない
- どのアクションが有効かをレビュー時に一覧で確認しやすい
- IDE 補完も効きやすい
- テスト時にレジストリ単体の検証がしやすい

#### レジストリで保証したいこと

- `action_id` が重複していない
- `menu_label` が空でない
- ハンドラが callable である
- メニューへ出す順番が定義順で安定する

#### 将来の拡張余地

もし将来、機能数がかなり増えて「一覧ファイルが長い」問題が出てきたら、その時点でカテゴリ別レジストリへ分割します。

- `attendance_actions.py`
- `debug_actions.py`
- `report_actions.py`

ただし、現時点ではやりすぎなので、まずは単一レジストリで十分です。

### アクション実行フロー

```text
main.py
  -> bootstrap.run()
    -> 認証またはリフレッシュ成功
    -> ActionContext を構築
    -> registry からメニュー項目一覧を作る
    -> menu.controller が選択結果の action_id を返す
    -> registry から handler を引く
    -> handler(context) を実行
    -> int の終了コードを返す
```

この流れにすると、`menu` は選択だけ、`action` は業務処理だけ、`bootstrap` は配線だけ、という形に揃います。

### API クライアント設計

#### `FreeeApiClient` の責務

- `Authorization: Bearer ...` ヘッダ付与
- 共通タイムアウト設定
- `requests` 例外のアプリ内例外への変換
- ステータスコード異常時のメッセージ整形
- JSON レスポンスの基本検証

#### 例

```python
class FreeeApiClient:
    def __init__(self, access_token: str, timeout_seconds: int = 30) -> None: ...

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def post(self, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]: ...
```

#### アクション側のイメージ

```python
def fetch_today_attendance_action(context: ActionContext) -> int:
    payload = context.api_client.get("/api/1/attendance")
    print_attendance_summary(payload)
    return EXIT_CODE_OK
```

これならアクション実装は「ユースケース」に集中できます。

### エラーハンドリング方針

#### 例外階層

```text
AppError
├── ConfigError
├── TokenStoreError
├── OAuthTokenError
├── MenuError
│   ├── MenuEnvironmentError
│   ├── MenuInputError
│   └── MenuCancelled
├── ActionError
│   ├── ActionRegistrationError
│   ├── UnknownActionError
│   └── ActionExecutionError
└── ApiClientError
    ├── ApiConnectionError
    ├── ApiResponseError
    └── ApiAuthenticationError
```

#### 方針

- `menu` 層はメニュー由来の例外だけ投げる
- `client` 層は通信由来の例外だけ投げる
- `action` 層は「何をしようとして失敗したか」を補足して投げ直してよい
- 最終的な終了コード変換は `main.py` か `bootstrap` のごく薄い層でまとめる

#### 終了コード方針

現状の `0 / 1 / 2 / 130` は維持してよいです。

- `0`: 正常終了
- `1`: 設定、認証、トークン保存、API 実行などのアプリエラー
- `2`: メニュー入力や端末条件などの対話エラー
- `130`: ユーザー中断

ポイントは、アクション失敗を無理に細分化しないことです。まずは `1` に寄せて十分です。

### ログ・標準出力の整理

今後アクションが増えると、標準出力に何を出して、標準エラーに何を出すかが重要になります。

#### 基本ルール

- 正常系の結果表示は `stdout`
- エラーメッセージは `stderr`
- デバッグ用途の機微情報はアクションごとに明示許可された場合のみ表示

#### `access_token` 生表示の扱い

- 現在の検証用アクションとしては残してよい
- ただし debug 系アクションとして分離し、「通常機能」とは文脈を分ける
- 将来的には `show_masked_access_token` 的な置き換えを検討する

### テストしやすさを意識した設計ポイント

#### 単体テストしやすい単位

- `registry`: 重複登録・未登録検知
- `menu.input_reader`: キー入力解釈
- `client`: エラー変換
- `action`: context を渡した時の戻り値と例外
- `bootstrap`: 正常系の実行順

#### テスト観点

- アクション追加時に、既存メニューが壊れないか
- 未登録 `action_id` を選んだ時に安全に失敗するか
- API 失敗時に UI 層まで例外責務が漏れないか
- `main.py` の変更が最小に保たれているか

## 段階的移行方針

いきなり全部分割せず、次の順番で進めるのが安全です。

### Step 1. 例外・終了コード・データ構造を外出しする

最初にやるのは大きな処理移動ではなく、共通定義の分離です。

- `errors.py`
- `exit_codes.py`
- `menu/models.py`
- `actions/context.py`

これで `main.py` の見通しが少し改善します。

### Step 2. メニュー層を `menu` パッケージへ移す

次に、すでにまとまりがあるメニュー処理を切り出します。

- `ensure_menu_terminal`
- `raw_stdin_mode`
- `read_menu_key`
- `render_menu`
- `select_menu_action`

ここは API 通信と独立しているので、比較的安全に移せます。

### Step 3. アクションレジストリを導入する

この段階で `if action == ...` をやめます。

- `ActionDefinition`
- `ActionContext`
- `registry.get_menu_items()`
- `registry.execute(action_id, context)`

まずは既存の `print_access_token` だけ登録すれば十分です。

### Step 4. OAuth / token 保存処理を `auth` パッケージへ移す

次に認証系をまとめます。

- `load_config`
- `build_authorize_url`
- `post_token`
- `exchange_auth_code`
- `refresh_access_token`
- `save_tokens`
- `load_refresh_token`

これで `main.py` はかなり薄くなります。

### Step 5. API クライアントを導入して、新規アクションは必ずそこ経由にする

ここで初めて「別 API を叩く機能」の土台を作ります。

- 既存処理は無理に全部置き換えなくてよい
- 今後追加する API 機能は必ず `client` 経由にする
- 必要なら後で既存の OAuth 通信も寄せる

### Step 6. `bootstrap.run()` を作って `main.py` を薄くする

最後に配線を整えます。

- `main.py` は引数取得と `SystemExit` のみ
- 実行フローは `bootstrap` に集約

## 追加時の実装ルール案

将来メニューを増やすときの迷いを減らすため、ルールも先に決めておきます。

### 新しいメニュー追加時にやること

1. `app/actions/<action_name>.py` を追加する
2. `handler(context) -> int` を実装する
3. `registry.py` に `ActionDefinition` を追加する
4. 必要なら `clients/` に API 呼び出し関数を追加する

### やってはいけないこと

- `main.py` に直接 API 呼び出しを書く
- `menu` 層で API 通信を始める
- アクションごとに `requests` 設定をバラバラに持つ
- 新規アクションの追加時に巨大な `if/elif` を再導入する

## この設計で得たい状態

- `main.py` をほとんど触らずに機能追加できる
- メニュー表示の修正と API 実装の修正が別々に進められる
- 将来、メニューが 10 件以上になっても見通しを保てる
- 失敗時に「どの層の責務で落ちたか」が分かりやすい
- 実装レビューで「登録漏れ」「責務混在」を見つけやすい

## 今回の設計確定事項

- `main.py` は最終的に入口専用へ寄せる
- メニューアクションは静的レジストリ方式で登録する
- 各アクションは `ActionContext` を受け取る独立ハンドラとして実装する
- freee API 呼び出しは `client` 層へ集約する
- 例外は `menu` / `action` / `client` ごとに責務を分ける
- 移行は段階的に進め、一気に全面書き換えしない

## レビュー観点

- 新しい API 機能を 1 件追加する時、変更箇所が `main.py` に波及しないか
- `action_id` の登録漏れや重複を検知できるか
- `menu` 層が業務知識を持っていないか
- `client` 層に HTTP 共通化が寄っているか
- 段階移行の途中でも既存の認証フローを壊さないか

## オーナー向け要約

- 今回の設計では、`main.py` を薄くして、メニュー追加や API 追加のたびに中央ファイルが太る状態を止めます
- メニュー項目ごとの処理はアクションとして独立させ、登録ベースで増やせる形にします
- API 呼び出しはクライアント層へまとめ、認証ヘッダやエラー処理の散らばりを防ぎます
- いきなり全面移植せず、定義分離 -> メニュー分離 -> レジストリ導入 -> 認証分離 -> クライアント導入の順で安全に進めます
