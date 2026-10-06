# Sincronização com a SEFAZ — as regras do jogo e como o Fluxa cumpre cada uma

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
| Depois de “nenhum documento novo” (137) ou de atingir `maxNSU`, **aguarde a janela oficial antes de iniciar outra varredura**. Consultar antes devolve **cStat 656 – Rejeição: Consumo Indevido**. | O cooldown não é "gentileza", é contrato. O Fluxa marca `proxima_consulta_em` ao esgotar a distribuição e **não dispara nada** dentro da janela — nem clique manual, nem agendador. |
| **Repetir a consulta antes de 1h zera o cronômetro do bloqueio.** | Por isso o botão "forçar" existe, mas é explícito (`forcar=true`) e fica registrado na execução. Clicar de novo "para ver se já deu" é exatamente o que trava o CNPJ. |
| A devolução 656 **também traz `ultNSU` e `maxNSU`**. | No bloqueio o sistema **realinha o cursor** com o `ultNSU` devolvido: é o que resolve o caso "outro sistema consultou este CNPJ e o nosso cursor ficou para trás". |
| `distNSU` anda **em sequência ascendente**; não existe filtro por data. | A competência (mês) **não** pode ser usada como recorte de busca: baixar tudo e filtrar no banco é o que garante que nada se perca. |
| `consNSU` / `consChNFe` (consulta pontual) têm teto de **20 consultas por hora por CNPJ**. | O preenchimento dos XMLs que vieram só em resumo roda com cota controlada (`consultas_pontuais` + `janela_pontual_em`) e pausa sozinha ao estourar ou ao tomar 656. |
| A distribuição entrega documentos dos **últimos ~3 meses** (retroativo de 90 dias). | Documentos mais antigos que isso precisam de outra fonte; o sistema avisa em vez de ficar varrendo o vazio. |
| Na **NF-e emitida** pela própria empresa, a distribuição não entrega os seus documentos (só quem participa: destinatário, transportadora…). | A aba "Prestadas" pode ficar vazia **e isso é correto**. O emitente consulta a própria SEFAZ autorizada. |
| Lote do ADN: no máximo **50 DF-e / 1 MB** por chamada; `ultNSU == maxNSU` significa "em dia". | A varredura continua página a página até `proximo >= maxNSU`, com espera entre páginas; chegar no `maxNSU` confirma o fim da distribuição, mas **em dia** exige também não haver lote recebido ilegível. Uma página curta não prova que a fila acabou. |
| Consultar o mesmo CNPJ com dois sistemas ao mesmo tempo causa corrida de NSU. | `lease` (`travado_em`, prazo maior que o hard timeout, renovado por lote) por empresa+tipo: duas varreduras nunca rodam juntas, e um worker que morre no meio não trava a fila para sempre. |

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
| `completar_xmls_pendentes` | `COMPLETAR_XMLS_A_CADA_HORAS` (1) | Registra a **Ciência da Operação** (210210) nas empresas com `manifestar_automaticamente` e, em seguida, busca o XML completo (`consChNFe`) das notas em `resumo` — respeitando a cota de 20/h por CNPJ e parando em 656. A fila é ordenada por urgência (a Ciência só vale 10 dias) e espaça a repetição da mesma nota (`tentativas_completar`, 2^n-1 até 24 h) para a cota não ser gasta nas mesmas chaves. Notas já recusadas (`manifestacao_erro`) saem da fila — inclusive o **596**, cuja saída é a manifestação conclusiva, não uma nova tentativa. |

Precisa de **exatamente uma** instância de `beat` (não escale este serviço).
Sem o `beat`, o sistema continua correto: só volta a depender de clique.

O round-robin é o que faz 30 empresas evoluírem juntas: cada tick pega as
empresas cuja janela venceu há mais tempo, na ordem em que estão prontas —
ninguém fica "preso atrás" de um CNPJ grande, e cada CNPJ mantém o intervalo
de 1h independentemente do número de empresas no escritório.

