freely-freee
===

好きに使わしてもらうぜ、 Freee を。

![](./docs/image-birds-fly.webp)

![](./docs/image-birds-at-tree.webp)

Docker (Python 3.12)
---

`docker compose` で Python 3.12 の実行環境を起動できます。  
ルートディレクトリの `.env` は `docker-compose.yml` の `env_file` で読み込みます。

```bash
docker compose up -d --build
docker compose exec app python --version
docker compose exec app python main.py
# => Python 3.12.x
docker compose down
docker compose run --rm app python main.py

docker compose run --rm app pipenv install requests
docker compose run --rm app pipenv install --dev ruff

```
