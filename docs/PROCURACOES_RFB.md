# Procurações RFB — arquitetura, fluxo e operação

Módulo de gestão e automação das **Autorizações de Acesso** da Receita Federal
(o que até dezembro de 2025 se chamava "Procuração Eletrônica").

Este documento é a referência principal. Os complementos são:

| Documento | Assunto |
|---|---|
| [`AGENT_CAJURU.md`](AGENT_CAJURU.md) | instalação, contrato e operação da estação Windows |
| [`PROCURACOES_CONFORMIDADE.md`](PROCURACOES_CONFORMIDADE.md) | base legal, o que é e o que não é automatizável |
| [`PROCURACOES_INTEGRACOES.md`](PROCURACOES_INTEGRACOES.md) | Integra Contador, Assinador SERPRO, Jettax 360 |
| [`PROCURACOES_OPERACAO.md`](PROCURACOES_OPERACAO.md) | troubleshooting, recuperação, backup, atualização |

---

## 1. O problema, em uma frase

Um escritório com 500 clientes precisa que cada um deles conceda, no portal da
Receita, uma autorização de acesso em favor do CNPJ da contabilidade. Sem ela,
não há e-CAC, não há caixa postal, não há certidão, não há DCTFWeb. Hoje isso é
feito à mão, cliente a cliente, e ninguém sabe dizer quantos estão vencidos.

O módulo responde três perguntas e executa o que for possível executar:

1. **Quem ainda não autorizou?**
2. **O que falta para resolver cada caso?**
3. **O que vence nos próximos 30, 60 e 90 dias?**

---

## 2. A decisão que define toda a arquitetura

A **Instrução Normativa RFB nº 2.320, de 6 de abril de 2026**, art. 13, veda
expressamente aplicativo, *webview*, *iframe*, camada de intermediação ou
sistema próprio que — por automação ou encapsulamento do ambiente digital da
Receita — possibilite **outorga, alteração ou revogação** de autorizações de
acesso. As sanções previstas incluem interrupção de acesso, bloqueio do
representante e cancelamento das autorizações existentes.

Um robô que preenchesse o formulário e clicasse em "Assinar" seria, em 2026,
exatamente a coisa proibida. Pior: o risco não recai sobre o fornecedor do
software, e sim sobre o escritório e seus clientes.

Daí a divisão em **três camadas de legitimidade**:

```
┌──────────────────────────────────────────────────────────────────────┐
│ CAMADA 1 · CANAL OFICIAL — consulta por API                          │
│ Integra Contador (SERPRO), serviço OBTERPROCURACAO41.                │
│ Responde: existe autorização? quais sistemas? até quando?            │
│ Status: contratual, documentado, estável. É a fonte da verdade.      │
├──────────────────────────────────────────────────────────────────────┤
│ CAMADA 2 · GESTÃO INTERNA — fora do ambiente da RFB                  │
│ Fila, estados, modelos, lock, auditoria, alertas, painel, estações.  │
│ Não toca o portal. Não é intermediação. É software de escritório.    │
├──────────────────────────────────────────────────────────────────────┤
│ CAMADA 3 · EXECUÇÃO NO PORTAL — assistida, nunca autônoma            │
│ O Agent valida os pré-requisitos, abre o NAVEGADOR REAL do operador  │
│ na URL oficial e o guia passo a passo. Quem clica e assina é a       │
│ pessoa, autenticada com o certificado, no ambiente da própria RFB.   │
└──────────────────────────────────────────────────────────────────────┘
```

O ganho de produtividade não vem de "clicar sozinho" — vem de eliminar tudo o
que cerca o clique: descobrir quem falta, achar o certificado certo, conferir
que o Assinador funciona, abrir a página certa, ditar os dados, registrar o
resultado e vigiar o prazo. Na prática, o tempo por cliente cai de "abrir cinco
abas e torcer" para "conferir e confirmar".

Detalhamento completo em [`PROCURACOES_CONFORMIDADE.md`](PROCURACOES_CONFORMIDADE.md).

---

## 3. Arquitetura

### 3.1 Componentes

