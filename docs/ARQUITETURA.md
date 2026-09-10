# Arquitetura

## Multiempresa desde o dia 1 (mesmo rodando para um escritório só)

Toda tabela do banco tem `escritorio_id`. Hoje existe um único registro em
`escritorios` (o seu). Quando (se) isso virar produto, não existe migração de
dado nem reescrita de modelo — só passa a existir mais de uma linha nessa
tabela e o isolamento já está lá, testado desde o começo. É bem mais barato
projetar isso agora do que "migrar para multiempresa" depois com dados reais
de clientes no meio.

## Por que sair do modelo "script + Streamlit + planilha de senha"

O `Importarnotas` original resolve muito bem o problema de *baixar a nota*.
O que ele não resolve (e não é papel dele resolver) é o problema de
*operar isso como sistema*:

| Problema no modelo atual                                   | Solução aqui |
| ------------------------------------------------------------ | ------------ |
| Senha de certificado em `.xlsx` sincronizado no Dropbox       | Cofre cifrado no banco, nunca em texto puro, nunca exportável |
| Importação roda no processo do Streamlit (trava se fechar)   | Fila (Celery) — roda independente da interface, com retry |
| Um `.db` SQLite local por máquina                             | PostgreSQL central, acesso concorrente, backup único |
| Sem controle de quem acessou o quê                            | Usuários com login (JWT) e log de execução por usuário |
| Sem separação entre "código" e "credencial"                   | `.env` + cofre; nada de segredo versionado |

## O cofre de segredos

Não é um serviço externo (Vault/KMS) na Fase 0 — seria over-engineering para
um único escritório. É uma camada de criptografia simétrica (Fernet/AES) na
própria aplicação: a senha do certificado é cifrada antes de gravar no banco,
com uma chave mestra que **vive só no `.env` do servidor**, nunca no banco,
nunca no repositório. Isso já elimina o problema real de hoje (senha em
planilha de Excel visível a qualquer um com acesso ao Dropbox).

A chave `VAULT_MASTER_KEY` precisa permanecer estável enquanto existirem
certificados gravados. Em uma rotação planejada, a chave nova fica em
`VAULT_MASTER_KEY` e a antiga entra temporariamente em
`VAULT_PREVIOUS_MASTER_KEYS` (separada por vírgula). O cofre grava somente
com a nova, mas consegue abrir as senhas antigas até cada certificado ser
reenviado. Se a chave anterior foi perdida, a criptografia não pode — e não
deve — ser quebrada: reenvie o `.pfx` e a senha para criar um registro novo.

Quando o projeto crescer para multiempresa de verdade, essa camada troca de
lugar (por HashiCorp Vault, AWS KMS, etc.) sem mudar a interface que o resto
do sistema usa (`vault.cifrar()` / `vault.decifrar()`) — só a implementação
por trás muda.

## Um único modelo de "importador", três fontes diferentes

NFS-e (ADN), NFe (SEFAZ) e CT-e (SEFAZ) têm protocolos diferentes (REST vs
SOAP) mas o mesmo formato de problema: autenticar com o certificado A1 via
mTLS, paginar por um cursor (NSU), baixar lotes, gravar XML, marcar de onde
continuar. Por isso existe uma interface comum
(`app/services/importadores/base.py`) que cada fonte implementa — isso é o
que permite adicionar NFe e CT-e na Fase 2/3 sem tocar no que já funciona
para NFS-e.

## Eventos de cancelamento (importação "completa", sem perder nota)

A distribuição (ADN e SEFAZ) mistura notas e **eventos** no mesmo lote.
Antes, eventos eram descartados: além de o usuário não saber que uma nota
tinha sido cancelada, o descarte fazia o lote parecer menor — e a paginação
por "tamanho do lote" concluía errado que não havia mais nada (o bug do
"não importa tudo").

Hoje o fluxo é:

1. `app/services/importadores/eventos.py` interpreta cada item: nota normal,
   **cancelamento** (`tpEvento` 110111/110112, `cStat` 135, `descEvento`, ou
   `TipoDocumento` do ADN) ou **evento não reconhecido** (CC-e, resumo, etc.).
2. O lote devolve `documentos`, `eventos` e contadores — nada é descartado
   sem rastro.
3. O worker aplica o cancelamento na nota (se já existe) ou guarda em
   `eventos_fiscais_pendentes` (se a nota ainda não chegou; ordem de NSU não
   é garantida) e aplica automaticamente quando a nota for gravada.
4. `DocumentoFiscal.status` (`normal`/`cancelada`), `motivo_cancelamento` e
   `cancelado_em` ficam visíveis em `GET /documentos` e
   `GET /documentos/resumo`; a execução registra `documentos_cancelados`,
   `eventos_nao_reconhecidos` e um `aviso` com os itens ignorados.

A paginação do ADN passou a usar o **tamanho do lote bruto** (eventos
incluídos) e o cursor é calculado por `UltNSU`/NSU bruto — nunca por contagem
de notas convertidas.

## O governador de consumo (por que nada vira erro vermelho)

