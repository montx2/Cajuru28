# Auditoria técnica — Cajuru28 / NotasFlow

**Data:** 19/09/2026
**Commit auditado:** `9e153f4` (`main`) — "Merge PR #31 — Corrige laço de recarregamento que impedia o login"
**Dimensão auditada:** backend 16.809 linhas (+5.671 de testes), frontend 17.408 linhas, 16 routers (6.212 l.), 14 telas (7.049 l.), 24 arquivos de teste / 217 casos.
**Escopo:** 100% do backend lido linha a linha; frontend lido por completo na camada de dados, contratos e telas principais; infraestrutura (Docker, Caddy, Celery), banco, documentação interna (`docs/`) e documentação pública da Jettax/Morfeu e do NFS-e Nacional.

## Método e limitações declaradas

O que sustenta cada afirmação deste relatório:

1. **Análise estática integral do código** — é a base da maioria absoluta dos achados e é verificável por qualquer pessoa abrindo os arquivos citados (arquivo + linha em todos os pontos relevantes).
2. **Execução local de testes** — a suíte do repositório roda inteira (217 casos, todos passando) e **um teste de reprodução novo**, escrito fora do repositório, foi usado para provar empiricamente o bug de paginação da Jettax (seção E).
3. **Documentação pública oficial** — coleção Postman "Morfeu" da Jettax, cartilha e manuais do NFS-e Nacional/ADN, material do Jettax 360.

**Limitação importante e honesta:** o ambiente desta auditoria **não tem saída TLS**. Nenhuma chamada a `morfeu-api.jettax.com.br`, `adn.nfse.gov.br` ou `www1.nfe.fazenda.gov.br` pôde ser feita ao vivo. Portanto:

- Tudo que depende do **comportamento em produção do servidor da Jettax** está marcado como **hipótese ordenada por probabilidade**, com o teste exato para confirmar ou descartar cada uma (seção E.6). Não vou afirmar que "o endpoint X retorna Y" sem ter visto.
- Os bugs de **código** (paginação, ausência de XML de NFS-e, campos faltantes no cadastro remoto, timezone) são **fatos**, não hipóteses: estão no código e um deles foi reproduzido em teste.

**Onde a lei/regra fiscal entra:** não inventei nenhuma regra. Quando algo depende de legislação, de parametrização municipal ou de contrato de fornecedor, está escrito explicitamente "depende de X e precisa ser confirmado com Y".

## Escala de severidade (critério técnico, não impressão)

| Nível | Critério objetivo |
|---|---|
| **CRÍTICO** | Causa perda de documento fiscal, impede a captura de uma categoria inteira de documento, corrompe dado fiscal já gravado, ou permite destruição de dados por quem não deveria poder. Efeito é irreversível ou só reversível com reprocessamento manual. |
| **ALTO** | Produz dado fiscal errado de forma silenciosa (sem erro visível), ou derruba a operação em condições normais de volume/horário, ou impede o diagnóstico de uma falha em produção. Reversível, mas com trabalho manual. |
| **MÉDIO** | Degrada confiabilidade, desempenho ou manutenção de forma mensurável, mas há contorno operacional e o dado permanece correto. |
| **BAIXO** | Dívida técnica, inconsistência ou risco futuro sem impacto operacional hoje. |

Severidade aqui é **consequência sobre o documento fiscal e sobre a operação**, não elegância de código. Um `float` num campo de valor é ALTO porque produz centavo errado em relatório; um router de 1.200 linhas é MÉDIO porque é feio mas não erra conta.

---

# A. Diagnóstico geral

## A.1. Veredito em uma página

Este **não** é um projeto ruim. É um projeto **acima da média** em concepção fiscal e **abaixo do necessário** em três eixos específicos que impedem que ele seja chamado de enterprise hoje: **operabilidade sob falha**, **integridade numérica/temporal do dado** e **um conector-chave quebrado (Jettax)**.

O que está genuinamente bem feito — e que seria caro e demorado refazer, portanto **deve ser preservado**:

- **A modelagem do problema fiscal está certa.** O sistema entendeu que o eixo é `(empresa, tipo de documento, cursor de distribuição)` e não `(usuário, upload, arquivo)`. Isso é a diferença entre um importador de XML e uma plataforma de captura. `services/sincronizacao.py` mapeia, regra por regra, o contrato oficial da distribuição DFe (cStat 137 = nada novo, cStat 656 = consumo indevido, `ultNSU`/`maxNSU`, 50 documentos por lote, 20 consultas pontuais por hora, lease de 25 minutos) para funções nomeadas. Poucos sistemas comerciais desse nicho fazem isso de forma explícita e testável.
- **O tratamento do cStat 656 (consumo indevido) é maduro.** `realinhar_cursor()` (`sincronizacao.py:150`) escuta o `ultNSU` que o ambiente devolveu em vez de insistir no cursor local. Isso é exatamente o que destrava o loop de bloqueio, e é um erro clássico que a maioria das implementações comete.
- **Eventos não somem.** `services/importadores/eventos.py` transforma **qualquer** item não-documento do lote em `EventoFiscal` — cancelamento é aplicado (inclusive pendente, para quando a nota chega depois) e o que não foi reconhecido é **contabilizado**, não descartado. A docstring do arquivo descreve exatamente o bug que isso corrigiu.
- **CNPJ alfanumérico (regra de 2026) já implementado** em `core/documentos.py`, com DV calculado por `ord(c) - 48`. É raro; a maioria dos sistemas brasileiros ainda vai quebrar nisso.
- **Certificado A1 tratado com seriedade.** `services/certificados.py` grava o PFX **sempre cifrado** (Fernet + marcador `NOTASFLOW-PFX-FERNET-V1`), com escrita atômica (`mkstemp` + `os.replace`), diretório 0700, arquivo 0600, e migra o legado em claro na primeira leitura. `services/mtls.py::sessao_mtls` materializa cert/key em PEM num tmpdir 0700/0600 e apaga na saída do context manager.
- **Idempotência de escrita real.** `_inserir_documento_sem_duplicar` / `_insert_sem_duplicar` usam `ON CONFLICT DO NOTHING` nativo (PG e SQLite), com `UniqueConstraint(empresa_id, chave_acesso)`. Reprocessar um lote não duplica nota.
- **Endurecimento de produção acima da média.** `docker-compose.production.yml` roda api/worker/beat com `read_only: true`, `cap_drop: ALL`, `no-new-privileges`, tmpfs em `/tmp`, e um container `volume-init` como gate. O `backend/Dockerfile` é multi-stage com usuário uid 10001 e sem pytest no runtime. `deploy/Caddyfile` sobrescreve `X-Forwarded-For` com `{remote_host}` — o que **impede spoofing do rate limiter**, detalhe que quase todo mundo erra.
- **Backup maduro:** JSONL gzip + `pg_dump`, manifesto com hashes, cifra Fernet, destino S3 obrigatório.

O que está errado e por quê isso importa:

- **A Jettax está quebrada em cinco pontos independentes e verificáveis no código** (E.3). Não é "a API não responde": é um bug `for/else` que transforma sucesso em erro, é NFS-e que entra sem XML nenhum, é cadastro remoto que omite o certificado, é um campo obrigatório (`codigo_ibge`) que nada no sistema preenche, e é a ausência de qualquer botão de disparo na interface. Nenhum desses depende do servidor da Jettax para ser confirmado.
- **Nenhum container define `TZ`, e as datas naive do XML são interpretadas como UTC.** O sistema processa competência e "hoje" com o relógio em UTC enquanto o Celery agenda em `America/Sao_Paulo`. Efeito prático: **a partir das 21h no Brasil, o sistema acha que já é amanhã**. Isso é erro de dado fiscal, silencioso, sem exceção nenhuma no log.
- **Valor monetário é `float`** no modelo (`models.py:206`) e nos schemas Pydantic (10 ocorrências). Somar 10.000 notas em ponto flutuante binário e apresentar como R$ produz divergência de centavos em fechamento. Um contador **vai** reclamar disso.
- **Não existe nenhuma configuração de logging.** Seis loggers nomeados, zero `dictConfig`, zero JSON, zero correlation ID, `uvicorn --no-access-log` em produção. A pergunta central do produto — *"por que a nota X não foi importada?"* — hoje só tem resposta se o operador for ler tabela por tabela no banco.
- **Não existe migração versionada.** `db/base.py::criar_tabelas()` é `create_all()` + um `db/migracoes.py` artesanal que faz `ALTER` idempotente. Funciona para adicionar coluna. **Não consegue mudar tipo de coluna** — hoje é fisicamente impossível corrigir o `FLOAT → NUMERIC(15,2)` sem escrever migração manual fora do framework. A própria docstring do arquivo já admite que Alembic é a troca necessária antes de produção com dado real.
- **Não existe manifestação do destinatário** (eventos 210200/210210) em nenhum ponto do backend. Consequência: NF-e de entrada fica eternamente em `leiaute="resumo"`, e o "completar XML" gasta cota de `consChNFe` (20/h) tentando algo que a SEFAZ só libera **depois** da manifestação. É um vazio conceitual, não um bug de implementação (seção G).

## A.2. O que "não funciona de forma alguma" na Jettax realmente significa

O relato do usuário é compatível com o código. Considerando o caminho completo que uma nota teria que percorrer:

```
[UI] disparar importação  ──►  NÃO EXISTE BOTÃO (achado E.3.4)
        │
[cadastro remoto] POST /api/clients  ──►  exige codigo_ibge, que nada preenche (E.3.3)
        │                            ──►  omite certificado se o toggle não for marcado (E.3.2)
        │                            ──►  não há campo para login/senha de prefeitura (E.3.2)
        │
[listagem]  _listar_paginas()  ──►  for/else transforma sucesso em erro (E.3.1) * reproduzido
        │
[persistência] NFS-e  ──►  grava sem XML, chave sintética (E.3.5)
        │
[entrega] ZIP / download  ──►  ignora a nota, porque depende de xml_path (E.3.5)
```

**Cada seta é um ponto de morte independente.** Mesmo que o servidor da Jettax estivesse perfeito e o token fosse válido, o usuário ainda veria "não funciona": não há como disparar pela tela; se disparasse pelo Beat, o cadastro remoto falharia por falta de IBGE; se o cadastro passasse, a captura municipal não teria credencial; se tivesse, a listagem poderia estourar em erro falso; e se trouxesse notas, elas não teriam XML para baixar.

Isso responde à exigência de um diagnóstico exato: **o problema não é (primariamente) a API da Jettax. O problema é o nosso lado.**

## A.3. Distância até "enterprise"

Defino enterprise, para este produto, por cinco propriedades mensuráveis:

| Propriedade | Hoje | Alvo |
|---|---|---|
| **Nenhum documento se perde silenciosamente** | Parcial — eventos são rastreados, mas NFS-e Jettax entra sem XML e o filtro de período descarta por data possivelmente errada (timezone) | Toda ausência é explicável por consulta |
| **Toda falha é explicável sem acesso ao servidor** | Não — sem logging estruturado, sem correlation ID | Uma tela responde "por que a nota X não veio" |
| **O dado numérico e temporal é exato** | Não — `float` + UTC implícito | `NUMERIC(15,2)` + tz explícito ponta a ponta |
| **Escala 1M+ documentos sem redesenho** | Não — busca `LIKE '%…%'` em 8 colunas, sem particionamento, pool padrão | Índices trigram/FTS, partição por competência, pool dimensionado |
| **Mudança de schema é segura e reversível** | Não — sem Alembic | Migração versionada com downgrade |

Nenhuma dessas exige reescrever o sistema. **Estimativa honesta: ~85% do backend se aproveita como está ou com ajuste local; ~10% precisa de refatoração estrutural (Jettax, logging, camada de dinheiro/data); ~5% precisa ser escrito do zero (Alembic, camada de connectors, manifestação).** O frontend se aproveita quase integralmente; o que falta lá é funcionalidade, não arquitetura.

## A.4. Alinhamento com a diretriz operacional do próprio projeto

`docs/DIRETRIZ_OPERACIONAL.md` define a ordem de prioridade do produto: (1) automação, (2) confiabilidade, (3) detecção automática de problemas, (4) recuperação automática, (5) visibilidade operacional, (6) pesquisa, (7) organização, (8) exportação — e coloca **segurança em 10º de 10**, proibindo funcionalidade que não reduza trabalho manual.

Não vou brigar com a diretriz; vou usá-la. **Quase tudo que classifico como CRÍTICO/ALTO aqui cai nos itens 2, 3, 4 e 5 da própria diretriz**, não em segurança:

- Jettax quebrada = falha de **automação** (1) e **confiabilidade** (2).
- Timezone errado = falha de **confiabilidade** (2) — nota na competência errada é retrabalho manual puro.
- Sem logging = falha de **detecção** (3) e **visibilidade** (5) — sem isso o operador vira o log do sistema.
- Sem manifestação = falha de **automação** (1) — obriga o operador a buscar XML de entrada em outro lugar.
- Sem Alembic = risco à **confiabilidade** (2) na primeira mudança de schema com dado real.

Os dois achados de segurança que mantenho como ALTO (`POST /sistema/reset-geral` e `POST /documentos/excluir-lote` sem exigir admin) também não são "segurança de SaaS": são **proteção contra perda de dado**, que é confiabilidade. Um operador cansado clicando errado apaga o acervo. Isso é o item 2 da diretriz, não o 10.

---

# B. Problemas críticos e altos — visão consolidada

Ordenado por severidade e, dentro dela, por custo de correção (mais barato primeiro). A coluna "Prova" diz como o achado foi verificado — isso separa fato de hipótese.

| # | Achado | Sev. | Local | Prova |
|---|---|---|---|---|
| B1 | `for/else` em `_listar_paginas` transforma paginação completa em erro quando o nº de páginas iguala o limite | **CRÍTICO** | `services/jettax.py:650-678` | **Reproduzido em teste** |
| B2 | NFS-e importada via Jettax é gravada **sem XML** (`xml_path=""`) e nunca aparece em ZIP/download | **CRÍTICO** | `services/jettax.py:1180-1220` | Código + fluxo de `_montar_zip` |
| B3 | `codigo_ibge` é obrigatório no `POST /api/clients` da Jettax e **nenhum fluxo do sistema o preenche** | **CRÍTICO** | `services/jettax.py:704-735`, `services/cnpj.py`, `models.py:117` | Código + doc Postman |
| B4 | Cadastro remoto omite o certificado por padrão e **não há campo para credencial de prefeitura** — as duas vias de captura de NFS-e do fornecedor ficam fechadas | **CRÍTICO** | `services/jettax.py:732-735`, `models.py:358-388` | Código + doc Jettax 360 |
| B5 | **Não existe botão de importação Jettax na interface** — funções existem em `lib/api.ts`, nenhuma tela as chama | **CRÍTICO** | `frontend/lib/api.ts:545-555`, `app/dashboard/empresa/Empresa.tsx` | `grep` em todo o `app/` |
| B6 | Nenhum container define `TZ`; datas naive do XML viradas para UTC; 6 usos de `date.today()`/`datetime.now()` sem tz | **ALTO** | `docker-compose*.yml`, `worker/tasks.py`, 5 routers | Código + `grep` exaustivo |
| B7 | Valor monetário como `float` no modelo e em 10 pontos dos schemas | **ALTO** | `models.py:206`, `schemas.py:439,490,785-858,1010` | Código |
| B8 | Zero configuração de logging (sem `dictConfig`, JSON, correlation ID, `LOG_LEVEL`); produção com `--no-access-log` | **ALTO** | `main.py`, `celery_app.py`, `docker-compose.production.yml` | `grep` exaustivo |
| B9 | Sem Alembic — `create_all()` + migrações artesanais que **não conseguem alterar tipo de coluna** | **ALTO** | `db/base.py`, `db/migracoes.py` | Código + docstring do próprio arquivo |
| B10 | Manifestação do destinatário (210200/210210) inexistente — NF-e de entrada presa em `leiaute="resumo"` | **ALTO** | ausência em todo `services/importadores/` | `grep` exaustivo |
| B11 | `POST /sistema/reset-geral` e `POST /documentos/excluir-lote` exigem só `requer_escrita`, não admin | **ALTO** | `api/routers/sistema.py`, `documentos.py` | Código |
| B12 | Busca textual por `LIKE '%termo%'` em 8 colunas, sem trigram/FTS | **ALTO** | `api/routers/documentos.py` | Código |
| B13 | `create_engine` sem `pool_size`/`max_overflow` com worker `--concurrency=4` | **MÉDIO → ALTO em carga** | `db/session.py` | Código |
| B14 | Fila Celery única — backup diário disputa worker com importação | **MÉDIO** | `celery_app.py` | Código |
| B15 | Sem particionamento nem política de retenção em `documentos_fiscais` | **MÉDIO** | `models.py` | Código |
| B16 | Chave sintética `jettax-nfse-{id}` impede deduplicação cross-fonte da mesma nota | **MÉDIO** | `services/jettax.py:1184` | Código |
| B17 | JWT HS256 de 20 min sem refresh token | **MÉDIO** | `core/security.py` | Código |
| B18 | Zero teste contra PostgreSQL real; zero contract test do conector Jettax; zero teste de carga | **MÉDIO** | `backend/tests/` | Inventário |
| B19 | Dev roda API como `user: "0:0"` com bind-mount e expõe db/redis no host | **BAIXO** | `docker-compose.yml` | Código |
| B20 | Routers e telas grandes demais (`documentos.py` 1.218 l., `Empresa.tsx` 943 l.) | **BAIXO** | vários | `wc -l` |