```
                        ┌───────────────────────────┐
                        │  Navegador do operador    │
                        │  (Next.js · Fluxa)        │
                        └────────────┬──────────────┘
                                     │ cookie de sessão + CSRF por Origin
                                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI · app/api/routers/procuracoes.py        (27 rotas, RBAC)    │
│ FastAPI · app/api/routers/procuracoes_agent.py  (11 rotas, HMAC)    │
├─────────────────────────────────────────────────────────────────────┤
│ SERVIÇOS · app/procuracoes/servicos/                                │
│  configuracao  modelos, vigência, outorgado, política               │
│  fila          criação idempotente, lock, transições, retry         │
│  certificados  inventário e seleção determinística                  │
│  agentes       matrícula, HMAC, nonce, heartbeat, revogação         │
│  assinador     avaliação do ambiente SERPRO (falha fechada)         │
│  evidencias    captura cifrada, com expurgo por retenção            │
│  sincronizacao reconciliação com as fontes, por precedência         │
│  eventos       trilha imutável + notificações internas              │
│  painel        KPIs, listagem, detalhe                              │
├─────────────────────────────────────────────────────────────────────┤
│ DOMÍNIO · estados.py (máquina de estados, taxonomia de erros,       │
│           política de conformidade) · portal.py (roteiro oficial)   │
├─────────────────────────────────────────────────────────────────────┤
│ PERSISTÊNCIA · modelos.py — 17 tabelas procuracao_*                 │
└──────────┬──────────────────────────────────┬───────────────────────┘
           │ PostgreSQL                        │ Redis + Celery beat
           ▼                                   ▼
   ┌───────────────┐              ┌──────────────────────────┐
   │ trilha, fila, │              │ manutenção (10 min)      │
   │ inventário    │              │ sincronização (6 h)      │
   └───────────────┘              │ triagem de estações      │
                                  └──────────────────────────┘
           ▲
           │ HTTPS + HMAC-SHA256 + nonce (sem cookie)
           │
┌──────────┴────────────────────────────────────────────────────────┐
│ CAJURU AGENT · Windows do escritório                              │
│  certificados.py  inventário via repositório do Windows           │
│  assinador.py     diagnóstico do Assinador SERPRO Desktop         │
│  roteiro.py       condução do operador + abertura do navegador    │
│  protocolo.py     cliente HTTP assinado                           │
│                                                                    │
│  A1 e chave privada NUNCA saem daqui.                             │
└────────────┬──────────────────────────────────────────────────────┘
             │ o operador, autenticado com o certificado
             ▼
   ┌─────────────────────────────────────────────┐
   │ servicos.receitafederal.gov.br  (oficial)   │
   │ Assinador Digital SERPRO · 127.0.0.1:65156  │
   └─────────────────────────────────────────────┘
```

### 3.2 Por que um Agent, e não upload de certificado

A alternativa óbvia — subir o `.pfx` e a senha para o servidor — foi descartada:

- concentra num só lugar a chave privada de centenas de empresas, o que
  transforma o servidor no alvo mais valioso do escritório;
- exige que o sistema conheça a senha do certificado do cliente, algo que ele
  não precisa saber para nada mais;
- o Assinador SERPRO, que o portal aciona, é um componente **desktop**: ele
  procura o certificado no repositório da máquina, não num servidor remoto.

Com o Agent, o servidor emite uma **ordem de trabalho** contendo apenas
identificadores (`thumbprint` + referência local opaca). Quem resolve isso em
um certificado utilizável é a própria estação, via CryptoAPI do Windows.

### 3.3 Extensibilidade

Os blocos genéricos deste módulo — fila com lease, protocolo do Agent,
inventário de certificados, trilha, evidências, roteiro assistido — não têm
nada de específico de procuração. Um módulo futuro de **CND**, **caixa
postal**, **DCTFWeb** ou **certidões** reusa tudo, mudando apenas:

1. o roteiro (`portal.py` equivalente);
2. as etapas do fluxo (`EtapaFluxo`);
3. o serviço de reconciliação com a fonte de dados.

---

## 4. Fluxo completo da procuração

### 4.1 Fase 1 — outorga (identidade do **cliente**)

