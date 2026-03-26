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

- `main.py` は最終的に「起動入口」と「`SystemExit` への接続」だけを担当する薄いファイルにする
- メニュー項目ごとの実処理は、`action_id` ごとに独立したアクションモジュールへ逃がす
- freee API 呼び出しはアクションの中に直書きせず、`client` 層に寄せる
- メニュー表示と選択制御は `menu` 層に閉じ込め、アクション実行の詳細を知らない状態にする
- 新しい選択肢を増やすときは、基本的に「アクションを 1 個追加して登録する」だけで済む形を目指す
- `menu` と `action` の境界は `MenuItem` と `ActionDefinition` を分けて明確にする
- 共通コンテキストは `app/context.py` に置き、`actions` と `clients` の循環依存を避ける

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
   - `SystemExit` への接続
2. `bootstrap` 層
   - 実行順の組み立て
   - 例外を終了コードへ寄せる薄い変換
3. `auth/token` 層
   - 認証、リフレッシュ、トークン保存、設定ロード
4. `menu` 層
   - メニュー描画、キー入力、選択確定
5. `action/client` 層
   - `action`: 選択された機能のユースケース実行
   - `client`: freee API との通信共通化

### 2. 依存方向を一方通行にする

依存は次の向きだけに揃えます。

`main.py -> bootstrap -> auth / menu / actions -> clients`

さらに、共通コンテキストは `app/context.py` に置いて、`actions` と `clients` のどちらからも参照できるようにします。これで `actions/context.py` が `clients` の型を参照して循環依存になりやすい形を避けます。

### 3. メニュー追加は「登録」で完結させる

新しい選択肢を足すたびに中央の巨大 `if` 文を増やすのではなく、`action_id` と実行関数をレジストリへ登録する方式にします。

これで追加時の作業は次の流れに揃えられます。

1. 新しいアクションモジュールを作る
2. そのアクションをレジストリへ登録する
3. メニュー項目へ変換して表示対象へ載せる

## 詳細設計

### 想定ディレクトリ構成

```text
.
├── main.py
└── app/
    ├── __init__.py
    ├── bootstrap.py
    ├── context.py
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

### 実行フロー

```text
main.py
  -> bootstrap.run() -> int
    -> config / auth を実行
    -> AppContext を構築
    -> registry.to_menu_items() で MenuItem 一覧を作る
    -> menu.controller が action_id を返す
    -> registry.execute() が handler を実行する
    -> 終了コードを返す
  -> raise SystemExit(code)