Detalhamento dos CRÍTICOS vem na seção E (todos os cinco são Jettax). B6 a B20 são detalhados nas seções temáticas.

---

# C. Arquitetura

## C.1. Como o sistema está organizado hoje

```
                    ┌──────────────────────────────┐
  navegador ──────► │ Caddy (TLS ACME, strip /api) │
                    └───────┬──────────────┬───────┘
                            │              │
                  ┌─────────▼───┐    ┌─────▼────────────┐
                  │ Next.js 16  │    │ FastAPI (uvicorn)│
                  │ React 19    │    │ 16 routers       │
                  └─────────────┘    └─────┬────────────┘
                                           │
                     ┌─────────────────────┼──────────────────────┐
                     │                     │                      │
              ┌──────▼──────┐      ┌───────▼────────┐    ┌────────▼────────┐
              │ PostgreSQL  │      │ Redis (broker) │    │ volume de XMLs  │
              └─────────────┘      └───────┬────────┘    └─────────────────┘
                                           │
                            ┌──────────────┴──────────────┐
                     ┌──────▼───────┐            ┌────────▼────────┐
                     │ Celery worker│            │ Celery Beat     │
                     │ concurrency 4│            │ 4 agendamentos  │
                     └──────┬───────┘            └─────────────────┘
                            │
        ┌───────────────────┼────────────────────┬─────────────────┐
  ┌─────▼─────┐      ┌──────▼──────┐     ┌───────▼──────┐   ┌──────▼──────┐
  │ ADN NFS-e │      │ SEFAZ NF-e  │     │ SEFAZ CT-e   │   │ Jettax      │
  │ (REST     │      │ (DistDFe    │     │ (DistDFe     │   │ (Morfeu     │
  │  mTLS A1) │      │  SOAP 1.2)  │     │  SOAP 1.2)   │   │  REST token)│
  └───────────┘      └─────────────┘     └──────────────┘   └─────────────┘
```

**Camadas do backend, na prática:**

| Camada | Diretório | Responsabilidade real | Qualidade |
|---|---|---|---|
| HTTP | `api/routers/` | Validação, autorização, orquestração | Boa, mas routers gordos |
| Contratos | `schemas.py` (1.139 l.) | Pydantic, validators de CNPJ/UF/IBGE/IM | Boa, exceto `float` |
| Domínio fiscal | `services/sincronizacao.py`, `periodo.py`, `referencia.py` | Regras de janela, cursor, competência | **Excelente** |
| Integração | `services/importadores/*`, `services/jettax.py`, `acessorias.py` | Conversa com o mundo externo | ADN/SEFAZ bom, Jettax quebrado |
| Processamento | `worker/tasks.py` (1.256 l.) | Lotes, checkpoint, fallback | Bom, mas grande demais |
| Persistência | `models.py`, `db/*` | ORM, migração artesanal | Modelagem boa, migração frágil |
| Transversal | `core/{config,security,vault,rate_limit,documentos}.py` | Config, JWT, cofre Fernet, rate limit, CNPJ | Boa |

## C.2. O que está arquiteturalmente CERTO (e por quê)

**1. A porta única de enfileiramento (`services/fila.py`).** Todo disparo de importação passa por uma função que verifica, em ordem: existe certificado ativo? a UF é conhecida? já há execução em andamento? a janela oficial permite? Só então enfileira. Isso é a coisa certa: a regra de consumo da SEFAZ **não pode** ser reimplementada em cada router. Sem essa porta, um botão novo na UI vira bloqueio de CNPJ em produção.

**2. Separação entre estado de sincronização e log de execução.** `sincronizacoes_dfe` guarda o cursor (o que a SEFAZ sabe sobre nós); `execucoes_importacao` guarda o histórico (o que nós fizemos). Misturar os dois é o erro clássico que faz "reprocessar" perder o cursor. Aqui está separado, com índice único `(empresa_id, tipo)`.

**3. Checkpoint por lote em `importar_documentos`.** O worker comita o cursor a cada lote processado, não no fim da execução. Se o processo morre no lote 7 de 40, os 6 primeiros estão salvos e o NSU aponta para o lugar certo. É o mínimo para alto volume e está feito.

**4. `DocumentoFiscalFonte` — proveniência sem duplicar identidade.** A mesma nota pode chegar pelo ADN e pela Jettax; a identidade fiscal continua única em `documentos_fiscais`, e cada fonte que a confirmou fica registrada. É a modelagem correta para um sistema multi-fonte. (Sabotada na prática pela chave sintética da Jettax — ver B16.)

**5. Lease com `with_for_update()` e recuperação de trava expirada.** Tanto a fila oficial quanto a Jettax travam a linha antes de enfileirar e desfazem o lock se o broker recusar. Previne o duplo-disparo em múltiplos workers.

## C.3. O que está arquiteturalmente ERRADO (e por quê)

**C.3.1. Não existe camada de abstração de provedor para NFS-e — MÉDIO hoje, CRÍTICO no próximo município.** (Detalhado em F.)

Hoje há dois caminhos independentes e acoplados para NFS-e — `ImportadorNFSeADN` e o ramo NFS-e do `services/jettax.py` — cada um com seu próprio modelo de cursor, sua própria persistência e seu próprio conceito de "documento". O `worker/tasks.py` conhece os dois nominalmente. Adicionar um terceiro provedor hoje significa mais um `if` no worker. Isso não escala para o cenário real do negócio, que é dezenas de origens municipais.

**C.3.2. `worker/tasks.py` acumula orquestração, política de negócio e persistência — MÉDIO.**

1.256 linhas contendo: seleção de empresas elegíveis, decisão de janela, chamada ao importador, filtro de período, conversão para o modelo, inserção idempotente, tratamento de 656, acionamento de Jettax como fallback, gestão de cota pontual e resumo de avisos. Funções privadas de apoio (`_parse_data_emissao`, `_documento_no_periodo`, `_resumir_avisos`…) que são regra de domínio morando no arquivo do Celery. Consequência prática: **essas regras só são testáveis através do Celery**, e é por isso que o bug de timezone em `_parse_data_emissao` nunca foi pego.

**C.3.3. A Jettax é tratada simultaneamente como "fonte primária" e "fallback", sem que a diferença esteja modelada — ALTO em previsibilidade.**

`_acionar_jettax_para_execucao` / `_acionar_jettax_para_empresa` são chamadas em **10 pontos** de `worker/tasks.py` com origens diferentes (`fallback_656`, `fallback_cooldown`, `fallback_erro`). Ao mesmo tempo, `executar_importacao` da Jettax é a via principal de NFS-e municipal. O sistema não tem um conceito de "esta nota veio da via preferencial / da via de contingência / de ambas e conferem". O `DocumentoFiscalFonte` daria isso, mas a chave sintética (B16) impede.

**C.3.4. Configuração e segredos misturam níveis — BAIXO.**

O token da Jettax existe em **dois lugares**: `settings.jettax_api_token` (env, global) e `jettax_credenciais` (por escritório, cifrado). `_credencial_disponivel` aceita qualquer um dos dois. Para um sistema multiempresa isso é ambíguo. Funciona, mas é o tipo de ambiguidade que produz "funcionou no meu ambiente".

## C.4. Recomendação arquitetural (sem reescrita)

Três movimentos, nenhum deles um rewrite:

1. **Extrair um pacote `app/dominio/`** com o que hoje está solto em `worker/tasks.py`: parsing de data/competência, filtro de período, normalização de documento. Funções puras, testáveis sem Celery e sem banco.
2. **Introduzir a interface `ProvedorNFSe`** (seção F.4) e fazer ADN e Jettax a implementarem. O worker passa a iterar provedores em vez de conhecer nomes.
3. **Criar `app/core/observabilidade.py`** com `dictConfig` JSON + correlation ID propagado por header e por task Celery. Sem isso, tudo o mais é adivinhação.

**O que NÃO recomendo**, e por quê:
- **Microsserviços.** O gargalo aqui não é escala de time nem de tráfego; é corretude de integração. Quebrar em serviços multiplicaria os pontos de falha exatamente na parte que já está frágil.
- **Event sourcing / CQRS.** Sedutor para "auditoria fiscal", mas `DocumentoFiscalFonte` + `execucoes_importacao` + `auditoria` já cobrem a rastreabilidade necessária a um custo muito menor.
- **Trocar Celery.** Com `acks_late`, `prefetch=1` e `visibility_timeout=6h` está corretamente configurado para tarefas longas e idempotentes. Não há problema aqui a resolver.
- **Trocar FastAPI/Next.js.** Não há nenhum sintoma que justifique.

---

# D. Backend

## D.1. FastAPI e camada HTTP

**Bom:**
- `main.py` impõe limite de 35 MiB **antes** do parser de body (evita DoS por upload), CSRF por validação de `Origin`, HSTS/CSP em produção, `/docs` desligado em produção, `TrustedHostMiddleware` ativo (o healthcheck do compose de produção precisa forçar `Host: api` justamente por causa dele — sinal de que está funcionando).
- Dependências de autorização bem nomeadas (`requer_escrita`, `escritorio_id_atual`) e aplicadas consistentemente.
- Export com `yield_per(200)` — streaming real, não `.all()` na memória.

**Problemas:**

**D.1.1 — Routers grandes demais (BAIXO, mas cresce).** `documentos.py` 1.218 l., `importacoes.py` 1.051 l., `empresas.py` 665 l., `integracoes.py` 618 l. Em `documentos.py` convivem listagem, detalhe, download unitário, ZIP em massa, exclusão em lote, exportação CSV e conferência. Cada nova feature aumenta a chance de que uma regra de autorização seja esquecida num endpoint novo.

**D.1.2 — `POST /sistema/reset-geral` exige apenas `requer_escrita` (ALTO).** O endpoint apaga documentos, execuções, sincronizações e configurações Jettax do escritório. Tem proteções (`confirmar=LIMPAR`, recusa com execução em andamento salvo `forcar=true`) — mas **um usuário de papel "operador" pode executá-lo**. O mesmo vale para `POST /documentos/excluir-lote`. Para um sistema cujo ativo é justamente o acervo de XMLs, destruição em massa deve exigir papel admin. Correção: trocar a dependência para `requer_admin`. Uma linha em cada endpoint.

**D.1.3 — Só 3 papéis efetivos (BAIXO).** admin / operador / leitura. Dado que a diretriz operacional diz que o sistema é de **um operador**, isso é adequado. Não recomendo expandir.

## D.2. Worker Celery

**Configuração (boa):** `acks_late=True` (task só é confirmada após concluir — reentrega em caso de morte do worker), `prefetch_multiplier=1` (não acumula tarefas longas num worker), `visibility_timeout=6h` (maior que a maior task), soft time limit 1800 s.

**Beat:** `sincronizar_tudo` a cada 5 min, `completar_xmls_pendentes` a cada 6 h, `varrer_alertas_webhook` a cada 15 min, backup diário.

**D.2.1 — Fila única (MÉDIO).** Todas as tasks vão para a mesma fila. O backup diário (`pg_dump` + cifra + upload S3, potencialmente minutos) ocupa um dos 4 slots de concorrência que deveriam estar importando notas. Em um dia de recuperação de backlog, isso importa. Correção: `task_routes` com filas `importacao`, `manutencao` e `notificacao`, e workers dedicados no compose.

**D.2.2 — `max_retries=0` em `importar_documentos_jettax` (MÉDIO).** A task não tenta de novo em falha transitória de rede. Como o lock é liberado corretamente, não há travamento — mas uma instabilidade de 10 segundos custa uma janela inteira. Dado que a operação é idempotente (ON CONFLICT), retry com backoff exponencial é seguro aqui.

**D.2.3 — Regra de domínio dentro do módulo de task (MÉDIO).** Ver C.3.2.

## D.3. Camada de integração ADN/SEFAZ

**`services/importadores/base.py`** define o contrato (`ImportadorFiscal`, `LoteImportado`, `DocumentoBaixado`) e o limite oficial de 20 consultas pontuais/CNPJ/hora. Bom desenho.

**`nfse_adn.py`** — a extração é **namespace-agnóstica** via `_achatar()`, que transforma a árvore XML em `{caminho: valor}` e busca por sufixo. Defensivo e correto para um leiaute nacional que ainda está estabilizando: um provedor que emita com namespace diferente não quebra a importação.

Observação técnica fina: o tratamento de **HTTP 404 com `StatusProcessamento` contendo "NENHUM"** como "nada novo" (e não como erro) está certo e é exatamente o que o manual descreve. Esse é o tipo de detalhe que só aparece em quem leu a especificação.

**Ponto de atenção em `nfse_adn.py` (~l.505):** `valor_total` é extraído com `float(valor_texto)`. Mesmo corrigindo o tipo da coluna (B7), essa linha precisa virar `Decimal(valor_texto)` — senão a imprecisão entra na origem.

**`_distribuicao_dfe.py`** — SOAP 1.2 montado com `consulta_especifica` como tupla `(tag, xml)`, o que é limpo. `cte_sefaz.py:88` documenta corretamente que o XSD do CT-e **não tem consulta por chave**, só `consNSU`. Detalhe correto e raramente conhecido.

## D.4. Tratamento de erros

`JettaxErro` tem `categoria` (`protocolo`, `configuracao`, `cadastro`, `limite_local`) — permite tratar diferente. `AmbienteIndisponivel` e `ConsumoIndevido` separam falha de infraestrutura de bloqueio oficial, e o worker trata cada um corretamente (5xx **não** consome cota pontual; 656 consome e realinha cursor).

**D.4.1 — `except Exception` amplo em pontos de fallback (BAIXO, aceitável).** Em `fila.py:145` há `except Exception:  # noqa: BLE001 — a fila oficial não pode falhar por causa da Jettax`. O comentário justifica a decisão e ela está certa. Mas o `except` **não loga nada** — a falha da Jettax desaparece. Correção trivial: `logger.exception(...)` dentro do bloco. Depende de B8 para ter valor.

## D.5. `services/acessorias.py`

Cliente httpx travado em `https://api.acessorias.com`, paginação de 20 itens, teto de 100 páginas. Funcional. Mesma classe de risco do `_listar_paginas` da Jettax: teto de páginas sem sinalização de "atingi o teto mas ainda há dados". Auditar pelo mesmo padrão quando o refactor de B1 for feito.

---

# E. Jettax — diagnóstico completo

Esta é a seção mais importante do relatório. Foram pedidas sete respostas exatas. Aqui estão.

## E.1. O que a integração faz HOJE

Inventário funcional real de `services/jettax.py` (1.388 linhas), verificado linha a linha:

| Capacidade | Estado | Onde |
|---|---|---|
| Normalizar token (remover `Bearer`, aspas, espaços, dupla colagem) | OK funciona | `normalizar_token()` l.61-80 |
| Tentar token puro primeiro, cair para `Bearer` em 401/403, **memorizar** o esquema aceito | OK bem feito | l.481, l.532, coluna `esquema_autenticacao` |
| Restringir o envio do token ao par oficial de hosts | OK funciona | `_url_segura()` l.468-478 |
| Recusar seguir redirect (`follow_redirects=False`) para não vazar `Authorization` | OK correto | cliente httpx |
| Redigir segredos das mensagens de erro remotas | OK funciona | `_mensagem_remota()` l.301-320 |
| Sondar host+esquema e persistir o vencedor em 401/403 | OK funciona | `diagnosticar_credencial()` l.337 |
| Sincronizar cliente remoto (GET → PUT se existe, POST se não) | OK idempotente por CNPJ | `_sincronizar_cliente_jettax` |
| **Nunca** chamar `DELETE /api/clients` | OK decisão correta e documentada | `empresas.py:293-295` |
| Enfileirar importação com lock e recuperação de trava expirada | OK desenho correto | `_enfileirar_importacao` |
| Acionar Jettax automaticamente quando a via oficial bloqueia (656/cooldown/erro) | OK funciona | `acionar_fallback_automatico()` l.904, 10 pontos de chamada |
| Receber webhook com validação HMAC de tempo constante | OK funciona | `integracoes.py:560-618` |
| Paginar listagens | **FALHA — BUG CRÍTICO** | `_listar_paginas()` l.650-678 |
| Persistir NFS-e com XML | **FALHA — não persiste XML** | `_persistir_nfse_metadados()` l.1180 |
| Enviar certificado no cadastro remoto | PARCIAL — só se toggle marcado | `carga_cliente()` l.732-735 |
| Enviar credencial de prefeitura | **FALHA — campo não existe** | `models.py:358-388` |
| Preencher `codigo_ibge` automaticamente | **FALHA — nada preenche** | `services/cnpj.py` |
| Disparar importação pela interface | **FALHA — nenhuma tela chama** | `frontend/` |
| Converter XML de NFS-e | FALHA — `_converter_xml` só suporta NFE | l.1332-1334 |
| CT-e via Jettax | Não suportado (decisão consciente e declarada) | l.927-932 |

