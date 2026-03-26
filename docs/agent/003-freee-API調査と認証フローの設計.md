# 003 freee API 調査と認証フローの設計

## 要望

- freee Public API のドキュメント (https://developer.freee.co.jp/reference) を参照する
- 以下の API の流れを調査する
    - アクセストークンを手に入れる
    - なんらか、簡単な API を叩く
- 今回は設計ノートまで。実装には入らない。

## 詳細設計

### 参考にしたドキュメント

- [freee Developers Community - API リファレンス](https://developer.freee.co.jp/reference)
- [アクセストークンを取得する](https://developer.freee.co.jp/startguide/getting-access-token)
- [freee API へ GET/POST リクエストを送信する](https://developer.freee.co.jp/startguide/getpost)
- [トークンの有効期限について](https://developer.freee.co.jp/reference/faq/token_lifetime)

### 前提知識

freee API は OAuth 2.0 (Authorization Code Grant) を採用してるよ。
ユーザが freee のログイン画面で認証して、アプリに権限を許可する流れになる。

API のベース URL は `https://api.freee.co.jp/` で、HTTPS のみ対応。

### 環境変数 (.env)

以下の値を `.env` に入れる想定。

| 変数名 | 説明 |
|---|---|
| `FREEE_CLIENT_ID` | freee アプリの Client ID |
| `FREEE_CLIENT_SECRET` | freee アプリの Client Secret |
| `FREEE_REDIRECT_URI` | コールバック URL (例: `urn:ietf:wg:oauth:2.0:oob`) |
| `FREEE_ACCESS_TOKEN` | 取得したアクセストークン |
| `FREEE_REFRESH_TOKEN` | 取得したリフレッシュトークン |
| `FREEE_COMPANY_ID` | 対象の事業所 ID |

Client ID と Client Secret は [freee 開発者ページ](https://app.secure.freee.co.jp/developers/applications) でアプリを作ると発行される。

### OAuth 認証フロー

#### ステップ 1: 認可コードの取得

ブラウザで以下の URL を開く。ユーザがログインして事業所を選んで許可すると、認可コードが返ってくる。

```
https://accounts.secure.freee.co.jp/public_api/authorize
    ?response_type=code
    &client_id={FREEE_CLIENT_ID}
    &redirect_uri={FREEE_REDIRECT_URI}
    &state={ランダム文字列}
    &prompt=select_company
```

パラメータの説明:

| パラメータ | 値 | 説明 |
|---|---|---|
| `response_type` | `code` | 固定値。認可コードを要求する |
| `client_id` | (アプリの Client ID) | アプリ登録時に発行されたもの |
| `redirect_uri` | (コールバック URL) | URL エンコード済みで指定する |
| `state` | (ランダム文字列) | CSRF 対策用。リダイレクト時にそのまま返ってくる |
| `prompt` | `select_company` | 事業所選択画面を表示する (任意) |

認可が成功すると、`redirect_uri` に `?code={認可コード}&state={state}` が付いてリダイレクトされる。

#### ステップ 2: アクセストークンの取得

認可コードを使って、トークンエンドポイントに POST する。

- エンドポイント: `POST https://accounts.secure.freee.co.jp/public_api/token`
- Content-Type: `application/x-www-form-urlencoded`

リクエストボディ:

| パラメータ | 値 |
|---|---|
| `grant_type` | `authorization_code` |
| `client_id` | (アプリの Client ID) |
| `client_secret` | (アプリの Client Secret) |
| `code` | (ステップ 1 で取得した認可コード) |
| `redirect_uri` | (コールバック URL) |

レスポンス例:

```json
{
    "access_token": "xxxxxxxxxxxx",
    "token_type": "bearer",
    "expires_in": 21600,
    "refresh_token": "yyyyyyyyyyyy",
    "scope": "read write default_read",
    "company_id": 12345
}
```

レスポンスに含まれる `scope` は、アプリに許可された操作範囲を表す。freee API ではアプリ作成時にスコープが決まるため、認可リクエスト時に `scope` パラメータで絞り込む必要は基本的にない。

ここで取れた `access_token`, `refresh_token`, `company_id` を `.env` に保存する。

#### ステップ 3: トークンのリフレッシュ

アクセストークンの有効期限は 6 時間、リフレッシュトークンは 90 日。

- エンドポイント: `POST https://accounts.secure.freee.co.jp/public_api/token`
- Content-Type: `application/x-www-form-urlencoded`

リクエストボディ:

| パラメータ | 値 |
|---|---|
| `grant_type` | `refresh_token` |
| `client_id` | (アプリの Client ID) |
| `client_secret` | (アプリの Client Secret) |
| `refresh_token` | (保存してあるリフレッシュトークン) |

注意点:
- リフレッシュトークンは 1 回しか使えない。新しいアクセストークンと一緒に新しいリフレッシュトークンも返ってくるので、毎回上書き保存する必要がある
- アクセストークンの有効期限は 6 時間。期限が切れた API リクエストは 401 で拒否される。リフレッシュトークンが有効 (90 日以内) であれば、アクセストークンの期限切れ後でもリフレッシュ可能。ただしリフレッシュトークン自体が期限切れの場合は認可コードの再取得が必要になる
- リフレッシュトークンの有効期限 (90 日) が切れた場合は、ステップ 1 からやり直す必要がある

### 簡単な API を叩く例

全リクエスト共通で、以下のヘッダーが必要。

```
Authorization: Bearer {access_token}
Content-Type: application/json
```

#### ユーザ情報取得

- エンドポイント: `GET https://api.freee.co.jp/api/1/users/me`
- パラメータ: `?companies=true` を付けると、所属する事業所の一覧も取れる

ログインユーザの情報と、紐づいてる事業所の一覧を返してくれるので、初回に叩くのにちょうどいい。

#### 事業所一覧の取得

- エンドポイント: `GET https://api.freee.co.jp/api/1/companies`

ユーザに紐づく全事業所のリストが返ってくる。ここで取れる `id` が `company_id` になる。

#### 事業所の詳細取得

- エンドポイント: `GET https://api.freee.co.jp/api/1/companies/{company_id}`
- パラメータ: `?details=true` を付けると、勘定科目・税区分・品目・取引先・口座情報を一括取得できる

### Python 実装イメージ

requests ライブラリを使った実装イメージをメモっとく。これはあくまで設計段階のメモで、実際の実装は次回やる。

#### 認可 URL の生成

```python
import secrets
from urllib.parse import urlencode

def build_authorize_url(client_id: str, redirect_uri: str) -> tuple[str, str]:
    """認可 URL を生成します。state 文字列も一緒に返します。"""
    state = secrets.token_urlsafe(32)
    params = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "prompt": "select_company",
    })
    url = f"https://accounts.secure.freee.co.jp/public_api/authorize?{params}"
    return url, state
```

#### アクセストークンの取得

```python
import requests

TOKEN_URL = "https://accounts.secure.freee.co.jp/public_api/token"

def get_access_token(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    """認可コードからアクセストークンを取得します。"""
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    })
    resp.raise_for_status()
    return resp.json()
```

#### トークンのリフレッシュ

```python
def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> dict:
    """リフレッシュトークンで新しいアクセストークンを取得します。
    返り値の refresh_token は必ず保存してください (1 回限り有効) 。
    """
    resp = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    })
    resp.raise_for_status()
    return resp.json()
```

#### API 呼び出し

```python
API_BASE = "https://api.freee.co.jp"

def get_user_me(access_token: str) -> dict:
    """ログインユーザの情報を取得します。"""
    resp = requests.get(
        f"{API_BASE}/api/1/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        params={"companies": "true"},
    )
    resp.raise_for_status()
    return resp.json()

def get_companies(access_token: str) -> dict:
    """事業所一覧を取得します。"""
    resp = requests.get(
        f"{API_BASE}/api/1/companies",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json()
```

### 実装するときの注意メモ

- リフレッシュトークンは 1 回限りなので、リフレッシュしたら `.env` (またはトークン保存先) を即座に上書きする仕組みが要る
- `state` パラメータはちゃんと検証する (CSRF 対策)
- `redirect_uri` は freee のアプリ設定で登録したものと完全一致させないとエラーになる
- 開発用なら `urn:ietf:wg:oauth:2.0:oob` をコールバック URL にすると、ブラウザに認可コードが表示される方式になって便利ｗ
- トークンの有効期限 (6 時間) を意識して、期限切れ前にリフレッシュするロジックを入れる
- エラーハンドリングの方針:
    - 401 Unauthorized (トークン期限切れ) → 自動リフレッシュしてリトライする
    - 403 Forbidden (権限不足) → エラーメッセージを出して処理を中断する
    - 429 Too Many Requests (レートリミット) → リトライ間隔を空けて再試行する

## レビュー

レビュワー: Claude Code (2026-03-25)

### 総評

全体的にとてもよく書けてる♡ OAuth フローのステップ、エンドポイント URL、パラメータ、Python 実装イメージ、どれも freee 公式ドキュメントと一致してて正確。スコープ (認証フロー + 簡単な API 呼び出し) に対して過不足なくまとまってるよ。

以下、いくつか指摘があるので対応よろしくｗ

### 指摘事項

#### 1. [要修正] トークンリフレッシュの注意書きが不正確

ステップ 3 の注意点に「古いアクセストークンがまだ有効なうちにリフレッシュする必要がある (期限切れてからだと 401 になる可能性あり)」とあるけど、これは誤解を招く表現。

freee の公式ドキュメントによると、リフレッシュトークン自体が有効 (90 日以内) であれば、アクセストークンが期限切れでもリフレッシュは可能。401 になるのは以下のケース:

- リフレッシュトークン自体の有効期限 (90 日) が切れた場合
- リフレッシュトークンを 2 回以上使い回した場合

修正案: 「アクセストークンの有効期限は 6 時間。期限が切れた API リクエストは 401 で拒否される。リフレッシュトークンが有効 (90 日以内) であれば、アクセストークンの期限切れ後でもリフレッシュ可能。ただしリフレッシュトークン自体が期限切れの場合は認可コードの再取得が必要になる」

対応: ステップ 3 の注意点を修正案のとおり書き換えた。

#### 2. [要修正] リフレッシュトークン期限切れ時の再認証フローへの言及がない

リフレッシュトークンが 90 日で切れた場合、認可コードの取得からやり直す必要がある。これは実装時にハマりやすいポイントなので、ステップ 3 の注意点に「リフレッシュトークンの有効期限 (90 日) が切れた場合は、ステップ 1 からやり直す必要がある」旨を追記してほしい。

対応: ステップ 3 の注意点に追記した。

#### 3. [軽微] エラーハンドリングの方針が未記載

Python 実装イメージで `resp.raise_for_status()` を使ってるけど、設計メモとして以下のエラーケースにどう対処するかの方針があると実装がスムーズになると思う:

- 401 Unauthorized (トークン期限切れ) → 自動リフレッシュ → リトライ
- 403 Forbidden (権限不足)
- 429 Too Many Requests (レートリミット)

設計段階のメモとして、少なくとも 401 時の自動リフレッシュ&リトライの方針だけでも書いておくと、実装者が助かるはず。

対応: 「実装するときの注意メモ」にエラーハンドリング方針 (401/403/429) を追記した。

#### 4. [軽微] `scope` パラメータの説明がない

トークンレスポンス例に `"scope": "read write default_read"` が含まれてるけど、この `scope` が何を意味するかの説明がない。認可リクエスト時に `scope` パラメータを指定して権限を絞れるかどうかも、ひとこと触れておくとよさそう。

対応: ステップ 2 のレスポンス例の後に scope の説明を追記した。

### まとめ

- 要修正: 2 件 (指摘 1, 2) → 対応済み
- 軽微: 2 件 (指摘 3, 4) → 対応済み

全件対応したので LGTM♡

### 2nd レビュー (2026-03-26)

レビュワー: Claude Code

前回の指摘 4 件 (要修正 2 件・軽微 2 件) の対応内容を確認した。

- 指摘 1: トークンリフレッシュの注意書き → 修正案どおりに正確な記述に書き換わってる。「リフレッシュトークンが有効であればアクセストークン期限切れ後でもリフレッシュ可能」という正しい説明になってる。OK
- 指摘 2: リフレッシュトークン期限切れ時の再認証フロー → ステップ 3 の注意点にちゃんと「ステップ 1 からやり直す必要がある」が追記されてる。OK
- 指摘 3: エラーハンドリング方針 → 401 (自動リフレッシュしてリトライ) / 403 (中断) / 429 (リトライ間隔を空けて再試行) の 3 パターンが具体的で実装しやすい。OK
- 指摘 4: scope の説明 → 「アプリ作成時にスコープが決まるため、認可リクエスト時に scope パラメータで絞り込む必要は基本的にない」という freee 仕様に沿った正確な説明。OK

新たな問題なし。LGTM♡
