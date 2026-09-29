# Auditoria — automação em massa de Autorizações de Acesso (RFB)

Data: 2026-09-29 · Branch: `arena/01a0ee8e-cajuru28` · Commit base: `6dc6ce9`

Documento produzido antes de qualquer alteração de código, conforme solicitado.
Responde aos itens **A** a **G** do pedido. O item **H** (implementação) está
bloqueado por um achado normativo descrito na seção B.1 e depende de decisão do
solicitante.

---

## A) Arquitetura atual

O repositório **não é um projeto vazio**. É um produto em produção
(`Fluxa`/`Cajuru28`) com um módulo de Procurações RFB já maduro. Fatos medidos,
não estimados:

| Camada | Tecnologia | Volume |
|---|---|---|
| Frontend | Next.js 16.3.4 · React 19 · TypeScript 5.6 · Tailwind | 13 arquivos de teste, 70 testes |
| Backend | FastAPI 0.141 · SQLAlchemy 2.0 · Pydantic 2.13 | 393 testes |
| Fila | Celery 5.6 + Redis 8.1 (worker + beat) | — |
| Banco | PostgreSQL (SQLite nos testes) | 17 tabelas `procuracao_*` |
| Estação | Python 3.11 puro (`agent/cajuru_agent`) | 28 testes |
| Deploy | Docker Compose (dev + produção isolada) + Caddy | — |

### Módulo de Procurações — mapa real

```
backend/app/procuracoes/
  estados.py      (701 l.) máquina de estados, taxonomia de erros, política
  portal.py       (348 l.) URLs oficiais, âncoras de texto, roteiro, allowlist
  modelos.py      (735 l.) 17 tabelas
  esquemas.py     (803 l.) contratos Pydantic
  servicos/
    fila.py         (1210 l.) criação idempotente, lock, lease, retry
    painel.py        (608 l.) KPIs, listagem, detalhe
    sincronizacao.py (538 l.) reconciliação por precedência de fonte
    agentes.py       (425 l.) matrícula, HMAC, nonce, heartbeat, revogação
    certificados.py  (390 l.) inventário e seleção determinística
    eventos.py       (272 l.) trilha imutável + `sanitizar()`
    evidencias.py    (250 l.) captura cifrada com expurgo por retenção
    assinador.py     (237 l.) avaliação do ambiente SERPRO (falha fechada)
    configuracao.py  (185 l.) outorgado, vigência, política
  integracoes/
    integra_contador.py (391 l.) SERPRO OBTERPROCURACAO41 — canal oficial
    planilha.py         (765 l.) importação CSV/XLSX
api/routers/procuracoes.py        (1257 l.) 37 rotas, RBAC por papel
api/routers/procuracoes_agent.py   (749 l.) protocolo HMAC da estação
worker/procuracoes_tasks.py        (324 l.) manutenção e sincronização agendadas

agent/cajuru_agent/
  importador.py  (772 l.) certificados + planilhas, tudo local
  certificados.py(310 l.) inventário via repositório do Windows
  __main__.py    (308 l.) CLI: configurar/diagnostico/certificados/importar/testar/executar
  protocolo.py   (306 l.) cliente HTTP assinado (HMAC-SHA256 + nonce)
  executor.py    (256 l.) laço principal
  assinador.py   (224 l.) diagnóstico do Assinador SERPRO Desktop
  roteiro.py     (217 l.) condução do operador + abertura do navegador real
```

### A máquina de estados já existe

`estados.py` define 15 estados de job (`StatusJob`), grafo de transições
validado (`TRANSICOES` / `exigir_transicao`), 9 situações de autorização
(`StatusAutorizacao`), 12 etapas de fluxo (`EtapaFluxo`), taxonomia de erros com
classe/retry/destino (`RegraErro`), backoff exponencial limitado a 30 min, e
`REGRA_PADRAO` que faz **erro desconhecido virar intervenção humana** em vez de
retry infinito. Também separa as duas identidades do processo
(`FaseJob.OUTORGA` = certificado do cliente, `FaseJob.ACEITE` = certificado da
contabilidade) com `certificado_exigido()` — exatamente a proteção pedida nos
itens 27/28/69 do seu briefing.

Isso cobre, com outros nomes, a máquina de estados que você propôs na seção 5.

