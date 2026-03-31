freely-freee
===

好きに使わしてもらうぜ、 Freee を。

![](./docs/image-birds-fly.webp)

## いいとこ

- Docker 内で動作するので、 Python とか不要
- Docker だけあれば OK

## しょしんしゃむけ つかいかた

Docker を入れる

```bash
# Mac のひと
brew install --cask docker

# Windows のひと
# Windows のことはよくしらんけどこれでインストールできるらしい
winget install Docker.DockerDesktop
```

.env ファイルを受け取ってこのファイル (README.md) の隣に置く。

そしたらこれ↓をやる。

```bash
# 最初のセットアップ
docker compose up -d --build

# これをコピペして Enter すると
docker compose run --rm app pipenv run python main.py

# こういうふうに出る↓
# 認可コードを再取得してください。以下の URL をブラウザで開いてください:
# https://accounts.secure.freee...._company

# この URL ↑を開いて、 Freee にログインして、自分用の "認可コード" を得る
# こんな形式↓ (例)
# MlPebabcdefghijklmnopqrstuvwxyzABCDEFGHeQU8

# 認可コードを使ってこうする↓
docker compose run --rm app pipenv run python main.py --auth-code MlPebabcdefghijklmnopqrstuvwxyzABCDEFGHeQU8

# するとこう↓なる
# 認可コードでトークンを取得し、token.json を更新しました。
# 今回は何をしたい? (↑↓で選択 / Enterで決定 / Ctrl+Cで中断)
#   指定の月に自分の勤怠を詰め込む
# > 指定の月に従業員ID指定で勤怠を詰め込む <-- これを選んで、機能を楽しんでください
#   指定の月の自分の勤怠をリセットする
#   あ、いや、アクセストークン取得までいけるか見たかっただけ
```

![](./docs/image-birds-at-tree.webp)

## ぼく用 Commands

```bash
# 最初のセットアップ
docker compose up -d --build

# Ruff を動かしてみる
docker compose run --rm app pipenv run ruff check .
docker compose run --rm app pipenv run ruff check --fix .

# Python スクリプトを動かしてみる
# まあとりあえずコレを実行。 "AUTH_CODE 入れろやあ!" って言われると思うので、エラーメッセージの案内に従って AUTH_CODE を手に入れて……
docker compose run --rm app pipenv run python main.py
# そんでこれを実行する。一度 token.json が出来ちゃえば、次からは AUTH_CODE なしで実行で OK.
# token.json は90日で expire する。
docker compose run --rm app pipenv run python main.py --auth-code AUTH_CODE

# Web UI を起動する（http://127.0.0.1:8000）
docker compose run --rm --service-ports app pipenv run python web.py
```