```

## 各モジュールの責務

#### `main.py`

- 本当に薄くする
- やることは `bootstrap.run()` を呼んで `SystemExit(code)` へつなぐだけ
- 業務ロジックやメニュー定義は置かない

#### `app/bootstrap.py`

- アプリ全体の実行順を組み立てる
- `run() -> int` を公開する
- 認証フロー完了後に `AppContext` を組み立て、メニューを起動する
- 内部では各層の例外を受け取り、終了コードへ寄せる薄い変換責務を持つ

#### `app/context.py`

- `AppContext` のような、アプリ全体の共通依存を束ねるデータ構造を置く
- `actions` と `clients` の中間に置くことで、型参照による循環依存を避ける
- `refresh_token` は持たせず、アクション実行中のトークン更新責務を `auth` 層へ漏らさない

#### `app/config.py`

- 環境変数読み込み
- `AppConfig` の構築
- 設定値の検証

#### `app/auth/oauth_service.py`

- 認可コード交換
- リフレッシュトークン更新
- authorize URL 生成
- OAuth レスポンス検証
- API 認証エラーを受けた時の再認証判断材料を返す

#### `app/auth/token_store.py`

- `token.json` の読み書き
- ファイル存在確認
- JSON 構造検証

#### `app/menu/*`

- `controller.py`: メニュー表示ループ、選択決定
- `renderer.py`: 表示文字列と再描画だけを担当
- `input_reader.py`: `↑/↓/Enter/Ctrl+C/Ctrl+D` の解釈
- `models.py`: `MenuItem` など UI 用データ構造

ポイントは、`menu` 層では「何の API を叩くか」を知らないことです。知るのは `MenuItem` の `label` と `action_id` までに留めます。

#### `app/actions/*`

- 各メニュー機能の本体
- 1 アクション = 1 モジュールを基本にする
- `print_access_token.py` のような小さいものも、将来の統一感のためここへ置く
- `AppContext` を受け取り、必要な `client` を使ってユースケースを実行する

#### `app/actions/registry.py`

- `action_id` と実行関数の対応表を持つ
- 重複登録や未登録をここで検知する
- `ActionDefinition` から `MenuItem` を組み立てる変換関数を持つ
- `menu` 層へは `list[MenuItem]` だけを渡す

#### `app/clients/*`

- freee API との HTTP 通信を共通化する
- ベース URL、ヘッダ、タイムアウト、エラー整形をまとめる
- アクション側は「API をどう呼ぶか」ではなく「何をしたいか」を書ける状態にする

## データ構造

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

#### `AppContext`

```python
@dataclass(frozen=True)
class AppContext:
    config: AppConfig
    access_token: str
    api_client: FreeeApiClient
    debug_mode: bool = False
```

- アクション実行に必要な共通依存を 1 つに束ねる
- これで `execute_menu_action(action_id, access_token, config, timeout, ...)` みたいなシグネチャ崩壊を防ぐ
- `refresh_token` は持たせない。更新責務は `auth` 層へ閉じる
- 将来 `company_id` や `employee_id` を持たせる余地もある

#### `ActionDefinition`

```python
from collections.abc import Callable

ActionHandler = Callable[[AppContext], int]

@dataclass(frozen=True)
class ActionDefinition:
    action_id: str
    menu_label: str
    handler: ActionHandler
    description: str | None = None
    debug_only: bool = False
```

- メニュー表示に必要な情報と実行ハンドラをまとめる
- レジストリの最小単位になる
- `debug_only` を持たせると、`access_token` 表示のような検証用機能を通常機能と分けやすい

### メニューアクション登録方式

今回の肝です。結論としては「静的レジストリ方式」を採用します。

#### 採用方式

```python
ACTIONS = (
    ActionDefinition(
        action_id="print_access_token",
        menu_label="あ、いや、アクセストークン取得までいけるか見たかっただけ",
        handler=print_access_token_action,
        debug_only=True,
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
- `debug_only=True` の項目は `debug_mode` 条件を満たす時だけ `MenuItem` 化する

#### `menu` と `action` の境界

- `menu` 層は `list[MenuItem]` を受け取り、選択された `action_id` を返すだけ
- `actions` 層は `list[ActionDefinition]` を持ち、`handler` の実行責務を持つ
- `registry.to_menu_items(definitions, *, debug_mode)` が `ActionDefinition` から `MenuItem` を組み立てる
- `bootstrap` がその変換を実行して、`menu.controller` へ渡す

この分け方にしておくと、`menu` は表示と選択だけに集中できて、「どんなアクションがあるか」の知識を持ちません。

### アクション実行フロー

```text
main.py
  -> bootstrap.run()
    -> 認証またはリフレッシュ成功
    -> AppContext を構築
    -> registry.to_menu_items() でメニュー項目一覧を作る
    -> menu.controller が選択結果の action_id を返す
    -> registry.execute(action_id, context) が handler を引いて実行する
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
- レスポンス本文が `dict` / `list` / 空のいずれでも扱える共通返却

#### 例

```python
@dataclass(frozen=True)
class ApiResponse:
    status_code: int
    headers: Mapping[str, str]
    body: dict[str, Any] | list[Any] | None


class FreeeApiClient:
    def __init__(self, access_token: str, timeout_seconds: int = 30) -> None: ...

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> ApiResponse: ...
    def post(self, path: str, *, json_body: dict[str, Any] | None = None) -> ApiResponse: ...
```

#### アクション側のイメージ

```python
def fetch_today_attendance_action(context: AppContext) -> int:
    response = context.api_client.get("/api/1/attendance")
    print_attendance_summary(response.body)
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
- API 認証エラー時は `ApiAuthenticationError` で上位へ返し、必要なら `bootstrap` から `auth` 層へ再認証導線をつなぐ
- 最終的な終了コード変換は `bootstrap.run() -> int` に寄せ、`main.py` は `SystemExit` へつなぐだけにする

#### 例外責務マップ

- `menu/controller.py`, `menu/input_reader.py`: `MenuEnvironmentError`, `MenuInputError`, `MenuCancelled`
- `actions/registry.py`: `ActionRegistrationError`, `UnknownActionError`
- `actions/*.py`: `ActionExecutionError`
- `clients/freee_api_client.py`: `ApiConnectionError`, `ApiResponseError`, `ApiAuthenticationError`
- `auth/oauth_service.py`: `OAuthTokenError`
- `auth/token_store.py`: `TokenStoreError`
- `config.py`: `ConfigError`

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
- `ActionDefinition.debug_only=True` の項目として扱う
- たとえば `DEBUG_MODE=1` のような条件を満たした時だけメニューへ出す設計にしておく
- 将来的には `show_masked_access_token` 的な置き換えも検討する

### テストしやすさを意識した設計ポイント

#### 単体テストしやすい単位

- `registry`: 重複登録・未登録検知、`to_menu_items()` の変換
- `menu.input_reader`: キー入力解釈
- `client`: エラー変換、`ApiResponse` 返却
- `action`: context を渡した時の戻り値と例外
- `bootstrap`: 正常系の実行順、終了コード変換

#### テスト観点

- アクション追加時に、既存メニューが壊れないか
- 未登録 `action_id` を選んだ時に安全に失敗するか
- API 失敗時に UI 層まで例外責務が漏れないか
- `main.py` の変更が最小に保たれているか
- `debug_only` 項目が通常モードで出ないか

## 段階的移行方針

いきなり全部分割せず、次の順番で進めるのが安全です。

### Step 1. 例外・終了コード・データ構造を外出しする

最初にやるのは大きな処理移動ではなく、共通定義の分離です。

- `errors.py`
- `exit_codes.py`
- `menu/models.py`
- `context.py`

これで `main.py` の見通しが少し改善します。

### Step 2. メニュー層を `menu` パッケージへ移す

次に、すでにまとまりがあるメニュー処理を切り出します。

- `ensure_menu_terminal`
- `raw_stdin_mode`
- `read_menu_key`
- `render_menu`
- `select_menu_action`

ここは API 通信と独立しているので、比較的安全に移せます。

### Step 3. アクションレジストリを hybrid で導入する

この段階では、いきなり既存分岐を消さずに進めます。

- `ActionDefinition`
- `AppContext`
- `registry.to_menu_items()`
- `registry.execute_registered(action_id, context)`
- `execute_menu_action()` は「登録済みならレジストリ実行、未登録なら既存 `if` 分岐へ fallback」の暫定構成にする

まずは既存の `print_access_token` だけ登録すれば十分です。全部を一度に移さず、1 アクションずつ登録方式へ寄せます。

### Step 4. 既存アクションを順番にレジストリへ移し、fallback を縮小する

- 追加済みの新アクションは最初から登録方式のみで実装する
- 既存アクションは動作確認しながら 1 件ずつ `if` 分岐を削る
- 最終的に fallback が空になった段階で旧 `execute_menu_action()` を取り除く

### Step 5. OAuth / token 保存処理を `auth` パッケージへ移す

次に認証系をまとめます。

- `load_config`
- `build_authorize_url`
- `post_token`
- `exchange_auth_code`
- `refresh_access_token`
- `save_tokens`
- `load_refresh_token`

これで `main.py` はかなり薄くなります。

### Step 6. API クライアントを導入して、新規アクションは必ずそこ経由にする

ここで初めて「別 API を叩く機能」の土台を作ります。

- 既存処理は無理に全部置き換えなくてよい
- 今後追加する API 機能は必ず `client` 経由にする
- 必要なら後で既存の OAuth 通信も寄せる

### Step 7. `bootstrap.run()` を作って `main.py` を薄くする

最後に配線を整えます。

- `main.py` は引数取得と `SystemExit` のみ
- 実行フローは `bootstrap` に集約

## 追加時の実装ルール案

将来メニューを増やすときの迷いを減らすため、ルールも先に決めておきます。

### 新しいメニュー追加時にやること

1. `app/actions/<action_name>.py` を追加する
2. `handler(context: AppContext) -> int` を実装する
3. `registry.py` に `ActionDefinition` を追加する
4. 必要なら `clients/` に API 呼び出し関数を追加する

### やってはいけないこと

- `main.py` に直接 API 呼び出しを書く
- `menu` 層で API 通信を始める
- アクションごとに `requests` 設定をバラバラに持つ
- 新規アクションの追加時に巨大な `if/elif` を再導入する
- アクションが自前で `refresh_token` を扱い始める

## この設計で得たい状態

- `main.py` をほとんど触らずに機能追加できる
- メニュー表示の修正と API 実装の修正が別々に進められる
- 将来、メニューが 10 件以上になっても見通しを保てる
- 失敗時に「どの層の責務で落ちたか」が分かりやすい
- 実装レビューで「登録漏れ」「責務混在」を見つけやすい

## 今回の設計確定事項

- `main.py` は最終的に入口専用へ寄せる
- `bootstrap.run() -> int` を実行フローの中心にする
- 共通コンテキストは `app/context.py` に置き、`actions` と `clients` の循環依存を避ける
- メニューアクションは静的レジストリ方式で登録する
- `menu` は `MenuItem`、`actions` は `ActionDefinition` を扱い、境界を分ける
- 各アクションは `AppContext` を受け取る独立ハンドラとして実装する
- `refresh_token` の責務は `auth` 層に閉じる
- freee API 呼び出しは `client` 層へ集約し、戻り値は `ApiResponse` でラップする
- 移行は hybrid 段階を挟みながら進め、一気に全面書き換えしない

## レビュー観点

- 新しい API 機能を 1 件追加する時、変更箇所が `main.py` に波及しないか
- `action_id` の登録漏れや重複を検知できるか
- `menu` 層が業務知識を持っていないか
- `client` 層に HTTP 共通化が寄っているか
- `debug_only` 項目の表示条件が明確か
- 段階移行の途中でも既存の認証フローを壊さないか

## オーナー向け要約

- 今回の設計では、`main.py` を薄くして、メニュー追加や API 追加のたびに中央ファイルが太る状態を止めます
- メニュー項目ごとの処理はアクションとして独立させ、登録ベースで増やせる形にします
- `menu` と `action` の間には `MenuItem` / `ActionDefinition` の境界を置き、責務を混ぜません
- API 呼び出しはクライアント層へまとめ、認証ヘッダやエラー処理の散らばりを防ぎます
- いきなり全面移植せず、hybrid 段階を挟みながら安全に移行します

## レビュー

### 修正必須点

#### 1. `ActionContext` の `api_client` 参照が循環依存を生むリスク

対応内容: `ActionContext` を `actions/context.py` に置く案をやめて、共通コンテキストを `app/context.py` の `AppContext` へ移しました。これで `actions` と `clients` のどちらからも参照しやすくなり、型参照由来の循環依存リスクを下げています。

#### 2. `refresh_token` を `ActionContext` に常時持たせるべきか検討不足

対応内容: `AppContext` から `refresh_token` を外しました。トークン更新責務は `auth/oauth_service.py` と `auth/token_store.py` に閉じ、アクション中に認証エラーが起きた場合は `ApiAuthenticationError` を上位へ返す方針へ修正しました。

#### 3. `menu` 層が `ActionDefinition` の `menu_label` に依存する設計が曖昧

対応内容: `MenuItem` と `ActionDefinition` の境界を明示し、`registry.to_menu_items()` を追加する方針へ修正しました。`menu` 層は `list[MenuItem]` だけを受け取り、`bootstrap` が変換を担当する流れにしています。

#### 4. 段階的移行の Step 3 で既存処理が壊れる危険が高い

対応内容: 段階移行を見直し、Step 3 を hybrid 導入へ変更しました。登録済みアクションはレジストリ実行、未登録アクションは既存 `if` 分岐へ fallback する暫定構成を許容し、Step 4 で段階的に fallback を削る流れへ直しています。

#### 5. `FreeeApiClient.get() / post()` の戻り値が `dict[str, Any]` 固定なのは制約がキツい

対応内容: 戻り値を `ApiResponse` ラッパーへ変更しました。`status_code` / `headers` / `body` をまとめて扱える形にし、`body` は `dict` / `list` / `None` を許容する設計へ修正しました。

### 軽微な指摘

#### 6. `bootstrap.py` が "orchestrator" と書いてるけど、責務定義がざっくりしすぎている

対応内容: `bootstrap.run() -> int` を明記し、`main.py` は `SystemExit` 接続だけを担当する形へ整理しました。

#### 7. 例外階層が充実してる割に、各例外が「どの層で投げられるか」の対応表がない

対応内容: 例外責務マップを追加し、どのモジュールがどの例外を投げるかを一覧で見えるようにしました。

#### 8. `access_token` 生表示の扱いが「将来検討」止まりで、セキュリティリスクが放置されてる

対応内容: `ActionDefinition.debug_only` を追加し、`DEBUG_MODE=1` のような条件でのみ表示対象に載せる設計を明記しました。

#### 9. ディレクトリ構成で `app/config.py` と `app/bootstrap.py` の配置が並列になってるけど、依存関係が不明

対応内容: 実行フロー図を追加し、`bootstrap.run()` が `config` / `auth` を呼んでから `AppContext` を構築する流れを明記しました。

---

## LGTM

### 前回レビュー対応確認

前回指摘した修正必須点 1-5 と軽微な指摘 6-9 はすべて対応済みです。

- `AppContext` を `app/context.py` に配置して循環依存リスクを解消
- `refresh_token` を `AppContext` から外して責務を `auth` 層に閉じる方針へ変更
- `MenuItem` と `ActionDefinition` の境界を分離し、`registry.to_menu_items()` で変換する設計へ修正
- hybrid 導入方式を追加して段階移行の安全性を向上
- `ApiResponse` ラッパーを導入して戻り値の柔軟性を向上
- `bootstrap.run() -> int` を明記して責務を明確化
- 例外責務マップを追加
- `ActionDefinition.debug_only` を追加してセキュリティリスクを軽減
- 実行フロー図を追加して依存関係を明確化

### 設計品質評価

この設計は、今後のメニュー追加と API 追加に十分耐えられる構造になっています。

- 層の責務分離が明確
- メニューアクション登録方式がシンプルで拡張しやすい
- 段階的移行方針が具体的で安全
- エラーハンドリングの方針が一貫している
- テスト観点も整理されている

実装へ進んで問題ありません。相棒、いい設計だよw

レビュワー: Claude Code