```
 [1] Sincronização / cadastro
     Jettax 360, Integra Contador ou planilha dizem quem tem autorização.
     Sem fonte configurada, a carteira inteira nasce "sem autorização".
                    │
                    ▼
 [2] "Processar pendências"        (operador, ou agendador a cada 1 h)
     Para cada empresa sem autorização vigente:
       · não existe job ativo?      → cria (chave idempotente)
       · já existe?                 → JOB_DUPLICADO, não duplica
       · sem A1 vigente na frota?   → marca o motivo e mostra na tela
                    │
                    ▼
 [3] Estação reivindica            (Cajuru Agent, a cada N segundos)
     PORTÃO 1 — Assinador SERPRO apto?  não → 409, nenhum job sai
     PORTÃO 2 — UM único A1 vigente do CNPJ nesta máquina?
                  vencido/ausente/ambíguo → job marcado, não entregue
     Sucesso: UPDATE condicional grava lease + token → ATRIBUIDO
                    │
                    ▼
 [4] Pré-requisitos                VERIFICANDO_PRE_REQUISITOS
     Certificado, Assinador, navegador. Nada abre se algo falhar.
                    │
                    ▼
 [5] Navegador abre na URL oficial PRONTO_PARA_OPERACAO → AUTENTICANDO
     O operador autentica com o certificado do CLIENTE.
     O sistema não digita credencial e não manipula chave privada.
                    │
                    ▼
 [6] Autorizações de Acesso → Minhas Autorizações → aba Concedidas
     Já existe autorização vigente? encerra sem duplicar.
                    │
                    ▼
 [7] Nova Autorização              PREENCHENDO
     passo 1 Pessoa   — CNPJ do outorgado + validade (teto legal: 5 anos)
     passo 2 Serviços — conforme o modelo configurado
     passo 3 Revisão  — divergência interrompe; não se corrige no impulso
                    │
                    ▼
 [8] Assinatura                    AGUARDANDO_ASSINATURA
     O portal abre o ambiente oficial de assinatura do Governo Federal.
     O operador assina. O Assinador SERPRO é acionado pelo portal.
                    │
                    ▼
 [9] Registro                      ASSINADO → AGUARDANDO_VALIDACAO
     Exige protocolo OU texto de confirmação do portal.
     Sem isso a API RECUSA. "Cliquei em assinar" não é prova.
     Grava a autorização como "Em análise" e arma o relógio de 30 dias.
```

### 4.2 Fase 2 — aceite (identidade da **contabilidade**)

```
[10] Estação reivindica de novo    (pode ser outro dia, outra máquina)
     Agora o certificado exigido é o da CONTABILIDADE.
     O lease da fase 1 já foi liberado — segurar a máquina à toa seria
     desperdiçar a cota de concorrência do escritório.
                    │
                    ▼
[11] Portal → Minhas Autorizações → aba Recebidas   VALIDANDO
     Localiza a autorização pendente e clica em "Validar".
                    │
                    ▼
[12] Registro da conclusão         CONCLUIDO
     Exige confirmação do portal. A autorização passa para ATIVA.
```

### 4.3 O relógio dos 30 dias

A Receita cancela automaticamente a autorização que o outorgado não validar em
30 dias. O módulo trata isso como cidadão de primeira classe:

- `prazo_aceite_ate` é gravado no momento da outorga;
- a varredura de manutenção avalia diariamente e **cancela localmente** o que
  venceu, notificando;
- a tabela mostra a contagem regressiva (`Aceite em 5d`), não a data crua;
- a partir de 3 dias o indicador fica vermelho.

---

## 5. Máquina de estados

