# Auditoria Técnica Enterprise — NotasFlow / Cajuru28 (FASE 0)

**Data:** 2026-09-10 · **Base auditada:** commit `be163f9` (branch `main`) · **Escopo:** 134 arquivos, ~8.900 LOC de código, 129 testes
**Método:** leitura integral do repositório, execução da suíte no sandbox (129/129 passando com o build do painel presente; 1 falha reproduzida sem ele), `pip-audit`, `npm audit`, verificação das afirmações críticas do projeto contra documentação oficial (SEFAZ/ADN/RFB) e pesquisa de concorrentes.

**Convenção deste documento:** cada afirmação é marcada como:

- **[FATO-CÓDIGO]** — verificado lendo/executando o código deste repositório;
- **[FATO-FONTE]** — verificado em documentação oficial (fonte citada);
- **[INFERÊNCIA]** — conclusão derivada do código com alto grau de confiança, não reproduzida de ponta a ponta;
- **[HIPÓTESE]** — plausível, exige validação (geralmente com certificado real / rede SEFAZ);
- **[RECOMENDAÇÃO]** — decisão de engenharia proposta, com justificativa.

Nada aqui foi presumido correto "porque funciona". Nada foi inventado.

---

## 0. Veredito executivo (sem elogios)

O projeto **não é um protótipo** — é um MVP de alto nível que acertou o problema mais
difícil da categoria: **o contrato de consumo da SEFAZ/ADN**. O governor (`sincronizacao.py`),
o modelo `sincronizacoes_dfe` (cursor + janela + lease), o erro 656 como *estado operacional*
e o checkpoint por lote são, na minha avaliação, **superiores ao comportamento documentado de
vários concorrentes** que tratam 656 como falha e disparam retry cego (o "anti-padrão" que
queima o CNPJ). **[FATO-CÓDIGO]**

Mas o projeto **não é, hoje, um produto enterprise**. Os gargalos não são o núcleo de
importação — são tudo em volta dele:

1. **Segurança de plataforma**: dependências com 35 vulnerabilidades conhecidas em 7 pacotes
   (`pip-audit`), CORS `*`+credentials gerada pelo instalador padrão, SECRET_KEY com default
   aceitável no startup, PostgreSQL/Redis publicados no host com credenciais fixas, login sem
   rate-limit, Swagger ativo no desktop, backup ZIP contendo a chave mestra do cofre ao lado
   do banco. **[FATO-CÓDIGO]**
2. **Operação multiempresa real**: isolamento por `escritorio_id` existe no schema, mas não há
   gestão de usuários/escritórios, cobrança, cota por tenant, nem fair-scheduling *entre*
   tenants (o tick do agendador é global e pode ser monopolizado por um escritório). **[FATO-CÓDIGO]**
3. **Dois defeitos silenciosos no núcleo**, ambos comprovados nesta auditoria: (a) execução
   `EM_ANDAMENTO` zumbi trava empresa+tipo **para sempre** quando duas varreduras colidem
   (reproduzido com script); (b) o "recibo" de um documento atribui a execução por heurística
   errada, quebrando a resposta à pergunta "por que essa nota entrou/saiu?". **[FATO-CÓDIGO]**
4. **Auditoria formal não existe**: há log de execução, não há *audit trail* imutável de ações
   humanas/sistema, não há correlação request→documento, não há hash/integridade do XML
   gravado (a janela crash→insert sem arquivo deixa documento apontando para XML inexistente
   **para sempre**, sem reconciliação). **[FATO-CÓDIGO]**
5. **UX está presa ao caso feliz do escritório**: não há tela de diagnóstico por documento
   ("por que essa nota falhou?"), não há trilha do usuário que fez o quê, o painel de estado
   faz N+1 queries por empresa×tipo (vai engasgar com centenas de tenants), e cadastro em
   massa não tem importação por CNPJ-base/matrizes. **[FATO-CÓDIGO]**
6. **Cobertura de fontes menor que a promessa competitiva**: só ADN (NFS-e nacional) +
   NFe/CT-e via AN. Faltam: manifestação do destinatário (caminho oficial do XML integral),
   MDF-e (existe `MDFeDistribuicaoDFe` oficial **[FATO-FONTE]**), NFC-e, CF-e/SAT, fontes
   municipais legadas de NFS-e (onde Jettax declara 2.200+ municípios — é a barreira real de
   "produto vs script"), e o modelo **autXML/contador**, que muda a arquitetura de captura.
7. **CI/CD de release está quebrado como publicado**: o workflow roda `pytest` **antes** do
   build do painel, mas o teste `test_primeira_execucao_do_programa` exige `frontend/out/` —
   falha reproduzida no sandbox. A Release "automática" nunca sairia. **[FATO-CÓDIGO]**

Nenhum desses pontos exige reescrever o núcleo. A arquitetura atual (domain em services,
dois modos sobre um código, fila trocável) é **correta e deve ser preservada** — o que falta
é transformá-la em *plataforma*: segurança, governança, observabilidade, cobertura de fontes.
O roadmap na seção 13 faz exatamente isso, em ordem.

---

## 1. Mapa completo do repositório

```
Cajuru28/
├── README.md                        # manifesto do produto, dois modos, fluxo de uso
├── PASSO_A_PASSO.md                 # guia do contador (não auditado em detalhe)
├── INICIAR.bat / PARAR.bat / SETUP.bat / ATUALIZAR.bat|.sh / INSTALAR_TUDO.bat|.sh
│                                    # automação de instalação/updater do modo SERVIDOR (Docker)
├── Makefile                         # up/down/logs/user/test/empacotar/desktop/diagnostico
├── versao.txt = 1.0.0               # fonte única de versão p/ empacotador e atualizador
├── docker-compose.yml               # db(pg16) redis api worker beat frontend — ver §7
├── docs/
│   ├── ARQUITETURA.md               # decisões documentadas (cofre, governor, desktop, etc.)
│   ├── SINCRONIZACAO.md             # regras do webservice e como o sistema as cumpre
│   ├── DISTRIBUICAO.md              # releases, manifesto, Inno, PyInstaller
│   ├── ROADMAP.md                   # Fases 0–6 prontas; Fase 7 futura; 3 pendências listadas
│   └── github-actions-release.yml   # workflow de release FORA do .github (não roda!)
├── scripts/
│   ├── empacotar.py                 # build desktop: painel→web/, PyInstaller, Inno, latest.json+SHA256
│   ├── gerar_env.py                 # gera .env (SECRET/VAULT/BOOTSTRAP) e CREDENCIAIS.txt ⚠ CORS=*
│   ├── gerar_icone.py
│   └── instalar_windows.ps1
├── installer/notasflow.iss          # Inno Setup: por-usuário, AppId fixo, dados fora do programa
├── backend/
│   ├── desktop_main.py              # entrada do .exe (args --diagnostico/--redefinir-senha/...)
│   ├── notasflow.spec               # PyInstaller onedir, excludes (celery/redis/psycopg2)
│   ├── requirements*.txt            # servidor / desktop / dev (versões fixadas — ver §7)
│   ├── Dockerfile                   # python:3.11-slim (sem pin de digest; pip sem hash)
│   ├── pytest.ini / conftest.py
│   ├── scripts/{criar_usuario_inicial.py, migrar.py}
│   └── app/
│       ├── main.py                  # FastAPI, CORS (com ramo "*"), lifespan, painel estático
│       ├── bootstrap.py             # cria 1º escritório+admin via env BOOTSTRAP_*
│       ├── models.py                # 7 tabelas (Escritorio, Usuario, Empresa, Certificado,
│       │                            #  DocumentoFiscal, ExecucaoImportacao, SincronizacaoDFe,
│       │                            #  EventoFiscalPendente)
│       ├── schemas.py               # Pydantic v2 (entrada/saída)
│       ├── core/{config.py, vault.py, security.py}
│       ├── db/{base.py, session.py, migracoes.py}   # create_all + ALTER idempotente (sem Alembic)
│       ├── api/
│       │   ├── deps.py              # JWT → usuario → escritorio_id
│       │   └── routers/             # auth, empresas, certificados, documentos, importacoes, sistema
│       ├── services/
│       │   ├── importadores/        # base.py (contrato), _distribuicao_dfe.py (SOAP/parse
│       │   │                        #  compartilhado NFe+CTe), nfe_sefaz, cte_sefaz, nfse_adn, eventos
│       │   ├── sincronizacao.py     # GOVERNOR: cooldown/656/cota/lease/em-dia
│       │   ├── fila.py              # portão único: API/lote/agendador → travas → task
│       │   ├── certificados.py      # identidade ICP-Brasil (OID 2.16.76.1.3.3), validação CNPJ/CPF
│       │   ├── mtls.py              # pfx → pem temporário 0700 → httpx cert=(...)
│       │   └── periodo.py           # parser de competência (08/2026, ago/2026, 202608…)
│       ├── worker/
│       │   ├── celery_app.py        # Celery|MiniCelery por MODO_DESKTOP; beat_schedule único
│       │   └── tasks.py             # importar_documentos, sincronizar_tudo, completar_xmls_pendentes
│       └── desktop/                 # ambiente.py, caminhos.py, fila_local.py (MiniCelery),
│                                    # atualizador.py, servidor.py, janela.py, bandeja.py, painel.py, controle.py
└── frontend/                        # Next.js 16 + React 19 + Tailwind (export estático p/ desktop)
    ├── app/{login, dashboard/{page,empresas,empresa,documentos,importacoes,configuracoes}}}
    ├── components/{PainelImportacao, SeletorEmpresas, CompetenciaPicker, AvisoAtualizacao, Sidebar, StatusDot}
    ├── lib/{api.ts, auth.ts (token em localStorage), competencia.ts, types.ts}
    └── scripts/build-desktop.mjs    # NEXT_BUILD_TARGET=desktop → output: export
```

**Densidade por módulo (LOC):** `worker/tasks.py` 861 · `desktop/atualizador.py` 539 ·
`routers/documentos.py` 779 · `routers/importacoes.py` 540 · `services/importadores/nfse_adn.py` 560 ·
`desktop/servidor.py` 470 · `_distribuicao_dfe.py` 477 · `desktop/fila_local.py` 443.
Documentação interna é anormalmente boa — comentários explicam *por quê* de cada regra
SEFAZ, o que reduz drasticamente o risco de regressão conceitual. **[FATO-CÓDIGO]**

---

## 2. Arquitetura atual (as-built)

### 2.1 Camadas reais

O README/docs propõem `CORE DOMAIN → APPLICATION → INFRASTRUCTURE → INTERFACES`. A
realidade observada no código é **hexagonal parcial**:

| Peça | Onde mora | Qualidade do isolamento |
| --- | --- | --- |
| Domínio fiscal (regras de consumo, cursor, estados) | `app/services/sincronizacao.py`, `app/models.py` (estado), `app/services/importadores/*` | Bom: governor é módulo puro sobre Session; importadores não conhecem Celery/FastAPI **[FATO-CÓDIGO]** |
| Aplicação (orquestração) | `app/worker/tasks.py`, `app/services/fila.py` | Médio: tasks conhecem modelos, vault, filesystem e dialetos de banco; fila conhece worker (import preguiçoso p/ quebrar ciclo) **[FATO-CÓDIGO]** |
| Infra | `app/db/*`, `app/core/vault.py`, `app/services/mtls.py`, `app/desktop/fila_local.py`, `app/worker/celery_app.py` | Bom: dois modos (Celery/Redis/PG × threads/SQLite) trocados por 1 variável **[FATO-CÓDIGO]** |
| Interfaces | `app/api/routers/*` + `frontend/` + `app/desktop/*` | Fraco: roteadores fazem agregação de negócio (estados N+1, recibo heurístico) **[FATO-CÓDIGO]** |

O ciclo "desktop e servidor compartilham a lógica" **é verdadeiro hoje**: os três pontos de
divergência (fila em `celery_app.py`, painel estático em `main.py`, caminhos em `caminhos.py`)
são exatamente os declarados na documentação, e o governor **não** vive na fila — vive no
banco. Isso foi confirmado lendo `fila_local.py` (nenhuma regra fiscal) e
`celery_app.py` (comentário: "a segurança do fluxo não mora na fila"). **[FATO-CÓDIGO]**

### 2.2 Modelo de dados atual

```
escritorios 1──N usuarios          (login; sem roles)
escritorios 1──N empresas           (UQ: (escritorio_id, cnpj_cpf))
empresas    1──N certificados       (pfx em disco; senha Fernet no banco; só 1 ativo)
empresas    1──N documentos_fiscais (UQ: (empresa_id, chave_acesso); xml_path em disco)
empresas    1──N sincronizacoes_dfe (UQ: (empresa_id, tipo); cursor/janelas/lease/cota)
empresas    1──N execucoes_importacao (log de varredura; status EM_ANDAMENTO|CONCLUIDA|ERRO|AGUARDANDO)
empresas    1──N eventos_fiscais_pendentes (cancelamento antes da nota; UQ por doc+evento)
```

