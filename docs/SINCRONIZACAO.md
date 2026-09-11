# Sincronização com a SEFAZ — as regras do jogo e como o NotasFlow cumpre cada uma

Este documento é a referência operacional de **por que** a importação se
comporta como se comporta. Ele existe porque os três erros mais caros de quem
puxa nota fiscal no Brasil não são erros de código: são violações do protocolo
de uso dos webservices. Um sistema que "baixa rápido" e queima o CNPJ do
cliente no autorizador é pior do que um sistema lento.

Fontes: Manual dos Contribuintes das APIs do ADN (NFSe), NT 2014.002 /
`NFeDistribuicaoDFe`, `CTeDistribuicaoDFe` e os XSDs oficiais de
`distDFeInt`/`retDistDFeInt`.

---

## 1. As regras oficiais (e o que cada uma significa na prática)

| Regra do webservice | Consequência para o sistema |
| --- | --- |
| Depois de uma consulta, a **próxima consulta do mesmo CNPJ só pode acontecer 1 hora depois**. Consultar antes devolve **cStat 656 – Rejeição: Consumo Indevido**. | O cooldown não é "gentileza", é contrato. O NotasFlow marca `proxima_consulta_em` em toda consulta e **não dispara nada** dentro da janela — nem clique manual, nem agendador. |
| **Repetir a consulta antes de 1h zera o cronômetro do bloqueio.** | Por isso o botão "forçar" existe, mas é explícito (`forcar=true`) e fica registrado na execução. Clicar de novo "para ver se já deu" é exatamente o que trava o CNPJ. |
| A devolução 656 **também traz `ultNSU` e `maxNSU`**. | No bloqueio o sistema **realinha o cursor** com o `ultNSU` devolvido: é o que resolve o caso "outro sistema consultou este CNPJ e o nosso cursor ficou para trás". |
| `distNSU` anda **em sequência ascendente**; não existe filtro por data. | A competência (mês) **não** pode ser usada como recorte de busca: baixar tudo e filtrar no banco é o que garante que nada se perca. |
| `consNSU` / `consChNFe` (consulta pontual) têm teto de **20 consultas por hora por CNPJ**. | O preenchimento dos XMLs que vieram só em resumo roda com cota controlada (`consultas_pontuais` + `janela_pontual_em`) e pausa sozinha ao estourar ou ao tomar 656. |
| A distribuição entrega documentos dos **últimos ~3 meses** (retroativo de 90 dias). | Documentos mais antigos que isso precisam de outra fonte; o sistema avisa em vez de ficar varrendo o vazio. |
| Na **NF-e emitida** pela própria empresa, a distribuição não entrega os seus documentos (só quem participa: destinatário, transportadora…). | A aba "Prestadas" pode ficar vazia **e isso é correto**. O emitente consulta a própria SEFAZ autorizada. |
| Lote do ADN: no máximo **50 DF-e / 1 MB** por chamada; `ultNSU == maxNSU` significa "em dia". | A varredura continua página a página até `proximo >= maxNSU`, com espera entre páginas; chegar no `maxNSU` fecha o ciclo como **em dia**. |
| Consultar o mesmo CNPJ com dois sistemas ao mesmo tempo causa corrida de NSU. | `lease` (`travado_em`, 25 min) por empresa+tipo: duas varreduras nunca rodam juntas, e um worker que morre no meio não trava a fila para sempre. |

## 2. O ciclo de uma execução