### Verificação executada (não é leitura de README)

```
backend  : 393 passed          em 36,2 s
agent    :  28 passed          em  1,2 s
frontend :  70 passed (13 arq) em 16,4 s
frontend : tsc --noEmit        sem erros
```

---

## B) Problemas encontrados

### B.1 — ACHADO BLOQUEANTE: o que foi pedido é vedado por norma em vigor

Este é o achado que determina todo o resto, e ele **não** é uma opinião do
código existente: foi verificado nas fontes.

A **Instrução Normativa RFB nº 2.320, de 6 de abril de 2026** (assinada pelo
secretário especial Robinson Sakiyama Barreirinhas, em vigor desde a
publicação no DOU de 06/04/2026), em seu **art. 13**, veda a utilização de
aplicativo, *webview*, *iframe*, camada de intermediação ou qualquer sistema
próprio do contribuinte ou de terceiros que, por **automação ou encapsulamento
do ambiente dos serviços digitais da Receita Federal**, possibilite **outorga,
alteração ou revogação** de autorizações de acesso.

A norma ainda define o que conta como acesso intermediado, e a definição é
literal quanto à tecnologia que você pediu:

> caracteriza-se como acesso intermediado a interação com o sistema por
> mecanismos automatizados ou semiautomatizados, incluindo **robôs de
> software, scripts, automação de navegador** e interfaces de programação não
> oficializadas pela Receita Federal.

"Automação de navegador" é a definição de Playwright. O sistema descrito no
briefing — login automatizado, `+ Nova Autorização`, preenchimento, seleção de
serviços, assinatura e validação como procurador, em lote, para 200 clientes —
é o caso central da vedação, não uma zona cinzenta.

**Sanções previstas, e sobre quem recaem:** a Receita pode interromper a
sessão, **bloquear preventivamente o uso do acesso como representante digital**
e **cancelar as autorizações de acesso já outorgadas**. O risco não é do
fornecedor do software: é do escritório (que perde a condição de representante)
e dos clientes (que perdem as autorizações já existentes). Para um escritório
com 200 clientes, o pior caso da automação é perder o e-CAC de toda a carteira
em um único evento de detecção — inclusive das autorizações que já funcionavam.

Fontes consultadas em 29/09/2026:

- Ministério da Fazenda / Receita Federal — *Receita Federal atualiza regras
  para acesso a serviços digitais* (10/04/2026):
  <https://www.gov.br/fazenda/pt-br/assuntos/noticias/2026/abril/receita-federal-atualiza-regras-para-acesso-a-servicos-digitais>
- Portal Contábeis — *Receita endurece regras de acesso digital com nova IN*
  (09/04/2026), com a transcrição do art. 13 e da definição de acesso
  intermediado:
  <https://www.contabeis.com.br/noticias/76072/receita-endurece-regras-de-acesso-digital-com-nova-in/>
- SICAP-SP, TAGD Advogados, Legisweb, Jornal Contábil — convergentes quanto à
  vedação e às sanções.

Observação de método: o briefing pediu (seção 80) para não assumir que
documentação de 2024/2025 continua valendo em 2026. Aplicando essa própria
regra, a conclusão é que o requisito central do briefing foi superado por norma
de abril de 2026.

**Consequência prática:** o repositório **já reflete esse achado**. A
arquitetura em três camadas (consulta oficial / gestão interna / execução
assistida) não é timidez de engenharia — é a resposta correta à IN 2.320. Os
comentários em `portal.py`, `roteiro.py` e `agent/README.md` documentam a
decisão de não embarcar cliques automatizados em outorga/assinatura/validação.

### B.2 — Problemas técnicos reais (independentes da questão normativa)

> **Situação em 29/09/2026: itens 1 a 6 corrigidos.** O fechamento de cada um
> está na seção H.