Índices declarados: `usuarios.email`, `empresas.cnpj_cpf`, `documentos.chave_acesso`,
`documentos.nsu`, `documentos.competencia`, e os criados em `migracoes.py`
(`ix_documentos_competencia`, `ix_documentos_empresa_competencia`,
`ix_sincronizacao_empresa_tipo`) + uniques de constraint. **[FATO-CÓDIGO]**

### 2.3 Componentes de execução

- **API (FastAPI)**: rotas sem prefixo de versão; auth JWT HS256 (480min servidor / 7d desktop);
  CORS por env; `/saude`; no desktop serve o painel exportado em `/`.
- **Worker (Celery / MiniCelery)**: 3 tasks (`importar_documentos`, `sincronizar_tudo`,
  `completar_xmls_pendentes`); concorrência 4 (compose) / 4 threads (desktop).
- **Beat**: `sincronizar_tudo` a cada 5min, `completar_xmls_pendentes` a cada 6h; no desktop
  o "beat" é o laço `_laco_relogio` do MiniCelery com `agenda.json` persistido.
- **Fila**: Redis broker, `acks_late`, `prefetch=1`, `visibility_timeout=21600s` (> countdown
  máximo), `task_time_limit=1860s`. **[FATO-CÓDIGO]** — projeto correto p/ duplicatas.

---

## 3. Fluxo completo da importação (verificado no código, passo a passo)

```
1. DISPARO
   POST /importacoes | /importacoes/lote | /importacoes/selecionadas | Beat
     └─ fila.enfileirar(db, empresa, tipo, forcar, periodo, origem)      [fila.py]
         ├─ preflight local: certificado ativo? UF válida (NFe/CTe)?     → 409 sem disparar
         ├─ já EM_ANDAMENTO? → reusa execução (idempotente a clique duplo)
         ├─ janela de consumo (liberacao_para) → em_cooldown: 429 c/ hora de liberação
         ├─ cria ExecucaoImportacao(EM_ANDAMENTO) + commit
         └─ importar_documentos.delay(...)  (falha de broker → execução vira ERRO, não zumbi)

2. WORKER importar_documentos(empresa_id, tipo, execucao_id)             [tasks.py]
   ├─ reexecução pós-redelivery: execução já CONCLUIDA → sai (não reconsulta SEFAZ)
   ├─ carrega Certificado ativo (path do .pfx) + decifra senha (vault)
   ├─ sincronizacao.obter_estado + travar(LEASE 25min) por empresa+tipo   ← atomicidade por UPDATE…WHERE
   │    └─ NÃO CONSEGUIU LEASE → loga e sai.  ⚠ BUG: a nova execução fica EM_ANDAMENTO eterna (§6.1)
   ├─ respeita janela (salvo forcar → AGUARDANDO com retomada reagendada)
   ├─ NSU inicial: execução → estado → max(histórico) → "0"               (nunca "regride")
   ├─ com sessao_mtls(pfx,senha): pasta temp 0700, pem+key, apaga no finally
   └─ LOOP ≤ MAX_LOTES_POR_EXECUCAO(50), sleep ≥2s entre páginas:
        lote = importador.buscar_lote(cnpj, ultNSU=cursor, uf)
        ├─ ConsumoIndevido(656|429) → adota ultNSU/maxNSU devolvidos, estado AGUARDANDO,
        │   bloqueado_ate = agora + 1h+6min, CONTINUAÇÃO REAGENDADA (mesma execução, tentativas++)
        ├─ AmbienteIndisponivel → AGUARDANDO curto (5min·2^n), até max_tentativas_transporte=4 → ERRO
        ├─ por doc: _gravar_documento → INSERT ... ON CONFLICT DO NOTHING (idempotente)
        │     └─ venceu a inserção → grava XML em dados/xml/<empresa>/<tipo>/<chave>.xml
        ├─ por evento: cancelamento aplicado na nota OU guardado em eventos_fiscais_pendentes
        ├─ eventos não reconhecidos / erros de parse → contadores + execucao.aviso (nada some)
        ├─ avança cursor (avançar_cursor: monotônico) + max_nsu; COMMIT por lote (checkpoint)
        └─ fim: em dia (ult≥max) → marcar_sem_novidade (cooldown 1h+6m) | senão consulta_ok
        (estourou o teto de páginas → fila_reagendar na MESMA execução)
   finally: libera lease (só se adquiriu)

3. BEAT sincronizar_tudo (5min)
   ├─ retoma execuções AGUARDANDO vencidas (limit 50/tick) — backstop se o countdown se perdeu
   └─ fila.disponiveis_para_sincronismo_automatico: round-robin por ultima_consulta_em
       (NULLS FIRST p/ empresas novas), limite 20 empresas/tick — ⚠ sem fair-share POR ESCRITÓRIO (§6.8)

4. BEAT completar_xmls_pendentes (6h) + POST /documentos/completar-xmls
   por empresa c/ NFe "resumo": cota de 20 consultas/h (consChNFe), respeita lease, para em 656,
   substitui arquivo + marca leiaute="completo"

5. DISTRIBUIÇÃO/EXPORT
   GET /documentos (filtros, busca, competência) · /resumo · /por-empresa ·
   /{id}/xml · /exportar (ZIP em tmp via yield_per(200), relacao.csv BOM;<=, LEIA-ME) ·
   /exportar/estimativa · /lote/{id}/recibo (⚠ heurística — §6.2)
```

**Aderência às fontes oficiais — o núcleo está certo:** a NT 2014.002 confirma
1h-after-137, 656=bloqueio de 1h por CNPJ com "tentar antes zera o cronômetro", uso do
`ultNSU` devolvido, máx. 50 docs/lote, ~90 dias de retenção, 20 consultas/h de
consNSU/consChNFe, base "em dia" por `ultNSU==maxNSU`, e o retorno de `ultNSU` dentro da
rejeição 656 desde a v1.14 da NT **[FATO-FONTE: nfe.fazenda.gov.br NT2014.002; groups.google.com/nfephp; tributos.io]**.
O Manual dos Municípios/Contribuintes do ADN confirma lote máx 50 DF-e / 1 MB e "sem
retroatividade no primeiro acesso". **[FATO-FONTE: Manual ADN (PDF dinamicasistemas), tabnews]**
Regra que o projeto **não** modela: **inatividade > 60 dias interrompe a geração de NSU e não
há retroatividade** — cursor "dormindo" perde documentos do período (§12.6). **[FATO-FONTE: NT2014.002]**

---

## 4. Inventário de tecnologias (com estado real)

| Categoria | Tecnologia | Versão | Avaliação |
| --- | --- | --- | --- |
| Linguagem | Python | 3.11 | ✅ manter |
| API | FastAPI/Starlette | 0.115.0 / 0.38.6 (transitivo) | ⚠ starlette 0.38.6 com 7 advisories (DoS multipart, path-reconstruction, SSRF-UNC no StaticFiles) **[FATO-CÓDIGO: pip-audit]** |
| Fila | Celery + Redis | 5.4.0 / 5.0.8 | ✅ manter (servidor); sem TLS/auth no Redis ⚠ §7 |
| Banco | PostgreSQL / SQLite | 16-alpine / embutido | ✅ manter os dois; SQLite do desktop é decisão correta |
| ORM | SQLAlchemy | 2.0.35 | ✅; sem Alembic (migração aditiva própria) ⚠ §9 |
| Validação | Pydantic | 2.9.2 | ✅ |
| Auth | python-jose + passlib/bcrypt | 3.3.0 / 1.7.4+bcrypt 4.0.1 | ❌ substituir jose→PyJWT e passlib→bcrypt direto (ambos abandonados; ecdsa transitivo com side-channel sem fix) **[FATO-CÓDIGO: pip-audit]** |
| Cripto | cryptography (Fernet, pkcs12, X.509) | 43.0.1 | ⚠ CVEs; subir para ≥49 (API usada é estável) |
| HTTP | httpx | 0.27.2 | ✅ (considerar 0.28.x p/ fix de cookie-redirect) |
| XML | `xml.etree.ElementTree` stdlib | — | ⚠ sem defusedxml; `lxml` está no requirements **mas nunca importado** **[FATO-CÓDIGO]** |
| Frontend | Next.js 16.3.4 + React 19 + Tailwind | — | ✅ `npm audit`: 0 vulnerabilidades no lockfile atual |
| Desktop | PyInstaller onedir + Inno Setup + pystray | 6.11.1 | ✅ arquitetura correta p/ o caso de uso |
| Empacotamento | Docker Compose | — | ⚠ ver §7 (exposição, --reload, credenciais fixas) |
| Testes | pytest + respx (HTTP mockado) | 8.3.3 / 0.21.1 | ✅ 129 testes, foco nos riscos reais; faltam categorias enterprise (§15) |

**Inventário de integrações externas** (todas as chamadas de rede do produto):

| Integração | Protocolo | Autenticação | Onde |
| --- | --- | --- | --- |
| ADN NFS-e (produção/hom) | REST JSON `GET /contribuintes/DFe/{nsu}` | mTLS A1 da empresa | `nfse_adn.py` |
| ADN eventos `GET /NFSe/{chave}/Eventos` | REST | mTLS | *declarado no docstring, NÃO implementado no importador* **[FATO-CÓDIGO]** |
| NFeDistribuicaoDFe (AN) | SOAP 1.2 `nfeDistDFeInteresse` (distNSU/consNSU/consChNFe) | mTLS + cUFAutor | `nfe_sefaz.py`/`_distribuicao_dfe.py` |
| CTeDistribuicaoDFe (AN) | SOAP 1.2 `cteDistDFeInteresse` (distNSU/consNSU) | mTLS | `cte_sefaz.py` |
| GitHub Releases (manifesto + instalador) | HTTPS + SHA-256 | token opcional | `atualizador.py` |
| Pasta de rede (manifesto alternativo) | SMB/UNC + SHA-256 | ACL do SO | `atualizador.py` |
| Sem integração: e-CAC, procuração eletrônica, autXML, municípios legados, MDF-e, NFC-e, SAT/CF-e, NFCom, DFe de eventos de CT-e por chave | — | — | §11/§12 |

---

## 5. Inventário de endpoints (API pública atual)

`/auth/login` · `/empresas` CRUD+`/lote` (massa pfx+CSV)+`/{id}/sincronizacao` ·
`/certificados` POST (upload), `/resumo`, `/empresa/{id}` ·
`/documentos` list/resumo/por-empresa/`{id}/xml`/`exportar`/`exportar/estimativa`/
`completar-xmls`/`lote/{id}/recibo` ·
`/importacoes` POST, `/lote`, `/selecionadas`, `/selecionadas/previa`, `/estado`, `/resumo`,
`/{id}` (lista) · `/sistema/info|atualizacao|atualizacao/verificar|atualizacao/aplicar|
iniciar-com-windows|encerrar|logs|backup|abrir-pasta|saude-detalhada` · `/saude`. **[FATO-CÓDIGO]**

Ausências estruturais para um produto: versionamento de rota (`/v1`), paginação de
empresas/rota de administração, endpoints de usuário, webhooks (nenhum consumidor externo —
"API de integração" dos concorrentes é feature central de retenção), OpenAPI desabilitável,
keys de serviço (API-token para ERPs).

---

## 6. Problemas encontrados (núcleo operacional)

Cada item: **[prova] → [causa] → [impacto] → [correção proposta]**. Prioridade P0–P3.

### 6.1 (P0) Execução zumbi trava empresa+tipo permanentemente
- **[FATO-CÓDIGO, reproduzido]** `importar_documentos` quando `sincronizacao.travar()` falha
  (lease ocupado) faz `log.info` e `return` — **sem encerrar a `ExecucaoImportacao` que
  carrega** (`tasks.py` linhas 153–160: `travado = sincronizacao.travar(...)` → `if not
  travado: ... return`). Nenhum componente recolhe EM_ANDAMENTO órfãs
  (`sincronizar_tudo` só varre AGUARDANDO; nada expira EM_ANDAMENTO). Comprovei com script:
  status permanece `EM_ANDAMENTO` indefinidamente.
- **Caminhos de entrada reais do bug:** (a) corrida entre clique manual e Beat cria duas
  execuções EM_ANDAMENTO para o mesmo empresa+tipo (check-then-insert em `fila.enfileirar`
  não é atômico e não há unique parcial que impeça); (b) API commita a execução e morre
  antes de `delay()` (crash/rollback de infra); (c) redelivery duplicado do broker.
- **Impacto:** a empresa+tipo fica **muda para sempre**: o agendador entende "já existe
  varredura em andamento" e nunca mais enfileira; clique do usuário "reusa" a execução morta.
  Silencioso — exatamente o tipo de falha que some do cliente meses depois.