```
POST /importacoes  ──►  fila.enfileirar
                          ├─ sem certificado         → 409 (e o que falta)
                          ├─ sem UF                  → 409
                          ├─ já em andamento         → 202 com a mesma execução (idempotente)
                          └─ dentro da janela        → 429 com "retoma às HH:MM"

worker importar_documentos(empresa_id, tipo, execucao_id)
  ├─ trava (lease) ───────────────────────────────► duas varreduras nunca se atropelam
  ├─ respeita a janela, salvo forcar=true
  ├─ loop de páginas (até max_lotes_por_execucao), com espera mínima entre requisições
  │    ├─ consulta loteDistDFe com ultNSU = nosso cursor
  │    ├─ grava documentos + eventos ── COMMIT por lote (checkpoint)
  │    ├─ avança o cursor para o ultNSU devolvido (nunca regride)
  │    └─ para quando proximo_nsu >= max_nsu
  ├─ em dia? → marca cooldown de 1h e encerra CONCLUIDA
  └─ cStat 656? → AGUARDANDO (não é erro), bloqueio registrado,
                  continuação reagendada para depois da janela
```

Pontos que valem a pena saber de cor:

- **Commit por lote.** Se a página 7 falhar, as 6 primeiras continuam no banco e
  o cursor já aponta para onde parar. Nada é reimportado nem perdido.
- **`AGUARDANDO` ≠ `ERRO`.** A tela mostra "Aguardando a SEFAZ · tenta sozinha
  22:38". Ninguém precisa fazer nada. O `_erro_656` vermelho do passado virou
  estado operacional normal.
- **Retomada pela mesma execução.** O reagendamento reusa `execucao_id`, então o
  histórico continua uma linha legível por varredura, com `tentativas`.
- **Teto de páginas por execução** (`max_lotes_por_execucao`). Ao bater no teto,
  a task se reagenda em vez de segurar o worker — importante em CNPJs com
  milhares de documentos acumulados.
- **A fila não duplica trabalho:** `task_acks_late` + `visibility_timeout` bem
  maior que qualquer countdown + `worker_prefetch_multiplier=1`.

## 3. O agendador (modo "não faço nada")

`celery beat` roda duas tasks:

| Task | Frequência | O que faz |
| --- | --- | --- |
| `sincronizar_tudo` | `SINCRONISMO_INTERVALO_MINUTOS` (5) | Retoma execuções `AGUARDANDO` vencidas e enfileira as empresas do modo automático, em **round-robin** por `ultima_consulta_em` (mais antigo primeiro), sem repetir empresa+tipo já em andamento. |
| `completar_xmls_pendentes` | `COMPLETAR_XMLS_A_CADA_HORAS` (6) | Busca pelo XML completo (`consChNFe`) os documentos que chegaram só em `resumo`, respeitando a cota de 20/h por CNPJ e parando em 656. |

Precisa de **exatamente uma** instância de `beat` (não escale este serviço).
Sem o `beat`, o sistema continua correto: só volta a depender de clique.

O round-robin é o que faz 30 empresas evoluírem juntas: cada tick pega as
empresas cuja janela venceu há mais tempo, na ordem em que estão prontas —
ninguém fica "preso atrás" de um CNPJ grande, e cada CNPJ mantém o intervalo
de 1h independentemente do número de empresas no escritório.

## 4. Competência (mês) — o que ela faz e o que ela não faz

- **Ela não filtra a descarga.** A SEFAZ só anda por NSU. Filtrar a consulta por
  mês é a receita para perder nota (e para tomar 656 tentando "pular" o cursor).
- **Ela filtra contagem, tela, ZIP e relatório.** Cada documento guarda a
  `competencia` declarada no próprio XML (`dComp`/`dhEmi`), indexada; o mês da
  tela é um `WHERE`, não uma requisição nova.
- **Ela entra na execução** (`data_inicio`/`data_fim`) para o histórico dizer
  "essa varredura foi pedida para 08/2026" e contar `documentos_no_periodo`.
- Formatos aceitos: `08/2026`, `8/2026`, `2026-08`, `ago/2026`, `082026`,
  `202608`, ou uma data completa (o mês dela vale). Entrada inválida responde
  422 com o formato esperado — nunca "mês 0".

## 5. Download em massa

`GET /documentos/exportar` aceita os **mesmos** filtros da listagem
(`empresa_ids`, `tipo`, `direcao`, `status`, `leiaute`, `competencia`,
`data_inicio`/`data_fim`, `busca`, `documento_ids`) e devolve:

