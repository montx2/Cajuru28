FROM python:3.11-slim AS base

WORKDIR /app

# O pg_dump canônico é uma segunda cópia do banco dentro do pacote. Dependências
# de compilação não ficam na imagem: requirements publicados têm wheels.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client \
    && groupadd --system --gid 10001 notasflow \
    && useradd --system --uid 10001 --gid notasflow --home-dir /app --shell /usr/sbin/nologin notasflow \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt requirements-dev.txt ./

# A imagem de produção não carrega pytest/respx. O compose local usa o estágio
# `test` abaixo para manter `make test` conveniente no ambiente de desenvolvimento.
FROM base AS runtime
RUN pip install --no-compile -r requirements.txt
COPY . .
RUN chown -R notasflow:notasflow /app
USER notasflow
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
USER root
RUN pip install --no-compile -r requirements-dev.txt
USER notasflow