- **Correção:** estado de execução com *lease de progresso*: ao perder o lease, marcar a
  execução como `CONCLUIDA`/`PULADA` com motivo (ou AGUARDANDO com retomada pelo Beat);
  Beat ganha sweep "EM_ANDAMENTO sem lease vivo por > X min → reclassifica"; unique parcial
  `WHERE status='em_andamento'` por (empresa_id,tipo) no banco (PG: índice parcial; SQLite:
  índice parcial também suportado) elimina a corrida de raiz. **~80 linhas + 1 índice + 3 testes.**

### 6.2 (P1) "Recibo" do documento é heurística, não proveniência
- **[FATO-CÓDIGO]** `GET /documentos/lote/{id}/recibo` escolhe "a execução mais recente com
  `ultimo_nsu` não-nulo" da empresa+tipo — ignora o NSU do documento e qualquer faixa de
  execução. Atribuição errada em qualquer retomada/backfill.
- **Impacto:** a pergunta-chave do produto ("por que essa nota entrou quando/quem/sob que
  execução?") não tem resposta confiável; auditoria contábil exige isso.
- **Correção:** `DocumentoFiscal.execucao_id` FK gravada no insert atômico
  (`_gravar_documento` já recebe o contexto); recibo vira um SELECT trivial. Tabela de
  eventos de auditoria (§12.7) registra o mesmo.

### 6.3 (P1) Janela de crash entre "linha no banco" e "XML em disco" nunca se reconcilia
- **[FATO-CÓDIGO]** `_gravar_documento`: INSERT ON CONFLICT → *depois* `open().write()`.
  Crash entre os dois deixa registro com `xml_path` inexistente; o ON CONFLICT impede nova
  gravação → **documento "importado" sem XML para sempre**; o ZIP pula silenciosamente
  (só o LEIA-ME conta a diferença, e os contadores da tela divergem do pacote).
- **Correção:** (a) escrever `<chave>.xml.part` + `os.replace()` (atômico por diretório);
  (b) reconciliador noturno (`verificar_integridade`): SELECT docs sem arquivo → re-busca
  por NSU/chave (cota própria) ou marca `leiaute="ausente"`; (c) hash SHA-256 gravado no
  insert e conferido na reconciliação. Resolve também a exigência de *checksum* do §13 do
  briefing.

### 6.4 (P1) Erro de certificado (vencido/401/TLS) não bloqueia empresa nem alerta — vira retry eterno
- **[FATO-CÓDIGO]** A classe de erro "CERTIFICADO" não existe: 401/403 no ADN sobem por
  `raise_for_status` como exceção genérica do laço (`httpx.HTTPStatusError` não é pega como
  TransportError no bloco de tentativa — escapa para o `except Exception` da task → ERRO);
  no SOAP, TLS-erro (cert vencido) cai em TransportError → `AmbienteIndisponivel` →
  AGUARDANDO → Beat re-dispara toda hora. O `Certificado.validade` é conferido **só no
  upload e na tela de resumo**, nunca no caminho de importação.
- **Impacto:** empresa com A1 vencido consome ciclos do governor indefinidamente e a tela
  mostra "Aguardando SEFAZ" (mensagem **errada** — o operador caça o problema no lugar
  errado). O requisito "CERTIFICADO → bloquear empresa e alertar" está descrito no briefing
  do README mas não implementado.
- **Correção:** exceção tipada `ErroCertificado` (401/403, `ssl.SSLCertVerificationError`,
  `Vault.SegredoIndecifravelError`, validade expirada verificada **antes** de gastar janela)
  → estado `BLOQUEADA_CERTIFICADO` na empresa (o agendador pula, a tela mostra vermelho com
  ação "reenviar certificado"), contador de bloqueio para alertas.

### 6.5 (P2) Competição de consumidor com outro sistema no mesmo CNPJ degrada em loop
- **[FATO-CÓDIGO]** `bloqueios_seguidos` é contabilizado e exibido, mas não age: 3–5 bloqueios
  consecutivos a uma empresa deveriam elevá-la de "espera educada" para *incidente*
  (outro sistema usando o CNPJ — o caso clássico citado nos próprios docs).
- **Correção:** política: `bloqueios_seguidos ≥ 3` → evento de auditoria + aviso destacado
  na empresa ("outro sistema consultando? desligue o outro lado ou aumente a folga") +
  backoff do próprio tick para aquela empresa (ex.: 2h, 4h, 8h até N, depois manual).
  Alavanca de custo baixo e percepção alta.

### 6.6 (P2) Agendador ignora o tenant no fair-share (multiempresa real)
- **[FATO-CÓDIGO]** `disponiveis_para_sincronismo_automatico` ordena por
  `min(ultima_consulta_em)` global com `LIMIT 20` **sem particionar por `escritorio_id`**.
  Um escritório com 500 empresas nunca-varridas (NULLS FIRST) consome todos os slots de todos
  os ticks; os outros escritórios ficam atrás indefinidamente. É a violação direta de
  "nenhuma empresa deve prejudicar as outras" em escala.
- **Correção:** round-robin **por tenant** (window function `ROW_NUMBER() OVER
  (PARTITION BY escritorio_id ORDER BY mais_antiga)` limitando por escritório), mais quota
  configurável de empresas/tick/escritório. Par do modelo `fila.enfileirar` que já recebe
  `origem` — manter.

### 6.7 (P2) N+1 nas rotas de estado e nos agregados do painel
- **[FATO-CÓDIGO]** `estados_do_escritorio` emite, por empresa, 1 query de estado × 3 tipos +
  1 query "em_andamento" × 3 tipos + contagem de documentos = ~(7·N) queries; `/documentos/por-empresa`
  com competência definida roda 1 query **por empresa**. Com 30 empresas o painel paga ~210
  queries a cada 20s de polling; com 1.000 empresas, ~7.000 por snapshot.
- **Correção:** 2 queries (estados por empresa via JOIN empresa×sincronizacoes LEFT JOIN
  execução EM_ANDAMENTO; agregação por empresa com `GROUP BY` único e filtro por período
  no mesmo SELECT). Ganho mensurável: polling do dashboard O(1).

### 6.8 (P2) Falta de validação do XML gravado + bombas de descompressão
- **[FATO-CÓDIGO]** `decodificar_xml_adn` aceita base64→gzip→zip sem limite de tamanho
  descomprimido (`gzip.decompress`, `zipfile.read` — clássico decompression/zip-bomb);
  NFe `_converter` **persiste o item mesmo quando `ET.fromstring` produziu raiz vazia**
  (dados zerados, chave vinda do JSON do lote) sem marcar rejeição; nenhum parser usa
  `defusedxml`/entidades bloqueadas (ET do stdlib é vulnerável a *billion laughs*). Fonte
  atual = HTTPS gov, então probabilidade baixa — mas o produto pretende aceitar *provedores
  municipais de terceiros* (§12), onde isto deixa de ser teórico.
- **Correção:** teto por item (ex.: 4 MB inflado), parser endurecido (entidades proibidas —
  `ET.XMLParser` com `resolve_entities=False` ou defusedxml), validação mínima obrigatória
  (chave presente + parseável + tamanho piso) antes do insert; item inválido vira
  `REJEITADO` com cópia do bruto para diagnóstico (nunca sumir — princípio já adotado no
  código para eventos).

### 6.9 (P3) Detalhamentos
- `POST /importacoes/lote` dispara N enfileiramentos síncronos dentro do request HTTP
  (1 commit por empresa) → com 500 empresas estoura timeout de gateway; mover para task
  "dispatcher" idempotente. **[FATO-CÓDIGO]**
- `valor_total` como `float` (IEEE754) para valor monetário fiscal — aceitável p/ exibição,
  **inaceitável** se o produto entrar em conciliação; migração para `NUMERIC(16,2)` no
  schema de destino. **[RECOMENDAÇÃO]**
- `chave_acesso` truncada em 60 por `_normalizar_chave` e colide silenciosamente se
  chave real for maior (NFS-e nacional tem chave de **50** dígitos **[FATO-FONTE: notagateway/portal
  NFS-e]** — hoje cabe, mas a "normalização" deveria **validar** 44/50 dígitos, não cortar).
- Enum do Postgres via `ALTER TYPE ADD VALUE` em startup com 3 subindo juntos: tratado
  com AUTOCOMMIT e tolerância — funciona, mas é migração *implícita* na import path;
  Alembic (§9) elimina a categoria inteira de risco.
- `completar_xmls_pendentes` varre **todas** as empresas por tick e só cobre NFe; CT-e que
  chega `resCTe` nunca é completado (XSD do CT-e não expõe consChCTe na v1.00 — o repo sabe;
  o correto é dizer isso na tela: "CT-e permanece em resumo — usar consNSU do NSU indicado",
  hoje fica como silêncio). **[FATO-CÓDIGO cte_sefaz.py]**
- `test_worker_importacao_fluxo.py` tem 1 teste; o fluxo completo (lote→gravar→cursor→commit
  por lote) está sub-coberto — ver plano de testes §15.

---

## 7. Vulnerabilidades (segurança)

### 7.1 Dependências — `pip-audit` no ambiente real do projeto (2026-09-10)
**35 advisories em 7 pacotes** **[FATO-CÓDIGO]**:

| Pacote | Atual | Risco material | Correção |
| --- | --- | --- | --- |
| python-multipart | 0.0.9 | ReDoS/DoS em upload multipart **nas rotas de pfx/CSV** (exatamente as rotas expostas), path-traversal em config de upload | ≥0.0.31 |
| starlette (via FastAPI) | 0.38.6 | DoS por field urlencoded gigante; path reconstruction (host confusão); StaticFiles SSRF/UNC no **Windows** (o painel do desktop usa ASGI próprio, mas a lib está no cliente) | via FastAPI ≥0.12x |
| cryptography | 43.0.1 | issues de parsing (PKCS7/OpenSSH/IPv6 ipaddress) | ≥49.0.0 |
| python-jose (+ecdsa transitivo) | 3.3.0 | biblioteca **abandonada**; ecdsa com side-channel Minerva sem correção "won't fix" | substituir por PyJWT (jose só é usado p/ HS256 — 30 min de trabalho) |
| lxml | 5.3.0 | advisory conhecido | **remover** (nunca importado) |
| pyOpenSSL | 24.2.1 | advisory | remover (httpx não precisa; nada importa `OpenSSL` **[FATO-CÓDIGO grep]**) |

`npm audit` no lockfile do frontend: **zero** vulnerabilidades (verificado). **[FATO-CÓDIGO]**

### 7.2 Configuração de plataforma (modo servidor)
- **[FATO-CÓDIGO] `docker-compose.yml` publica `5432` e `6379` no host** com
  `notasflow/notasflow` e **Redis sem senha** — em "PC zerado do escritório" isso expõe o
  banco inteiro (senhas cifradas, mas o **arquivo `.env` com a VAULT_MASTER_KEY não** — e o
  compose monta `./backend:/app`, onde ele mora) e a fila (injeção de tasks = execução de
  código no container worker, pois Celery/Redis serializa pickle? — não, json por padrão,
  mas ainda permite enfileirar qualquer task registrada). Mitigação trivial: remover `ports:`
  (rede interna basta) ou casar com `127.0.0.1:` e senha forte no Redis. **P1 imediato.**
- **[FATO-CÓDIGO] API com `--reload` no compose de produção** (dev do uvicorn, sem workers). **P2.**
- **[FATO-CÓDIGO] `gerar_env.py` grava `CORS_ORIGINS=..., *`** e `main.py` combina `*` com
  `allow_credentials=True` → origem refletem-qualquer. O token é localStorage+header (não
  cookie), então roubo de sessão via CORS exige pré-XSS; ainda é **P1** para um produto que
  pode introduzir cookie no futuro e é indefensável em review. Fix: default sem `*` e
  validação de origens.
- **[FATO-CÓDIGO] Sem guarda de startup contra segredos default**: `SECRET_KEY` default
  "troque-esta-chave-em-producao" **assina JWTs válidos** se alguém subir com `.env.example`
  copiado → forja de admin. Adicionar: recusar modo servidor com secret default/vazio e com
  `VAULT_MASTER_KEY` vazia. **P1 (30 linhas).**
- **[FATO-CÓDIGO] `/auth/login` sem rate-limit/lockout**; timing-side-channel de enumeração
  de email (bcrypt só roda se usuário existe). **P2** (o painel desktop local mitiga; servidor
  multi-tenant não).
- **[FATO-CÓDIGO] Swagger `/docs` aberto** nos dois modos (desktop: superfície local;
  servidor: superfície pública — expõe contrato a varredores). Config `DOCS_ENABLED`. **P2.**
- **[FATO-CÓDIGO] `POST /sistema/backup` ZIPpa `.env` (chave mestra) + certificados + banco
  sem cifra** e o material vai para OneDrive/pen drive por recomendação da UI. Vazamento do
  backup = cofre comprometido (senha do banco PG local + chave Fernet + pfx juntos). Fix:
  backup com passphrase (AES do próprio zip ou envelope), ou excluir `.env` do ZIP e instruir
  fluxo separado. **P1.**
- **[FATO-CÓDIGO] `NOTASFLOW_PERMITIR_REDE=true` serve o painel em HTTP puro na LAN** com
  login/senha de certificados trafegando em claro (o `--host 0.0.0.0` com aviso no log). Se a
  feature existe, precisa de TLS self-signed + HSTS local ou remoção. **P2.**
- **[FATO-CÓDIGO] Atualização automática:** HTTPS + SHA-256 confere integridade, não
  **origem do conteúdo** — quem pode escrever no `latest.json` da release (ou da pasta de
  rede) pode trocar o instalador e o hash juntos; Authenticode e assinatura de manifesto
  (TUF-style detached) são os próximos passos, reconhecidos nos próprios docs. Sem
  verificação de assinatura no workflow (runner Windows + `choco install innosetup` sem pin =
  supply-chain residual). Para produto comercial: assinar o exe **e** o manifesto. **P2 (P1
  quando houver clientes fora do escritório).**

### 7.3 Threat model resumido (matriz RISCO → P(robabilidade) → I(mpacto) → mitigação → prioridade)

| # | Risco | P | I | Mitigação atual | Gap / ação | Prio |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Senha de certificado exposta em logs/respostas/DB | B | A | Fernet no banco; campos omitidos nas respostas; pfx nunca devolvido; senha só em memória no escopo curto (`mtls.py`) | bom; faltar lint anti-log de `senha`/`pfx_bytes` (CI) | P3 |
| 2 | Chave privada em disco durante varredura | B | B | temp 0700 + unlink em finally | considerar `ssl.SSLContext.load_pkcs12` (sem arquivo) quando httpx suportar | P3 |
| 3 | Roubo de `VAULT_MASTER_KEY` (.env) | M | A | chave fora do banco; rotação com `VAULT_PREVIOUS_MASTER_KEYS` | .env desktop sem ACL explícita (0600 não é definido! `ambiente._gerar_env` usa `write_text` padrão) → **chmod 600 no .env**; backup cifra (§7.2) | P1 |
| 4 | PG/Redis expostos na LAN (compose) | A | A | nenhum (bind 0.0.0.0 implícito do Docker) | remover `ports:` ou 127.0.0.1; senha Redis | P1 |
| 5 | Forja de JWT (secret default/fraco) | M | A | gerar_env aleatório | guarda de startup (recusar default) | P1 |
| 6 | Brute-force de login | M | B | nenhum | rate-limit + lockout progressivo (slowapi/Redis p/ servidor; in-memory p/ desktop) | P2 |
| 7 | IDOR/escala entre tenants | B | A | **todas** as leituras filtram por `escritorio_id` do JWT (verificado rota a rota: empresas, certificados, documentos, importações, recibo, export) ✅ | manter + testes de isolamento por tenant (§15) + RLS como defesa em profundidade | P2 (RLS) |
| 8 | SQL injection | B | A | 100% ORM/params; raw SQL só DDL migratório com constantes | manter | — |
| 9 | XXE / bombas XML | B | B | parser ET sem hardening; fontes = gov (mitigante) | defusedxml/limites (§6.8) — obrigatório **antes** de aceitar provedores municipais | P1 (já listado) |
| 10 | Caminho de arquivo (upload/traversal) | B | A | nomes sanitizados (`chave` só alnum), painel estático com `relative_to` (verificado bom), `_slug` sem pontuação | manter | — |
| 11 | DoS por export/ZIP no request | M | B | teto 25k + tmp file + background delete | mover p/ job de fila com link de resultado | P2 |
| 12 | SSRF | B | B | nenhuma URL externa do usuário além do manifesto (config local, aceita só https/UNC) | manter restrição de esquema no `atualizador` (está OK) | — |
| 13 | Supply chain (deps + instaladores) | A | A | pin de versões (bom!); lock npm | pip-audit/Dependabot **contínuos** + renovate; hash em pip (pip-tools); assinar exe | P1 |
| 14 | Update comprometido (release/shared) | B | A | https+sha256 | assinatura de manifesto + Authenticode (fase comercial) | P2 |
| 15 | Vazamento de CNPJ/razões por telemetria acidental | B | B | nenhuma telemetria externa (bom) | manter princípio: nada sai da máquina sem opt-in | — |

Probabilidades: B=baixa, M=média, A=alta dado o público (contadores) e a ausência de hardening
de borda. **[RECOMENDAÇÃO]** com base nos achados acima.

---

## 8. Gargalos e limites de escala (com a matemática, não "números de bala")

**A restrição soberana é a janela de consumo, não CPU/rede.** Por empresa+tipo, o steady-state
é **1 ciclo de consulta/hora** (137→espera; docs oficial). Logo:

- 1.000 empresas × 3 tipos = **3.000 ciclos/h** ≈ 0,83 ciclo/s. Cada ciclo médio ~1–3
  requisições (1 página + 1 vazio) → **~2 req/s de pico por instância** — nada para httpx; o
  gargalo real é *horas de parede para cobrir a carteira*, o que o round-robin já resolve.
- **Backfill inicial (o caso pesado):** durante corrente de documentos (138) o cliente pode
  varrer página a página a cada ≥2s **[FATO-FONTE: NT + sped-nfe]**; com teto de 50 páginas e
  lote de 50 → **até ~2.500 docs por varredura**, ou ~20 docs/s de download efetivo (rede+parse)
  ≈ 1.200 docs/min por empresa em backlog. 30 empresas em backlog em paralelo total:
  o worker vira o limite (concorrência 4 → 4 empresas em varredura por container; escalar
  `--scale worker=N`, **seguro** porque o lease é por empresa+tipo no banco — [FATO-CÓDIGO,
  verificado em `sincronizacao.travar`]).
- **Banco:** 1M docs ≈ 1KB linha ×1M (~1GB com índices) + **XML em disco ~6GB cru**
  (`_estimar_bytes` usa média 6KB **[FATO-CÓDIGO]**) → 250M docs (5 anos de escritório médio)
  ≈ 2,5GB banco + 1,5TB XML sem compressão → **compressão on-disk (zstd 10:1) ou object
  storage é a alavanca (§13-arma). `execucoes_importacao` cresce ~3 linhas/dia/empresa** →
  300k linhas/ano por 1k empresas (ok, mas com política de retenção/arquivamento).
- **SQLite desktop:** WAL + busy_timeout 30s + 1 escritor por vez (threads) aguenta o uso
  declarado (≤dezenas de empresas). Limite prático honesto: **~50–100 empresas/máquina**;
  acima, migrar o cliente para o modo servidor é o caminho certo (não otimizar SQLite).
- **Polling do painel:** `/importacoes/resumo` e `/estado` fazem N+1 (§6.7); a 1.000
  escritórios simultâneos em servidor, o polling de 20s multiplica — O(1) por rota antes de
  vender "painel para escritório inteiro". **[INFERÊNCIA das queries, FATO do código]**
- **consChNFe gap-fill:** 20/h/CNPJ oficial **[FATO-FONTE]** — backlog grande de "só resumo"
  esvazia a fila de gap-fill por dias; correto e inevitável; o produto deve **mostrar a
 ETA** ("faltam N, ~M horas no ritmo oficial") em vez de silenciar.
- **Risco regulatório-operacional de escala:** com 60 dias de inatividade a geração de NSU
  **para e não retroage** **[FATO-FONTE: NT2014.002 §3.4]** — um plano de manutenção que
  desligue o beat >2 meses **perde a carteira inteira** (docs só ficam ~90 dias na
  distribuição). O produto precisa de: alerta de "heartbeat quebrado há X dias" +
  política de janela de recuperação + (futuro) download pelo portal/e-CAC para >90d.

**Metas objetivas propostas [RECOMENDAÇÃO]:** p95 de varredura (empresa+tipo em regime,
sem backlog) < 30s; snapshot de estado de 1.000 empresas em < 1,5s (pós-§6.7); 0 tarefas
duplicadas por 1M de dispatches (teste de concorrência §15); recuperação de worker morto
no meio de download sem perda e sem re-baixar >1 lote (checkpoint é lote — meta atingível
hoje, falta o teste de caos que prove).

---

## 9. Dívida técnica — classificação componente a componente

| Componente | Veredicto | Justificativa |
| --- | --- | --- |
| `sincronizacao.py` (governor) | **IMPROVE** | Núcleo correto e testado; faltam: sweep de EM_ANDAMENTO zumbi, política de bloqueios_seguidos, fair-share por tenant, "heartbeat 60d" |
| `worker/tasks.py` | **REFACTOR** | 861 linhas misturando orquestração+persistência+ZIP+eventos; extrair `PipelineImportacao` (domain service) e manter a task como casca; corrigir 6.1/6.3/6.4 aqui |
| `_distribuicao_dfe.py` + importadores | **KEEP** | Contrato SOAP/REST correto, resiliente, namespace-agnóstico, docZip/gzip ok; endurecer parser (6.8) e extrair validação |
| `eventos.py` (cancelamento/pendentes) | **KEEP** | Design correto (evento antes da nota, nunca descartar); falta generalizar p/ CC-e/manifestação quando implementado |
| `nfse_adn.py` | **IMPROVE** | Decodificação tolerante certa; adicionar `GET /NFSe/{chave}/Eventos` (declarado, não feito), validação de chave 50, limites de inflate |
| `fila.py` (portão) | **IMPROVE** | Ordem de travas certa; tornar o par "criar execução + dispatch" à prova de crash (status intermediário ENFILEIRANDO + sweep) |
| `vault.py` | **KEEP + hardening** | Interface certa p/ trocar por KMS depois; adicionar: cifrar com AAD por empresa (context binding), chaves por tenant quando houver multiempresa paga, `chmod 600` no .env desktop |
| `mtls.py` | **KEEP** | Correto; mover para `load_pkcs12` no SSLContext quando viável; reusar contexto por varredura (já é 1 por varredura ✅) |
| `certificados.py` (identidade X.509) | **KEEP** | Fallbacks com validação de dígitos, sem "adivinhação" — bom; adicionar parsing completo de OtherName DER (hoje é regex latin-1 — suficiente p/ ICP-Brasil real, documentar a limitação) |
| `models.py`/schema | **IMPROVE** | Adicionar: hash/tamanho de XML, `execucao_id` no documento, status de processamento formal (§12.3), índices das queries reais, NUMERIC p/ valores; **não** re-normalizar o que está bom |
| `migracoes.py` (sem Alembic) | **REPLACE em produção** | Funciona e é idempotente; Alembic antes do multi-cliente (janela de upgrade com 2 instâncias subindo é aceitável *hoje* só porque é aditiva) |
| `db/session.py` (SQLite WAL) | **KEEP** | Decisão certa para desktop; documentar teto (§8) |
| `fila_local.py` (MiniCelery) | **KEEP** | Espelho honesto da interface Celery com testes nos pontos críticos (agenda persistida, tick único, sem broker-loss de correctness porque o estado está no banco) |
| `celery_app.py` | **KEEP** | `acks_late`/`visibility`/`prefetch` corretos; adicionar `events_enabled=False` (evita tráfego Redis) p/ escala |
| `atualizador.py` | **IMPROVE** | Solidez notável (hash, origem https, flags Inno, rollback=publicar versão menor); adicionar assinatura de manifesto + pin de versão do instalador e `.env` permissões |
| `ambiente.py` (1ª execução) | **IMPROVE** | Fluxo certo; `chmod 600` no `.env`/`CREDENCIAIS.txt`; gerar `REDIS_URL` com senha no compose |
| `caminhos.py`, `painel.py`, `servidor.py`, `bandeja.py`, `janela.py`, `controle.py` | **KEEP** | Separação correta dos 3 "mundos" (fonte/pacote/dados); painel com anti-traversal verificado |
| Roteadores API | **IMPROVE** | Boas travas de tenant; extrair agregações p/ services (kill N+1), versionar `/v1`, `forcar` com confirmação de escrita (idempotency-key) |
| `schemas.py` | **KEEP** | Validação correta (CNPJ dígitos, UF, competência); faltar validação de chave 44/50 p/ documentos |
| Frontend (pages/components) | **IMPROVE** | UX do caso feliz forte; falta tela de diagnóstico por documento/empresa com "próxima tentativa" clara (§12-UX), e telas admin de usuários/escritório |
| `docker-compose.yml`/Dockerfiles | **REPLACE (endurecer)** | §7.2: ports internos, sem `--reload`, `--scale` documentado, secrets via env file não-montado, healthcheck na api, digest pin imagens base |
| `docs/github-actions-release.yml` | **REPLACE** | Ordem quebrada (tests antes do painel build — reproduzido); falta `npm run build:desktop` ANTES do pytest ou condicionar o teste; falta job separado de teste; falta pin de actions/versões (supply-chain); falta publicar artefato com assinatura (futuro) |
| `INSTALAR_TUDO.*` | **IMPROVE** | `curl get.docker.com | sh` e brew sem checksum são risco aceitável para on-prem interno, **inaceitável** para distribuição comercial "padrão"; verificar sha256 dos instaladores baixados |
| Testes | **IMPROVE** | Qualidade alta p/ o porte; faltam as 6 categorias enterprise (§15) |

Regra pedida — *não reescrever o que não precisa*: **nenhum componente foi marcado REPLACE
"estilisticamente"; os 3 REPLACE têm motivo material** (Alembic p/ schema de clientes reais,
CI para publicar, compose para expor menos).

---

## 10. Benchmark — o que os concorrentes resolvem e onde este projeto está

Fontes: páginas oficiais e material público dos players (links na seção 19). Números de
"cobertura" são **afirmações de marketing do concorrente** — tratadas como such.

### 10.1 A matriz

| Capacidade | NotasFlow hoje | Jettax 360 | Domínio (TR) + rotinas | Fiscal.io Monitor | BoxFiscal | XMLHub (HubStrom) |
| --- | --- | --- | --- | --- | --- | --- |
| Captura NF-e/NFC-e via DFe (A1 cliente) | ✅ (AN distNSU, governor completo) | ✅ "Módulo Federal" | ⚠ ERP **não captura**; importa ZIP/pasta via *Rotinas Automáticas* | ✅ "captura com certificado, a cada hora" | ✅ "SEFAZ via Distribuição DF-e (NSU)" | ✅ |
| CT-e | ✅ | ✅ | ⚠ (importa arquivo) | ⚠ | ✅(claim) | ✅ |
| CF-e/SAT | ❌ | ✅ (claim "CFe") | ❌ | ❌ | ❌ | ❌ |
| MDF-e | ❌ | ❓ | ❓ | ❓ | ✅ (claim captura MDF-e) | ❓ |
| NFS-e nacional (ADN) | ✅ | ✅ | ⚠ | ❓ | ✅ | ✅ |
| NFS-e municípios legados | ❌ (gap central) | ✅ **2.200+ municípios** (claim), +600 cidades "tomados de fora" | ❌ | ⚠ (parceiros) | ❓ | ✅(claim "Portal Nacional"+prefeituras) |
| Certificado: cofre multiempresa | ✅ (Fernet + cofre local; 1 pfx/empresa) | ✅ gestão central (claim) | ✅ módulo dedicado "Domínio Certificados Digitais" (gestão/cobrança de certificação!) | ✅ | ✅ A1/A3 (claim) | ✅ |
| Manifestação do destinatário | ❌ (gap-fill por chave é o atalho) | ✅ "sem depender de manifestações obrigatórias" (autXML/contador — [ver §12.5]) | ❌ | ❓ | "registra Ciência automaticamente" (claim apogeu) | **decide não manifestar** (posicionamento jurídico — "evita vincular CNPJ do escritório") |
| Automação agendada | ✅ beat + retomada | ✅ 24h (claim) | ✅ agendador de rotinas do ERP | ✅ | ✅ | ✅ |
| Governor/retry consciente | ✅ **melhor da categoria vista em código aberto: 656=estado, cursor realinhado, cooldown com folga** | ❓ (não público) | n/a (não consulta por conta) | ❓ | ❓ | ❓ |
| Dedup/idempotência | ✅ UQ (empresa,chave) + ON CONFLICT | ❓ | ⚠ import por arquivo | ❓ | ❓ | ❓ |
| Auditoria/trilha | ⚠ log de execução; sem audit trail humano | ✅ auditorias fiscais (NCM, PIS/COFINS, ST, DIFAL) — **auditoria de *conteúdo*, não de processo** | ✅ módulo ASIS p/ auditoria de XML | ✅ rastreabilidade origem/data/destino do XML | ✅ "auditor 6 regras" | ✅ relatórios |
| Escala multiempresa | ⚠ schema pronto; fair-share §6.6; sem gestão | ✅ "plataforma do escritório" | ✅ (ERP multi-empresa clássico) | ✅ | ✅ | ✅ |
| API p/ ERPs | ⚠ API interna; sem integrações Out (Domínio/Onvio) | ✅ API "motor fiscal" + **integração nativa Domínio, Contmatic, G5** | ⚠ entrada via Onvio API (terceiros empurram p/ Domínio) | ✅ push Onvio | ✅ "export 1-clique pro layout Domínio" | ✅ "integração+ envia pro servidor" |
| UX contador (português, competência, ZIP com Excel BR) | ✅ **acima da média da categoria** no fluxo core | ✅ | ✅ (dentro do ERP) | ✅ | ✅ | ✅ |
| Desktop offline | ✅ (único neste conjunto com .exe autônomo + auto-update + bandeja) | ❌ (web) | (o ERP é desktop, mas sem captura) | ❌ | "MonitorDFe desktop" (claim) | ❌ |
| Self-service onboarding | ❌ | ✅ (SaaS) | n/a | ✅ | ✅ | ✅ |
| Preço modelo | (interno) | SaaS módulos | licenças TR + módulo cert. | planos p/ carteira | freemium SaaS | SaaS |

### 10.2 Leitura honesta

1. **O fosso competitivo real não é a captura NF-e** — todo mundo faz; a NT2014.002 é
   pública. O fosso é: (a) **cobertura de NFS-e municipal legada** (Jettax vende 2.200+
   municípios; isso é uma frota de adaptadores + parcerias, não código heroico — mas é
   *trabalho*), (b) **auditoria de conteúdo** (DIFAL, ICMS-ST, NCM, Simples) — o mercado
   monetiza *consequência fiscal*, não *arquivo XML*, (c) **integração com o ERP do
   contador** (Domínio/Onvio, Contmatic) — retenção, (d) **e-CAC/DF-e de terceiros**
   (pendências, procurações, autXML em escala).
2. **Onde este projeto já ganha:** o governor de consumo e o desktop autônomo com
   atualização são melhores do que qualquer descrição pública dos concorrentes no ponto
   mais caro (queimar CNPJ; escritório pequeno sem TI). Manter essa vantagem **escrita e
   testada** é estratégia.
3. **Onde perde hoje:** cobertura de fonte (municípios legados, NFC-e/CF-e, MDF-e,
   eventos NFSe), nada de auditoria de conteúdo, nada de integração de ida (empurrar p/
   ERP), sem multiempresa self-service.
4. **Domínio não é (só) concorrente — é o destino**: o formato de pasta "TipoNota/Atividade/
   Empresa-Código/MAAA/Nota.xml" das *Rotinas Automáticas* (documentado no help do próprio
   Jettax) é uma **feature barata e decisiva para este projeto**: exportar no layout Domínio
   (e importar via Onvio API quando houver conta) converte o NotasFlow em "parceiro de
   suprimento do Domínio", não substituto — time-to-market menor. **[RECOMENDAÇÃO]**