| # | Severidade | Problema | Local |
|---|---|---|---|
| 1 | Média | Artefato de 1,03 MB versionado na raiz: `01a0b6e4-96f6-70a1-89b0-898746ab0511.patch`. Entrou no commit `6dc6ce9`. Não é código, não é doc, polui o repositório e não está coberto pelo `.gitignore`. | raiz |
| 2 | Média | `diagnostico` da estação cobre **apenas** o Assinador SERPRO. Não verifica relógio do Windows, DNS, alcance do Portal, versão do navegador, resumo do repositório de certificados nem certificados a vencer. É menos do que os itens 74/75 do briefing pedem. | `agent/cajuru_agent/__main__.py:73` |
| 3 | Média | Não existe **pré-voo de lote** (item 44). Os pré-requisitos são verificados job a job (`VERIFICANDO_PRE_REQUISITOS`); nada impede descobrir no cliente 57 que o outorgado está mal configurado ou que 12 certificados estão vencidos. | `servicos/fila.py` |
| 4 | Média | Não existe **exportação de relatório final** (item 57). `planilha.py` é só importação; não há rota que devolva CSV/JSON consolidado de resultado do lote. | `api/routers/procuracoes.py` |
| 5 | Baixa | Métricas parciais: há `duracao_media_minutos` e `taxa_sucesso`, mas não tempo por etapa (login, espera humana, assinatura, validação), nem erros por categoria, nem clientes/hora (item 91). | `servicos/painel.py:66` |
| 6 | Baixa | `sanitizar()` existe e funciona, mas está em `servicos/eventos.py` — lugar pouco óbvio para uma função de segurança transversal, o que convida a reimplementações divergentes. | `servicos/eventos.py:55` |
| 7 | Informativo | `StarletteDeprecationWarning`: `TestClient` com `httpx` legado. Não quebra hoje; quebra em atualização futura do Starlette. | dependências de teste |

### B.3 — O que eu procurei e **não** encontrei (resultado negativo é resultado)

O briefing pede para caçar uma lista específica de fragilidades. Todas foram
verificadas por varredura no código, e o resultado é limpo:

- **Nenhum** `pyautogui`, **nenhum** Selenium, **nenhum** clique por coordenada,
  **nenhuma** automação por imagem de tela. (`grep -rni` sobre todo o código.)
- **Nenhum** `sleep` arbitrário. Os 6 `time.sleep` existentes são todos backoff
  exponencial calculado (`_ESPERA_BASE_SEGUNDOS * 2**(tentativa-1)`) ou espera
  de laço limitada a 1 s no executor do Agent.
- **Nenhum** `TODO`, `FIXME`, `XXX` ou `HACK` em código de produção. Os 4
  resultados do grep são falsos positivos (a palavra "TODOS" em português e
  "METODO" em docstring de HMAC).
- **Nenhuma** senha, chave privada ou PFX trafega para o servidor. O desenho é
  explícito: a estação envia apenas metadados (titular, CNPJ do OID ICP-Brasil
  2.16.76.1.3.3, serial, validade, thumbprint).
- **Nenhum** `--ignore-certificate-errors`. O único `verify=False` está
  restrito a `https://127.0.0.1:65156` — o Assinador SERPRO usa certificado
  local autoassinado por natureza, e a requisição só pergunta "a porta está
  viva?", sem trafegar dado sensível. Está documentado no próprio arquivo.
- **Segredos**: cofre Fernet com rotação de chave
  (`VAULT_PREVIOUS_MASTER_KEYS`), Argon2id para credencial de estação, DPAPI /
  Windows Credential Manager na ponta. `.gitignore` cobre `*.pfx`, `*.p12`,
  `*.pem`, `*.key`, `.env`.
- **Concorrência**: `UPDATE ... WHERE agente_id IS NULL` + `rowcount` em vez de
  `SELECT FOR UPDATE` — funciona igual em PostgreSQL e SQLite. Lease por job
  com expiração; estação que some devolve o job no mesmo ponto.
- **Seletores**: as âncoras de `portal.py` são texto visível e vocabulário
  legal ("Nova Autorização de Acesso", "Validar"), nunca `div:nth-child(3)`.
  É a preferência da sua seção 62, já aplicada.

Em resumo: o código existente já satisfaz a maior parte da sua seção 84
("Proibido") e da seção 83 ("Qualidade"). Não encontrei protótipo incompleto,
função fake, banco fake, endpoint inventado nem exceção ignorada.

---

## C) Arquitetura proposta

A arquitetura de três camadas já existente está **correta** e deve ser
preservada. A proposta é fechar as lacunas B.2, não reescrever.