```
                       ┌──────────┐
                       │ PENDENTE │
                       └────┬─────┘
                            ▼
                  ┌────────────────────┐
           ┌──────│ AGUARDANDO_AGENTE  │◄──────── lease expirado
           │      └────────┬───────────┘          (volta no mesmo ponto)
           │               ▼
           │      ┌────────────────┐
           │      │   ATRIBUIDO    │
           │      └────────┬───────┘
           │               ▼
           │   ┌───────────────────────────┐
           │   │ VERIFICANDO_PRE_REQUISITOS│
           │   └───────────┬───────────────┘
           │               ▼
           │   ┌────────────────────────┐
           │   │  PRONTO_PARA_OPERACAO  │  ← esperando o humano
           │   └───────────┬────────────┘
           │               ▼
           │      ┌────────────────┐     ┌──────────────┐
           │      │  AUTENTICANDO  │────►│ PREENCHENDO  │
           │      └────────────────┘     └──────┬───────┘
           │                                     ▼
           │                        ┌────────────────────────┐
           │                        │ AGUARDANDO_ASSINATURA  │ ← humano
           │                        └───────────┬────────────┘
           │                                     ▼  (confirmação real)
           │                              ┌────────────┐
           │                              │  ASSINADO  │
           │                              └─────┬──────┘
           │                                    ▼
           └────────────────────►┌────────────────────────┐
                                 │ AGUARDANDO_VALIDACAO   │ ← humano
                                 └───────────┬────────────┘
                                              ▼
                                       ┌─────────────┐
                                       │  VALIDANDO  │
                                       └──────┬──────┘
                                              ▼  (confirmação real)
                                       ┌─────────────┐
                                       │  CONCLUIDO  │  terminal
                                       └─────────────┘

  De quase todo estado:  ──► INTERVENCAO_MANUAL  (retomável, guarda a etapa)
                         ──► CANCELADO / FALHOU  (terminais)
```

Três invariantes garantidas por `app/procuracoes/estados.py`:

1. **Nenhuma fase é pulada.** O grafo é explícito; `mudar_status` é a única
   porta e levanta `TransicaoInvalidaError` fora dele.
2. **Terminal é terminal.** `CONCLUIDO`, `FALHOU` e `CANCELADO` não voltam.
   Reprocessar cria um job **novo**, com outra chave idempotente — reabrir
   apagaria a evidência do que aconteceu.
3. **Marco exige prova.** `ASSINADO` e `CONCLUIDO` só são alcançáveis via
   `registrar_outorga`/`registrar_aceite`, que exigem protocolo ou texto do
   portal. Nem o relato de progresso da estação atravessa esses estados.

---

## 6. Taxonomia de erros e retry

Cada código tem classe, número de tentativas, espera-base, destino ao esgotar
e uma explicação acionável (`REGRAS` em `estados.py`). Código desconhecido cai
em `REGRA_PADRAO`: **zero tentativa, intervenção manual** — falha fechada.

| Classe | Exemplos | Retry | Destino |
|---|---|---|---|
| `TRANSIENTE` | `FALHA_DE_REDE`, `PORTAL_INDISPONIVEL` | sim, backoff exponencial com teto de 30 min | volta à fila |
| `CERTIFICADO` | `CERTIFICADO_EXPIRADO`, `_AMBIGUO`, `_NAO_ENCONTRADO` | **não** | falhou / intervenção |
| `ASSINADOR` | `ASSINADOR_NAO_INSTALADO`, `_DESATUALIZADO` | não | intervenção |
| `PORTAL_ALTERADO` | âncora oficial ausente na tela | **não** | intervenção |
| `AUTENTICACAO` | `DESAFIO_DE_SEGURANCA` (CAPTCHA/MFA) | não | intervenção |
| `PERMANENTE` | `OUTORGADO_INVALIDO`, `VIGENCIA_INVALIDA` | não | falhou |
| `DUPLICADO` | `JOB_DUPLICADO`, `AUTORIZACAO_JA_EXISTE` | não | cancelado |
| `TIMEOUT` | etapa ou job estourou o tempo | uma vez | intervenção |

Por que certificado vencido não entra em retry: tentar de novo em cinco minutos
produz exatamente o mesmo resultado, e cada tentativa custa uma sessão aberta
no portal de um terceiro. O que resolve é renovar o A1 — então o job para, diz
isso na tela, e volta a ser elegível sozinho quando o certificado novo aparece
no inventário (`triar_por_certificado` limpa o motivo antigo).

---

## 7. Modelo de dados

17 tabelas, todas com prefixo `procuracao_`. Três decisões estruturais:

1. **Status como `String` validado no domínio**, não `ENUM` do PostgreSQL.
   Adicionar um estado novo num `ENUM` exige `ALTER TYPE` coordenado com o
   deploy; aqui o domínio valida e a migração não trava.
2. **Nenhum material secreto.** O inventário guarda metadados X.509 e uma
   `referencia_local` opaca. Não há coluna para senha, PFX ou chave privada —
   e é por isso que não existe endpoint que possa vazá-los.