5. **Posicionamento de manifestação**: XMLHub anuncia *não* manifestar por risco jurídico;
   Jettax se apoia em certificado do contador/autXML. O produto precisa de uma decisão de
   produto consciente (§12.5): capturar sem manifestar (hoje, +gap-fill), oferecer
   manifestação **opt-in por empresa com trilha auditável** (ciência/confirmação são atos do
   contribuinte), e o modelo autXML (contador no XML do emitente) como via de escala de
   carteira. **[FATO-FONTE sobre limites: NT2014.002 tabela de atores; Ajuste SINIEF 16/2018 autXML
   máx. 10 terceiros; FAQ Portal NF-e]**

---

## 11. Funcionalidades ausentes (e o que NÃO vale a pena fazer)

**Vale fazer (ordem lógica):** manifestação do destinatário (NFeRecepcaoEvento4 — ciência →
XML integral pela própria distribuição, reduzindo dependência do gap-fill 20/h); MDF-e
(WS oficial existe, custo marginal baixo:复用 `_distribuicao_dfe.py`); auditor do estado
de sincronização ("heartbeat 60d", §8); exportadores de destino (pasta-Domínio, Onvio,
webhook de "documento novo"); tela de diagnóstico por documento; audit trail; gestão de
usuários/planos; multi-certificado por empresa (matriz filiais; hoje `Certificado` só tem
1 ativo por empresa — e a *consulta é por CNPJ base com qualquer filial [FATO-FONTE: NT — "autenticada pelo CNPJ base"]*,
o que permite **um certificado A1 por empresa-mãe cobrindo filiais** — recurso que o schema
ainda não expõe!); captura municipal de NFS-e (adaptadores, começando pelas top-N cidades
da carteira); verificação de assinatura XML (gama "confiança zero") — opcional.

