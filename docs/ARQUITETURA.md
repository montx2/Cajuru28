# Arquitetura

O NotasFlow é executado exclusivamente por Docker Compose.

```text
Navegador -> Frontend Next.js -> API FastAPI -> PostgreSQL
                                  |
                                  +-> Redis -> Celery workers
                                             Celery Beat
                                  |
                                  +-> ADN / SEFAZ (mTLS)
```

## Serviços

| Serviço | Responsabilidade |
|---|---|
| `frontend` | Interface web |
| `api` | Autenticação, cadastro, consultas e comandos |
| `worker` | Importações fiscais assíncronas |
| `beat` | Sincronismo e retomadas agendadas |
| `db` | Persistência PostgreSQL |
| `redis` | Broker e resultados da fila |

Os certificados e XMLs ficam em volumes separados. O backend nunca grava a
senha do certificado em texto puro; ela é protegida pelo cofre Fernet.

## Operação

A API, workers e agenda usam a mesma imagem do backend. Escale workers conforme
a quantidade de empresas, mantendo apenas uma instância de `beat` para evitar
disparos duplicados.