## 4. Período — obrigatório, e por quê

O período é **um intervalo de datas e é obrigatório** em toda consulta ao acervo
(`/documentos`, `/documentos/resumo`, `/documentos/por-empresa`,
`/documentos/exportar`) e em todo pedido de importação (`POST /importacoes`,
`/importacoes/lote`, `/importacoes/selecionadas`). Sem ele a resposta é **422**
com a frase do formato aceito. A única exceção é a exportação por
`documento_ids`: ali o operador já escolheu nota a nota.

- **A data que vale é a data de emissão.** Uma regra só, em
  `app/services/referencia.py`, usada pela listagem, pelo resumo, pelo ZIP, pelo
  dashboard, pelo fechamento e pela gravação no worker. Antes cada lugar usava
  `coalesce(competencia, data_emissao)`, e como a `competencia` declarada no XML
  é opcional e costuma trazer o mês anterior (serviço de julho faturado em
  agosto), pedir "agosto" devolvia julho e junho junto — era o bug de "o filtro
  não funciona".
- **A descarga continua por NSU e nada é descartado.** A SEFAZ/ADN não aceita
  recorte por data; pular cursor é receita para perder nota e para tomar 656.
  Baixa-se tudo o que a fila tiver e **tudo é gravado**. O período vira recorte
  de relatório: o que cai fora dele é contado em
  `ExecucaoImportacao.documentos_fora_do_periodo` e sai no aviso da execução
  ("3 documento(s) vieram fora do período 08/2026 e foram guardados assim
  mesmo"); o recorte que o operador vê acontece nos filtros de tela.

  Até a v3.1 a nota fora do período era descartada **e o cursor avançava assim
  mesmo**. Como o cursor não regride e o ambiente não reapresenta NSU
  consumido, aquele documento sumia para sempre. O sintoma clássico era uma
  empresa recém-cadastrada: captura com HTTP 200, cursor de 0 ao máximo,
  "nada para ler" e acervo vazio. Entre guardar um mês que ninguém pediu e
  perder nota fiscal de forma irreversível, guardar é o erro barato.
- **Rebobinar o cursor** (`POST /importacoes/rebobinar`) é o caminho de volta
  para quem já perdeu documentos assim: manda o NSU para trás e libera a
  consulta na hora. É a única porta manual que pode regredir o cursor —
  revarrer gasta cota do ambiente, então não é operação de rotina; notas já
  existentes são reconhecidas pela chave e não duplicam.
- **Documento sem data legível é mantido**, não descartado: na dúvida, guardar é
  reversível; perder nota não é.
- **Precedência:** `data_inicio`/`data_fim` vencem `competencia`. A
  `competencia` continua aceita como atalho para o mês fechado, mas o frontend
  sempre manda o par de datas — uma forma só, sem ambiguidade.
- Formatos aceitos nas datas: `DD/MM/AAAA` e `AAAA-MM-DD`. Na competência:
  `08/2026`, `8/2026`, `2026-08`, `ago/2026`, `082026`, `202608`, ou uma data
  completa (o mês dela vale). Entrada inválida responde 422 com o formato
  esperado — nunca "mês 0". Data inicial depois da final também é 422, dizendo
  para inverter as duas.

## 5. Download em massa

`GET /documentos/exportar` aceita os **mesmos** filtros da listagem
(`empresa_ids`, `tipo`, `direcao`, `status`, `leiaute`, `data_inicio`/`data_fim`
— obrigatórios salvo com `documento_ids` —, `competencia`, `busca`) e devolve:

```
Fluxa/<empresa-slug>/<tipo>/<chave>.xml   ; SÓ XML de nota
Fluxa/_sem-xml-completo/<empresa>/<tipo>/<chave>.xml  ; só com incluir_incompletos=true
Fluxa/relacao.csv      ; e BOM — abre direto no Excel brasileiro
Fluxa/pendencias.csv   ; o que ficou de fora, com motivo e o que fazer
Fluxa/LEIA-ME.txt      o que o pacote contém e o que falta
```

### Por que a pasta da empresa leva só XML de nota

O pacote é o que vai para o sistema contábil. Enquanto `resNFe`/`protNFe`
entravam na mesma pasta das NF-e, todos com o nome `<chave>.xml`, o importador
respondia **"isto é uma autorização de nota"** no meio de um lote — e ninguém
tinha como saber qual arquivo era o culpado sem abrir um por um.

A decisão é pelo **conteúdo** do arquivo (`app/services/xml_integridade`), não
pelo cadastro: no legado existe linha marcada `leiaute = "completo"` com um
`resNFe` no disco, herança do `consChNFe` que devolvia resumo. Confiar no
cadastro aqui é reproduzir o defeito.

- entra na pasta da empresa: XML com `infNFe` / `infCTe` / `infNFSe`;
- `resumo`, `protocolo`, `evento`, `metadados-sem-xml` e
  `arquivo-ausente-no-disco` ficam de fora e viram linha em `pendencias.csv`,
  com `motivo` e `o_que_fazer` (o 596 diz "Manifestar operação", o resto diz
  "Buscar XML completo");
- `relacao.csv` continua listando **tudo** do filtro, com a coluna
  `xml_completo` dizendo a verdade (`sim`, `so-resumo`, `metadados-sem-xml`,
  `arquivo-ausente-no-disco`);
- `incluir_incompletos=true` (checkbox no diálogo de exportação) grava os
  incompletos em `Fluxa/_sem-xml-completo/` — **nunca** misturados com as notas.

- O ZIP nasce de um `SELECT` único (`.yield_per(200)`), não de N requests: um
  pacote com 20.000 XMLs não custa 20.000 chamadas de API.
- `LIMITE_DOCUMENTOS_POR_EXPORTACAO` (25.000) vira **413 com explicação** em vez
  de um download que estoura o navegador.
- `GET /documentos/exportar/estimativa` devolve a contagem, o tamanho estimado e
  `sem_xml_completo` **antes** do clique, para a tela poder avisar "são 4.213
  arquivos, ~24 MB, e 140 não vão entrar no pacote". A contagem de
  `sem_xml_completo` vem do cadastro (a estimativa não lê arquivos); a verdade
  definitiva é a `pendencias.csv` do pacote.
- Como a listagem, o resumo e o ZIP compartilham a mesma função de filtro,
  o número da tela bate com o número de arquivos.
- A auditoria (`exportacao_zip`) registra quantas notas entraram e quantas
  pendências ficaram: é o que responde depois a pergunta "por que o lote de
  09 faltou nota?".


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
| `COMPLETAR_XMLS_A_CADA_HORAS` | 1 | Frequência da rodada de Ciência da Operação + gap-fill de XML. |
| `LIMITE_DOCUMENTOS_POR_EXPORTACAO` | 25000 | Teto do ZIP. |
| `SINCRONISMO_AUTOMATICO` | true | `false` = **desagenda de verdade** as tasks de consulta à SEFAZ (ver seção 8). |

## 7. Sintomas e diagnóstico

| Sintoma na tela | O que está acontecendo | O que fazer |
| --- | --- | --- |
| "Aguardando a SEFAZ · bloqueada até HH:MM" | 656 real, janela em curso | Nada. Vai retomar sozinha. Se outro sistema (ex.: Jettax360) consulta o mesmo CNPJ/certificado, é isso — veja a seção 8. |
| `pendencia` alta que não cai | CNPJ com muito documento acumulado; o round-robin está distribuindo as horas | Espere os ciclos; ou suba `MAX_LOTES_POR_EXECUCAO`. |
| "só resumo" em muitas NFe | **Falta a Ciência da Operação.** Enquanto o destinatário não se manifesta, o Ambiente Nacional só distribui o `resNFe` — e o `consChNFe` também volta vazio (NT 2014.002). Não é página seguinte nem cota. | Confira "Manifestação automática" da empresa (vem ligada por padrão). Depois da Ciência o `procNFe` chega pelo próprio fluxo de NSU e substitui o resumo. O detalhe do documento mostra se a Ciência foi registrada ou o motivo da recusa. |
| "A Ciência da Operação não é mais aceita para esta nota" (cStat 596) | A nota passou dos **10 dias** da autorização: a Ciência não é mais aceita e não existe XML completo por essa via | Use **Manifestar operação** na ficha da nota e escolha o evento conclusivo (Confirmação da Operação, se a mercadoria foi recebida). É ato de negócio: o robô não decide. Depois do evento a busca do XML completo volta sozinha. |
| Prestadas vazio para NFe | A distribuição não entrega os documentos do próprio emitente | Normal. Emitente consulta a SEFAZ autorizadora. |
| ZIP responde 413 | Filtro maior que o teto | Afine por empresa ou mês; o teto é configurável. |
| Mês antigo não aparece | Documento anterior aos ~3 meses disponíveis na distribuição | Reimportar não resolve; a fonte é a empresa/contador. |
| “⚠ N dias sem varrer com documento faltando” na tela | `dias_sem_varrer ≥ DIAS_DISPONIVEIS_NA_DISTRIBUICAO` com pendência aberta: a janela de recuperação está fechando | Rode a varredura dessa empresa o quanto antes (a fila prioriza sozinha); o que passou dos ~3 meses pode já ter saído da distribuição. |

## 8. Outro sistema capturando (ex.: Jettax360) — desligar e importar por XML

**O problema.** Dois sistemas consultando a Distribuição DF-e com o **mesmo
certificado/CNPJ** se travam mutuamente: a SEFAZ devolve **656 (consumo
indevido)** e bloqueia o certificado por ~1 hora — para os dois. Não é defeito
de nenhum dos lados; é o protocolo da SEFAZ: um capturador por certificado.

**A decisão.** Só um sistema fica com a consulta. Se for o outro (Jettax360),
o Fluxa para de consultar **de verdade** e passa a receber as notas como
arquivo:

1. No `.env` (ou ambiente do Docker Compose):
   `SINCRONISMO_AUTOMATICO=false`
2. Reinicie o serviço do worker/beat (`docker compose up -d` novamente, ou
   `docker compose restart worker beat`). As tasks `sincronizar-tudo` e
   `completar-xmls-pendentes` saem da agenda — não rodam "vazias", não
   aparecem no log e não competem pela janela de consumo.
3. As notas chegam por **Importações → Importar XMLs do computador**
   (`POST /importacoes/xml`): um `.zip` exportado do outro sistema ou os
   `.xml` soltos. Não gasta cota da SEFAZ — a nota é lida do próprio arquivo,
   com os mesmos conversores das fontes oficiais, e gravada sem duplicar.

**Como o upload casa as notas.** Pelo CNPJ do destinatário (nota tomada) ou
do emitente (nota prestada). CNPJ fora do cadastro volta como item "Sem
empresa" — nada é importado para a empresa errada. Até 200 XMLs por lote,
cada XML de até 2 MB, ZIP de até 100 MB. NF-e e CT-e completos e NFS-e do
leiaute nacional são aceitos; outro formato volta como "Não reconhecido".

**Para voltar atrás.** `SINCRONISMO_AUTOMATICO=true` + reiniciar. Nada foi
removido: os cursores, as janelas e o histórico continuam onde estavam, e a
primeira varredura realinha o cursor com o `ultNSU` que a SEFAZ devolver.


## Do `resNFe` ao `procNFe` — a regra do protocolo (e onde o código a cumpre)

**Por que a "nota" que chegava era só o resumo.** Para NF-e em que a empresa é
**destinatária**, o Ambiente Nacional distribui apenas o `resNFe` — chave,
emitente, valor e protocolo, sem item, imposto ou total — até que o
destinatário registre a **Ciência da Operação** (evento 210210). Não é falha de
paginação nem de cota: a **consulta pontual pela chave (`consChNFe`) obedece à
mesma checagem** e também devolve só o resumo (NT 2014.002). O documento
integral (`procNFe`) é liberado depois do evento, pelo fluxo de NSU e/ou pela
consulta por chave. Emitente não recebe os próprios documentos por essa via;
transportador/`autXML` recebem sem manifestar — nenhum dos dois é o caso do
acervo do escritório.

**O que o sistema faz sozinho.** `completar_xmls_pendentes` (Beat, 1×/h, ou o
botão "Completar XMLs") registra a Ciência com o A1 da empresa e, na sequência,
consulta a chave. O XML completo normalmente aparece em minutos, mas pode levar
mais de 24 h — por isso a nota fica na fila e volta espaçada, sem gastar as 20
consultas/h do CNPJ nas mesmas chaves.

**Quando os 10 dias passaram.** A Ciência só é aceita até **10 dias** contados
da autorização (Ajuste SINIEF 44/20 / NT 2020.001): depois disso a SEFAZ devolve
**596** e o robô para — não é erro a ser retentado, é mudança de caminho. A
saída são as manifestações **conclusivas**: Confirmação da Operação (210200),
Desconhecimento (210220) e Operação não Realizada (210240). As duas últimas
exigem justificativa de 15 a 255 caracteres; **Desconhecimento não devolve o XML
completo** (por regra) e Confirmação impede o emitente de cancelar a nota — por
isso quem escolhe é o operador, na ficha da nota (**Manifestar operação**). O
prazo para o evento conclusivo é de **90 dias** (Ajuste SINIEF 14/2026; eram
180); sem nenhum evento, a operação é tida como tacitamente confirmada.

**As três camadas que impedem o acervo de mentir.** O resumo ja foi gravado no
lugar da nota e o registro marcado como "completo" — o que tirava a nota da fila
para sempre. Agora: (1) o importador classifica **pelo conteúdo** (não pelo nome
do schema) e só documento integral vira/sobrescreve a nota; (2) `_sobrescrever_xml`
recusa qualquer payload que não traga `infNFe`/`infCTe`/nota NFS-e; (3) no boot,
`_rebaixar_xmls_incompletos()` relê os arquivos e devolve à fila o que estava
marcado completo com resumo no disco — e `xml_integridade.rebaixar_divergentes()`
faz o mesmo sob demanda. O relatório de exportação (`xml_completo`) também passa
a classificar o arquivo, não o cadastro: nunca mais diz `sim` para um `resNFe`.


## Revisão de captura e recuperação — 02/10/2026

Consulte [a revisão completa](REVISAO_IMPORTACAO_2026.md) para os defeitos
corrigidos, testes executados e limites da verificação.

- Respostas de lotes ficam em `DADOS_DIR/xml/.lotes_pendentes` até o commit
  completo e sem falha. Esse diretório pertence ao volume persistente de XML
  compartilhado pela API/worker e entra no backup existente.
- Itens ilegíveis não são mais descartados silenciosamente com avanço de NSU.
  São sinalizados como **Importação parcial**, e podem ser reprocessados
  localmente sem consultar o mesmo NSU outra vez.
- Com A1 válido e janela aberta, a pendência antiga não impede a captura de
  notas novas. Sem A1 ou com janela fechada, a recuperação pode rodar só local.
- `lotes_pendentes > 0` impede o selo de completude e a liberação do fechamento,
  mesmo quando cursor e máximo sejam iguais.
- A fila conta o teto por empresas que realmente foram enfileiradas; quem está
  sem A1 ou em cooldown não ocupa o lugar de um cliente elegível.
- XML manual completo promove uma nota em resumo. ZIPs homônimos são lidos
  individualmente, e falhas de um item não desfazem outros XMLs válidos.

Não foram realizadas consultas reais com certificado do escritório nesta
revisão. Para confirmar um caso operacional, use o ID da execução, tipo,
horário, mensagem/cStat e filtros do acervo — nunca envie o A1/senha no chat.