3. **`escritorio_id` em toda raiz**, para que o isolamento multi-tenant seja
   uma condição de `WHERE` e não uma convenção.

| Tabela | Papel | Chave de unicidade |
|---|---|---|
| `procuracao_configuracoes` | parâmetros do escritório | `escritorio_id` |
| `procuracao_modelos` / `_servicos` | template de vigência e serviços | — |
| `procuracao_agentes` | estações matriculadas (segredo em Argon2id) | `identificador` |
| `procuracao_agente_sessoes` | sessões HMAC de 12 h | — |
| `procuracao_agente_nonces` | anti-replay, janela de 5 min | `agente + nonce` |
| `procuracao_certificados_inventario` | A1 visíveis por estação | `agente + thumbprint` |
| `procuracao_autorizacoes` | situação perante a RFB | `escritorio + empresa + outorgado` |
| `procuracao_autorizacao_permissoes` | serviços concedidos | — |
| `procuracao_jobs` | fila de trabalho, lease, dados congelados | `escritorio + chave_idempotencia` |
| `procuracao_job_eventos` | **trilha imutável** | — |
| `procuracao_job_evidencias` | capturas cifradas, com retenção | — |
| `procuracao_sessoes_navegador` | rastro da sessão assistida | — |
| `procuracao_integracao_jobs` / `_erros` | execuções de sincronização | — |
| `procuracao_credenciais_integracao` | credenciais externas (Fernet) | `escritorio + fonte` |
| `procuracao_notificacoes` | avisos internos, deduplicados | `escritorio + chave` |

Índices operacionais em `app/db/migracoes.py` (`ix_proc_*`): fila por
escritório+status, varredura de lease, autorizações por validade, eventos por
job, nonces por expiração.

**A trilha não tem rota de exclusão.** Não existe `DELETE` em
`procuracao_job_eventos` na API — nem para administrador. O expurgo por
retenção alcança apenas evidências (imagem/HTML), que são dado pessoal com
finalidade operacional, nunca a trilha.

---

## 8. Segurança

### 8.1 Certificados

| Risco | Mitigação |
|---|---|
| Chave privada vazar do servidor | o servidor nunca a recebe; ela não sai do CryptoAPI do Windows |
| Senha do A1 em log/banco | não existe campo para ela em lugar nenhum do módulo |
| Certificado errado ser usado | seleção ancorada no CNPJ do OID ICP-Brasil (2.16.76.1.3.3); ambiguidade → intervenção |
| Certificado vencido na hora H | margem de 1 dia na seleção + alerta em 30/60/90 dias + portão na entrega |
| Credencial da estação vazar | Argon2id no servidor; DPAPI (Credential Manager) na estação |

### 8.2 Protocolo do Agent

- **HMAC-SHA256** sobre `MÉTODO\nCAMINHO\nTIMESTAMP\nNONCE\nsha256(corpo)`;
- **nonce de uso único** com janela de 5 minutos → replay devolve `409`;
- **tolerância de relógio** de 5 minutos → requisição antiga é recusada;
- **sessão de 12 h**, revogável na hora (revogar encerra tudo e devolve os jobs);
- **lease por job**: só o dono do lease, com o token idêntico e não vencido,
  altera o job;
- corpo limitado a 12 MiB; evidência viaja como binário puro com o lease em
  **cabeçalho**, não em query string (query string entra em log de proxy).

### 8.3 API interna

Herda o que o Cajuru28 já faz: JWT em cookie `HttpOnly`, CSRF por `Origin`
quando há cookie, rate limit em toda mutação, RBAC por papel. O que o módulo
acrescenta: rotas administrativas exigem `admin`; rotas operacionais exigem
papel de escrita; toda mutação grava auditoria **antes** do commit, na mesma
transação.

### 8.4 O que o módulo se recusa a fazer

Burlar CAPTCHA, contornar MFA, quebrar anti-bot, ocultar automação, interceptar
sessão, extrair chave privada, guardar senha em claro, falsificar resposta do
portal ou considerar concluída uma operação sem confirmação real. Ao encontrar
desafio de segurança, o resultado é `MANUAL_INTERVENTION` com a sessão
entregue ao operador.

---

## 9. Observabilidade

