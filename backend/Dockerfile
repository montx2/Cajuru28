FROM python:3.11-slim

WORKDIR /app

# postgresql-client: dá ao backup o pg_dump canônico (o dump lógico JSONL
# continua existindo como formato restaurável em qualquer banco).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libssl-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# requirements-dev inclui o pytest: o alvo `make test` roda os testes
# dentro do container (diagnóstico com o mesmo ambiente de produção).
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