**Não fazer (custo sem benefício real, hoje):** reescrever em outro stack; microserviços;
multi-infra (Terraform/K8s) antes de 100 clientes; IA generativa em qualquer ponto do
pipeline de captura (determinístico por natureza — IA só serve p/ *diagnóstico assistido*
e classificação de erros desconhecidos, seção 18); fila durável RabbitMQ/Kafka (o broker é
decorativo — a correctness está no banco; trocaria risco por risco); reescrever MiniCelery
como subprocesso separado (o ganho seria marginal p/ o perfil desktop); substituir SQLite
no desktop; "importar notas emitidas pela própria empresa via distribuição" — **não
existe** para emitentes puros (NT2014.002 tabela; docs do projeto acertam) → resolver via
autXML/manifestação/e-CAC, não "descobrindo" NSU.

---

## 12. Arquitetura-alvo (FASE 10)

### 12.1 Componentes

```
                    ┌────────────────────────────────────────────────────────────┐
                    │                        INTERFACES                          │
                    │  Web app (Next)  ·  Desktop .exe  ·  REST /v1  ·  Webhooks │
                    │  Operações: console admin + observabilidade (dash/alertas)  │
                    └───────────────┬────────────────────────────────────────────┘
                                    │ HTTPS + JWT/keys
                    ┌───────────────▼──────────────────────────────┐
                    │           API LAYER (FastAPI, stateless)     │
                    │ auth/tenants/cert/docs/imports/admin/healthz │
                    └───┬───────────────┬──────────────┬───────────┘
        read/write      │               │ commands     │ events
  ┌─────────────────────▼───┐   ┌───────▼─────────────────────┐   ┌────────────────┐
  │  PostgreSQL              │   │  QUEUE (Redis/RabbitMQ)     │   │ Object Storage │
  │  (ou SQLite embutido)    │   │  discover/collect/ingest/   │   │  XML bruto     │
  │  tenants, docs, estado,  │   │  manifest, reconcile        │   │  + zstd, hash  │
  │  jobs, events_auditoria  │   │  DLQ + idempotency keys      │   │  (local fs no   │
  └──────────┬───────────────┘   └───────┬─────────────────────┘   │   desktop)     │
             │                          │                          └────────┬───────┘
             │            ┌─────────────▼────────────────┐                 │
             │            │  FISCAL ENGINE (workers)     │                 │
  ┌──────────▼─────────┐  │  Scheduler/Governor ─────────┼── quota, janela, lease, backoff,
  │  STATE PLANE        │  │  Discoverer (distNSU/ADN)    │   circuit-breaker POR AMBIENTE
  │ sincronizacoes_dfe  │◄─┤  Collector (download/parse)  │   (SEFAZ/ADN/Município independentes)
  │ checkpoints, quotas │  │  Classifier (eventos/estado) │
  │ (TABELAS, não fila) │  │  Manifestor (ciência/confirma)│
  └────────────────────┘  │  Reconciler (XML∫banco, gaps) │
                           └──────────────┬───────────────┘
                                          │
                    ┌─────────────────────▼──────────────────────┐
                    │  SOURCE ADAPTERS (plug-in, mesmo contrato) │
                    │  ADN · AN-NFe · AN-CTe · AN-MDFe ·         │
                    │  Manifestação/RecepcaoEvento · e-CAC ·      │
                    │  MunicipalNFS-e (adaptadores por cidade) ·  │
                    │  autXML-Contador (certificado do escritório)│
                    └─────────────────────────────────────────────┘
```

### 12.2 Máquina de estados formal de documento (exigência 9)

```
DISCOVERED → QUEUED → DOWNLOADING → DOWNLOADED → PARSED → STORED → CLASSIFIED
     → (docs só-resumo) AWAITING_MANIFEST/GAPFILL → ENRICHED → READY_FOR_IMPORT
     → (futuro: pushed ao ERP) DELIVERED → ARCHIVED
Transições de erro (tipadas, cada uma com política):
     RETRYABLE(TEMPORARY|RATE_LIMIT|ENVIRONMENT)  → backoff por classe
     BLOCKED(CERTIFICATE|TENANT_QUOTA|AUTHORITY_DOWN) → pausa empresa/tenant (não queima cota)
     REJECTED(MALFORMED_XML|NO_KEY|INTEGRITY) → preserva bruto + motivo
     DEAD_LETTER(exaustão de retries) → fila de revisão humana, reprocessável
Persistência: `documentos.state` + `documentos_transicoes` (append-only) — nunca UPDATE de
string solta; máquina declarada no código (dataclass registry) e testada (transições
inválidas falham no teste, não no cliente).
```