```
CAMADA 1 · CANAL OFICIAL (leitura)           ← já existe, manter
  Integra Contador / SERPRO · OBTERPROCURACAO41
  Responde: existe autorização? quais serviços? até quando?
  É a fonte da verdade para reconciliação.

CAMADA 2 · GESTÃO INTERNA (fora da RFB)      ← já existe, ampliar
  Fila, estados, lock, auditoria, painel, alertas, estações.
  + PRÉ-VOO DE LOTE          (lacuna 3)
  + RELATÓRIO FINAL CSV/JSON (lacuna 4)
  + MÉTRICAS POR ETAPA       (lacuna 5)
  Não toca o portal. Não é intermediação. É software de escritório.

CAMADA 3 · EXECUÇÃO NO PORTAL (assistida)    ← já existe, ampliar
  O Agent valida pré-requisitos, abre o NAVEGADOR REAL do operador na
  URL oficial e conduz passo a passo. Quem clica e assina é a pessoa.
  + DIAGNÓSTICO DE SISTEMA COMPLETO (lacuna 2)
```

O ganho de produtividade não vem de clicar sozinho — vem de eliminar tudo o que
cerca o clique. Na prática isso é o item 95 do seu briefing quase inteiro:
importar 200 clientes, mapear certificados, configurar outorgado/validade/
serviços uma vez, iniciar o lote, ser avisado do que precisa de pessoa, e
receber relatório no fim. A diferença em relação ao pedido original está
concentrada nos passos que a IN 2.320 reserva ao humano.

---

## D) Fluxo completo

```
PRÉ-VOO DO LOTE  (novo)
  portal alcançável? · relógio do Windows? · DNS? · navegador?
  outorgado configurado e válido? · modelo de serviços válido?
  por cliente: certificado presente? vigente? confere com o CNPJ?
  duplicidade? autorização já vigente?
  → resultado: APTO / BLOQUEADO, com motivo, antes de abrir o 1º navegador

FASE 1 · OUTORGA (certificado do CLIENTE)
  PENDENTE → AGUARDANDO_AGENTE → ATRIBUIDO
  → VERIFICANDO_PRE_REQUISITOS   [sistema] certificado + Assinador
  → PRONTO_PARA_OPERACAO         [sistema] abre navegador real na URL oficial
  → AUTENTICANDO                 [pessoa]  certificado, CAPTCHA, 2FA
  → PREENCHENDO                  [pessoa]  dados ditados pelo painel; sistema confere
  → AGUARDANDO_ASSINATURA        [pessoa]  assinatura no ambiente oficial
  → ASSINADO                     [sistema] registra protocolo + evidência

FASE 2 · ACEITE (certificado da CONTABILIDADE — contexto separado)
  → AGUARDANDO_VALIDACAO         prazo legal de 30 dias
  → VALIDANDO                    [pessoa]  aba "Recebidas" → Validar
  → CONCLUIDO                    [sistema] reconsulta pelo Integra Contador

DESVIOS (qualquer ponto)
  INTERVENCAO_MANUAL ← CAPTCHA, 2FA, PIN, nível de conta insuficiente,
                        portal alterado, divergência de dados
  FALHOU / CANCELADO ← erro permanente ou decisão do operador
  Retomada volta ao estado da ETAPA em que parou, nunca ao início.

RECONCILIAÇÃO (na subida e a cada 6 h)
  A realidade do portal vence o estado local.
  job dizia FALHOU mas a autorização existe → corrige para CONCLUIDO.
```

---

## E) Componentes necessários