O gargalo real de puxar nota fiscal não é throughput, é **quota**: a SEFAZ
libera uma consulta por CNPJ por hora e rejeita com **cStat 656** quem consulta
antes — e cada tentativa antecipada **reinicia** o bloqueio. Um sistema que
trata isso como exceção vira um botão que o operador aperta com raiva e que
trava o CNPJ do cliente.

Então existe uma peça só para isso, `app/services/sincronizacao.py`, e um
estado por (empresa, tipo) na tabela `sincronizacoes_dfe`:

| Campo | Para que serve |
| --- | --- |
| `ultimo_nsu` | checkpoint — de onde a próxima varredura continua (nunca regride) |
| `max_nsu` | até onde o ambiente tem documento: `ultimo >= max` é **em dia** |
| `proxima_consulta_em` | a janela de 1h (+ folga), válida para clique manual **e** agendador |
| `bloqueado_ate`, `motivo_bloqueio`, `bloqueios_seguidos` | o 656 como estado operacional, não como falha |
| `consultas_pontuais`, `janela_pontual_em` | cota de 20/h das consultas por chave/NSU |
| `travado_em` | `lease` de 25 min: duas varreduras nunca disputam o mesmo NSU |
| `tarefas_pendentes` | execução `AGUARDANDO` reagendada que o beat retoma |

Quem consome isso:

- **`POST /importacoes`** — responde 429 com a hora da liberação em vez de
  disparar uma task que ia tomar 656; `forcar=true` atravessa e fica registrado;
- **`worker/tasks.importar_documentos`** — commit por lote (checkpoint real),
  espera entre páginas, teto de páginas com reagendaamento da *mesma* execução,
  656 → `AGUARDANDO` + realinhamento de cursor + retomada automática;
- **`sincronizar_tudo` (beat)** — round-robin por `ultima_consulta_em` (quem
  está pronto primeiro; NULLS FIRST para empresas novas), sem enfileirar duas
  vezes a mesma combinação;
- **`completar_xmls_pendentes` (beat)** — preenche os `leiaute="resumo"` pela
  chave, com a cota de 20/h e pausando ao tomar 656.

A resposta de uma importação nunca é "Erro" quando a SEFAZ só pediu para
esperar: `StatusExecucao.AGUARDANDO` existe exatamente para isso.

Regras completas e diagnóstico: [`SINCRONIZACAO.md`](SINCRONIZACAO.md).

## Competência no banco, não na requisição

Nenhum webservice de distribuição aceita filtro por data — e fingir que aceita
(cortando o cursor) é como se perdem notas. O modelo grava, em cada documento, a
`competencia` declarada no próprio XML (`dComp`/`dhEmi`, coluna `date`
indexada), e toda a API usa **uma única função de filtro**
(`documentos._filtrar`) para lista, resumo e ZIP. Consequência prática:

- trocar de mês na tela custa zero requests à SEFAZ;
- o número na tela é o número de arquivos no ZIP;
- uma competência antiga vira um `WHERE`, não uma "reimportação do mês".

O ZIP (`GET /documentos/exportar`) é montado num arquivo temporário a partir de
um `SELECT` paginado (`.yield_per(200)`), servido por `FileResponse` e apagado
em `BackgroundTask` — não existe caminho em que um download de 20 mil arquivos
segure conexão do banco ou estoure memória do processo.

## Cadastro em massa de empresas

`POST /empresas/lote` recebe vários `.pfx` + senha (compartilhada ou por
linha do CSV) e extrai CNPJ/razão social do X.509 (ICP-Brasil:
`SubjectAltName` OID 2.16.76.1.3.3, com fallback para `serialNumber` do
Subject e para o nome do arquivo). Cria a empresa, salva o `.pfx` com
permissão 0600, cifra a senha no cofre e devolve um relatório item a item
(criada / certificado vinculado / já existia / erro). A senha é sempre
**explícita**: não existe loop de tentativa de senhas candidatas.

## Migração de schema sem Alembic (por enquanto)

Como o schema ainda é criado com `create_all`, colunas novas em tabelas já
existentes não aparecem sozinhas. `app/db/migracoes.py` resolve isso com
`ALTER TABLE ... ADD COLUMN` idempotente (PostgreSQL usa `IF NOT EXISTS`;
SQLite checa `PRAGMA table_info`), chamado no startup por `criar_tabelas()`.
Script manual: `docker compose exec api python scripts/migrar.py`.

## O que fica para depois de propósito

- **Alembic (migrations versionadas)**: a camada de migração leve acima
  cobre os casos atuais, mas antes de ter mais de uma pessoa mexendo no
  schema ao mesmo tempo, ou antes de ir para produção com dado de cliente
  real, trocar para Alembic é o próximo passo natural — o ponto de troca
  continua isolado em `app/db/base.py`.
- **Vault externo (HashiCorp/KMS)**: ver seção acima.
- **Fila durável (RabbitMQ/Postgres) no lugar de Redis**: o Redis é broker
  aqui, não store — por isso `task_acks_late`, `visibility_timeout` maior que
  qualquer countdown e checkpoint no banco. Se um dia a fila precisar de
  garantia transacional, a troca é no `celery_app`, não nas tasks.