- **Logs estruturados** em JSON (o formatador do Cajuru28), com `request_id`
  correlacionável. Nenhum log carrega segredo: `sanitizar()` redige `senha`,
  `password`, `pfx`, `token`, `cookie` e afins antes de qualquer registro.
- **Trilha por job** em `procuracao_job_eventos`: toda transição tem ator,
  etapa, status anterior/novo e código de erro.
- **KPIs** em `GET /procuracoes/resumo`: fila, aguardando humano, erros,
  concluídos em 24 h, duração média, taxa de sucesso, estações online, A1
  vencendo, notificações abertas.
- **Notificações internas** deduplicadas por chave estável — a mesma estação
  offline não gera 300 avisos.
- **Health**: `situacao()` por estação (online / ociosa / offline / revogada)
  derivada do heartbeat contra a tolerância configurada.

---

## 10. Escala: de 100 a 5.000 empresas

| Ponto de pressão | Como o desenho responde |
|---|---|
| Montar a fila | consulta em lote com índice `escritorio+situacao`; `enfileirar_pendencias` aceita limite por ciclo |
| Concorrência | `UPDATE ... WHERE agente_id IS NULL` + `rowcount`: funciona igual em PostgreSQL e SQLite, sem `SELECT FOR UPDATE` |
| Muitas estações | roteamento por documento disponível: o job só é oferecido a quem tem o A1 |
| Rajada no portal | teto global (`max_jobs_simultaneos`) e por estação (`max_jobs_por_agente`) |
| Estação que some | lease expira e o job volta **no mesmo ponto**, sem intervenção |
| Trilha crescendo | evidências têm retenção configurável; eventos são append-only e indexados por job |
| Multi-tenant | `escritorio_id` em toda raiz e em todo índice composto |

O gargalo real, em qualquer escala, é humano: quantos operadores existem para
autenticar-se nos portais. O sistema reconhece isso ao separar
`jobs_aguardando_humano` do resto — é esse número que dimensiona o dia.

---

## 11. Configuração

Nada é fixo no código. Tudo em **Procurações → Configurar**:

| Parâmetro | Padrão | Observação |
|---|---|---|
| CNPJ/nome do outorgado | — | obrigatório; sem ele nada é criado |
| Vigência do modelo | 60 meses | teto legal de 5 anos aplicado na origem |
| Serviços | todos | ou lista explícita por modelo |
| Montar fila automaticamente | desligado | montar fila em nome de terceiros é decisão do escritório |
| Sincronização automática / hora | ligada / 06 h | por escritório |
| Processos simultâneos | 2 (escritório) / 1 (estação) | protege o portal e o operador |
| Alertas | 30, 60, 90 dias | vale para autorização e certificado |
| Versão mínima do Assinador | 4.0.0 | rejeita estação desatualizada |
| Exigir Assinador apto | sim | desligar só em treinamento |

Variáveis de ambiente (`backend/app/core/config.py`):

```
PROCURACOES_ATIVO=true                      # interruptor geral (desagenda tudo)
PROCURACOES_MANUTENCAO_A_CADA_MINUTOS=10
PROCURACOES_SINCRONIZACAO_A_CADA_HORAS=6
PROCURACOES_EVIDENCIA_RETENCAO_DIAS=180
PROCURACOES_EVIDENCIA_MAX_MB=8
PROCURACOES_MAX_JOBS_POR_CICLO=20
```

`validar_producao()` recusa subir em produção com valores fora de faixa ou sem
`VAULT_MASTER_KEY` quando o módulo está ativo.

---

## 12. APIs internas

### Operação (cookie de sessão + RBAC)