| Componente | Situação | Ação |
|---|---|---|
| `StateStore` / máquina de estados | existe (`estados.py`) | manter |
| `JobQueue` | existe (`servicos/fila.py`) | manter |
| `ErrorClassifier` | existe (`RegraErro`/`regra_do_erro`) | manter |
| `CertificateProvider` | existe (`servicos/certificados.py` + agent) | manter |
| `SessionManager` (2 identidades) | existe (`FaseJob`/`certificado_exigido`) | manter |
| `SignatureProvider` | existe (`servicos/assinador.py` + `agent/assinador.py`) | manter |
| `AuditLogger` | existe (`servicos/eventos.py`, append-only) | manter |
| `NotificationService` | existe (`procuracao_notificacoes`) | manter |
| `PortalClient` (âncoras, allowlist) | existe (`portal.py`) | manter |
| Painel operacional + fila de intervenção | existe (frontend) | manter |
| **`SystemDiagnostics` completo** | parcial | **ampliar** (B.2-2) |
| **`BatchPreflight`** | ausente | **criar** (B.2-3) |
| **`ReportExporter` CSV/JSON** | ausente | **criar** (B.2-4) |
| **Métricas por etapa** | parcial | **ampliar** (B.2-5) |
| `security/mascaramento` | existe, mal localizado | **mover/centralizar** (B.2-6) |
| Automação de clique em outorga | **ausente por decisão** | **não criar** (B.1) |

---

## F) Riscos

| Risco | Probabilidade | Impacto | Tratamento |
|---|---|---|---|
| **Bloqueio do escritório como representante digital + cancelamento das autorizações da carteira**, por uso de automação de navegador (IN 2.320 art. 13) | Alta, se a automação for construída | **Catastrófico** — perda do e-CAC de todos os clientes | Não construir a camada de clique automatizado. É o único tratamento eficaz. |
| Responsabilização do contador: a autorização equivale a procuração; automação vedada pode ser lida como violação administrativa e falha na guarda de credenciais | Média | Alto | Trilha de auditoria imutável + operação assistida documentada |
| Portal muda a interface | Alta (é questão de quando) | Médio | Âncoras por texto legal + `PORTAL_ALTERADO` → intervenção, sem retomada automática |
| Certificado A1 vence no meio do lote | Alta em carteira grande | Médio | Alertas 30/60/90 dias + portão na entrega + pré-voo |
| Prazo de 30 dias para validação estoura | Média | Alto (autorização cancelada de ofício) | Estado `AGUARDANDO_VALIDACAO` com prazo + alerta |
| Certificado do cliente usado na fase de aceite (identidades trocadas) | Baixa | Alto | `certificado_exigido()` + contexto isolado por fase |
| gov.br do cliente sem nível prata/ouro | Média | Médio | Classificar `ACCOUNT_LEVEL_INSUFFICIENT`, nunca contornar |
| Gargalo humano: nº de operadores, não de threads | Certa | Médio | `jobs_aguardando_humano` separado no painel dimensiona o dia |

---

## G) Plano de implementação

Fase 0 é a decisão que destrava o resto. As fases 1–4 são legítimas sob a IN
2.320 e independem dela, exceto quanto ao escopo da fase 5.

| Fase | Entrega | Depende de |
|---|---|---|
| **0** | **Decisão sobre o escopo da automação** (ver pergunta abaixo) | você |
| 1 | Higiene: remover o `.patch` de 1 MB do versionamento e cobrir no `.gitignore`; centralizar `sanitizar()` em `core/` | — |
| 2 | `SystemDiagnostics` completo + comando `diagnose` com saída PASS/WARNING/FAIL (Windows, navegador, relógio, DNS, portal, Assinador + versão, repositório de certificados, certificados a vencer) | — |
| 3 | `BatchPreflight`: portão de lote com relatório APTO/BLOQUEADO por cliente antes do primeiro navegador | fase 2 |
| 4 | `ReportExporter`: CSV + JSON com Cliente / Documento / Status / Validade / Procurador / Erro; e métricas por etapa no painel | — |
| 5 | Testes para tudo acima + documentação operacional | fases 1–4 |

---

## Pergunta que bloqueou a implementação — e a resposta

O briefing pedia um robô que clica e assina. A IN RFB nº 2.320/2026, art. 13,
veda exatamente isso, e a sanção recai sobre o escritório e a carteira de
clientes — não sobre quem escreve o código.

A camada de clique automatizado em outorga, assinatura e revogação **não foi
implementada, e não será**: seria entregar um passivo com aparência de
produtividade, e contraria o princípio absoluto da própria seção 94 do briefing
(na dúvida, parar). Pelo mesmo motivo não há nenhuma técnica de humanização ou
anti-detecção no repositório — a seção 65 do briefing as proíbe explicitamente.

As fases 1–5 foram autorizadas e estão concluídas.

---

## H) O que foi implementado

### H.1 Fases

