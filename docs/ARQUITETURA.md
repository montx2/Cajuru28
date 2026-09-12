# Arquitetura

O NotasFlow é executado por Docker Compose. O arquivo padrão é o ambiente
local de desenvolvimento; dados fiscais reais usam a pilha isolada de
[`DEPLOY_PRODUCAO.md`](DEPLOY_PRODUCAO.md).

```text
Navegador -> Frontend Next.js -> API FastAPI -> PostgreSQL
                                  |
                                  +-> Redis -> Celery workers
                                             Celery Beat
                                  |
                                  +-> ADN / SEFAZ (mTLS)
                                  +-> Jettax 360 / Morfeu (token de deploy)
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

Os certificados, XMLs e pacotes de backup ficam em volumes persistentes
compartilhados apenas pelos processos que precisam deles. O backend nunca grava
a senha do certificado em texto puro; ela e o PFX são protegidos pelo cofre
Fernet. Cada pacote de backup é cifrado com uma chave Fernet **separada** e
replicado para storage S3 configurado em produção.

A Jettax/Morfeu é um adaptador complementar, com token somente no ambiente do
servidor e cursores próprios: ele não divide estado NSU com ADN/SEFAZ. A
operação e os limites do conector estão em [`JETTAX.md`](JETTAX.md).

A Jettax/Morfeu é um adaptador complementar, com token somente no ambiente do
servidor e cursores próprios: ele não divide estado NSU com ADN/SEFAZ. A
operação e os limites do conector estão em [`JETTAX.md`](JETTAX.md).

## Operação

A API, workers e agenda usam a mesma imagem do backend. Escale workers conforme
a quantidade de empresas, mantendo apenas uma instância de `beat` para evitar
disparos duplicados.
