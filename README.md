# NotasFlow

Importação automática de documentos fiscais (NFS-e, NFe e CT-e) pelas fontes
oficiais ADN/SEFAZ, usando certificados A1. A aplicação é distribuída e
executada exclusivamente com **Docker Compose**.

## Arquitetura

- **Frontend:** Next.js
- **API:** FastAPI
- **Banco:** PostgreSQL
- **Fila:** Redis + Celery
- **Agendamento:** Celery Beat

## Instalação

### Windows

Execute `INSTALAR_TUDO.bat`. O script instala/verifica o Docker Desktop, gera as
chaves locais, sobe os contêineres e abre o painel.

Depois, use:

- `INICIAR.bat` para iniciar;
- `PARAR.bat` para parar;
- `ATUALIZAR.bat` para atualizar e reconstruir.

### Linux/macOS

```bash
./INSTALAR_TUDO.sh
```

Ou manualmente:

```bash
cp backend/.env.example backend/.env
# Preencha as chaves exigidas no arquivo .env
docker compose up --build -d
```

Acesse:

- Painel: http://localhost:3000
- API/Swagger: http://localhost:8000/docs

## Comandos úteis

```bash
make up       # constrói e inicia
make down     # para os serviços
make logs     # acompanha logs
make user     # cria o usuário inicial
make test     # executa os testes dentro do contêiner da API
make build    # constrói as imagens
```

## Serviços e dados

O `docker-compose.yml` inicia `db`, `redis`, `api`, `worker`, `beat` e
`frontend`. Os dados persistentes ficam nos volumes `db_data`, `certificados` e
`xml_saida`; inclua esses volumes na política de backup do servidor.

Consulte `docs/ARQUITETURA.md` e `docs/SINCRONIZACAO.md` para detalhes técnicos.
