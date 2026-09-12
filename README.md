# NotasFlow — Cajuru28

**Sistema operacional fiscal privado**: captura automática de documentos
fiscais (NFS-e, NFe e CT-e) pelas fontes oficiais ADN/SEFAZ, com certificados
A1, feito para **um operador administrar centenas de empresas** com o mínimo
possível de intervenção manual.

> A pergunta que guia cada tela: *"como fazer para que o operador precise
> fazer cada vez menos?"* — ver [`docs/DIRETRIZ_OPERACIONAL.md`](docs/DIRETRIZ_OPERACIONAL.md).

## O que muda na v3.0

O sistema deixou de se apresentar como "SaaS de escritório" e passou a ser
uma **ferramenta de operação fiscal para um único operador**:

- **Painel (home)** — responde imediatamente *"está tudo funcionando?"*:
  semáforo de status, saúde da automação (empresas sincronizadas hoje,
  erros, certificados, tempo médio das varreduras), componentes de fundo
  (banco, fila, worker, agendador) e o que está rodando agora.
- **Precisa da sua atenção** — a lista operacional principal: poucas linhas,
  ordenadas por gravidade, cada uma com o botão que resolve.
- **Execuções** — central do que o sistema está fazendo: rodando agora,
  próximas janelas de consulta, falhas com reprocessamento em um clique.
  Resumo primeiro, detalhe técnico só quando pedido.
- **Certificados** — centro de certificados: validade, dias restantes,
  **última utilização real** e **último erro de autenticação** de cada A1.
- **Saúde do sistema** — componentes + **backup de verdade**: pacote diário
  (dump do banco + manifesto + espelho de XMLs) e **teste de restauração**
  que recria o schema num banco de prova e confere as contagens.
- **Menu enxuto** — Visão geral · Fiscal · Sistema. Sem gestão de equipe,
  planos ou qualquer ruído de SaaS na experiência principal (a arquitetura
  continua multiusuária por baixo, pronta para o futuro).

## Destaques (já existentes)

- **Sincronismo automático:** o Celery Beat varre as empresas sozinho,
  respeitando a janela oficial de 1 hora por CNPJ e tipo — com governador
  de consumo (cStat 656, cotas de 20 consultas/h, lease por empresa+tipo).
- **Recuperação automática:** retry com reagendamento, checkpoint de NSU a
  cada lote, uma nota que falha nunca para as outras 9.999.
- **Importação em massa:** cadastro de empresas+certificados por lote e
  importação por seleção, com prévia do que vai acontecer.
- **Fechamento mensal:** mapa empresa × tipo da competência, exportável em
  CSV e ZIP.
- **Busca global:** `Ctrl+K` encontra qualquer documento por chave, número
  ou emitente.
- **Alertas externos:** webhook JSON para Slack, Discord, n8n ou gateway
  WhatsApp.
- **Trilha de auditoria** e **métricas Prometheus** (`GET /metricas`).
- **Jettax 360/Morfeu (opcional):** conector backend-first, com token em
  segredo de deploy, registro explícito de clientes, saúde/auditoria,
  deduplicação por fonte e captura de NFS-e/NF-e pelos contratos públicos
  verificados (CT-e permanece protegido por contrato ainda incompleto). Veja
  [`docs/JETTAX.md`](docs/JETTAX.md).

## Arquitetura

- **Frontend:** Next.js
- **API:** FastAPI
- **Banco:** PostgreSQL
- **Fila:** Redis + Celery
- **Agendamento:** Celery Beat (sincronismo, retomada de XMLs, alertas e backup)

## Instalação

### Windows

Execute `INSTALAR_TUDO.bat`. O script instala/verifica o Docker Desktop, gera
as chaves locais, sobe os contêineres e abre o painel.

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

> **Portas ocupadas ou reservadas?** No Windows, o Hyper-V reserva faixas
> de portas e a 3000 costuma cair nelas — o Docker então falha com
> `ports are not available ... access permissions`. Os scripts
> `INICIAR.bat`/`INSTALAR_TUDO` testam as portas antes de subir e escolhem
> automaticamente a próxima livre (gravada no `.env` da raiz), e o
> `INICIAR.bat` só diz "Pronto!" quando **todos** os serviços estão de pé.
> Para fixar portas manuais, defina `FRONTEND_PORT`/`API_PORT` no `.env` da
> raiz. Veja [SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md).

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
`frontend`. Os dados persistentes ficam nos volumes `db_data`, `certificados`
e `xml_saida` — e o job de backup diário gera pacotes restauráveis dentro do
volume de dados (tela **Saúde do sistema** para acompanhar e testar).

Consulte `docs/ARQUITETURA.md` e `docs/SINCRONIZACAO.md` para detalhes técnicos.