| Fase | Entrega | Onde |
|---|---|---|
| 1 | `.patch` de 1 MB fora do versionamento e coberto pelo `.gitignore`; `sanitizar()` centralizado | `.gitignore`, `backend/app/core/mascaramento.py` |
| 2 | Diagnóstico completo da estação, 9 verificações, 4 níveis, saída `--json`, `--sem-rede` e código de saída 0/1 | `agent/cajuru_agent/diagnostico.py`, `AGENT_CAJURU.md` §6 |
| 3 | Pré-voo de lote: gate de ambiente + APTO/ATENÇÃO/BLOQUEADO/DISPENSADO por cliente | `backend/app/procuracoes/servicos/prevoo.py`, `GET /procuracoes/pre-voo`, tela `procuracoes/pre-voo` |
| 4 | Exportação CSV/JSON (12 colunas) e métricas por etapa | `backend/app/procuracoes/servicos/relatorio.py`, `GET /procuracoes/relatorio`, `GET /procuracoes/metricas` |
| 5 | Testes e documentação operacional | abaixo |

Item extra, pedido durante a implementação: **vigência de 5 anos** contada
exatamente a partir da outorga (`VIGENCIA_MAXIMA_MESES = 60`, soma de meses via
`calendar.monthrange` da biblioteca padrão — não por aproximação de 1825 dias, e
sem depender de `dateutil` para aritmética de prazo legal).

### H.2 Decisões de projeto que valem registro

**`DISPENSADO` é um estado próprio, não um `BLOQUEADO`.** "Já tem autorização
ativa, nada a fazer" é um bom desfecho. Se aparecesse como problema, o operador
perseguiria cliente já resolvido e a fila de trabalho nasceria inflada.

**O pré-voo é somente leitura, e isso é testado.** `test_prevoo_nao_tem_efeito_colateral`
garante que nenhuma chamada cria job ou autorização; `test_prevoo_e_a_fila_concordam`
garante que pré-voo e `fila.criar_job` recusam pelos mesmos motivos. Um pré-voo
que aprove o que a fila vai recusar é pior que não ter pré-voo.

**Métricas vêm da trilha de eventos, não de contadores no job.** Custa mais a
cada leitura e é deliberado: um contador incrementado por transição vira segunda
fonte de verdade e diverge no primeiro crash no meio de etapa. O que se
reconstrói é a divisão entre **espera humana** e **processamento** — em operação
saudável a espera humana domina, e isso não é defeito.

**Documento mascarado por padrão na exportação.** O CNPJ completo exige
`documento_completo=true`, e a escolha fica registrada na auditoria como
`procuracao.relatorio.exportado_sem_mascara`. Não é proibido; é rastreável.

**CSV com `;` e BOM UTF-8.** Sem isso o Excel em português não separa colunas e
corrompe acentos. Download por `fetch` autenticado, não por `<a href>`: o cookie
de sessão é HttpOnly e o link direto voltaria 401.

**`PULADO` nunca conta como `PASS` no diagnóstico.** Com `--sem-rede` as
checagens de rede saem como não verificadas e o relatório diz isso. Diagnóstico
que finge ter verificado é pior que diagnóstico nenhum.

### H.3 Verificação

| Suíte | Antes | Depois |
|---|---|---|
| `backend/tests` | 393 | **432** |
| `agent/tests` | 28 | **57** |
| `frontend` (`npm test`) | 70 | **74** |
| `frontend` (`tsc --noEmit`) | limpo | limpo |

Arquivos de teste novos: `backend/tests/test_procuracoes_prevoo.py` (29),
`agent/tests/test_diagnostico.py` (29),
`frontend/testes/procuracoes-pre-voo.test.tsx` (4), mais 10 testes de rota
acrescentados a `backend/tests/test_procuracoes_api.py`.

### H.4 O que continua fora de escopo

- clique/assinatura automatizados em outorga, alteração ou revogação (art. 13);
- qualquer humanização, randomização de comportamento ou anti-detecção;
- resolução de CAPTCHA, 2FA do gov.br e PIN do certificado — sempre humanos.

Para volume real sem tocar no portal, o caminho legítimo continua sendo o
**Integra Contador** (canal oficial, já integrado em
`integracoes/integra_contador.py` para leitura).
