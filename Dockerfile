FROM python:3.12-slim

RUN pip install --no-cache-dir pipenv

WORKDIR /app

# 先に Pipfile と Pipfile.lock だけコピーします (レイヤーキャッシュ活用)
COPY Pipfile Pipfile.lock* ./

# コンテナ内では仮想環境をプロジェクト直下に作ります
ENV PIPENV_VENV_IN_PROJECT=1

# Pipfile.lock があれば依存をインストールします
RUN if [ -f Pipfile.lock ]; then pipenv sync --dev; fi

# ソースコードをコピーします
COPY . .
