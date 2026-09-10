# NotasFlow

Importação automática de documentos fiscais (NFS-e, NFe e CT-e) pelas fontes
oficiais ADN/SEFAZ, usando certificados A1 — com dashboard executivo, central
de alertas e fechamento mensal. A aplicação é distribuída e executada
exclusivamente com **Docker Compose**.

## Destaques

- **Visão geral executiva:** KPIs do mês, evolução de 12 meses, quebra por tipo,
  ranking de empresas, maiores emitentes e feed de atividades — tudo ao vivo.
- **Central de alertas:** certificados vencidos/vencendo, bloqueios SEFAZ,
  risco de perda na distribuição, XMLs pendentes e saúde do disco, com ação
  direta para cada item.
- **Fechamento mensal:** mapa empresa × tipo da competência, exportável em CSV
  e ZIP, pronto para imprimir e enviar ao cliente.
- **Detalhe de documento:** clique em qualquer nota para ver a ficha completa
  (estilo DANFE), copiar a chave e inspecionar ou baixar o XML.
- **Busca global:** `Ctrl+K` na barra superior encontra qualquer documento por
  chave, número ou emitente.
- **Sincronismo automático:** o Celery Beat varre as empresas sozinho,
  respeitando a janela oficial de 1 hora por CNPJ e tipo.
- **Equipe com papéis:** admin, operador e somente-leitura — a API barra de
  verdade, e a interface esconde o que cada perfil não pode fazer.
- **Trilha de auditoria:** cada login, cadastro, disparo e download registrado
  com quem, quando e o detalhe.
- **Alertas externos:** webhook JSON para Slack, Discord, n8n ou gateway
  WhatsApp, com nível mínimo, cooldown e botão de teste.
- **Métricas Prometheus:** `GET /metricas` com documentos, execuções,
  certificados e alertas por escritório.

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
