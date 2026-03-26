freely-freee
===

好きに使わしてもらうぜ、 Freee を。

![](./docs/image-birds-fly.webp)

![](./docs/image-birds-at-tree.webp)

## Commands

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
```