**Resumo honesto:** a camada de *transporte e segurança* da integração é competente — melhor que a média do mercado. A camada de *funcionalidade* está quebrada em cinco pontos independentes.

## E.2. O que a integração DEVERIA fazer

Objetivo de negócio: **capturar NFS-e municipais que o ADN/Emissor Nacional ainda não cobre**, sem o operador entrar em portal de prefeitura.

Fluxo correto, ponta a ponta:

```
1. CADASTRO LOCAL
   Empresa com CNPJ + razão social + código IBGE (7 dígitos) + inscrição municipal (CCM)
   + UMA credencial de captura municipal:
        (a) certificado A1 (base64 do .pfx) + senha, OU
        (b) login + senha do portal da prefeitura
   → hoje: IBGE não é preenchido, (b) não existe

2. REGISTRO REMOTO
   GET  /api/clients/{cnpj}       → existe?
   POST /api/clients              → cria, com credencial
   PUT  /api/clients/{cnpj}       → atualiza
   Campos confirmados na doc pública: razao_social, codigo_ibge, cnpj, ccm
   (obrigatórios); digital_certificate, digital_certificate_password,
   baixar_nfes, baixar_nfes_enviadas (opcionais). CCM e CNPJ únicos no fornecedor.
   → hoje: implementado, MAS falha por falta de IBGE e pode ir sem credencial

3. HABILITAÇÃO NO FORNECEDOR
   A documentação do Jettax 360 indica que capturar NFS-e exige, no cadastro do
   cliente, A1+senha OU login/senha da prefeitura, MAIS a ativação do módulo de
   serviços na conta.
   → hoje: o sistema não verifica nem reporta isso; se o módulo estiver inativo,
     o sintoma é "lista vazia", indistinguível de "nada novo"

4. CAPTURA
   Polling paginado por cursor (lastId), OU webhook empurrando o ticket.
   → hoje: ambos existem; o polling tem o bug B1 e não é disparável pela UI

5. PERSISTÊNCIA
   Documento gravado com chave de acesso REAL (município no padrão nacional tem
   chNFSe de 44 dígitos) e com o XML arquivado.
   → hoje: chave sintética + sem XML

6. ENTREGA
   A nota aparece na listagem, no ZIP em massa e no download unitário.
   → hoje: aparece na listagem, some do ZIP e do download
```

## E.3. ONDE está o problema — os cinco defeitos, com prova

### E.3.1 — CRÍTICO — `for/else` transforma sucesso em erro

**Local:** `backend/app/services/jettax.py:650-678`

```python
for _ in range(limite):            # limite = JETTAX_MAX_PAGINAS_POR_EXECUCAO, padrão 50
    if not rota_atual:
        break                      # <- ÚNICA saída que evita o else
    ...
    documentos.extend(pagina)
    rota_atual = str(proxima) if proxima else None
else:
    raise JettaxErro(
        "Limite de páginas da Jettax atingido; reduza o período ou aumente "
        "JETTAX_MAX_PAGINAS_POR_EXECUCAO.",
        categoria="limite_local",
    )
return documentos
```

**Por que está errado:** em Python, o bloco `else` de um `for` executa quando o laço **termina por exaustão do iterável**, sem `break`. Quando a última página é buscada exatamente na iteração de número `limite`, `rota_atual` vira `None` **no fim dessa iteração** — o `range` se esgota, o `break` nunca é alcançado, e o `else` dispara. **Todos os documentos foram baixados com sucesso, e mesmo assim é levantada uma exceção.** Os dados coletados em `documentos` são descartados junto com a pilha.

**Prova empírica.** Foi escrito um teste de reprodução isolado (fora do repositório, para não poluir a árvore durante a auditoria) com um cliente falso:

| Cenário | Limite | Resultado |
|---|---|---|
| 3 páginas de resposta | 3 | **FALHA** — `JettaxErro: Limite de páginas da Jettax atingido`, apesar de ter baixado tudo |
| 2 páginas de resposta | 3 | OK — retorna os documentos |

Isto é um off-by-one confirmado, não uma suspeita.

**Por que a suíte de testes do repositório nunca pegou:** o teste existente exercita 2 páginas com limite 3 — cai exatamente no caso que passa. A fronteira `n == limite` nunca é testada.

**Impacto operacional em cadeia:** `executar_importacao` (l.1300) envolve a chamada num `try`. A exceção marca a execução como erro e **o cursor não avança** (`cursor_depois` nunca é gravado). Na próxima rodada, o sistema busca a partir do mesmo `lastId`, baixa as mesmas páginas, estoura o mesmo erro. **Reprocessamento perpétuo**, consumindo quota do fornecedor, sem nunca importar nada. Do ponto de vista do usuário: "não funciona de forma alguma".

### E.3.2 — CRÍTICO — cadastro remoto sem credencial de captura

**Local:** `services/jettax.py:704-735` (`carga_cliente`) e `models.py:358-388` (`JettaxConfiguracaoEmpresa`)

```python
if certificado_base64 is not None and senha_certificado is not None:
    resultado["digital_certificate"] = certificado_base64
    resultado["digital_certificate_password"] = senha_certificado
```

Esses valores só chegam quando o chamador passa `enviar_certificado=True`. No frontend, `registrarJettaxEmpresa(empresaId, enviar_certificado = false)` — **o padrão é `false`**. Ou seja, o caminho mais provável do operador (clicar "Registrar") cria no fornecedor um cliente **sem nenhuma credencial**.

Pior: **não existe campo algum** em `JettaxConfiguracaoEmpresa` para login/senha de prefeitura. Os campos do modelo são: `status`, `ativa`, `baixar_nfes`, `baixar_nfes_enviadas`, três cursores (`ultimo_id_nfse`, `ultimo_id_nfe_saida`, `ultimo_id_nfe_entrada`), timestamps, `ultimo_erro`, `falhas_seguidas`, `travado_em`. Nenhum campo de credencial municipal.

**Por que isso mata a integração:** segundo a documentação do próprio fornecedor (Jettax 360), a captura de NFS-e depende de o cliente ter cadastrada **ou** o A1 **ou** o login/senha da prefeitura. Sem nenhum dos dois, o fornecedor não tem como entrar no portal municipal. O cliente existe, o `GET` responde 200, a listagem de notas volta vazia — e o sistema reporta "nada novo".

Isso explica o sintoma mais frustrante: **tudo parece OK e nenhuma nota chega**.

### E.3.3 — CRÍTICO — `codigo_ibge` obrigatório que nada preenche

**Local:** `services/jettax.py:707-719`, `services/cnpj.py`, `models.py:117`

`carga_cliente` valida corretamente e rejeita antes de chamar a API:

```python
if len(codigo_ibge) != 7:
    faltantes.append("código IBGE")
...
raise JettaxErro("Complete antes do registro Jettax: " + ", ".join(faltantes) + ".",
                 categoria="cadastro")
```

A validação está certa (o `POST /api/clients` documenta `codigo_ibge` como obrigatório). O problema é que **nada no sistema preenche esse campo**:

- `models.py:117` — `codigo_ibge: Mapped[str | None]`, nullable, sem default.
- `services/cnpj.py` — consulta a BrasilAPI e devolve `DadosCNPJ(documento, razao_social, nome_fantasia, uf, municipio)`. Traz o **nome** do município, **não o código IBGE**.
- Nenhuma tabela de municípios IBGE existe no projeto.
- A tela de empresa tem o campo, mas o operador teria que saber e digitar o código de 7 dígitos manualmente.

**Resultado:** para uma empresa cadastrada pelo fluxo normal, "Registrar na Jettax" falha imediatamente com "Complete antes do registro Jettax: código IBGE." — e o operador não tem de onde tirar esse número dentro do sistema.

### E.3.4 — CRÍTICO — não existe botão de importação na interface

**Verificação:** `grep -rn "importarNFSeJettax\|importarNFeJettax" frontend/app` → **zero ocorrências**.

As funções existem em `frontend/lib/api.ts:545-555`. Nenhuma tela as chama. A aba Jettax de `app/dashboard/empresa/Empresa.tsx` (l.605-628) oferece: toggles de `baixar_nfes` / `baixar_nfes_enviadas`, botão "Registrar/atualizar cliente" (`registrarJettaxEmpresa` / `atualizarClienteJettaxEmpresa`), e exibição de cursor e histórico de execuções.

**Não há botão "Importar agora".**

Consequência: a única forma de a Jettax importar algo é (a) o fallback automático disparado por bloqueio da via oficial, ou (b) o webhook. O operador que quer testar "trazer as notas de agosto desta empresa" **não tem como**, e conclui — corretamente, da posição dele — que a integração não funciona.

### E.3.5 — CRÍTICO — NFS-e sem XML: a nota entra mas não pode ser entregue

**Local:** `services/jettax.py:1180-1220`

```python
chave = _normalizar_chave(f"jettax-nfse-{identificador}")
...
"xml_path": "",           # <- sem arquivo
"leiaute": "metadados",
```

O comentário no código é honesto: *"A API documenta metadados e uma URL opcional, mas não documenta contrato de download. Não gravar conteúdo não confirmado como XML."* A decisão defensiva é **compreensível** — gravar lixo como se fosse XML seria pior.

Mas a consequência não foi tratada em nenhum outro lugar do sistema:

1. `_montar_zip` e `baixar_xml` (`api/routers/documentos.py`) dependem de `xml_path`. Nota com `xml_path=""` **não entra no ZIP e não pode ser baixada**. O contador pede "todas as NFS-e de agosto", recebe um ZIP incompleto, e **nada avisa que faltou**.
2. A chave sintética `jettax-nfse-{id}` nunca vai colidir com a chave real de 44 dígitos que o ADN traria para a mesma nota. Se a nota chegar pelas duas vias, viram **dois documentos**. O `UniqueConstraint(empresa_id, chave_acesso)` não protege, e o `DocumentoFiscalFonte` — que existe exatamente para esse caso — não é acionado. (B16)
3. `_converter_xml` só trata `TipoDocumentoFiscal.NFE`; NFS-e nunca passa por conversão de XML.

**Para um sistema cujo produto final é o arquivo XML, importar NFS-e sem XML entrega metade do valor e não sinaliza a metade que falta.** É por isso que classifico como CRÍTICO e não como ALTO.

## E.4. POR QUE falha — hipóteses ordenadas, com o teste de cada uma

Separando o que é certeza do que é hipótese:

**Certezas (no nosso código, verificáveis sem rede):** E.3.1 a E.3.5.

**Hipóteses sobre o lado do fornecedor** (não verificáveis nesta auditoria por falta de egress TLS), ordenadas por probabilidade:

| # | Hipótese | Probab. | Como confirmar em 5 minutos |
|---|---|---|---|
| H1 | Cliente cadastrado no fornecedor **sem credencial de captura** (A1 ou login de prefeitura) → listagem sempre vazia | **Alta** | `GET /api/clients/{cnpj}` e conferir se o retorno indica certificado/credencial; ou olhar o cliente no painel da Jettax |
| H2 | **Módulo de serviços (NFS-e) não ativado** na conta do fornecedor | **Alta** | Conferir no painel Jettax / perguntar ao suporte: "o módulo de serviços está ativo nesta conta?" |
| H3 | Cliente **nunca chegou a ser criado** por falta de `codigo_ibge` (E.3.3) | **Alta** | `GET /api/clients/{cnpj}` → 404 confirma |
| H4 | Município da empresa **não está entre os cobertos** pelo fornecedor | Média | `GET /api/nfse/cities` (o cliente já implementa em `listar_cidades`, l.639) e procurar o IBGE da empresa |
| H5 | Token válido, mas **sem permissão** para as rotas de NFS-e | Média | Chamar `POST /api/clients` (documentado) e `GET /api/nfse/invoices/{cnpj}`; se a primeira responde e a segunda dá 403, é escopo |
| H6 | Rotas `/api/nfse/invoices/{cnpj}` e `/api/nfes/clients/{cnpj}/{sales,purchases}/` **não existem com essa forma** na instância | Baixa-média | Chamar e observar 404 vs 200 vazio |
| H7 | Formato de paginação (`meta.pagination.links.next`) **diferente** do assumido | Baixa-média | Inspecionar o JSON bruto de uma listagem |
| H8 | Token expirado/revogado | Baixa | `diagnosticar_credencial()` já cobre — se 401 em ambos os esquemas e ambos os hosts, é o token |

**Declaração de limite honesta:** a coleção Postman pública da Jettax renderiza **apenas a seção Client** (3 operações: `POST`, `PUT`, `DELETE /api/clients`), **sem corpo de resposta documentado em nenhuma delas**. As rotas de listagem de notas que o conector usa — `/api/nfse/invoices/{cnpj}`, `/api/nfse/cities`, `/api/nfes/clients/{cnpj}/{sales,purchases}/` — **não são confirmáveis por nenhuma fonte pública**. Podem estar certas (vieram de algum lugar), mas nesta auditoria não há como afirmar isso. H6 e H7 permanecem abertas até alguém executar as chamadas contra a instância real com o token do usuário.

## E.5. COMO CORRIGIR

### Correção 1 — o `for/else` (15 minutos, resolve o erro falso)

```python
paginas_lidas = 0
while rota_atual and paginas_lidas < limite:
    paginas_lidas += 1
    url = self._url_segura(rota_atual)
    if url in visitadas:
        raise JettaxErro("A Jettax retornou paginação cíclica.", categoria="protocolo")
    visitadas.add(url)
    resposta = self._requisitar("GET", rota_atual, params=parametros_atuais)
    parametros_atuais = None
    ...  # parsing idêntico ao atual
    documentos.extend(pagina)
    rota_atual = str(proxima) if proxima else None

if rota_atual:                      # SÓ é erro se AINDA há próxima página
    raise JettaxErro(
        f"Limite de {limite} páginas atingido com mais páginas pendentes; "
        f"reduza o período ou aumente JETTAX_MAX_PAGINAS_POR_EXECUCAO.",
        categoria="limite_local",
    )
return documentos
```

O `while` com guarda explícita elimina a classe inteira do bug. A condição de erro passa a ser semanticamente correta: *"parei e ainda havia mais"*, não *"usei todas as iterações"*.

**Melhoria adicional recomendada:** em vez de descartar tudo ao atingir o teto, devolver o que foi coletado **junto com** um marcador de continuação, para que o cursor avance parcialmente. Reprocessar 50 páginas para conseguir a 51ª é desperdício. Exige mudar a assinatura para devolver `(documentos, ha_mais)`.

### Correção 2 — credencial de captura municipal (meio dia)

1. **Modelo** — adicionar a `JettaxConfiguracaoEmpresa`:
   - `credencial_tipo: str` — `"certificado" | "portal" | "nenhuma"`
   - `portal_usuario: str | None`
   - `portal_senha_cifrada: str | None` — **via `core/vault.cifrar_segredo`**, nunca em claro, nunca retornado por API
2. **`carga_cliente`** — passar a **exigir** uma credencial:
   ```python
   if configuracao.credencial_tipo == "nenhuma":
       raise JettaxErro(
           "A Jettax não captura NFS-e sem credencial municipal. Anexe o certificado A1 "
           "ou informe login/senha da prefeitura antes de registrar.",
           categoria="cadastro",
       )
   ```
   Isso transforma uma falha silenciosa (lista vazia para sempre) numa mensagem acionável no momento do cadastro.
3. **Default invertido** — `enviar_certificado` deve ser `True` quando existe A1 ativo. O padrão atual (`false`) é a escolha errada.

> **Declaração explícita:** os nomes de campo para login/senha de prefeitura **não constam na documentação pública** da Morfeu. Antes de implementar, é obrigatório confirmar com o suporte do fornecedor quais chaves usar no `POST /api/clients`. Não vou inventar nomes de campo.

### Correção 3 — código IBGE automático (meio dia)

Duas opções, complementares:

- **(a) Tabela local de municípios IBGE** (5.570 linhas, dado público e estável, ~200 KB). Carregar via seed na migração. `uf + nome do município` → código. Como `services/cnpj.py` já devolve `uf` e `municipio` da BrasilAPI, o preenchimento vira automático no cadastro. **É a opção correta**: zero dependência de rede no caminho crítico e funciona offline.
- **(b) `GET /api/nfse/cities`** do próprio fornecedor (já implementado em `listar_cidades`, l.639) para validar que o município é coberto **antes** de registrar, devolvendo mensagem clara se não for.

