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
docker compose run --rm app pipenv run python main.py
docker compose run --rm app pipenv run python main.py --auth-code AUTH_CODE
```