**[RECOMENDAÇÃO] de modelagem:** não introduzir um novo "job state machine" paralelo a
`ExecucaoImportacao`/`SincronizacaoDFe` — evoluir os dois para carregarem os estados acima
(execução = tentativa de lote; documento = ciclo de vida fiscal). Duplicar máquina = duplicar
divergência (o erro que os concorrentes cometem).

### 12.3 Import Engine (pipeline com prioridade)

Filas nomeadas: `discover` (barato, round-robin por tenant c/ quotas), `collect` (pesado,
prioridade por SLA: backfill > pedido-manual > rotina > gap-fill), `ingest` (parse/validar/
gravar), `deliver` (exportadores), `reconcile` (noite). Cada stage: idempotência por
`(empresa, tipo, nsu|chave)`, lease próprio (o atual `travar()` já é o padrão correto),
DLQ, métricas por fila (lag, throughput, erro-por-classe). Backpressure: `SINCRONISMO_*`
vira *policy object* por tenant (`max_concorrência`, `max_páginas`, `janela_por_tipo`),
lido do banco — não env global. **[RECOMENDAÇÃO]**

### 12.4 Governor de consumo v2 (exigência 10)

O atual é bom e **não deve ser substituído — estendido**:

1. manter cooldown/lease/cota/realinhamento por empresa+tipo (fonte da verdade no banco);
2. **health do ambiente** (circuit breaker por SEFAZ/ADN: 5xx/timeout em janela → abre por
   N min, todos os tenants pausam aquela fonte; meia-abertura com 1 sondagem) — evita a
   "tempestade de retries" de §6.4 e o desperdício de slots com SEFAZ fora do ar;
3. **heartbeat por empresa**: se `ultima_consulta_em > 45 dias` → alerta; `> 60 dias` →
   incidente crítico (regra oficial de corte de NSU **[FATO-FONTE]**), com botão de
   "retomada assistida" (varrer dos 90 dias disponíveis e reconciliar lacunas);
4. prioridade intra-tenant: empresa com pendência alta + risco de janela (o flag
   `risco_documento_fora_da_distribuicao` já existe!) vai para frente da fila `discover`;
5. fairness **por tenant** dentro do tick (fix §6.6) — e *entre* tipos (NF-e costuma valer
   mais que CT-e para o fechamento; ordem configurável);