Recomendo **(a) para preencher + (b) para validar**.

### Correção 4 — botão de importação na interface (2 horas)

Na aba Jettax de `Empresa.tsx`, adicionar:

- Campo de período (reutilizar `SeletorData`, já existente em `components/ui/`)
- Botão "Importar NFS-e do período"
- Botão "Importar NF-e (entradas/saídas)"
- Exibir o resultado da execução: criados / duplicados / ignorados / fora do período / avisos — todos esses contadores **já são calculados e persistidos** em `JettaxExecucao` (l.1346-1348). Só falta mostrar.

### Correção 5 — XML de NFS-e (1 a 2 dias, depende de confirmação com o fornecedor)

Três caminhos, em ordem de preferência:

- **(a) Se a Jettax expõe download de XML** (a persistência atual menciona "uma URL opcional"): baixar, validar que é XML bem-formado, arquivar no mesmo volume das demais notas, gravar `xml_path` e `leiaute="completo"`. **Confirmar o contrato de download com o fornecedor antes.**
- **(b) Se o município está no padrão nacional** e a nota tem `chNFSe` de 44 dígitos: usar a chave real como `chave_acesso` (resolve B16 de brinde) e buscar o XML pelo ADN. A Jettax vira a fonte de *descoberta*, o ADN a fonte de *conteúdo*. Arquiteturalmente é a melhor solução onde aplicável.
- **(c) Se nenhum dos dois:** manter metadados, mas **tornar a lacuna visível**. Concretamente:
  - `leiaute="metadados"` exibido na UI como etiqueta "sem XML";
  - o ZIP em massa deve **incluir um `AUSENTES.txt`** listando as notas que não puderam ser empacotadas e o motivo;
  - a tela de conferência de competência deve contar essas notas separadamente.

  O erro atual não é não ter o XML — é **não avisar** que não tem.

### Correção 6 — instrumentação do conector (meio dia; faça primeiro)

Antes de qualquer correção funcional, instrumente. Cada chamada à Jettax deve logar em JSON: método, rota (sem query com dados sensíveis), status HTTP, tempo, quantidade de itens, cursor antes/depois, `execucao_id`. Sem isso, as hipóteses H1-H8 continuam sendo hipóteses. **Este é o item de maior retorno por hora investida em toda a seção E.**

## E.6. COMO TESTAR

### E.6.1 — Testes unitários (rodam hoje, sem rede)

```python
def test_paginacao_com_numero_de_paginas_igual_ao_limite(monkeypatch):
    """Regressão do for/else: N páginas com limite N deve ter sucesso."""
    monkeypatch.setattr(settings, "jettax_max_paginas_por_execucao", 3)
    cliente = _cliente_falso(paginas=3)          # 3 páginas, a 3ª sem "next"
    documentos = cliente._listar_paginas("/api/nfse/invoices/00000000000191", {})
    assert len(documentos) == 3                  # HOJE: levanta JettaxErro

def test_paginacao_estoura_quando_ha_mais_paginas_que_o_limite(monkeypatch):
    monkeypatch.setattr(settings, "jettax_max_paginas_por_execucao", 3)
    cliente = _cliente_falso(paginas=5)          # 4ª página existe
    with pytest.raises(JettaxErro, match="páginas pendentes"):
        cliente._listar_paginas("/api/nfse/invoices/00000000000191", {})

def test_carga_cliente_recusa_sem_credencial_municipal():
    with pytest.raises(JettaxErro, match="credencial"):
        carga_cliente(empresa_completa, config_sem_credencial)

def test_carga_cliente_exige_ibge_com_mensagem_acionavel():
    with pytest.raises(JettaxErro, match="código IBGE"):
        carga_cliente(empresa_sem_ibge, config)
```

O primeiro teste é o mais importante do relatório inteiro: **ele falha hoje** e é a prova do B1.

### E.6.2 — Contract tests com fixtures gravadas

Gravar **uma vez** (em ambiente com rede) o JSON bruto de cada rota usada, redigir os segredos, e versionar em `backend/tests/fixtures/jettax/`. A partir daí, o conector é testado contra a forma real do payload sem depender de rede. Hoje isso **não existe** e é a lacuna de teste mais cara do projeto.

### E.6.3 — Roteiro de diagnóstico ao vivo (executar com o token do usuário, nesta ordem)

```
Passo 1 — o token vale alguma coisa?
  Rodar diagnosticar_credencial(token, base_url).
  Já testa os 2 hosts x 2 esquemas e diz qual combinação responde.
  Se todas derem 401 → o problema é o token. Pare aqui.

Passo 2 — o cliente existe no fornecedor?
  GET /api/clients/{cnpj}
  404 → nunca foi criado (provável H3: faltou IBGE)
  200 → conferir no corpo se há indicação de certificado/credencial (H1)

Passo 3 — o município é coberto?
  GET /api/nfse/cities  → procurar o código IBGE da empresa
  Ausente → H4. A Jettax não é a via para esta empresa; use ADN.

Passo 4 — a rota de notas responde?
  GET /api/nfse/invoices/{cnpj}
  404 → H6 (rota diferente da assumida no código)
  403 → H5 (escopo do token)
  200 com lista vazia → H1 ou H2 (sem credencial ou módulo inativo)
  200 com dados → o problema é 100% nosso: é o B1

Passo 5 — a forma da paginação bate?
  Inspecionar o JSON: existe meta.pagination.links.next?
  Não → H7, ajustar o parsing.
```

**Cada passo elimina hipóteses.** Em menos de 15 minutos com rede, o diagnóstico fica fechado.

### E.6.4 — Teste de aceitação ponta a ponta

> Empresa real, com IBGE, CCM e A1 válido → "Registrar na Jettax" → cliente criado com certificado → "Importar NFS-e de 08/2026" → N notas aparecem na listagem → ZIP de 08/2026 contém N arquivos (ou contém `AUSENTES.txt` explicando exatamente quantas e por quê).

Enquanto esse teste não passar, a integração não está pronta. E note: **ele não passa hoje em nenhum dos cinco pontos.**

## E.7. ARQUITETURA CORRETA para a Jettax

O erro conceitual de fundo é que **`services/jettax.py` é ao mesmo tempo cliente HTTP, mapeador de domínio, política de fallback e camada de persistência**, em 1.388 linhas. Separar em quatro responsabilidades:

```
app/integracoes/jettax/
├── cliente.py       # SÓ HTTP: auth, hosts, retry, paginação, redação de segredos.
│                    # Devolve dict cru. Não conhece Empresa nem DocumentoFiscal.
├── mapeador.py      # SÓ tradução: dict cru -> DocumentoBaixado (o MESMO dataclass
│                    # usado por ADN/SEFAZ). Funções puras, testáveis com fixtures.
├── provedor.py      # Implementa a interface ProvedorNFSe (seção F.4).
└── politica.py      # Quando acionar como fallback, janela de repetição,
                     # deduplicação de acionamento.

A persistência sai daqui e passa a ser a MESMA de ADN/SEFAZ
(_inserir_documento_sem_duplicar), com DocumentoFiscalFonte registrando a origem.
```

**Ganhos concretos, não estéticos:**

1. **NFS-e da Jettax passa a percorrer o mesmo caminho de persistência do ADN** — herda deduplicação por chave real, `DocumentoFiscalFonte`, filtro de competência e arquivamento de XML. O bug E.3.5 deixa de existir por construção, em vez de ser corrigido caso a caso.
2. **`cliente.py` fica testável com fixtures** sem tocar em banco.
3. **`politica.py` concentra as 10 chamadas de fallback espalhadas** em `worker/tasks.py`.
4. **Trocar de fornecedor** (ou adicionar um segundo) passa a ser implementar `provedor.py`, não caçar `if` no worker.

**Custo:** 2 a 3 dias. **Não é reescrita** — é mover código existente para arquivos com fronteiras claras. A lógica de autenticação, `_url_segura`, redação de segredos e o lock de enfileiramento são preservados integralmente: são as partes boas.

**Ordem correta:** primeiro as correções 1-6 (fazem a integração **funcionar**), depois o refactor (faz ela **durar**). Não inverta — refatorar código quebrado só produz código quebrado mais bonito.

---

# F. NFS-e e portais municipais

## F.1. O problema real do NFS-e no Brasil

NFS-e é municipal. Até a padronização nacional, cada um dos 5.570 municípios podia escolher leiaute, protocolo, autenticação e regra de emissão. Na prática existem: o padrão nacional (ADN), alguns provedores privados dominantes (GINFES, ISSNet, WebISS, Betha, Simpliss, entre outros) e centenas de sistemas próprios.

**Consequência arquitetural inescapável:** qualquer plataforma séria de captura de NFS-e precisa de uma **camada de provedores**. Não é over-engineering — é a forma do problema.

## F.2. Estratégia atual do projeto: avaliação

O projeto tem **duas** vias:

| Via | Cobertura | Estado |
|---|---|---|
| ADN (padrão nacional) | Municípios ativos no padrão nacional | Bem implementada |
| Jettax | Municípios cobertos pelo fornecedor (marketing: +2.200) | Quebrada (seção E) |

**A escolha das duas vias está estrategicamente certa.** ADN é a via oficial, gratuita, estável e crescente. Um agregador comercial cobre a cauda longa que o ADN ainda não alcança. Essa é a arquitetura que eu recomendaria se o projeto estivesse começando do zero.

**O que está errado é a execução:**

1. As duas vias não compartilham nada — nem interface, nem modelo de cursor, nem persistência.
2. **Não existe roteamento por município.** Nada no sistema responde "para esta empresa, qual via devo usar?". `quais_tipos_sincronizar` decide o **tipo** (nfse/nfe/cte), nunca a **origem**.
3. **Não há fallback ordenado.** A Jettax só é acionada quando a via oficial *bloqueia* (656/cooldown/erro) — nunca quando a via oficial simplesmente *não cobre* aquele município. Esse é o caso mais comum e não está tratado.
4. **Não há normalização comum.** ADN produz `DocumentoBaixado`; Jettax produz um dict que vai direto para o banco por caminho próprio.

## F.3. Dado público de 2026 que muda o cálculo de investimento

- **~5.070 municípios** já assinaram Termo de Adesão ao NFS-e Nacional (posição de 15/12/2025). **Atenção:** adesão ≠ operacional — cada município ainda precisa parametrizar e definir data de vigência.
- **~2.000 municípios** já operam no Emissor Nacional (posição de 27/05/2026).
- **A cartilha oficial "Perguntas e Respostas NFS-e" v1.00, de 08/09/2026, estabelece que a partir de 01/11/2026 ME/EPP do Simples Nacional emitem exclusivamente pelo Emissor Nacional** (Web ou API), e os sistemas próprios de prefeitura deixam de autorizar essas notas.

**Leitura estratégica:** a cobertura do ADN está crescendo rápido, e a partir de novembro de 2026 uma fatia grande do volume de NFS-e do país passa obrigatoriamente pelo padrão nacional para uma classe inteira de contribuintes.

**Recomendação derivada:** **o ADN deve ser a via preferencial por padrão, e o agregador comercial a exceção.** Não invista pesado em cobertura de agregador para municípios que estarão no ADN em poucos meses. Consertar a Jettax é necessário (é a cobertura de hoje), mas o investimento arquitetural de longo prazo vai para o ADN. Isso também reduz custo de fornecedor ao longo do tempo.

> **Ressalva obrigatória:** vigência e obrigatoriedade dependem de calendário oficial e de parametrização municipal, que mudam. Confirme a situação de cada município antes de decisão operacional. Não trate as datas acima como garantia.

## F.4. Camada de abstração proposta

```python
# app/integracoes/nfse/protocolo.py
from typing import Protocol

class ProvedorNFSe(Protocol):
    """Contrato único para qualquer origem de NFS-e."""

    nome: str                    # "adn" | "jettax" | "ginfes" | ...
    prioridade: int              # menor = tentado primeiro

    def cobre(self, empresa: Empresa) -> bool:
        """Este provedor atende o município/regime desta empresa?
        Resposta local e barata — NUNCA faz chamada de rede."""

    def requisitos(self, empresa: Empresa) -> list[Requisito]:
        """O que falta para funcionar: A1, CCM, IBGE, login de portal,
        módulo habilitado no fornecedor. Alimenta a tela de diagnóstico e
        permite avisar ANTES de tentar — é isto que transforma
        'não funciona' em 'falta o CCM da empresa X'."""

    def capturar(self, empresa: Empresa, periodo: Periodo,
                 cursor: Cursor | None) -> ResultadoCaptura:
        """Captura efetiva. Devolve DocumentoBaixado — o MESMO dataclass do
        ADN/SEFAZ — mais o cursor novo e diagnósticos."""
```

Com um `RegistroDeProvedores` que resolve, para cada empresa, a lista ordenada de provedores que a cobrem, e um orquestrador que tenta em ordem e registra em `DocumentoFiscalFonte` quem trouxe o quê.

**Por que esse desenho e não outro:**

- `cobre()` local evita gastar chamada de rede para descobrir que o provedor não atende — importante a 1.000 empresas.
- `requisitos()` é o que resolve a classe inteira de problema "não funciona e não sei por quê". É a peça que falta hoje e a de maior valor operacional.
- Devolver `DocumentoBaixado` (dataclass que **já existe**) força a normalização e permite persistência única.
- `Protocol` em vez de classe base abstrata: menos acoplamento, sem hierarquia forçada.

**Custo:** 3 a 5 dias, incluindo migrar ADN e Jettax para a interface. **Só faça depois** de a Jettax estar funcionando (seção E).

## F.5. Emissor Nacional / Portal Nacional — captura em lote de XMLs

Foi pedido explicitamente: verificar via oficial primeiro e **não recomendar scraping de qualquer maneira**.

**Existe via oficial? SIM.** O Ambiente de Dados Nacional (ADN) é exatamente isso, e o contrato (conforme o Manual dos Municípios) é:

| Operação | Contrato oficial | Implementado? |
|---|---|---|
| `GET /DFe/{UltimoNSU}` | Devolve até **50 DF-e** por chamada, sequencial por NSU | Sim — `nfse_adn.py` |
| `GET /DFe/{NSU}` | Consulta unitária por NSU | Sim |
| `POST /DFe/` | Envio de lote: ≤ 50 DF-e, ≤ 1 MB, **em ordem crescente de NSU** | n/a (só recepção) |
| Rejeição de schema | Documento a documento, não o lote inteiro | Sim — tratado |
| Documentos compartilhados pelo próprio município | **Não retornam** na consulta | Limitação oficial, não bug |
| Autenticação | mTLS com certificado digital | Sim — `services/mtls.py` |

**Veredito: a arquitetura de captura do NFS-e Nacional neste projeto está correta e alinhada ao contrato oficial.** Elogio técnico merecido: os limites de 50 por lote, o cooldown de 1 h, o respeito ao `Retry-After` e o tratamento do 404/`NENHUM_DOCUMENTO_LOCALIZADO` como "nada novo" estão todos implementados como a especificação manda.

**Sobre scraping do portal gov.br — recomendação: NÃO.** Justificativa técnica e jurídica, não ideológica:

*Técnica:*
1. **A via oficial já existe e cobre o caso de uso.** Scraping aqui não resolveria nenhum problema que a API não resolva. Essa razão sozinha encerra a discussão.
2. O portal de consulta pública tem **filtro limitado a 30 dias** e não oferece consulta em massa — seria mais lento e menos confiável que o ADN.
3. Autenticação gov.br envolve certificado digital e/ou fluxo de conta gov.br, com sessão que expira e mecanismos anti-automação. Manutenção permanente contra mudanças de HTML.
4. Sem NSU, não há cursor confiável → impossível garantir que nada foi perdido. Isso **destrói** a propriedade central do produto ("nenhum documento se perde").

*Jurídica (área do Direito, não da Engenharia — consulte um advogado):*
5. Automação não autorizada contra sistema de governo pode configurar violação dos termos de uso e, dependendo da forma, ter implicações na Lei 12.737/2012 (invasão de dispositivo informático) e na LGPD quanto ao tratamento de dados de terceiros.
6. Bloqueio do CNPJ ou do certificado por uso considerado indevido é risco operacional concreto — o próprio tratamento de cStat 656 no projeto mostra que a consciência desse risco já existe.

**Para municípios fora do padrão nacional**, onde não há API oficial: use agregador comercial (Jettax e similares), que assume o risco contratual e a manutenção. Se um município específico e relevante não tiver nenhuma via, a resposta honesta é **"este município exige operação manual hoje"**, e o sistema deve **dizer isso na tela** (via `requisitos()` da seção F.4) em vez de fingir cobertura. Uma lacuna declarada é infinitamente melhor que uma lacuna silenciosa.

---

# G. SEFAZ (NF-e / CT-e)

## G.1. A abordagem atual faz sentido?