```
NotasFlow/<empresa-slug>/<tipo>/<tomada-ou-prestada>/<chave>.xml
NotasFlow/relacao.csv      ; e BOM — abre direto no Excel brasileiro
NotasFlow/LEIA-ME.txt      o que o pacote contém e o que falta
```

- O ZIP nasce de um `SELECT` único (`.yield_per(200)`), não de N requests: um
  pacote com 20.000 XMLs não custa 20.000 chamadas de API.
- `LIMITE_DOCUMENTOS_POR_EXPORTACAO` (25.000) vira **413 com explicação** em vez
  de um download que estoura o navegador.
- `GET /documentos/exportar/estimativa` devolve a contagem e o tamanho estimado
  **antes** do clique, para a tela poder avisar "são 4.213 arquivos, ~24 MB".
- Como a listagem, o resumo e o ZIP compartilham a mesma função de filtro,
  o número da tela bate com o número de arquivos.

## 6. Ajustes que dá para fazer sem tocar em código

| Variável | Padrão | Quando mexer |
| --- | --- | --- |
| `SINCRONISMO_INTERVALO_MINUTOS` | 5 | Tick do agendador. Não precisa ser menor que 1h — a janela manda. |
| `SINCRONISMO_LOTE_EMPRESAS` | 20 | Quantas empresas um mesmo tick pode enfileirar (escritórios grandes sobem isso). |
| `COOLDOWN_HORAS` | 1 | Só para ambiente de homologação mais permissivo. **Não reduza em produção.** |
| `MARGEM_COOLDOWN_MINUTOS` | 6 | Folga além da hora oficial, para relógio desencontrado e latência. |
| `LIMITE_CONSULTAS_PONTUAIS_POR_HORA` | 20 | Teto do `consNSU`/`consChNFe`. |
| `ESPERA_ENTRE_LOTES_SEGUNDOS` | 2 | Intervalo entre páginas da mesma varredura (recomendação da NT). |
| `MAX_LOTES_POR_EXECUCAO` | 50 | Quantas páginas antes de se reagendar. |
| `COMPLETAR_XMLS_A_CADA_HORAS` | 6 | Frequência do gap-fill de XML. |
| `LIMITE_DOCUMENTOS_POR_EXPORTACAO` | 25000 | Teto do ZIP. |
| `SINCRONISMO_AUTOMATICO` | true | `false` = só consulta manual (útil em homologação). |

## 7. Sintomas e diagnóstico

| Sintoma na tela | O que está acontecendo | O que fazer |
| --- | --- | --- |
| "Aguardando a SEFAZ · bloqueada até HH:MM" | 656 real, janela em curso | Nada. Vai retomar sozinha. Verifique se outro sistema/planilha usa o mesmo CNPJ. |
| `pendencia` alta que não cai | CNPJ com muito documento acumulado; o round-robin está distribuindo as horas | Espere os ciclos; ou suba `MAX_LOTES_POR_EXECUCAO`. |
| "só resumo" em muitas NFe | O `procNFe` chega numa página seguinte da distribuição | O gap-fill cuida; `POST /documentos/completar-xmls` acelera (dentro da cota). |
| Prestadas vazio para NFe | A distribuição não entrega os documentos do próprio emitente | Normal. Emitente consulta a SEFAZ autorizadora. |
| ZIP responde 413 | Filtro maior que o teto | Afine por empresa ou mês; o teto é configurável. |
| Mês antigo não aparece | Documento anterior aos ~3 meses disponíveis na distribuição | Reimportar não resolve; a fonte é a empresa/contador. |
| “⚠ N dias sem varrer com documento faltando” na tela | `dias_sem_varrer ≥ DIAS_DISPONIVEIS_NA_DISTRIBUICAO` com pendência aberta: a janela de recuperação está fechando | Rode a varredura dessa empresa o quanto antes (a fila prioriza sozinha); o que passou dos ~3 meses pode já ter saído da distribuição. |