6. política de 656 repetido → incidente com sugestão ("há outro sistema consultando este
   CNPJ" — o xMotivo oficial literalmente distingue os três casos **[FATO-FONTE: NT §3.11.4]** →
   classificar por texto do motivo é cheap e preciso: aguardar-1h vs fora-da-sequência vs
   limite-20-h — cada um com contramedida diferente (esperar / realinhar-cursor / pausar
   gap-fill). O código atual trata os três igualmente.

### 12.5 Camadas de captura (o diferencial de produto)

```
L0 (hoje):  A1 do cliente por empresa        — cobertura: tomadas (destinatário) NFe/CTe/NFSe
L1 (fácil): A1 de empresa-mãe por CNPJ base  — NT permite consultar qualquer filial com
            certificado da matriz [FATO-FONTE] → reduzir N certificados p/ grupos; expor
            no modelo (empresa_pai + filiais) — schema já aceita via novo vínculo
L2 (médio): manifestação do destinatário com A1 do cliente (opt-in por empresa; trilha
            auditável; só eventos que o próprio contribuinte pode praticar — ciência,
            confirmação, desconhecimento, ONR [FATO-FONTE: Portal NF-e FAQ]) → destrava o
            XML integral na corrente normal e aposenta o gap-fill 20/h como caso de erro
L3 (estratégico): modelo CONTADOR via autXML — cliente cadastra escritório/CPFlataforma na
            emissão (até 10 terceiros; NF-e/CT-e/MDF-e [FATO-FONTE: Ajuste SINIEF 16/2018])
            → plataforma consulta com o próprio certificado, sem espalhar A1 de cliente —
            é o modelo que Jettax anuncia ("sem depender do cliente") e o único escalável
            p/ escritório de 1.000+ CNPJs; onboarding assistido (gerar config autXML p/
            cada ERP do cliente) vira feature de vendas
L4 (parceria): e-CAC/procuração eletrônica p/ pendências (monitor estilo Jettax "Prevenção")
L5 (necessário p/ NFS-e): adaptadores municipais legados — SP, BH, POA, Recife, Goiânia,
            Curitiba... (a LC 214/2025 obriga compartilhamento c/ ADN a partir de
            01/01/2026, mas **municípios mantêm emissores próprios** (SP/DF confirmados)
            → ADN NÃO cobre tudo em 2026; o "gap de legado" é plurianual) [FATO-FONTE:
            notagateway, regys, sindifisco]
```

### 12.6 Banco de dados-alvo

Novo schema **incremental** (não greenfield):

- `documentos_fiscais` + `state`, `execucao_id`, `xml_sha256`, `xml_bytes`, `xml_codec`
  (raw|zstd|enc), `xml_object_key`, `chave_validada`, `tentativas`, `proxima_tentativa_em`,
  `motivo_ultimo_erro`; unique adicional parcial `(empresa_id,nsu,origem)` onde couber
  (defesa dupla contra re-ingestão).
- `documentos_eventos` (append-only: state transition, ator, contexto JSON) — responde
  "por que essa nota não foi importada?" com um `WHERE documento_id=? ORDER BY id` —
  índice único necessário.
- `auditoria` (append-only, **sem UPDATE/DELETE grants**, trigger p/ bloquear UPDATE):
  quem/quando/empresa/ação/resultado/versão_sistema/request_id — atende exigência 14.
- `tenants` (escritório: plano, quotas, prioridades, estado_geral), `tenant_usuarios` (papéis
  `admin|operador|leitura` — RBAC mínimo; o resto dos papéis é YAGNI até haver cobrança).
- índices das queries reais do §8: documentos `(empresa_id, competencia)`, `(empresa_id,
  leiaute, tipo)` parcial p/ resumo-pendente, execuções `(empresa_id, tipo, status)`;
  `sincronizacoes_dfe (proxima_consulta_em) WHERE ...` p/ o tick.
- RLS (`escritorio_id = current_setting('app.escritorio')`) como *segunda* linha de defesa
  no PG multi-tenant — o filtro da aplicação continua obrigatório (SQLite desktop não tem
  RLS; a camada de aplicação é a única nos dois modos, a RLS só endurece o servidor).
- Retenção: execuções/auditoria particionadas por mês, arquivamento para tabela fria após
  12 meses (nunca DELETE — fiscal).

### 12.7 Armazenamento (centenas de milhões de docs sem drama)

- Separar **metadado** (banco) / **documento bruto** (object storage ou disco com prefixo
  `shard={empresa_id%1024}/{chave[0:2]}/…` + `.zst`; hash no banco) / **derivados**
  (PDF/DANFE, CSV de relação, ZIPs export — temporários, TTL 7d, não versionáveis).
- Imutabilidade: chave de objeto = `<sha256>.xml.zst`; reimport idempotente = mesmo hash →
  no-op. Corrupção detectável: reconciliador noturno amostra N objetos e confere hash.
- Desktop: mesma API com backend `filesystem` (abstração `ObjectStore` com 2 implementações;
  PyInstaller não ganha S3 — a regra do jogo continua "um arquivo por máquina").
- Ciclo de vida: XML fica na distribuição ~90 dias **[FATO-FONTE]** → política de
  retenção própria (guarda 5 anos por Ajuste/CCM, custo 10× menor c/ zstd) + export
  automático opcional.

### 12.8 Observabilidade (exigência 15) — não "um dashboard", o mínimo operacional

1. **Correlação**: `request_id` (middleware, todo request), propagado p/ task
   (`headers` da Celery) e todo log; `tenant_id`+`document_id`/`execucao_id` como campos
   estruturados (JSON logger — o formato atual é texto plano `%(name)s` **[FATO-CÓDIGO]**).
2. **Métricas Prometheus** (`/metrics`): scans/hr por ambiente, docs/hr, `cStat` por código
   (656/137/138!), latência p50/p95 por stage, lag de fila, leases perdidos, docs em
   backlog (`max_nsu-ultimo_nsu` somado), tempo-por-empresa-entre-consultas (guarda do §60d),
   certificados a vencer (histograma por dias), erros p/ classe, tamanho da DLQ, disco.
3. **Health**: `/readyz` (banco+broker), `/livez`, healthz por worker; liveness p/ compose.
4. **Alertas** (regras, não IA): fila collect parada > 30min em horário útil; empresa sem
   consulta há >30/45d; `erro_rate(SEFAZ)>20% em 15min`; DLQ>0; vault decode error (quase
   sempre = rotação quebrada de chave — alertar imediatamente!); Redis sem memória;
   certificado ≤30/≤7/≤0 dias. No desktop: mesmo pacote → log estruturado + tela própria
   (o `saude-detalhada` vira dashboard real), sem agente externo.
5. **Auditoria de UI**: "por que essa nota não foi importada?" = `GET /documentos/{id}/trilha`
   retornando a tabela `documentos_eventos` + recibo correto (§6.2) — resposta em segundos,
   como pede o briefing.

### 12.9 Cofre de certificados enterprise (exigência 6) — incremental, sem revolução

- manter Fernet como interface (`cifrar/decifrar`), trocar implementação por **KMS-envelope**
  quando multiempresa (chave por tenant no KMS; desktop: chave no SO — DPAPI no Windows
  (`wincred`) como opção, com Fernet como fallback atual já documentado) **[RECOMENDAÇÃO]**;
- AAD (context binding): cifrar com `(escritorio_id, empresa_id)` associado → banco furtado
  com a chave não abre senhas em outro contexto;
- `.env`/`CREDENCIAIS.txt`/backups com `0600`; backup do cofre com passphrase; rotação com
  janela + relatório "N certificados pendentes de reenvio" (o `VAULT_PREVIOUS_MASTER_KEYS`
  atual já dá a base — falta a UX da rotação);
- verificação ativa: teste de handshake do A1 **no cadastro** (buscar_lote ultNSU=current
  como ping autenticado — barato, 1 cota) e checagem de validade **antes** de cada varredura
  (§6.4); expiração 30/7/0 dias em `certificados/resumo` já existe — plugar em alerta;
- **nunca** logar: senha, pem, key, pfx (lint de CI + scrubber de exceções que peguem
  `senha=` em repr); resposta de upload sem `arquivo_path`; verificado hoje ✅ (exceto o
  `.env` no backup — §7.2).

### 12.10 Teste de integração contra homologação

AMBIENTE_FISCAL=homologacao já flui pelo config — falta uma suíte **contract** que rola
opcional com um "certificado de laboratório" (empresa de homologação pública) e grava
fixtures reais dos envelopes de distDFe/ADN (hoje os fixtures são escritos à mão — risco de
o fixture mentir junto com o parser). **[RECOMENDAÇÃO]**

---

## 13. Roadmap (FASE 0–10, ordem exata)

> Regra: nada começa sem teste de regressão do defeito correspondente; cada fase tem
> *feature flag* de volta-atrás e migração reversible.

**FASE 1 — Correções críticas (1–2 sprints).** P0/P1 da seção 6+7, sem arquitetura nova:
(zumbi-execução §6.1; sweep+unique parcial; certificado-bloqueio §6.4; hash+atômico p/
XML §6.3; hardening do compose (ports→127.0.0.1, redis senha, sem `--reload`); upgrade de
dependências §7.1 + `pip-tools` (hashes) + pip-audit/Dependabot no CI; guarda de SECRET_KEY;
CORS default sem `*`; chmod 600 `.env`; `chmod 0600` CREDENCIAIS.txt; rate-limit login;
CI: mover `build:desktop` antes do pytest no workflow; remover lxml/pyopenssl/jose→PyJWT.)
**Critério de aceite:** os 8 bugs acima com teste vermelho→verde; `pip-audit` zero HIGH
nestes requisitos; fluxo de release verde no Actions.

**FASE 2 — Fundação arquitetural.** Alembic (baseline + desligar create_all em produção);
split `tasks.py` em `pipeline` (discover/collect/ingest) + `execucao_id` no documento +
tabela `documentos_eventos`; config validada (pydantic-settings com validators p/ produção:
recusar defaults); `ObjectStore` abstraction (fs local p/ ambos modos agora; S3 depois);
`/v1` prefixo (aliases antigos por 1 ciclo); CI com matriz (py3.11/3.12, pg/sqlite).

**FASE 3 — Import Engine robusto.** Máquina de estados do documento (§12.2) com estados
tipados + reconciliador (XML faltante, gaps de NSU via consNSU c/ cota); DLQ visível na
UI com reprocessar; classificação completa do 656 por xMotivo (§12.4.6); retry por classe
com `retry-after` respeitado; idempotência auditada (mesma nota vista 2× = 1 linha +
2 transições, **teste**); circuit-breaker por ambiente; exportadores como jobs de fila.

**FASE 4 — Scheduler/Governor v2.** fair-share por tenant + quotas (§6.6/§12.4);
heartbeat-60d e "retomada assistida"; priorização por risco de janela; política por fonte
(ADN e AN independentes — hoje o cooldown é por empresa+tipo, mas o breaker é global);
janela de manutenção anunciada (não consultar X).

**FASE 5 — Multiempresa produto.** `tenants` + RBAC (admin/operador/leitura) + gestão de
usuários/convites; bootstrap p/ onboarding self-service; quotas (empresas, docs/dia) e
billing-hooks (sem billing: medidor de uso já vale); isolamento de filas por
prioridade (clusters p/ depois — não antes); RLS no PG (defesa em profundidade); testes
de cross-tenant automaticamente para toda rota nova (parametrizado no conftest).

**FASE 6 — Observabilidade.** JSON logs + correlation/request-id ponta a ponta; `/metrics`;
dashboards (Grafana pronto p/ servidor, tela própria p/ desktop) com os 12 painéis da
exigência 15; alert rules versionados no repositório; página "por que essa nota não foi
importada?" consumindo a trilha (§12.8.5).

**FASE 7 — UX enterprise.** Redesign incremental das telas existentes (não reescrever):
empresa→(certificado, última sync, encontrados/importados/pendentes, **motivo de cada
falha**, próxima tentativa com ETA do gap-fill), filtros salvos, busca global por chave,
export "pasta Domínio/Contmatic" (§10.2.4), assistente de cadastro em massa com relatório
baixável. O fluxo atual já é melhor que a média — aqui é lapidação, não invent.

**FASE 8 — Cobertura de fontes & escala.** MDF-e; NFC-e (via estados/QR — decisão de design,
não óbvio); eventos NFS-e (`/NFSe/{chave}/Eventos` — declarado e não feito); **manifestação
do destinatário** (L2) com opt-in e trilha; **autXML-Contador** (L3) com onboarding por
escritório; 5 primeiros adaptadores municipais de NFS-e legado (top da carteira média);
object storage S3 + lifecycle; particionamento de documentos/execucoes por tenant+mês;
benchmarks §15/§24 com metas publicadas.

**FASE 9 — Inteligência.** Apenas três usos, todos determinísticos primeiro:
(a) classificador de erros desconhecidos (agrupamento por assinatura + sugestão humana);
(b) anomalia de volume por empresa (z-score semanal sobre docs/dia — detecta "SEFAZ
mudou", "cliente trocou de emissor", "município saiu do ar" — e gera incidente);
(c) previsão de expiração de certificado agregada + "carteira em risco" p/ o gestor.
LLM é opcional aqui: gerar *texto* do diagnóstico a partir da trilha determinística,
nunco decidir retry por LLM. **[RECOMENDAÇÃO forte]**

**FASE 10 — Hardening comercial.** Authenticode + assinatura de manifesto; SBOM +
`pip-audit`/`npm audit` bloqueando release; testes de carga/canos no CI noturno;
pen-test externo; documentação SOC2-ready (trilha de auditoria, retenção, RBAC, cripto,
incident response); instaladores verificados nos scripts; política de dados (LGPD: o banco
tem CNPJ+razão+números fiscais — DPA padrão).

---

## 14. Backlog priorizado (tarefa, arquivo, aceite)

| ID | P | Tarefa (arquivo/área) | Critério de aceite verificável |
| --- | --- | --- | --- |
| A1 | P0 | Sweep de execuções EM_ANDAMENTO órfãs + executar `PULADA` ao perder lease (`tasks.py`, `sincronizacao.py`, `fila.py`) | Teste: duas varreduras concorrentes → nenhuma execução fica EM_ANDAMENTO após 30s; `psql`: sem zumbis em carga de 200 enfileiramentos simultâneos |
| A2 | P0 | Unique parcial (empresa,tipo,status='em_andamento') + INSERT ON CONFLICT em `fila.enfileirar` | Corrida API×Beat não cria 2ª execução (teste com 2 sessões) |
| A3 | P0 | `ErroCertificado` tipado + `BLOQUEADA_CERTIFICADO` por empresa (base.py, nfse_adn, _distribuicao_dfe, tasks) | pfx vencido → execução ERRO com mensagem "certificado", agendador **pula** empresa, banner na UI; teste com TLS mock falho |
| A4 | P0 | Escrita atômica do XML (tmp+`os.replace`) + `xml_sha256` no insert | Kill -9 entre insert e arquivo (teste de caos) → reconciliador recupera e hash bate |
| A5 | P1 | compose: remover `ports:` de db/redis (ou 127.0.0.1), `requirepass`, sem `--reload` | `nc -z host 5432/6379` falha fora do host; api saudável |
| A6 | P1 | Upgrades: starlette/fastapi, python-multipart≥0.0.31, cryptography≥49, PyJWT, remover lxml/pyOpenSSL; pip-tools | `pip-audit -r requirements.txt` == 0 advisories; suíte 100% verde |
| A7 | P1 | Guarda de startup (SECRET_KEY default, VAULT vazia c/ certificados existentes, CORS `*`) | subir com defaults → API se recusa com mensagem de 1 linha; teste |
| A8 | P1 | chmod 0600 `.env`/`CREDENCIAIS.txt` desktop; backup ZIP com passphrase opcional | `stat` nos arquivos; backup exige senha p/ abrir (teste) |
| A9 | P1 | CI: `npm run build:desktop` antes do `pytest` (+ falhar se `frontend/out` ausente no runner) | workflow publicado fica verde e publica (prova: dry-run release 1.0.1) |
| A10 | P1 | Reconciliador de integridade (docs sem XML / hash mismatch / gaps de NSU) + contadores na UI | injetar documento órfão → reconciliador rebaixa p/ GAP e re-busca (teste com mock do buscar_por_nsu) |
| A11 | P2 | O(1) `estados_do_escritorio` + `por-empresa` (JOIN/agregados) | <10 queries p/ 100 empresas (assert em teste com counter de engine); p95 < 1s/1000 empresas em pg |
| A12 | P2 | fair-share por tenant no tick + quota por escritório | teste com 2 escritórios (1 gigante): ambos progridem por tick |
| A13 | P2 | Classificação do 656 por xMotivo (aguardar/sequência/20-h) c/ contramedidas distintas | fixtures dos 3 textos oficiais → ações distintas (esperar/realinhar/pausar gap-fill) |
| A14 | P2 | `execucao_id` no documento + `/documentos/{id}/trilha` | recibo exato sob retomadas (teste de 2 fases) |
| A15 | P2 | rate-limit login + lockout + timing equalizado | 100 tentativas → 429 com `Retry-After`; tempo de e-mail inexistente ≈ existente |
| A16 | P2 | defusedxml/limites inflate (gzip/zip máx 4MB; entidades off) | fixture bomb → `REJEITADO` com aviso, sem estourar memória (teste de 64MB bomb) |
| A17 | P2 | manifestação opt-in (NFeRecepcaoEvento4: ciência/confirmação/desconhecimento/ONR) | empresa com opt-in: resumo→ciência→lote seguinte traz procNFe (fixture); flag por empresa + registro em auditoria |
| A18 | P3 | `/metrics` Prometheus + JSON logs + request-id middleware | métricas listadas no §12.8 expostas; 1 request com `X-Request-Id` aparece em todos os logs da task |
| A19 | P3 | Alembic baseline + desligar create_all em prod | upgrade/downgrade testados em snapshot de banco de produção; docs migrados |
| A20 | P3 | MDF-e importer (reuse `_distribuicao_dfe`) | testes de parse com fixtures MDFe distDFe; tipo no enum + UI + export |
| A21 | P3 | Exportador "pasta Domínio" (`Tipo/Atividade/Empresa-CD/MAAA/nota.xml`) + ZIP | layout confere c/ manual Domínio (testes golden) |
| A22 | P3 | autXML-contador: onboarding (gera config p/ ERPs), captura p/ cert do escritório, quotas | e2e fixture: nota c/ autXML do escritório entra na carteira sem A1 do cliente |
| A23 | P3 | Alertas de expiração (30/7/0) via canais plugáveis (e-mail/webhook; desktop: bandeja) | regra dispara c/ fixture `validade=now+7d` |
| A24 | P3 | Retenção/arquivamento de execuções (partição mensal) + política de crescimento | 24 meses de dados sintéticos em pg16: ingestão sem degradação >10% |
| A25 | P2 | Multi-certificado por empresa (matriz/filiais) + "1 A1 por CNPJ-base cobrindo filiais" | empresa-mãe c/ 3 filiais: 1 upload, 3 sincronismos independentes (teste); schema `certificado.empresa_base` |

---

## 15. Plano de testes (estratégia enterprise)

**Pirâmide atual:** 129 testes, concentração correta nos pontos caros (cooldown, 656,
idempotência do insert, competência/export, updates desktop) **[FATO-CÓDIGO: leitura dos
17 arquivos de teste]**. Lacunas e plano:

1. **Contrato (fixtures oficiais gravadas)** — distDFe/retDistDFeInt/ADN: gerar acervo de
   respostas reais (produção/hom) por `respx`; validar parser contra *todos* os schemas
   conhecidos (resNFe, procNFe com/sem prot, resEvento, procEventoNFe, cancelamento antes
   da nota, lote cheio de 50, lote misto doc+evento). Hoje os fixtures são escritos à mão
   — risco de parser+fixture errarem juntos.
2. **Propriedades (hypothesis)** — invariâncias do governor: cursor nunca regride exceto
   realinhamento autorizado; 2 tarefas nunca seguram lease juntas; AGUARDANDO sempre tem
   `bloqueado_ate>now`; N reentregas idênticas → 1 linha de documento; competência sempre
   dentro de [inicio,fim] do pedido quando houver.
3. **Concorrência/transação** — pg real em CI (docker service): 2 processos × mesma
   empresa (lease), corrida enfileirar×beat (A2), commit-por-lote sob SIGKILL no meio
   (checkpoint retoma no NSU certo), SQLite: writer+reader 8 threads (WAL).
4. **Caos (cenários exigidos):** (a) SEFAZ cai no meio da sincronização → AmbienteIndisponivel
   → AGUARDANDO curto → recuperação com 137/138 normais; (b) worker morre após baixar e
   antes do commit → redelivery reusa execução, nenhum dup; (c) Redis reinicia → tasks em
   voo reassumidas; (d) dois workers mesma empresa → 1 varredura (lease) e **nenhuma
   zumbi** (A1); (e) banco perde conexão → commit falha, cursor não avança antes do
   arquivo; (f) certificado expira durante → erro de handshake → `BLOQUEADA_CERTIFICADO`
   (A3); (g) update do desktop no meio de varredura → `.cmd` espera processo sair,
   retomada via `agenda.json`+checkpoint.
5. **Segurança** — testes automatizados: IDOR entre escritórios parametrizado em **todas**
   as rotas (novo endpoint sem teste = CI falha); limites de upload; traversal; XXE/zip-bomb
   (A16); tokens: expiração/assinatura errada; CORS preflight (sem `*`+credentials).
6. **Performance/load** — k6: snapshot do painel 100/1k/10k empresas (A11); ingestão sintética
   1M docs (benchmark de referência, ver §16); export de 25k XMLs (memória<500MB, stream
   OK); 10k enfileiramentos (A2 sem p95>2s).
7. **E2E** — Playwright: cadastro em massa com pfx real de teste → upload → sync com
   mocks → documentos → ZIP abre no Excel; desktop: primeira abertura em VM limpa (o
   `test_primeira_execucao_do_programa` já cobre o núcleo do fluxo — estender p/ janela+
   bandeja em smoke manual documentado).
8. **Requisito de processo** — CI: suíte inteira **sem** `frontend/out` (testes dependentes
   de build devem ser pulados explicitamente com marca `requires_panel_build`, e o job de
   release roda a variante com build) — mata a fragilidade que reproduzi.

---

## 16. Plano de escalabilidade

**Modelo de custo real por tenant:** 1 consulta/(empresa·tipo·hora) no regime + ~2–50 na
varredura de backlog. Consequências de dimensionamento:

| Dimensão | 100 empresas | 1.000 | 10.000 |
| --- | --- | --- | --- |
| Ciclos/h (×3 tipos) | 300 | 3k | 30k (≈8 req/s médios p/ o AN inteiro — irrelevante de rede; o gargalo é **horas de calendário** p/ cobrir 10k×3 janelas) |
| Worker | 1 container (conc.4) | 3–5 (conc.4–8) | partições: workers por *faixa de empresa* + `discover` dedicado; N workers seguros (lease no banco — **já é verdade hoje [FATO-CÓDIGO]**) |
| Beat | 1 | 1 | 1 (crítico: single-flight — considerar beat lockado p/ DB advisory-lock p/ HA, não escala horizontal) |
| PG | 1M docs/ano | 10M | particionar docs/execuções; read replica p/ o painel; índices do §12.6 obrigatórios |
| XML disco | 6GB/ano | 60GB | object store + zstd (≈8–10×) |
| Fila | Redis trivial | visibility/timeout já ok | mover p/ RabbitMQ/Postgres-queue **somente** se houver requisito de garantia transacional — hoje o design já é "fila decorativa" **[FATO-CÓDIGO: docs+código]** |

Plano concreto: (1) matar N+1 e tornar o *tick* O(tenants ativos) não O(empresas);
(2) `discover` leve separado de `collect`; (3) quotas/pesos por tenant; (4) cache de
estado (materialização `empresa_resumo` atualizada pelo pipeline, o painel lê 1 tabela);
(5) horizontal worker stateless (já é, exceto caminho de arquivo local no desktop — no
servidor mover p/ ObjectStore compartilhado: NFS→S3); (6) métricas p/ validar as metas do
§8 antes de prometer números a clientes. **[RECOMENDAÇÃO com números derivados de [FATO-FONTE]]**

---

## 17. Plano de segurança (além de §7)

1. **Imediato (semana 1):** A5/A6/A7/A8/A15/A16; secrets scan no CI (gitleaks); branch
   protection c/ testes obrigatórios; publicar o workflow (A9) já endurecido.
2. **Curto (Fase 2):** RLS; KMS-ready (interface vault já o permite); token de API
   por-tenant p/ integrações (hash em banco, escopos, rotação); CSP/Cookie/CSRF review
   (o app é header-only — adicionar `SameSite`, headers seguros no painel desktop);
   auditoria imutável (append-only + revogação de UPDATE/DELETE + trigger de bloqueio);
   log de autenticação.
3. **Médio:** SBOM + assinaturas (cosign no manifesto da release, Authenticode no exe,
   chave de release em HSM/KMS do GitHub); pen-test antes do 1º cliente externo; política
   de vuln (24h/7d p/ CVSS alto/crítico na cadeia de distribuição — um instalador é
   *execução de código em massa*).
4. **Operação:** runbooks de incidente (656 em cadeia, chave do cofre perdida, broker
   corrompido); backup testado p/ restore (desktop hoje só "cria" o ZIP — testar restaurar
   numa VM limpa é o que prova o mecanismo); LGPD: DPA, registro de tratamento (dados =
   documentos fiscais, base legal = obrigação legal), DSR manual p/ escritório, retenção
   definida (5+ anos fiscal ⇒ exclusão tem limite legal — documentar, não apagar "por
   GDPR").

---

## 18. Inteligência/automação (exigência 18) — os únicos 4 pontos com ROI

1. **Agrupador de erros desconhecidos** (não-LLM): assinatura (cStat+xMotivo normalizado+
   stack-root) → clusters com contagem/tempo; deteciona "SEFAZ SP mudou o contrato" antes
   do suporte. 30 linhas. ROI direto: cada erro novo hoje = 1 chamado.
2. **Anomalia de volume** por empresa/tipo (z-score 8 semanas, sazonalidade semanal) →
   "carteira 12% abaixo do esperado em CT-e" — pega indisponibilidade parcial e troca de
   rotina do cliente.
3. **Diagnóstico assistido** (LLM opcional): sobre a *trilha determinística* do documento/
   empresa, gerar em PT-BR a explicação de 3 linhas pro contador ("faltam 2 NSUs, o
   ambiente respondeu 137 há 40min, próxima varredura 22:38") — texto, não decisão.
4. **Previsão de carteira em risco**: certificado×expiração × inadimplência de sync →
   ranking p/ o gestor do escritório (retenção).

Nada de LLM no pipeline de parsing/idempotência — determinístico é vantagem, não
limitação. **[RECOMENDAÇÃO absoluta]**

---

## 19. Atualização do sistema (exigência 25) — avaliação do mecanismo atual

**Presente e bem feito acima da média para o estágio:** manifesto sem cota de API
(`releases/latest/download`), comparação numérica de versão (não lexicográfica), SHA-256,
flags Inno que sobrevivem a "arquivos em uso", dados fora do programa, rollback = publicar
versão menor com migrações aditivas, log do updater, "obrigatória" sem botão adiar.
**[FATO-CÓDIGO]**

Faltando (listado em ordem de necessidade): (1) assinatura do manifesto (chave de
publicação detached — protege contra reposicionar `latest.json` com novo hash) e Authenticode
(p/ fora do escritório); (2) **canary interno**: flag `percentual_instalacoes` no manifesto
→ o programa só aceita "versão nova" se `hash(instalação)%100 < pct`, publisher controla a
onda — 40 linhas que evitam "update ruim em todas as máquinas ao mesmo tempo" (o risco que
o próprio DISTRIBUICAO.md admite); (3) **estado de pós-update**: o programa gravar
"apliquei vN e subi OK" — o publisher vê se uma versão quebrou (rollback dirigido via
manifesto); (4) teste do `.cmd` em VM limpa automatizado (hoje é teste manual documentado);
(5) migração de schema **antes** do update trocar binário (o Inno pode rodar `migrar.py`
pré-troca — hoje a migração roda no startup da API, ok, mas com estado "migração rodando"
no log fica difícil auditar falha); (6) servidor: `ATUALIZAR.bat` = `git pull` sem pin de
tag/checksum (aceitável p/ on-prem do dono do repo; inaceitável como "produto" — mudar p/
imagem versionada/assinada). **[FATO-CÓDIGO + RECOMENDAÇÃO]**

---

## 20. Fontes consultadas (críticas sinalizadas)

**Governo / especificações:**
1. Portal NF-e — **NT 2014.002** (todas as regras de consumo: 1h/137, 656 por variante de
   xMotivo, ultNSU na rejeição (v1.14+), lote≤50, 20/h consNSU/consChNFe, 90 dias, **60 dias
   de inatividade corta NSU**, tabela de atores (emitente não baixa as próprias NF-e;
   transportador/autXML recebem integral; destinatário só completo pós-manifestação)).
   https://www.nfe.fazenda.gov.br/portal (exibirArquivo NT2014.002) — **[FATO-FONTE central]**
2. Portal NF-e FAQ/Consulta Pública — manifestação do destinatário: eventos, prazos
   (ciência→manifestação conclusiva em ≤180d), "sistema só permite download p/ destinatário
   manifestado". https://www.nfe.fazenda.gov.br/portal/perguntasFrequentes.aspx **[FATO-FONTE]**
3. **ADN** — Manual dos Municípios/Contribuintes (APIs ADN v1.2): `GET /DFe/{ultNSU}` lote
   máx 50 DF-e / 1 MB, "sem retroatividade ao primeiro acesso", `ultNSU==maxNSU` = em dia,
   eventos por `GET /NFSe/{chave}/Eventos`; swagger https://adn.nfse.gov.br/contribuintes/docs.
   **[FATO-FONTE]** (PDF público do manual + swagger)
4. **CT-e** — NT 2015.002 (CTeDistribuicaoDFe; distNSU/consNSU; **sem consChCTe** no XSD
   v1.00); URLs www1/hom1.cte.fazenda.gov.br. cte.fazenda.gov.br **[FATO-FONTE]**
5. **MDF-e** — NT 2015.002 (MDFeDistribuicaoDFe, `mdfeDistDFeInteresse`, 3–6 meses de
   retenção, autXML p/ MDF-e). sped.rfb.gov.br/arquivo/download/5491 + portal.fazenda.sp.gov.br
   **[FATO-FONTE — justifica A20]**
6. **LC 214/2025 art. 62** — NFS-e padrão nacional obrigatória a todos os municípios a partir
   de 01/01/2026, com convivência de emissores próprios integrados ao ADN (SP/DF
   declararam manutenção). [notagateway](https://notagateway.com.br/blog/nfse-nacional-tudo-que-voce-precisa-saber-chega-de-boatos/), [sigcorp](https://sigcorp.com.br/nfs-e-nacional-municipios-devem-se-preparar-para-adesao-obrigatoria-ate-2026/), [Sindifisco](https://sindifisco.org.br/noticias/nfs-e-nacional-a-padronizacao-que-comporta-divergencias) **[FATO-FONTE — sustenta L5 do §12.5]**
7. Suspensão/reativação histórica de consNSU/consChNFe (2022) e normalização posterior
   (NT v1.15: consChNFe dispensa NSU prévio) — [Totvs](https://www.totvs.com/blog/fiscal-clientes/nfe-suspensao-dos-servicos-consnsu-e-conschnfe-da-nt-2014-002/), [Tecnospeed](https://blog.tecnospeed.com.br/nota-tecnica-2014-002-versao-1-10-da-nf-e/) **[FATO-FONTE — risco operacional do gap-fill: se suspender de novo, o sistema degrada p/ apenas-distNSU — o breaker deve saber disso]**

**Concorrentes (páginas oficiais, informações públicas):**
8. Jettax: módulos/cobertura/integração nativa Domínio — jettax.com.br **[claim]**;
   help Jettax p/ rotinas de pasta do Domínio — jettax360-help.freshdesk.com **[FATO-FONTE do formato Domínio]**
9. Domínio: ecossistema (ASIS auditoria, Domínio Certificados Digitais) — dominiosistemas.com.br/ecossistema
10. Fiscal.io (parceiro homologado TR; captura horária; push Onvio; Enterprise p/ API): fiscal.io
11. BoxFiscal: desktop+nuvem, auditoria, export p/ Domínio: boxfiscal.app
12. HubStrom XMLHub: decisão de NÃO manifestar (risco jurídico): hubstrom.com/solucoes/xmlhub
13. Apogeu (modelo autXML por CNPJ + limites de NFC-e p/ terceiros): apogeu.tech/blog/como-baixar-xml-clientes-automatico-cnpj **[FATO-FONTE secundário, consistente c/ NT/Ajuste 16/2018]**
14. Ajuste SINIEF 16/2018 (autXML ≤10 terceiros p/ NF-e/CT-e/MDF-e) via [webmania](https://ajuda.webmania.com.br/pt-browser/articles/12680806) **[verificar texto original do Ajuste ao implementar]**

**Ferramentas open source de referência (validação de comportamento):**
15. nfephp-org/sped-nfe (`DistDFe.md`, limite de loop 50/2s), nfephp-org/sped-cte,
    TadaSoftware/PyNFe — github.com **[usados pelos próprios docs do repo; consistentes]**
16. Forum SPED Brasil — consenso "emitente não recebe as próprias NF-e via distDFe"
    [portalspedbrasil.com.br/forum](https://portalspedbrasil.com.br/forum/nf-e-regra-de-distribuicao-via-download-do-xml-nt-2014-002-versao-1-02c-agosto-2020/) **[corrobora README]**

**Evidência local (esta auditoria):**
17. `pip-audit` 2026-09-10 contra os requirements exatos → 35 advisories/7 pacotes;
    `npm audit` → 0; `pytest` → 128/129 (falha só sem `frontend/out`), 129/129 com;
    script de reproducao do zumbi EM_ANDAMENTO (seção 6.1) — outputs no histórico da sessão.

---

## 21. Dúvidas residuais honestas (não resolvíveis sem ambiente real)

1. **Validação ponta-a-ponta com A1 real** contra produção/hom (o ROADMAP do próprio repo
   lista; sem cert, nada aqui foi exercido na rede) — **[HIPÓTESE: tudo indica que sim,
   pois a origem é o pipeline Importarnotas validado em produção, segundo o README]**.
2. Cobertura do endpoint de eventos por chave do ADN para empresas emitentes de NFS-e
   nacional (prestadas): o Manual descreve o contribuinte como tomador/intermediário;
   se NFS-e **emitida** cai no DFe do próprio CNPJ, a aba "Prestadas" enche; senão, o
   produto deve dizer isso na UI como no caso NF-e. **[HIPÓTESE — testar em 1ª homologação]**
3. Se a homologação CT-e/NFe está operacional para esses WSs hoje (o comentário em
   `nfe_sefaz.py` sobre "só produção na prática" deve ser revalidado contra o portal). **[HIPÓTESE]**
4. `429` do ADN: tratado como bloqueio igual 656 (correto por cautela); confirmar se o ADN
   contribuintes usa header `Retry-After` (poderia acelerar retomada). **[HIPÓTESE menor]**

---

*Documento gerado na FASE 0. Próximo passo recomendado: iniciar FASE 1 com A1–A9 (todos
localizados, sem impacto em dados, cada um com teste vermelho pronto). Nenhuma linha de
código de produção foi alterada por esta auditoria — e não será, até confirmação do escopo
da FASE 1.*