**Sim, e é a abordagem certa.** A distribuição DFe (`NFeDistribuicaoDFe` / `CTeDistribuicaoDFe`) com certificado A1 e controle de NSU é o mecanismo oficial e correto para capturar documentos de interesse de um CNPJ. Não há alternativa melhor. O projeto não inventou nada aqui, e isso é o elogio.

Conferência do que o contrato oficial exige contra o que está implementado:

| Regra oficial | Implementado | Onde |
|---|---|---|
| SOAP 1.2 | Sim | `_distribuicao_dfe.py` |
| mTLS com A1 | Sim | `services/mtls.py` |
| `distNSU` sequencial | Sim | `nfe_sefaz.py`, `cte_sefaz.py` |
| Máximo 50 documentos por lote | Sim | `sincronizacao.py` |
| cStat 137 = nada novo → cooldown 1 h | Sim | `marcar_sem_novidade()` |
| cStat 656 = consumo indevido → **realinhar pelo `ultNSU` devolvido** | Sim | `realinhar_cursor()` l.150 |
| `consChNFe` / `consNSU` ≤ 20 por hora por CNPJ | Sim | `consumir_cota_pontual()` |
| Intervalo mínimo entre consultas | Sim (50/2 s) | `sincronizacao.py` |
| CT-e não tem consulta por chave, só `consNSU` | Sim — documentado no código | `cte_sefaz.py:88` |
| `cUFAutor` na consulta | Sim (por isso `Empresa.uf` é obrigatório) | `models.py:108` |
| **Manifestação do destinatário (210200/210210)** | **AUSENTE** | — |

Detalhe adicional bem resolvido: `avançar_cursor()` **nunca regride** e o cursor é calculado sobre **todos** os itens recebidos, inclusive eventos — o comentário em `nfse_adn.py` explica que calcular só sobre documentos válidos fazia a importação repetir ou parar ao encontrar um cancelamento no meio do lote. Esse é um bug real que já foi corrigido.

## G.2. A lacuna conceitual: manifestação do destinatário — ALTO

`grep` exaustivo: **não há nenhuma implementação de evento de manifestação em todo o backend.**

**Por que isso é grave, mecanicamente:**

Quando uma NF-e é emitida **contra** o CNPJ da empresa (entrada), a distribuição DFe entrega inicialmente apenas o **resumo** (`resNFe`) — chave, emitente, valor, data. O **XML completo** é liberado ao destinatário **após** a manifestação (tipicamente "Ciência da Operação", 210210, ou "Confirmação da Operação", 210200).

O projeto sabe disso — o comentário em `models.py:208-210` diz literalmente: *"a SEFAZ libera o XML completo do destinatário após manifestação — dá para buscar pela chave, e o botão 'completar XML' faz isso respeitando a cota de 20/h"*.

**Mas a manifestação nunca é feita.** O `completar_xmls_pendentes` chama `consChNFe` para documentos em `leiaute="resumo"` — sem ter manifestado antes. Resultado provável: a consulta não devolve o XML completo, e o sistema **queima cota pontual (20/h, recurso escasso) sem resultado**, indefinidamente, a cada 6 horas.

**Impacto de negócio:** para um escritório de contabilidade, **NF-e de entrada é metade do trabalho** (crédito de ICMS/PIS/COFINS, conferência de compras). Hoje o sistema entrega resumos em vez de XMLs para essa metade. Se o operador precisa buscar esses XMLs em outro lugar, o produto falhou no objetivo declarado de "não depender de operação manual em portais".

**Correção:**

1. Implementar `NFeRecepcaoEvento` com `tpEvento=210210` (Ciência da Operação) para documentos de entrada em `leiaute="resumo"`.
2. Só depois chamar `consChNFe` para o XML completo.
3. Respeitar o prazo legal: a manifestação tem janela definida na legislação — **não vou afirmar o prazo exato aqui**; confirme no Manual de Orientação do Contribuinte vigente antes de implementar.
4. **Decisão de produto que exige o usuário:** "Ciência da Operação" (210210) é operação de baixo compromisso. "Confirmação da Operação" (210200) tem efeito fiscal de reconhecimento da transação. **Automatizar 210200 sem decisão explícita do contribuinte é errado** — pode-se estar confirmando nota indevida ou fraudulenta. A recomendação técnica é: **automatizar 210210, nunca 210200 sem ação humana.**

> Prazos, efeitos e obrigatoriedade de manifestação por segmento dependem de legislação federal e estadual vigente. Isto é uma recomendação de arquitetura, não uma orientação fiscal.

## G.3. Outros pontos

**G.3.1 — Não há como reprocessar a partir de um NSU anterior (MÉDIO).** `avançar_cursor()` **nunca regride** por design (correto), e `realinhar_cursor()` só é chamado quando a própria SEFAZ manda. Não existe endpoint administrativo para "reprocessar a partir do NSU X". Se um bug de parsing corromper 200 documentos, a única forma de reimportar é `POST /sistema/reset-geral` — que apaga também as `sincronizacoes_dfe` e todo o acervo do escritório. **Destruição total para resolver um problema pontual.** Desproporcional.

Correção: endpoint `POST /importacoes/{empresa_id}/reposicionar-cursor` restrito a admin, com auditoria obrigatória e aviso de que consultar NSU antigo conta contra a regra de consumo. É a válvula que todo sistema de captura precisa ter.

**G.3.2 — `dias_disponiveis_na_distribuicao = 90` (BAIXO, verificar).** Definido em `core/config.py:96` e usado em `importacoes.py:528` e `:780` para alertar que a empresa não é varrida há muito tempo. O número 90 é plausível como janela de retenção da distribuição, mas **é um parâmetro operacional que depende do ambiente oficial**; confirme contra a documentação vigente e documente a fonte no `config.py`.

**G.3.3 — Ausência de ambiente de homologação configurável para NF-e (BAIXO).** `nfse_adn.py` aceita `ambiente="producao"|"homologacao"`. Não identifiquei o mesmo grau de parametrização para NF-e/CT-e. Testar mudanças contra homologação é o que evita bloqueio em produção.

---

# H. Banco de dados

## H.1. Modelagem

**Bom:** entidades corretas e bem nomeadas (`Escritorio`, `Empresa`, `Certificado`, `DocumentoFiscal`, `DocumentoFiscalFonte`, `ExecucaoImportacao`, `SincronizacaoDFe`, `EventoFiscalPendente`, `JettaxConfiguracaoEmpresa`, `JettaxExecucao`). Multi-tenancy por `escritorio_id` com `UniqueConstraint(escritorio_id, cnpj_cpf)`. Separação estado × histórico. `DocumentoFiscalFonte` para proveniência.

### H.1.1 — `valor_total` como `float` — ALTO

```python
valor_total: Mapped[float] = mapped_column()     # models.py:206
```

No PostgreSQL isso vira `DOUBLE PRECISION`. Ponto flutuante binário **não representa exatamente** valores decimais como 0,10 ou 1.234,56.

Consequência prática, não teórica: somar 10.000 notas para um fechamento mensal acumula erro. O contador confere R$ 1.234.567,89 e o sistema mostra R$ 1.234.567,90. Ele perde a confiança no sistema inteiro — e está certo.

Agrava: os schemas Pydantic também usam `float` (`schemas.py` l.439, 490, 785, 795, 803, 810, 841, 850, 858, 1010), e `nfse_adn.py` (~l.505) faz `float(valor_texto)`. **A imprecisão entra na origem e se propaga.**

**Correção completa (ordem obrigatória):**
1. Coluna → `Numeric(15, 2)`
2. Schemas → `condecimal(max_digits=15, decimal_places=2)`
3. Extração nos importadores → `Decimal(texto)`, nunca `float(texto)`
4. Serialização JSON → string, para o JS não reintroduzir float no frontend
5. Arredondamento explícito → `ROUND_HALF_UP` (a convenção usual em documento fiscal brasileiro é meio para cima; **confirme a regra aplicável ao tributo específico** antes de fixar)

**Bloqueio real:** o passo 1 exige alterar tipo de coluna, e `db/migracoes.py` **não sabe fazer isso**. Portanto **B9 (Alembic) é pré-requisito de B7**. Essa dependência aparece no plano (seção Q).

### H.1.2 — `chave_acesso` como `String(60)` com valores sintéticos — MÉDIO

Chave de NF-e/CT-e/NFS-e nacional tem 44 dígitos. O campo tem 60 para acomodar `jettax-nfse-{id}`. Isso significa que a coluna de identidade fiscal **mistura identificador fiscal real com identificador de fornecedor**, e nenhuma constraint distingue os dois. Deduplicação cross-fonte fica impossível (B16).

Correção: `chave_acesso` só recebe chave fiscal real (ou `NULL`); identificador de fornecedor vai para `DocumentoFiscalFonte.identificador_externo`, que **já existe exatamente para isso**. Para nota sem chave fiscal, gerar identidade determinística de `(empresa_id, tipo, numero, serie, emitente_documento, data_emissao)` — reproduzível e colidível corretamente entre fontes.

### H.1.3 — Enums nativos do PostgreSQL — BAIXO

`TipoDocumentoFiscal`, `DirecaoDocumento`, `StatusDocumentoFiscal`, `StatusExecucao` são `Enum` nativos. Adicionar valor exige `ALTER TYPE ... ADD VALUE`, que **não roda dentro de transação** — o `migracoes.py` já contorna isso, e o comentário no arquivo documenta uma armadilha real (`.name` vs `.value`) que já causou falha em produção: usar o `.value` minúsculo criava um rótulo que o SQLAlchemy nunca consultava, e toda leitura/escrita de `StatusExecucao.AGUARDANDO` falhava.

Não é urgente. Se houver mudança estrutural futura, `VARCHAR` + `CHECK` é mais flexível ao custo de menos rigor. Deixe como está por ora.

### H.1.4 — Ausência de campos fiscais relevantes — MÉDIO

`DocumentoFiscal` guarda valor total, mas **não** guarda a decomposição que um escritório precisa: base de cálculo, alíquota, ISS retido, PIS/COFINS/CSLL/IR/INSS retidos, código do serviço, município de incidência, CNAE, natureza da operação.

Hoje isso está dentro do XML, não consultável. Consequências: não dá para responder "quanto de ISS retido no mês" sem abrir XML por XML; não dá para conferir retenções; não dá para relatório de apuração.

**Não recomendo criar 20 colunas agora.** Recomendo o caminho incremental: **uma coluna `dados_fiscais JSONB`** populada na importação com o que o leiaute oferecer, mais índices GIN sobre as chaves efetivamente consultadas. Quando um campo provar uso constante, promova a coluna real com índice.

> Quais campos são obrigatórios em cada leiaute e como cada tributo é apurado depende de legislação federal/municipal e do leiaute vigente. Este relatório indica **onde** guardar, não **como** calcular. Não implemente cálculo tributário sem validação de um especialista fiscal.

## H.2. Índices

Existentes (`db/migracoes.py:88-98`):

```
ix_documentos_competencia               (competencia)
ix_documentos_empresa_competencia       (empresa_id, competencia)
ix_documentos_tipo_competencia          (tipo, competencia)
ix_documentos_empresa_tipo              (empresa_id, tipo)
ix_documentos_emitente                  (emitente_documento)
ix_execucoes_empresa_tipo_status        (empresa_id, tipo, status)
ix_sincronizacao_empresa_tipo           (empresa_id, tipo) UNIQUE
ix_jettax_execucao_empresa_status       (empresa_id, status)
ix_jettax_webhook_ticket                (ticket)
```

Boa cobertura para os filtros das telas. **Faltam**, considerando as consultas que o código realmente faz:

| Índice sugerido | Consulta que o justifica |
|---|---|
| `(empresa_id, tipo, competencia)` | Filtro combinado da tela de documentos — hoje usa dois índices parciais |
| `(empresa_id, data_emissao)` | `data_referencia_sql()` filtra por emissão (`documentos.py:182-189`) e **não há índice** |
| `(empresa_id, leiaute)` parcial `WHERE leiaute='resumo'` | `completar_xmls_pendentes` varre isso a cada 6 h |
| `(escritorio_id, ativa)` em `empresas` | `sincronizar_tudo` varre a cada 5 min |
| GIN trigram nas colunas de busca textual | H.3 |

**O de `data_emissao` é o mais importante** e está ausente: o filtro de período da listagem principal é por data de emissão, não por competência.

## H.3. Busca textual — ALTO acima de 100k documentos

`api/routers/documentos.py` faz `LIKE '%termo%'` em **8 colunas** (chave, número, emitente nome/documento, destinatário nome/documento, situação…). `LIKE` com curinga à esquerda **não usa índice B-tree**. É sequential scan da tabela inteira a cada busca.

Projeção: 100k documentos → busca na casa de segundos; 1M → dezenas de segundos e pressão de I/O que degrada a importação simultânea.

**Correção, em ordem de custo:**
1. `CREATE EXTENSION pg_trgm` + índice GIN `gin_trgm_ops` nas 2-3 colunas realmente buscadas por texto livre. Resolve `LIKE '%x%'` mantendo a query igual. **Melhor relação custo/benefício.**
2. Para nome de emitente/destinatário, `tsvector` + GIN com busca por prefixo dá resultado melhor.
3. Chave de acesso e número **não devem** usar `LIKE '%…%'` — são identificadores; busca exata ou por prefixo, com índice B-tree comum.

O item 3 é gratuito e provavelmente responde pela maioria das buscas reais.

## H.4. Particionamento e retenção — MÉDIO hoje, ALTO em 1M+

Não há particionamento nem política de retenção. `documentos_fiscais` cresce indefinidamente.

Aritmética simples: 1.000 empresas × 200 documentos/mês × 12 meses = **2,4M linhas/ano**, mais o volume de XMLs em disco.

**Recomendação:** particionar `documentos_fiscais` por `RANGE (competencia)`, uma partição por ano (não por mês — 12× mais partições sem ganho proporcional, e o planner sofre). Ganhos: consulta de competência atinge uma partição só; arquivar ano antigo vira `DETACH PARTITION` (operação de metadados, instantânea) em vez de `DELETE` de milhões de linhas.

**Atenção:** particionamento exige que a chave de partição faça parte da PK/unique. Hoje `UniqueConstraint(empresa_id, chave_acesso)` não inclui `competencia`. Isso precisa ser resolvido no desenho — é exatamente o tipo de mudança que se faz **antes** de ter 2M linhas, não depois. **Planeje agora, execute antes dos 500k.**

**Retenção de XML:** documento fiscal tem prazo legal de guarda (varia por tributo e situação — **confirme com o contador**; a referência frequentemente citada é 5 anos). Depois disso, mover para storage frio (S3 Glacier ou equivalente) mantendo os metadados no banco. Hoje não existe nada disso, e o volume só cresce.

## H.5. Migrações — ALTO

`db/base.py::criar_tabelas()` = `create_all()` + `aplicar_migracoes()` artesanal.

O que `db/migracoes.py` faz bem: `ALTER TABLE ADD COLUMN` idempotente, `CREATE INDEX IF NOT EXISTS`, `ALTER TYPE ADD VALUE` fora de transação, backfill de `competencia`. Para o estágio atual, funcionou.

O que ele **não** faz, e por isso é bloqueio:
- **Não altera tipo de coluna** → B7 (`FLOAT → NUMERIC`) é impossível hoje
- **Não versiona** → não há como saber em que revisão um banco está
- **Não faz downgrade** → deploy ruim não tem volta
- **Não renomeia nem remove** coluna
- **Não suporta migração de dados complexa** (ex.: recalcular competência com timezone correto)
- **Não coordena múltiplas instâncias** → duas APIs subindo juntas rodam migração concorrente

A própria docstring de `db/base.py` já declara Alembic como o ponto de troca antes de produção com dado real. **Concordo integralmente — e classifico como bloqueio, não como preferência.**

**Migração para Alembic:** `alembic init`, gerar a revisão inicial por autogenerate contra o schema atual, marcar os bancos existentes com `alembic stamp head`, e converter `migracoes.py` em revisões. 1 a 2 dias. **É pré-requisito de H.1.1, H.1.2 e H.4.**

## H.6. Pool de conexões — MÉDIO, vira ALTO em carga

`create_engine` sem `pool_size`/`max_overflow` → padrão do SQLAlchemy: 5 permanentes + 10 overflow.

Contas: worker `--concurrency=4` + API com N workers uvicorn + Beat. Sob carga, `TimeoutError: QueuePool limit of size 5 overflow 10 reached` — e o sintoma não é "lento", é **erro 500 na API enquanto a importação roda**.

Correção (uma linha, alto retorno):
```python
create_engine(
    url,
    pool_size=10, max_overflow=20,
    pool_pre_ping=True,     # descarta conexão morta — essencial com PgBouncer/restart de PG
    pool_recycle=1800,      # evita conexão derrubada por timeout de rede
)
```
E confirmar que `max_connections` do PostgreSQL comporta a soma de todos os processos.

---

# I. Segurança

