freely-freee
===

好きに使わしてもらうぜ、 Freee を。

![](./docs/image-birds-fly.webp)

![](./docs/image-birds-at-tree.webp)

Docker (Python 3.12)
---

`docker compose` で Python 3.12 の実行環境を起動できます。  
ルートディレクトリの `.env` は `compose.yml` の `env_file` で読み込みます。

```bash
docker compose up -d --build
docker compose exec app python --version
docker compose exec app python main.py
# => Python 3.12.x
docker compose down
docker compose run --rm app pipenv run python main.py
docker compose run --rm app pipenv run python main.py --auth-code AUTH_CODE

docker compose run --rm app pipenv install requests
docker compose run --rm app pipenv install --dev ruff
```

Ruff
---

lint と format のチェックは Docker 経由で実行します。設定は `pyproject.toml` に記載しています。

```bash
# lint チェック
docker compose run --rm app pipenv run ruff check .

# lint 自動修正
docker compose run --rm app pipenv run ruff check --fix .

# format チェック
docker compose run --rm app pipenv run ruff format --check .

# format 実行
docker compose run --rm app pipenv run ruff format .
```