| Método | Rota | Papel |
|---|---|---|
| GET | `/procuracoes/resumo` | leitura |
| GET | `/procuracoes` | leitura |
| GET | `/procuracoes/situacoes` | leitura |
| GET | `/procuracoes/empresas/{id}` | leitura |
| GET | `/procuracoes/roteiro` | leitura |
| POST | `/procuracoes/jobs` | escrita |
| POST | `/procuracoes/processar-pendencias` | escrita |
| GET | `/procuracoes/jobs` · `/jobs/{id}` | leitura |
| POST | `/procuracoes/jobs/{id}/retomar` · `/cancelar` · `/reprocessar` · `/intervencao` | escrita |
| POST | `/procuracoes/jobs/{id}/registrar-outorga` · `/registrar-aceite` | escrita |
| GET | `/procuracoes/jobs/{id}/evidencias/{eid}` | leitura |
| GET/PUT | `/procuracoes/configuracao` | leitura / **admin** |
| GET/POST/PUT/DELETE | `/procuracoes/modelos` | leitura / **admin** |
| GET/PUT/DELETE | `/procuracoes/integracoes` | leitura / **admin** |
| POST | `/procuracoes/integracoes/{fonte}/testar` · `/sincronizar` · `/importar-planilha` | escrita |
| GET/POST | `/procuracoes/agentes` | leitura / **admin** |
| GET | `/procuracoes/agentes/requisitos` | leitura |
| POST | `/procuracoes/agentes/{id}/revogar` | **admin** |
| GET | `/procuracoes/notificacoes` · POST `/{id}/reconhecer` | leitura / escrita |

### Protocolo do Agent (HMAC, sem cookie)

Contrato completo em [`AGENT_CAJURU.md`](AGENT_CAJURU.md) §4.

---

## 13. Testes

| Arquivo | Cobre |
|---|---|
| `backend/tests/test_procuracoes_dominio.py` | máquina de estados, retry, política, roteiro, normalização |
| `backend/tests/test_procuracoes_fluxo.py` | ciclo A→B com banco, idempotência, lock, lease, certificados |
| `backend/tests/test_procuracoes_seguranca.py` | HMAC, replay, revogação, isolamento, evidências, RBAC |
| `backend/tests/test_procuracoes_api.py` | ponta a ponta pela API, incluindo os critérios C, D, E, F, G |
| `agent/tests/test_agent.py` | protocolo assinado, inventário sem segredo, condução |
| `frontend/testes/procuracoes-estados.test.tsx` | vocabulário visual e navegação |

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
cd agent   && python -m pytest tests/ -q
cd frontend && npm run typecheck && npm test
```

**Sobre ambiente de testes:** a Receita Federal **não oferece sandbox** para o
fluxo de autorizações de acesso. O Integra Contador tem ambiente *trial* apenas
para consulta, com dados fixos. Portanto: nenhum teste deste repositório chama
o portal, e nenhum simula uma resposta real dele. O que os testes verificam é o
contrato do nosso lado — inclusive, e principalmente, o ponto exato em que o
sistema para e devolve o volante ao humano. Ver
[`PROCURACOES_INTEGRACOES.md`](PROCURACOES_INTEGRACOES.md) §4.

---

## 14. Quando o portal mudar

É questão de *quando*, não de *se*. O comportamento é deliberado:

1. a estação relata a âncora ausente → `POST /procuracoes/agente/jobs/{id}/portal-alterado`;
2. o job vai para `INTERVENCAO_MANUAL` com código `PORTAL_ALTERADO`;
3. uma notificação de nível erro é aberta para o escritório;
4. **nenhum job é retomado automaticamente**.

A manutenção é uma edição em `app/procuracoes/portal.py`: as âncoras são
**texto visível** (vocabulário legal: "Nova Autorização de Acesso", "Validar"),
não seletores CSS. Texto legal muda em ciclo de anos; `div.css-1x2y3z` muda
toda sexta-feira.

---

## 15. Limitações conhecidas

1. **Jettax 360 não publica API REST documentada.** Não existe adaptador
   remoto — e a decisão é não ter: sem contrato publicado, a entrada é
   **importação da lista** (colagem da tela ou CSV exportado), sem credencial
   de terceiro no cofre. A migração de referência apaga credenciais `jettax360`
   de instalações antigas.
2. **O Integra Contador só consulta.** Não existe serviço oficial de criação,
   assinatura ou validação de autorização — por isso a fase de execução é
   assistida.
3. **O Assinador SERPRO é Windows-only** neste fluxo. O diagnóstico roda em
   outros sistemas, mas informa honestamente que não é ambiente homologado.
4. **Arquivos `.pfx` soltos em pasta** aparecem no inventário como pendência,
   não como certificado utilizável: abri-los exigiria a senha, e guardar senha
   de certificado é justamente o que este desenho evita.