Reordeno para respeitar a diretriz operacional: começo pelo que protege **dado**, depois o que protege **acesso**.

## I.1. Proteção do acervo (é confiabilidade, prioridade 2 da diretriz)

**I.1.1 — `POST /sistema/reset-geral` sem exigir admin — ALTO.** Detalhado em D.1.2. Apaga documentos, execuções, sincronizações e configurações Jettax. Exige `confirmar=LIMPAR` e recusa com execução em andamento (salvo `forcar=true`) — proteções reais, mas **o papel exigido é `requer_escrita`**. Um operador pode zerar o acervo. Correção: `requer_admin`. Uma linha.

**I.1.2 — `POST /documentos/excluir-lote` sem exigir admin — ALTO.** Mesma classe. Exclusão em massa de documentos fiscais deve ser privilégio de admin.

**I.1.3 — Não há "lixeira" nem soft delete — MÉDIO.** Exclusão é física e imediata. Para um acervo com valor legal, soft delete com expurgo pós-janela (ex.: 30 dias) é barato e evita perda definitiva por engano. O `DocumentoFiscal` já tem `status`; adicionar `excluido_em` é trivial.

**I.1.4 — Backup: bom.** JSONL gzip + `pg_dump`, manifesto com hashes, Fernet, S3 obrigatório. **O que não vi: teste de restauração.** Backup não testado é hipótese de backup. Recomendo task mensal que restaura em banco temporário e valida contagens.

**I.1.5 — Exclusão de empresa é cuidadosa e merece nota.** `excluir_empresa` recusa com importação em andamento (409), apaga na ordem explícita para funcionar igualmente em SQLite e PostgreSQL sem depender de cascatas do banco, e **jamais chama `DELETE /api/clients`** na Jettax — com comentário explicando que esse DELETE apagaria as notas remotas. Decisão correta e bem documentada.

## I.2. Credenciais e certificados — o ponto mais forte

| Item | Estado |
|---|---|
| PFX em disco | **Sempre cifrado** (Fernet + marcador), escrita atômica, 0700/0600, migra legado em claro |
| Senha do certificado | `core/vault.cifrar_segredo()`, nunca em claro |
| PEM temporário para mTLS | tmpdir 0700/0600, apagado na saída do context manager |
| Token Jettax | Cifrado por escritório |
| Validação CNPJ do A1 vs. empresa | Impede usar certificado de outra empresa |
| Segredos em log | `_mensagem_remota()` redige sequências longas sem espaço (formato de token/JWT) |
| Token só vai para hosts oficiais | `_url_segura()` |
| Redirect não seguido | Evita vazar `Authorization` em 3xx |

**Isso está acima da média de mercado.** Não mexa, exceto:

**I.2.1 — Não há rotação de chave do cofre — MÉDIO.** Se `FERNET_KEY` vazar, não há procedimento de rotação. Já está no ROADMAP como "rotação assistida das chaves do cofre". Correção: suportar lista de chaves (`MultiFernet`), decifrando com qualquer uma e recifrando com a primeira.

**I.2.2 — Nenhum alerta de certificado vencido bloqueia a fila — BAIXO.** Existe alerta na central, mas a importação tenta mesmo assim e falha no handshake. Melhor: `fila.py` recusa enfileirar com A1 vencido e explica.

## I.3. Autenticação e sessão

- **JWT HS256, 20 min, sem refresh token — MÉDIO.** Cookie HttpOnly + validação de `Origin`. Para um sistema de um operador, 20 min sem refresh significa relogar várias vezes ao dia. É atrito operacional, que a diretriz combate. Correção: refresh token rotativo com família revogável, ou sessão deslizante.
- **Argon2id com rehash automático — excelente.** Escolha correta de algoritmo.
- **Sem 2FA — BAIXO.** Já no ROADMAP. Dado o perfil (um operador, acesso restrito), não é prioridade.
- **Rate limit por SHA-256 do IP — bom.** Hash preserva privacidade; o Caddy sobrescrevendo `X-Forwarded-For` com `{remote_host}` impede spoofing. Detalhe bem resolvido.
- **Sem bloqueio progressivo após N falhas de login — BAIXO.** O rate limit cobre parcialmente.

## I.4. Revisão OWASP-like

| Categoria | Avaliação |
|---|---|
| A01 Broken Access Control | **I.1.1/I.1.2** (destruição sem admin). Isolamento por `escritorio_id` consistente nos endpoints lidos. |
| A02 Cryptographic Failures | OK — Fernet para segredos, Argon2id para senha, TLS via Caddy com ACME |
| A03 Injection | OK — SQLAlchemy ORM em todo lugar; não encontrei SQL cru concatenado |
| A04 Insecure Design | Ausência de manifestação (G.2) e de camada de provedores (F.4) são falhas de desenho, não de código |
| A05 Security Misconfiguration | Produção endurecida. Dev com `user: "0:0"` e portas expostas (B19) |
| A06 Vulnerable Components | OK — dependências atuais e enxutas; `python-jose` e `pyOpenSSL` removidos conscientemente (comentário no `requirements.txt`) |
| A07 Auth Failures | Sem refresh (I.3), sem 2FA |
| A08 Data Integrity | **`float` em valor (H.1.1)** — integridade de dado fiscal |
| A09 Logging & Monitoring | **B8 — o pior item da lista.** Sem log estruturado, incidente é indetectável e não auditável |
| A10 SSRF | OK — `_url_segura()` restringe hosts; `follow_redirects=False`. Tratamento exemplar |

**O item mais fraco é A09**, e é também o que mais atrapalha a operação diária — o que o alinha com as prioridades 3 e 5 da diretriz, não com "segurança em 10º".

## I.5. Webhook Jettax

`POST /integracoes/jettax/webhooks/{segredo}`: `hmac.compare_digest` (tempo constante), 404 se não configurado (não revela existência), redige mensagem que cite credencial, idempotente via `IntegrityError`, correlaciona escritório pelo ticket com fallback "escritório único". `config.py:238` exige segredo com ≥ 32 caracteres.

**Bem feito.** Uma observação: o fallback "se só há um escritório, assume esse" é pragmático e aceitável hoje, mas vira ambiguidade no dia em que houver dois. Deixe um `TODO` explícito ou um log de alerta quando o fallback for usado.

---

# J. Frontend

## J.1. Arquitetura

Next.js 16 + React 19 + Tailwind. **Zero dependência de runtime além de `next`, `react`, `react-dom`.** Decisão excelente e deliberada: sem biblioteca de componentes, sem gerenciador de estado, sem lib de gráfico. Superfície de segurança mínima, build rápido, nada de churn de ecossistema.

`components/ui/` com 30 primitivas próprias (`Tabela`, `Modal`, `Combobox`, `SeletorData`, `Toast`, `Kpi`, `Esqueleto`, `EstadoVazio`, `EstadoErro`, `Paginacao`, `Progresso`…). `Tabela.tsx` suporta colunas configuráveis, ordenação, seleção e densidade — é o componente certo para um sistema de alto volume, e ter feito isso à mão foi a escolha certa.

`lib/format.ts` centraliza toda formatação pt-BR, com `moedaPartes` para evitar fatiar a saída de `Intl` (detalhe que evita bug clássico de moeda).

## J.2. Problemas

**J.2.1 — `NEXT_PUBLIC_API_URL` fixado em build — MÉDIO.** Variável `NEXT_PUBLIC_*` é inlinada na compilação. Mudar o endereço da API exige rebuild. Em produção está como `/api` (relativo, atrás do Caddy), o que é o certo — mas a rigidez permanece para outros ambientes. Alternativa: endpoint `/config.json` lido em runtime.

**J.2.2 — Telas grandes — BAIXO.** `Empresa.tsx` 943 l., `Documentos.tsx` 722 l., `Empresas.tsx` 714 l. `Empresa.tsx` concentra dados cadastrais, certificados, sincronização, Jettax e histórico numa árvore só. Decomponha por aba quando for mexer nela (o que vai acontecer na correção E.5.4).

**J.2.3 — Não achei tratamento explícito de sessão expirada — MÉDIO.** Com JWT de 20 min sem refresh (I.3), a expiração acontece **várias vezes por dia**. O comportamento precisa ser: detectar 401, preservar o estado do formulário, reautenticar, retomar. Se hoje for "redireciona para login e perde o que estava preenchido", é atrito operacional diário — exatamente o que a diretriz manda eliminar.

**J.2.4 — Falta a tela de diagnóstico de integração — ALTO em termos de valor.** Ver M.3. É a funcionalidade de maior retorno operacional de todo o frontend.

## J.3. UX para operação fiscal de alto volume

A diretriz pede zero enfeite. Concordo. O que falta não é visual, é **funcional**:

1. **"Por que esta nota não veio?"** — busca por chave/número que responde: nunca chegou / chegou e foi filtrada por período / chegou sem XML / erro na importação X às HH:MM. Hoje isso exige consulta manual no banco.
2. **Conferência de completude por competência** — "agosto tem 143 notas, 12 sem XML, 3 canceladas, última varredura às 14h32". Existe uma rota `/importacoes/conferencia`; garantir que a tela mostre isso com destaque.
3. **Fila visível** — o que está rodando, o que está esperando janela, quanto falta. O dado existe em `sincronizacoes_dfe.proxima_consulta_em`; falta exibir como fila e não como estado por empresa.
4. **Ação em massa com feedback de progresso** — ZIP de 5.000 notas precisa de progresso e retomada, não de spinner indefinido.
5. **Atalhos de teclado nas telas de alto volume** — já existe `Ctrl+K`; estender para navegação e seleção na tabela.

## J.4. Sobre a reescrita "Papel & Grafite"

Há no repositório um patch (`01a0b6e4-*.patch`) com reescrita integral do frontend: 41 arquivos reescritos, 12 removidos, 75 criados, ~8,7k → ~17,2k linhas, **zero dependência nova e contrato de API inalterado**.

Avaliação: manter contrato de API e não adicionar dependência é a forma certa de fazer uma reescrita de UI — o risco fica contido na camada de apresentação. O design system com tokens WCAG medidos em `globals.css` é trabalho sério.

**Ressalva:** dobrar a quantidade de código de frontend precisa se pagar em funcionalidade. Se as 8,5k linhas novas entregam as cinco capacidades de J.3, valeu. Se entregam o mesmo com outra aparência, foi custo de manutenção sem retorno — e a diretriz operacional (que proíbe funcionalidade que não reduza trabalho manual) seria o argumento contra. **Meça por isso, não por aparência.**

---

# K. Padrão brasileiro

## K.1. Formatação de saída — correta

`lib/format.ts` centraliza tudo em pt-BR:
- Data DD/MM/YYYY — correto
- Moeda R$ 1.234,56 — correto, com `moedaPartes` para não fatiar `Intl`
- CNPJ/CPF formatados — correto
- `core/documentos.py` valida **CNPJ alfanumérico (regra de 2026)** com DV por `ord(c)-48` — raro e correto

**A camada de apresentação não é o problema.**

## K.2. Timezone — ALTO, e é problema de DADO, não de máscara

Três defeitos que se compõem:

**K.2.1 — Nenhum container define `TZ`.** `grep -rn "TZ" docker-compose*.yml deploy/ backend/Dockerfile` → **nada**. Todos os processos rodam em **UTC**. Enquanto isso, o Celery Beat está configurado com `timezone = "America/Sao_Paulo"`. **O agendador pensa em horário de Brasília; o código que ele executa pensa em UTC.**

**K.2.2 — `_parse_data_emissao` assume UTC para data naive.** Em `worker/tasks.py`, quando o XML traz data sem offset, o código anexa `UTC` em vez de `America/Sao_Paulo`. Toda comparação subsequente com "agora" fica deslocada em 3 horas, e em datas de virada de mês isso muda a **competência** do documento.

Há também fallback para `datetime.now(utc)` quando a data é malformada — **isso é perigoso**: uma nota com data ilegível recebe a data de hoje e entra na competência errada, silenciosamente. Melhor seria marcar o documento como "data indeterminada" e sinalizar para conferência.

**K.2.3 — Seis usos de relógio local sem timezone:**
```
api/routers/dashboard.py     (2 ocorrências)
api/routers/importacoes.py:897
api/routers/painel.py:68
api/routers/painel.py:262
api/routers/relatorios.py:38
```
`date.today()` e `datetime.now()` sem tz usam o relógio do processo = UTC. **Todo dia, das 21h00 às 23h59 no horário de Brasília, o sistema acha que já é o dia seguinte.** O painel mostra "hoje" errado, o relatório do dia pega a janela errada, o alerta de "não varrido hoje" dispara cedo demais.

**Correção completa (não é só trocar a máscara):**
1. `TZ=America/Sao_Paulo` em **todos** os containers (compose dev e produção).
2. Um único helper `app/core/tempo.py` com `agora()` (aware, em `America/Sao_Paulo`) e `hoje()`. **Proibir `datetime.now()` / `date.today()` diretos no código** — garantir com regra de lint.
3. `_parse_data_emissao`: data naive de XML brasileiro deve ser interpretada como **horário local brasileiro**, não UTC.
4. Armazenar em UTC no banco (`DateTime(timezone=True)` já está certo), converter para exibição na borda.
5. Competência derivada da data **local**, nunca da UTC.
6. Teste explícito: nota emitida às 23h30 de 31/08 cai na competência 08/2026. **Esse teste falha hoje.**

**Por que classifico como ALTO e não CRÍTICO:** não perde documento nem corrompe XML. Mas produz **classificação fiscal errada de forma silenciosa**, o que gera retrabalho manual — o oposto do objetivo do produto.

## K.3. Precisão monetária — ALTO

Ver H.1.1. Resumo: `float` do modelo até o schema, com `float(texto)` já na extração. Correção exige Alembic antes.

**Arredondamento:** não encontrei política explícita. Documento fiscal brasileiro comumente usa meio para cima, mas **a regra correta depende do tributo e do leiaute** — não vou fixar aqui. Defina, documente e teste (`ROUND_HALF_UP` como ponto de partida, validado com o contador).

## K.4. Padrões fiscais brasileiros — cobertura

| Padrão | Estado |
|---|---|
| CNPJ (numérico + **alfanumérico 2026**) | Validado com DV correto |
| CPF | Validado |
| Inscrição Municipal (CCM) | Campo existe, sem validação (varia por município — validar é difícil e talvez não valha) |
| Inscrição Estadual | Não modelada |
| Código IBGE do município | Campo existe, **nada preenche** (E.3.3) |
| NFS-e | ADN + Jettax (quebrado) |
| NF-e | DistDFe |
| NFC-e | Modelo 65 chega pela DistDFe; não vi tratamento distinto |
| CT-e | DistDFe |
| MDF-e | Não tratado |
| Competência | Modelada e indexada — **decisão acertada**, permite trocar de mês sem consultar a SEFAZ |
| Prestador / Tomador | Extraídos na NFS-e |
| Emitente / Destinatário | Extraídos |
| Direção (prestada/tomada, entrada/saída) | Derivada corretamente (prestada se prestador == CNPJ da empresa) |
| Cancelamento | Evento aplicado, inclusive pendente |
| Código de serviço (LC 116) | Não extraído |
| CNAE | Não modelado |
| Natureza da operação | Não extraída |
| ISSQN / ICMS / PIS / COFINS / CSLL / IR / INSS | Nenhum valor de tributo extraído |
| Retenções | Não extraídas |
| Regime tributário | Não modelado |

**Leitura:** a cobertura de **identificação e ciclo de vida** do documento é boa. A cobertura de **conteúdo tributário** é inexistente — tudo fica dentro do XML.

Isso é aceitável se o produto é "capturar e entregar XML". **Deixa de ser aceitável** se alguém pedir apuração, conferência de retenção ou relatório de ISS. Ver H.1.4 para o caminho incremental (`JSONB` primeiro, colunas depois).

> Não implemente extração de tributo sem validação de especialista fiscal. Base de cálculo, alíquota e retenção têm regras por município, por tributo, por regime e por natureza da operação. Errar aqui é pior que não fazer.

---

# L. Escalabilidade

## L.1. Onde quebra, por faixa de volume

| Volume | Componente | Sintoma | Causa |
|---|---|---|---|
| **10k docs** | — | Funciona bem | — |
| **100k docs** | Busca textual | Segundos por busca | `LIKE '%…%'` sem trigram (H.3) |
| | Pool de conexões | 500 intermitente na API durante importação | pool 5+10 (H.6) |
| | ZIP em massa | Timeout ou estouro de memória | sem streaming nem retomada |
| **500k docs** | Índices | Planner escolhe scan | falta `(empresa_id, data_emissao)` (H.2) |
| | Tabela única | Vacuum/autovacuum pesado | sem particionamento (H.4) |
| | Fila única | Backup bloqueia importação | sem `task_routes` (D.2.1) |
| **1M+ docs** | `documentos_fiscais` | Toda query lenta | particionamento agora é **caríssimo** de introduzir |
| | Disco de XML | Diretório com milhões de arquivos | sem sharding de caminho nem storage frio |
| | Dashboard | Agregações varrem tudo | sem tabela de sumarização |
| | Worker | Não escala horizontalmente por empresa | varredura serial (L.2.1) |

