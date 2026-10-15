# Fluxa — Cajuru28

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
  (dump + XMLs/certificados integrais + manifesto SHA-256, cifrado e com cópia
  externa) e **teste de restauração**
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
- **Importação em massa fiscal:** cadastro de empresas+certificados por lote —
  seleção da pasta de certificados + planilha de senhas existente
  ([como usar](docs/IMPORTACAO_CERTIFICADOS.md)).
- **Fechamento mensal:** mapa empresa × tipo da competência, exportável em
  CSV e ZIP.
- **Busca global:** `Ctrl+K` encontra qualquer documento por chave, número
  ou emitente.
- **Alertas externos:** webhook JSON para Slack, Discord, n8n ou gateway
  WhatsApp.
- **Trilha de auditoria** e **métricas Prometheus** (`GET /metricas`).
- **Manifestação do destinatário (NF-e):** a NF-e que chega apenas como resumo
  só libera o XML completo depois da Ciência da Operação (evento 210210). O
  worker faz isso automaticamente para as empresas que ativarem a opção — ela
  vem desligada porque a Ciência é irreversível e inicia o prazo da
  manifestação conclusiva.

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

### Instalação manual (qualquer SO com Docker)

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
docker compose up --build -d              # constrói e inicia
docker compose down                       # para os serviços
docker compose logs -f api worker frontend  # acompanha logs
docker compose exec api pytest -q         # testes dentro do contêiner da API
docker compose build                      # constrói as imagens
```

(O usuário inicial é criado automaticamente na primeira subida — veja
`BOOTSTRAP_*` em `scripts/instalar_windows.ps1`.)

## Serviços e dados

O `docker-compose.yml` inicia `db`, `redis`, `api`, `worker`, `beat` e
`frontend` para desenvolvimento local. Os dados persistentes ficam nos volumes
`db_data`, `certificados`, `xml_saida` e `backups_local`. Para produção, use
`docker-compose.production.yml`: ele expõe somente Caddy/TLS e exige S3,
segredos fortes e um volume dedicado de backup. Veja
[`docs/DEPLOY_PRODUCAO.md`](docs/DEPLOY_PRODUCAO.md).

Consulte `docs/ARQUITETURA.md` e `docs/SINCRONIZACAO.md` para detalhes técnicos.

## Jettax Morfeu 360 — NFS-e

Em **Configurações → Integrações → Jettax Morfeu 360**, o administrador salva
um token cifrado por escritório. Operadores podem importar NFS-e de uma ou
até 30 empresas por competência; cada empresa tem tarefa Celery e resultado
próprios. O pipeline de XML existente evita duplicatas e registra origem
`jettax`. PDFs são opcionais e não são baixados; links temporários não são
armazenados. Apenas GETs são enviados ao Jettax.

Depois de aplicar esta versão, na raiz do projeto (Docker Compose local):

```sh
docker compose up -d --build api worker beat frontend
docker compose restart api worker
```

Comece por uma empresa/competência conhecida e repita o pedido após terminar:
a segunda consulta deve contar duplicatas, sem criar cópias extras. Veja
[`docs/JETTAX.md`](docs/JETTAX.md) para configuração, resultados, testes,
arquivos envolvidos, limitações, produção e como desfazer.

**NFe/CT-e e fallback não fazem parte desta etapa.** Nunca deixe os dois
coletores consultando a SEFAZ com o mesmo certificado: há risco de **cStat
656** e bloqueio de aproximadamente uma hora. A configuração oficial
existente não é alterada por salvar o token ou importar NFS-e.

O diagnóstico independente permanece em `diagnostico_jettax.py` e está
explicado em [`docs/DIAGNOSTICO_JETTAX.md`](docs/DIAGNOSTICO_JETTAX.md).