## L.2. Gargalos por camada

**L.2.1 — Worker: paralelismo limitado pelo desenho, não pela máquina.** `sincronizar_tudo` roda a cada 5 min e itera empresas elegíveis em **um único processo**. `concurrency=4` ajuda nas tasks disparadas, mas a varredura em si é serial. Com 1.000 empresas e uma varredura de 200 ms cada, são 200 s só para percorrer a lista — 2/3 do intervalo do Beat.

Correção: `sincronizar_tudo` vira **dispatcher** — seleciona elegíveis e enfileira uma task por empresa, sem executar nada. Aí o paralelismo é real e escala com o número de workers.

**L.2.2 — Armazenamento de XML.** Volume Docker, caminho por documento. Milhões de arquivos num diretório degradam qualquer filesystem. Correção: sharding por `escritorio/ano/mes/` (ou hash), e S3 para o acervo frio. O backup já usa S3 — a infraestrutura existe.

**L.2.3 — Dashboard e métricas.** Agregações calculadas ao vivo. A 1M documentos, cada carregamento do painel é um scan. Correção: tabela de sumarização `(escritorio_id, empresa_id, competencia, tipo)` com contagem e soma, atualizada incrementalmente na importação ou por job. Com valor em `NUMERIC`, a soma fica exata de brinde.

**L.2.4 — Rate limit em memória.** Se a API escalar para múltiplas instâncias, o limite por processo deixa de ser global. Correção: mover contador para Redis, que já está no stack.

## L.3. O que NÃO é gargalo (não gaste tempo aqui)

- **FastAPI/uvicorn.** O I/O externo (SEFAZ, ADN, Jettax) domina qualquer overhead do framework por ordens de grandeza.
- **Celery.** Bem configurado. O gargalo é o desenho da varredura (L.2.1), não o broker.
- **Redis.** Volume de mensagens é baixíssimo.
- **Next.js.** Renderização não é o problema; consulta de banco é.

## L.4. Ordem de investimento em escala

1. Pool de conexões (1 linha, evita erro 500 hoje)
2. Índice `(empresa_id, data_emissao)` (1 linha, corrige a query mais usada)
3. Trigram na busca (1 migração)
4. Filas separadas (config de Celery)
5. `sincronizar_tudo` como dispatcher (meio dia)
6. Sumarização do dashboard (1-2 dias)
7. Particionamento (**decidir antes dos 500k**, executar depois)
8. Storage frio de XML (quando o volume justificar)

---

# M. Observabilidade

Esta seção responde à pergunta colocada como teste do sistema: **"por que a nota X não foi importada?"**

## M.1. Estado atual — ALTO

| Capacidade | Estado |
|---|---|
| Logging estruturado | **Nenhuma configuração**; 6 loggers nomeados, zero `dictConfig` |
| Nível de log configurável | Sem `LOG_LEVEL` |
| Correlation ID | Inexistente |
| Log de acesso HTTP | `uvicorn --no-access-log` em produção |
| Log de chamada externa | Nenhuma chamada a SEFAZ/ADN/Jettax é logada |
| Métricas | `GET /metricas` (Prometheus, autenticado) existe |
| Tracing | Inexistente |
| Auditoria de ação de usuário | OK — `services/auditoria.py` + tela `/auditoria` |
| Histórico de execução | OK — `execucoes_importacao`, `jettax_execucoes` |
| Alertas | OK — central de alertas + webhook com nível mínimo e cooldown |

**Diagnóstico:** o sistema tem boa observabilidade de **negócio** (execuções, auditoria, alertas) e **nenhuma** observabilidade **técnica**. Quando algo falha dentro de uma chamada externa, a informação **não existe em lugar nenhum** — não foi perdida, nunca foi produzida.

Isso é o que impede responder à pergunta do usuário hoje.

## M.2. Correção mínima viável (1-2 dias, maior retorno do relatório)

**M.2.1 — `app/core/observabilidade.py` com `dictConfig`:**
- Formato JSON em produção, legível em dev
- `LOG_LEVEL` por env
- Campos fixos: `timestamp` (com timezone!), `nivel`, `logger`, `mensagem`, `correlation_id`, `escritorio_id`, `empresa_id`, `execucao_id`
- Filtro de redação reaproveitando a lógica que **já existe** em `_mensagem_remota()` do `jettax.py`

**M.2.2 — Correlation ID ponta a ponta:**
- Middleware gera/propaga `X-Request-ID`
- `contextvars` para não passar o ID por parâmetro
- Celery propaga o ID no header da task
- Toda linha de log carrega o ID
- **A UI mostra o ID quando dá erro** — o operador copia e cola; isso muda completamente o suporte

**M.2.3 — Logar toda chamada externa:**
```json
{"evento":"chamada_externa","provedor":"jettax","operacao":"listar_nfse",
 "metodo":"GET","status":200,"ms":842,"itens":37,"pagina":2,
 "cursor_antes":"1042","cursor_depois":"1079",
 "empresa_id":17,"execucao_id":903,"correlation_id":"..."}
```
Com isso, as hipóteses H1-H8 da seção E deixam de ser hipóteses.

**M.2.4 — Reativar log de acesso** com formato JSON e filtro de ruído (healthcheck).

## M.3. "Por que a nota X não foi importada?" — a funcionalidade

Endpoint `GET /documentos/rastrear?chave=...` (ou número + empresa) que responde, em ordem:

```
1. O documento existe na base?
   SIM  → mostra empresa, competência, origem, tem XML?, importado em, fontes.
   NÃO  → segue.

2. Foi recebido e descartado?
   Consultar log de importação por chave → "recebido no NSU 4471 em 14/08,
   descartado: fora do período 08/2026".
   Este é o caso mais comum e hoje é INVISÍVEL.

3. Houve erro na importação?
   execucoes_importacao com aviso mencionando a chave (_resumir_avisos já guarda
   até 20 itens ignorados por execução — o dado existe, falta expor).

4. A empresa foi varrida no período?
   sincronizacoes_dfe: ultimo_nsu, max_nsu, ultima_consulta_em, bloqueado_ate,
   motivo_bloqueio. "Está em dia" = ultimo_nsu == max_nsu.

5. A empresa está elegível?
   Certificado ativo e válido? sincronizar_automaticamente ligado? tipo incluído
   em quais_tipos_sincronizar? janela liberada?

6. O provedor cobre esta empresa?
   (depois de F.4) requisitos() de cada provedor → "Jettax: falta código IBGE".

7. Nada disso?
   "O documento não foi disponibilizado pelo ambiente oficial até agora.
    Última varredura em DD/MM/YYYY HH:MM, NSU 4471 de 4471 (em dia)."
```

**Cada ramo dessa árvore já tem o dado no banco.** O que falta é a consulta e a tela. É a funcionalidade de maior valor operacional do relatório inteiro, e é barata: 2-3 dias.

## M.4. Métricas que faltam

Existe `GET /metricas`. Adicionar:
- `documentos_importados_total{escritorio,empresa,tipo,origem}`
- `importacao_duracao_segundos{tipo,origem}` (histograma)
- `chamada_externa_total{provedor,operacao,status}`
- `chamada_externa_duracao_segundos{provedor,operacao}`
- `empresas_bloqueadas{motivo}`
- `documentos_sem_xml_total{tipo,origem}` — detectaria E.3.5 automaticamente
- `cursor_atraso{empresa,tipo}` = `max_nsu - ultimo_nsu` — **a métrica mais importante**: mede diretamente "estou em dia?"

---

# N. Testes

## N.1. Estado atual

- **179 funções `test_` em 23 arquivos, 217 casos, todos passando.** 5.671 linhas de teste para 16.809 de código — proporção de 1:3, razoável.
- Roda inteira em **SQLite**.
- `conftest.py` só define variáveis de ambiente.
- `make test` executa dentro do container.

Ter 217 testes passando num projeto desse porte é mérito real, e a existência deles é o que torna as correções deste relatório seguras de fazer.

## N.2. Lacunas — MÉDIO

**N.2.1 — Nenhum teste contra PostgreSQL real.** Tudo em SQLite. O que isso deixa passar:
- `ON CONFLICT ON CONSTRAINT` (PG) vs `ON CONFLICT (cols)` (SQLite) — caminhos **diferentes** no código (`_insert_sem_duplicar`), só um é testado de verdade
- Enums nativos do PG e o problema `.name` vs `.value` — o comentário em `migracoes.py` mostra que isso **já quebrou em produção** e o teste não pegou
- `with_for_update()` — SQLite não tem lock de linha; **toda a lógica de lease é efetivamente não testada**
- Tipos: `Numeric`, `DateTime(timezone=True)`, `JSONB`
- Migrações reais

**Isto é a lacuna mais cara.** Correção: testcontainers ou serviço PG no CI, com a suíte parametrizada nos dois bancos.

**N.2.2 — Nenhum contract test do conector Jettax.** Não há fixtures de resposta real. O bug B1 sobreviveu porque o teste existente usa 2 páginas com limite 3, nunca a fronteira `n == limite`. **Teste de fronteira é exatamente onde bug de laço mora.**

**N.2.3 — Nenhum teste de carga ou concorrência.** Sem isso, o limite do pool (H.6), o comportamento de dois workers na mesma empresa e o tempo de query a 1M linhas são desconhecidos.

**N.2.4 — Nenhum teste de timezone.** Explica B6 ter sobrevivido. O teste "nota emitida às 23h30 de 31/08 cai na competência 08/2026" falharia hoje.

**N.2.5 — Nenhum teste de propriedade nos validadores.** CNPJ (inclusive alfanumérico), CPF e chave de acesso são candidatos ideais a Hypothesis: gerar milhares de casos e verificar invariantes.

## N.3. Pirâmide recomendada

| Camada | Alvo | Hoje |
|---|---|---|
| Unitário puro (parsing, validação, cálculo de data/competência) | ~60% | Existe, mas regra de domínio presa no worker dificulta |
| Contract test (fixtures gravadas por provedor) | ~20% | **0%** |
| Integração com PG real | ~15% | **0%** |
| Ponta a ponta | ~5% | 0% |

**Ordem de investimento:**
1. Testes de fronteira nos laços de paginação (o bug já está provado)
2. Fixtures de Jettax e ADN → contract tests
3. PostgreSQL no CI
4. Testes de timezone e de dinheiro
5. Carga

---

# O. Infraestrutura e DevOps

## O.1. O que está bom

**Produção (`docker-compose.production.yml`) — acima da média:**
- `read_only: true` em api/worker/beat
- `cap_drop: ALL`, `no-new-privileges`
- tmpfs em `/tmp`
- `volume-init` como gate de inicialização (garante permissão antes de subir)
- Healthcheck da API força `Host: api` (necessário por causa do `TrustedHostMiddleware` — sinal de que a proteção funciona)
- Frontend como `user: node`
- `NEXT_PUBLIC_API_URL=/api` (relativo, atrás do proxy — correto)

**`backend/Dockerfile`:** multi-stage (`base`/`runtime`/`test`), usuário `notasflow` uid 10001, `postgresql-client` só para `pg_dump`, pytest **ausente** do runtime.

**`deploy/Caddyfile`:** TLS ACME automático, strip de `/api`, `request_body max_size 35MB` (casa com o limite da aplicação), HSTS + X-Frame-Options + nosniff, `header_up X-Forwarded-For {remote_host}` (sobrescreve, impedindo spoof do rate limiter).

**`scripts/ajustar_portas.py`** escolhe portas livres em dev — detalhe de qualidade de vida bem pensado.

## O.2. Problemas

**O.2.1 — `TZ` ausente em todos os containers — ALTO.** Ver K.2. Uma linha por serviço.

**O.2.2 — Dev roda API como `user: "0:0"` com bind-mount — BAIXO.** Arquivo criado pelo container fica como root no host. Some com `user: "${UID}:${GID}"`.

**O.2.3 — Dev expõe db/redis em portas do host — BAIXO.** Conveniente, mas se a máquina estiver em rede não confiável, é exposição. Aceitável em dev local.

**O.2.4 — Não vi pipeline de CI.** Sem CI, os 217 testes dependem de alguém lembrar de rodar. Correção: GitHub Actions com lint + testes (SQLite **e** PG) + build de imagem em cada PR. Barato e alto retorno.

**O.2.5 — Sem estratégia de deploy sem downtime.** Com `create_all()` no startup (H.5), duas instâncias subindo simultaneamente podem colidir na migração. Com Alembic, a migração vira passo separado do deploy — mais um motivo para B9.

**O.2.6 — Sem healthcheck profundo.** O healthcheck verifica que a API responde. Não verifica banco, Redis nem volume de XML. Um `/saude/profundo` que testa as três dependências evita "container saudável, sistema morto".

**O.2.7 — Restauração de backup não testada.** Ver I.1.4.

## O.3. Recomendações

| Item | Custo | Prioridade |
|---|---|---|
| `TZ=America/Sao_Paulo` em todos os containers | 5 min | **Agora** |
| Pool de conexões dimensionado | 5 min | **Agora** |
| CI com lint + testes | 2 h | Alta |
| PostgreSQL no CI | 2 h | Alta |
| Alembic como passo de deploy | 1-2 dias | Alta |
| Filas Celery separadas + workers dedicados | 2 h | Média |
| Healthcheck profundo | 1 h | Média |
| Teste mensal de restauração | 1 dia | Média |
| `user` não-root em dev | 10 min | Baixa |

---

# P. Arquitetura futura

## P.1. Alvo em 12 meses (justificado, não aspiracional)

```
┌──────────────────────────────────────────────────────────────────────┐
│                         BORDA (Caddy)                                │
└──────────────────────────────┬───────────────────────────────────────┘
        ┌──────────────────────┴──────────────────────┐
┌───────▼────────┐                          ┌─────────▼──────────┐
│  Frontend      │                          │  API (FastAPI)     │
│  Next.js       │                          │  routers finos     │
└────────────────┘                          └─────────┬──────────┘
                               ┌──────────────────────┴───────────────┐
                               │      app/dominio/  (funções puras)   │
                               │  competência · período · documento   │
                               │  dinheiro (Decimal) · tempo (tz BR)  │
                               └──────────────────────┬───────────────┘
        ┌─────────────────────────────────────────────┴─────────────┐
        │              app/integracoes/  (camada de provedores)     │
        │  ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐  │
        │  │ ProvedorNFSe │  │ ProvedorNFe  │  │ ProvedorCTe     │  │
        │  ├──────────────┤  ├──────────────┤  ├─────────────────┤  │
        │  │ adn          │  │ sefaz_distdfe│  │ sefaz_distdfe   │  │
        │  │ jettax       │  │ jettax       │  │                 │  │
        │  │ (futuro: X)  │  │              │  │                 │  │
        │  └──────────────┘  └──────────────┘  └─────────────────┘  │
        │   Todos devolvem DocumentoBaixado.                        │
        │   Todos expõem cobre() e requisitos().                    │
        └─────────────────────────────┬─────────────────────────────┘
                    ┌─────────────────▼──────────────────┐
                    │  Persistência única e idempotente  │
                    │  + DocumentoFiscalFonte            │
                    └─────────────────┬──────────────────┘
   ┌──────────────────┬───────────────┼────────────────┬──────────────┐
   │ PostgreSQL       │ Storage XML   │ Redis          │ Observab.    │
   │ particionado     │ quente + frio │ broker + rate  │ log JSON +   │
   │ NUMERIC · tz     │ (S3)          │ limit          │ métricas     │
   └──────────────────┴───────────────┴────────────────┴──────────────┘
```

**Justificativa de cada bloco:**

- **`app/dominio/` puro** — porque hoje regra de domínio mora em `worker/tasks.py` e só é testável via Celery. Foi assim que o bug de timezone passou.
- **Camada de provedores** — porque o problema NFS-e é irredutivelmente multi-origem (seção F).
- **Persistência única** — porque duas rotas de gravação (ADN e Jettax) já produziram o bug E.3.5.
- **Particionamento + `NUMERIC` + tz** — porque são correções de integridade e escala que ficam mais caras a cada mês.
- **Observabilidade** — porque sem ela o resto é adivinhação.

**Continua fora do alvo, deliberadamente:** microsserviços, event sourcing, Kubernetes, service mesh, multi-região. Nenhum resolve um problema que este sistema tenha, e todos multiplicam os pontos de falha na área mais frágil (integração externa).

## P.2. Decisões que exigem o usuário, não o auditor

| Decisão | Opções | Recomendação |
|---|---|---|
| Manter a Jettax? | Consertar / trocar de agregador / só ADN | **Consertar agora** (é a cobertura de hoje), **reduzir peso com o tempo** (ADN cresce — F.3) |
| Manifestação automática? | 210210 (ciência) / 210200 (confirmação) / manual | **210210 automático; 210200 nunca sem ação humana** (G.2) |
| Extrair tributos? | Não / JSONB / colunas | **JSONB primeiro**, promover o que provar uso (H.1.4) |
| Storage de XML | Volume / S3 / híbrido | **Híbrido**: quente em volume, frio em S3 |
| Multi-tenant real? | Um escritório / vários | Diretriz diz um operador → **não investir** em isolamento maior |
| Retenção | Guardar sempre / expurgar | Definir prazo **com o contador** e implementar storage frio |

---

# Q. Plano de implementação

## Q.1. Princípios do plano

1. **Consertar antes de refatorar.** Refatorar código quebrado produz código quebrado mais bonito.
2. **Instrumentar antes de consertar o que depende de rede.** Sem log da Jettax, corrigir é adivinhação.
3. **Alembic antes de qualquer mudança de tipo de coluna.** É bloqueio físico, não preferência.
4. **Cada fase termina com um teste que falharia na fase anterior.** Sem isso não há prova de progresso.

## Q.2. Fase 0 — Instrumentação e ajustes de 5 minutos (2-3 dias)

Pré-requisito de todo o resto.

| # | Item | Sev. | Custo |
|---|---|---|---|
| 0.1 | `TZ=America/Sao_Paulo` em todos os containers | ALTO | 5 min |
| 0.2 | Pool de conexões (`pool_size`, `max_overflow`, `pre_ping`, `recycle`) | MÉDIO | 5 min |
| 0.3 | `requer_admin` em `reset-geral` e `excluir-lote` | ALTO | 10 min |
| 0.4 | `app/core/observabilidade.py` — `dictConfig` JSON + `LOG_LEVEL` + redação | ALTO | 1 dia |
| 0.5 | Correlation ID (middleware + contextvars + Celery + UI) | ALTO | 1 dia |
| 0.6 | Log estruturado de **toda** chamada externa | ALTO | 4 h |
| 0.7 | Reativar log de acesso em JSON com filtro de ruído | MÉDIO | 1 h |

**Critério de saída:** uma falha de importação produz linhas de log correlacionáveis, com provedor, rota, status, tempo e cursor.

## Q.3. Fase 1 — Jettax funcionando (1 semana)

Resolve o problema nº 1 relatado. Todos os itens derivam de achados CRÍTICOS.

| # | Item | Ref. | Custo |
|---|---|---|---|
| 1.1 | Corrigir `for/else` → `while` com guarda | E.5.1 | 15 min |
| 1.2 | Teste de fronteira `n == limite` (falha hoje) | E.6.1 | 30 min |
| 1.3 | Auditar `acessorias.py` pelo mesmo padrão | D.5 | 30 min |
| 1.4 | Tabela de municípios IBGE + preenchimento automático | E.5.3 | meio dia |
| 1.5 | Validar cobertura via `GET /api/nfse/cities` antes de registrar | E.5.3 | 2 h |
| 1.6 | Campos de credencial municipal (tipo, usuário, senha cifrada) | E.5.2 | meio dia |
| 1.7 | `carga_cliente` recusa cadastro sem credencial, com mensagem acionável | E.5.2 | 2 h |
| 1.8 | Inverter default de `enviar_certificado` para `True` quando há A1 | E.5.2 | 15 min |
| 1.9 | Botão "Importar agora" + período na aba Jettax | E.5.4 | 2 h |
| 1.10 | Exibir contadores da execução (já persistidos) | E.5.4 | 1 h |
| 1.11 | Executar o roteiro de diagnóstico ao vivo com o token real | E.6.3 | 1 h |
| 1.12 | Gravar fixtures reais → contract tests | E.6.2 | meio dia |
| 1.13 | Decidir e implementar o caminho do XML de NFS-e | E.5.5 | 1-2 dias |
| 1.14 | `AUSENTES.txt` no ZIP quando houver nota sem XML | E.5.5 | 2 h |

**Critério de saída:** o teste de aceitação E.6.4 passa ponta a ponta com uma empresa real.

**Nota sobre 1.11:** este item **não pôde ser feito nesta auditoria** (sem egress TLS no ambiente). É o primeiro item que exige rede e é o que resolve H1-H8.

## Q.4. Fase 2 — Integridade de dado (1-2 semanas)

| # | Item | Sev. | Ref. |
|---|---|---|---|
| 2.1 | **Alembic** (init, baseline, stamp, converter `migracoes.py`) | ALTO | H.5 |
| 2.2 | `app/core/tempo.py` + proibir `datetime.now()`/`date.today()` via lint | ALTO | K.2 |
| 2.3 | Corrigir `_parse_data_emissao` (naive = horário brasileiro) | ALTO | K.2 |
| 2.4 | Corrigir os 6 usos de relógio local | ALTO | K.2 |
| 2.5 | Testes de timezone (23h30 de 31/08 → competência 08/2026) | ALTO | N.2.4 |
| 2.6 | `valor_total` → `NUMERIC(15,2)` (**depende de 2.1**) | ALTO | H.1.1 |
| 2.7 | Schemas → `condecimal`; extração → `Decimal` | ALTO | H.1.1 |
| 2.8 | Política de arredondamento documentada e testada | ALTO | K.3 |
| 2.9 | Índices faltantes, com destaque para `(empresa_id, data_emissao)` | ALTO | H.2 |
| 2.10 | `pg_trgm` + GIN; busca exata em chave/número | ALTO | H.3 |
| 2.11 | PostgreSQL no CI | MÉDIO | N.2.1 |

**Critério de saída:** nota de 31/08 às 23h30 cai em 08/2026; soma de 10.000 notas bate com a soma manual ao centavo.

## Q.5. Fase 3 — Completude fiscal (2-3 semanas)

| # | Item | Sev. | Ref. |
|---|---|---|---|
| 3.1 | Manifestação 210210 (Ciência da Operação) automática | ALTO | G.2 |
| 3.2 | `consChNFe` **após** manifestação, com cota | ALTO | G.2 |
| 3.3 | Decisão explícita sobre 210200 (recomendação: nunca automático) | ALTO | G.2 |
| 3.4 | `GET /documentos/rastrear` — "por que a nota X não veio" | ALTO | M.3 |
| 3.5 | Tela de rastreamento | ALTO | M.3, J.2.4 |
| 3.6 | `requisitos()` por provedor + tela de diagnóstico | ALTO | F.4 |
| 3.7 | Endpoint de reposicionamento de cursor (admin + auditoria) | MÉDIO | G.3.1 |
| 3.8 | Métricas novas, com `cursor_atraso` em destaque | MÉDIO | M.4 |

**Critério de saída:** para qualquer nota ausente, o sistema explica sozinho o motivo; NF-e de entrada tem XML completo.

## Q.6. Fase 4 — Camada de provedores (2-3 semanas)

| # | Item | Sev. | Ref. |
|---|---|---|---|
| 4.1 | `ProvedorNFSe` (Protocol) + registro + orquestrador | MÉDIO | F.4 |
| 4.2 | ADN migrado para a interface | MÉDIO | F.4 |
| 4.3 | Jettax migrado (cliente/mapeador/provedor/politica) | MÉDIO | E.7 |
| 4.4 | Persistência única para todos os provedores | MÉDIO | E.7 |
| 4.5 | Chave de acesso real; sintético vai para `identificador_externo` | MÉDIO | H.1.2 |
| 4.6 | Deduplicação cross-fonte via `DocumentoFiscalFonte` | MÉDIO | B16 |
| 4.7 | Extrair `app/dominio/` de `worker/tasks.py` | MÉDIO | C.3.2 |
| 4.8 | `sincronizar_tudo` vira dispatcher | MÉDIO | L.2.1 |

**Critério de saída:** adicionar um terceiro provedor é criar um arquivo, sem tocar no worker.

## Q.7. Fase 5 — Escala e operação (contínuo)

| # | Item | Sev. |
|---|---|---|
| 5.1 | Filas Celery separadas + workers dedicados | MÉDIO |
| 5.2 | Sumarização do dashboard | MÉDIO |
| 5.3 | Particionamento por competência (**decidir antes dos 500k**) | MÉDIO |
| 5.4 | Storage frio de XML (S3) + sharding de caminho | MÉDIO |
| 5.5 | Retenção conforme prazo legal (definir **com o contador**) | MÉDIO |
| 5.6 | `dados_fiscais JSONB` + GIN | MÉDIO |
| 5.7 | Refresh token / sessão deslizante | MÉDIO |
| 5.8 | Rate limit no Redis | BAIXO |
| 5.9 | Rotação de chave do cofre (`MultiFernet`) | MÉDIO |
| 5.10 | Teste mensal de restauração de backup | MÉDIO |
| 5.11 | Testes de carga | MÉDIO |
| 5.12 | Decompor routers e telas grandes | BAIXO |

## Q.8. Aproveitar / refatorar / reescrever / remover / isolar / substituir

### APROVEITAR sem tocar (é bom; mexer é risco)

- `services/sincronizacao.py` — regras oficiais mapeadas ao código. **A melhor parte do projeto.**
- `services/importadores/eventos.py` — nenhum evento some.
- `services/mtls.py` e `services/certificados.py` — manejo de A1 exemplar.
- `core/documentos.py` — CNPJ alfanumérico 2026.
- `services/periodo.py` — período obrigatório, múltiplos formatos (`MM/AAAA`, `ago/2026`, `202608`, intervalos).
- `services/fila.py` — porta única de enfileiramento.
- `services/backup.py` — maduro (falta só testar restauração).
- `main.py` — limite de body, CSRF por `Origin`, HSTS/CSP, docs off.
- `deploy/Caddyfile` e `docker-compose.production.yml` — endurecimento acima da média.
- `backend/Dockerfile` — multi-stage correto.
- Autenticação/hosts/redação de segredo do `jettax.py` — as partes boas de um arquivo problemático.
- `components/ui/` do frontend — 30 primitivas próprias, zero dependência.
- `lib/format.ts` — formatação pt-BR centralizada.
- `excluir_empresa` — ordem de exclusão explícita e recusa a chamar o DELETE remoto.

### REFATORAR (mover, não reescrever)

- `services/jettax.py` → `app/integracoes/jettax/{cliente,mapeador,provedor,politica}.py` (E.7)
- `worker/tasks.py` → extrair `app/dominio/` (C.3.2)
- `api/routers/documentos.py` (1.218 l.) → separar listagem / download / exportação / exclusão
- `api/routers/importacoes.py` (1.051 l.) → separar disparo / estado / conferência
- `frontend/app/dashboard/empresa/Empresa.tsx` (943 l.) → um componente por aba
- `nfse_adn.py` e `nfe_sefaz.py` → adaptar à interface `Provedor*` (mudança de assinatura, lógica preservada)

### REESCREVER (o desenho atual não chega lá)

- **`db/migracoes.py` → Alembic.** Não é evolução; é substituição. Bloqueia H.1.1, H.1.2 e H.4.
- **`_listar_paginas`.** 30 linhas. O `for/else` é o desenho errado, não um detalhe.
- **`_persistir_nfse_metadados`.** Deve deixar de existir: NFS-e passa a usar a persistência comum.

### REMOVER

- Nada relevante. O projeto **não tem código morto significativo** — sinal de manutenção cuidadosa. As funções `importarNFSeJettax`/`importarNFeJettax` de `lib/api.ts` parecem mortas, mas o certo é **usá-las** (Q.3 item 1.9), não removê-las.

### ISOLAR

- **Toda chamada externa atrás de uma interface** com timeout, retry, circuit breaker e log — hoje cada integração implementa o seu jeito.
- **Regra de domínio fora do Celery** — `app/dominio/` puro.
- **Segredos exclusivamente no cofre** — remover o caminho de token global por env (`settings.jettax_api_token`), deixando só o por-escritório cifrado (C.3.4).
- **Dinheiro e tempo em módulos únicos** — `app/core/dinheiro.py` e `app/core/tempo.py`, com lint proibindo `float` em valor e `datetime.now()` direto.

### SUBSTITUIR

- `float` → `Decimal` / `NUMERIC(15,2)` (H.1.1)
- `datetime.now()` / `date.today()` → `tempo.agora()` / `tempo.hoje()` (K.2)
- `LIKE '%…%'` → trigram/FTS em texto; busca exata em identificador (H.3)
- `create_all()` → Alembic (H.5)
- Chave sintética `jettax-nfse-{id}` → chave fiscal real + `identificador_externo` (H.1.2)
- Fila única → filas por natureza de tarefa (D.2.1)

## Q.9. Resumo executivo do plano

| Fase | Duração | Entrega | Risco se não fizer |
|---|---|---|---|
| **0 — Instrumentação** | 2-3 dias | Log JSON, correlation ID, tz, pool, admin em destruição | Toda correção seguinte é adivinhação |
| **1 — Jettax** | 1 semana | Integração funcionando ponta a ponta | Problema nº 1 permanece |
| **2 — Integridade** | 1-2 semanas | Alembic, timezone, `Decimal`, índices | Competência e centavo errados, silenciosos |
| **3 — Completude** | 2-3 semanas | Manifestação, rastreamento, diagnóstico | NF-e de entrada sem XML; "não sei por quê" |
| **4 — Provedores** | 2-3 semanas | Camada extensível, persistência única | Cada município novo é mais um `if` |
| **5 — Escala** | contínuo | Partição, storage frio, filas, sumarização | Degradação progressiva acima de 500k |

**Total até "enterprise" nas cinco propriedades de A.3: 7 a 10 semanas de trabalho focado.**

**Se houver tempo para apenas uma semana:** Fase 0 completa + itens 1.1, 1.2, 1.4, 1.6, 1.7, 1.9 da Fase 1. Isso entrega observabilidade real e a Jettax deixando de estar quebrada por defeito nosso — que é, literalmente, o que foi pedido.

---

## Anexo — Índice de achados por arquivo

| Arquivo | Linha | Achado | Sev. |
|---|---|---|---|
| `services/jettax.py` | 650-678 | `for/else` — sucesso vira erro | CRÍTICO |
| `services/jettax.py` | 704-735 | `carga_cliente` sem credencial obrigatória | CRÍTICO |
| `services/jettax.py` | 1180-1220 | NFS-e sem XML, chave sintética | CRÍTICO |
| `services/cnpj.py` | — | não devolve código IBGE | CRÍTICO |
| `models.py` | 358-388 | sem campo de credencial municipal | CRÍTICO |
| `frontend/lib/api.ts` | 545-555 | funções de importação nunca chamadas | CRÍTICO |
| `models.py` | 206 | `valor_total` como `float` | ALTO |
| `schemas.py` | 439, 490, 785-858, 1010 | valores como `float` | ALTO |
| `services/importadores/nfse_adn.py` | ~505 | `float(valor_texto)` | ALTO |
| `worker/tasks.py` | `_parse_data_emissao` | naive → UTC (deveria ser horário BR) | ALTO |
| `api/routers/dashboard.py` | ×2 | `date.today()` sem tz | ALTO |
| `api/routers/importacoes.py` | 897 | `datetime.now()` sem tz | ALTO |
| `api/routers/painel.py` | 68, 262 | relógio local sem tz | ALTO |
| `api/routers/relatorios.py` | 38 | relógio local sem tz | ALTO |
| `docker-compose*.yml` | — | sem `TZ` em nenhum container | ALTO |
| `api/routers/sistema.py` | reset-geral | não exige admin | ALTO |
| `api/routers/documentos.py` | excluir-lote | não exige admin | ALTO |
| `api/routers/documentos.py` | busca | `LIKE '%…%'` em 8 colunas | ALTO |
| `db/base.py` / `db/migracoes.py` | — | sem Alembic; não altera tipo de coluna | ALTO |
| (ausência) | `services/importadores/` | sem manifestação 210200/210210 | ALTO |
| (ausência) | todo o backend | sem `dictConfig`/JSON/correlation ID | ALTO |
| `db/session.py` | `create_engine` | sem pool configurado | MÉDIO |
| `celery_app.py` | — | fila única | MÉDIO |
| `services/jettax.py` | 1184 | chave sintética impede dedupe cross-fonte | MÉDIO |
| `core/security.py` | — | JWT 20 min sem refresh | MÉDIO |
| `backend/tests/` | — | sem PG real, sem contract test, sem carga | MÉDIO |
| `docker-compose.yml` | api | `user: "0:0"` + bind-mount | BAIXO |
| vários | — | routers e telas grandes demais | BAIXO |

---

*Auditoria conduzida por leitura integral do código, execução da suíte de testes, reprodução empírica do defeito de paginação e consulta à documentação pública oficial da Jettax/Morfeu e do NFS-e Nacional. Conclusões que dependem do comportamento em produção de serviços externos estão explicitamente marcadas como hipóteses, com o procedimento de verificação indicado. Nenhuma regra fiscal foi inventada; onde a decisão depende de legislação, de parametrização municipal ou de contrato de fornecedor, isso está declarado no texto.*
