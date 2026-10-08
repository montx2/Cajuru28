# Prompt de reconstrução do front-end — Fluxa 2.0

> **Como usar este documento:** ele é um prompt completo e autossuficiente. Entregue-o inteiro,
> junto de `design/SISTEMA.md`, para o engenheiro ou agente que vai executar a reconstrução.
> Não resuma, não parafraseie, não "melhore" as regras — elas foram calibradas sobre uma
> auditoria real do código que está no repositório hoje (122 arquivos TS/TSX, 20.440 linhas).
> A específicidade é proposital: prompt genérico produz interface genérica.

---

## 0. Seu papel

Você é o engenheiro de produto dono do front-end do **Fluxa** — o sistema de captura fiscal de
um escritório de contabilidade. Você vai reconstruir a camada de interface **de novo**, do shell
às telas, sem quebrar o contrato com a API e sem violar o sistema visual **Papel & Grafite**.

Você não é um "redesigner criativo". Você é um **editor**. O produto já existe, já tem clientes,
já roda em produção. Seu trabalho é cortar, reordenar e calar — não inventar. A cada decisão,
pergunte: *isso ajuda a pessoa que opera a fechar o mês, ou só ocupa tela?* Se a resposta for a
segunda, corte.

Três critérios, nesta ordem, vêm do sistema visual e não são negociáveis:
**silencioso, preciso, confiável.**

---

## 1. O produto e quem opera

- **O que é:** captura automática de documentos fiscais (NFS-e nacional, NF-e, CT-e) pela
  SEFAZ/ADN com certificado A1, organização por empresa e competência, e exportação para o
  sistema contábil (Unico).
- **Quem opera:** 1 a 3 pessoas de um escritório contábil, o dia inteiro, em telas abertas por
  horas. Não é demo, não é vitrine, não é landing page. É instrumento de trabalho contínuo.
- **Escala:** centenas de empresas, milhões de documentos. Toda decisão de UI passa por isso.
- **O trabalho real do operador, em ordem:** (1) conferir que a máquina está saudável;
  (2) resolver o que pede decisão humana — certificado vencido, execução com erro, empresa sem
  captura; (3) exportar o mês e conferir o fechamento; (4) ocasionalmente: cadastrar empresa,
  trocar certificado, importar XML de fora, olhar auditoria.

Se o operador faz a ação (1) vinte vezes por dia e a (4) uma vez por mês, a interface reflete
essa frequência: (1) e (2) são o topo de tudo; (4) mora em menus discretos.

---

## 2. Estado atual — auditoria (o ponto de partida é este, não zero)

O front-end já passou por uma reconstrução integral ("Papel & Grafite", 108 arquivos). Ela foi
boa: tokens medidos, WCAG AA documentada, teclado, URL como estado, zero dependência nova.
**Não jogue isso fora.** O que segue é o que a auditoria encontrou de errado — é o backlog
desta reconstrução.

### 2.1 Manter como está (já está certo)

- Arquitetura de pastas e fronteira servidor/cliente (`page.tsx` servidor + tela cliente).
- `lib/api.ts` e `lib/types.ts` como contrato único — **nenhuma tela escreve `fetch`**.
- URL como fonte de verdade de filtro/período; `localStorage` só preferência.
- Os hooks do produto (`useRecurso`, `usePolling`, `useCamada`, `useFocoPreso`, `usePreferencia`,
  `ProvedorAgora`).
- Paleta medida, um acento, três níveis de elevação, sem `shadow-*` real, sem `rounded-*` real.
- Tabela virtualizada com os quatro estados e refetch que não pisca.
- Paleta de comandos `Ctrl/⌘K`, atalhos `g`+letra, `j`/`k`/`x`, `/`, `?`.
- Acessibilidade WCAG 2.2 AA inteira (§10 do SISTEMA.md) — é piso, não meta.

### 2.2 Corrigir — hierarquia

- **Painel (`app/dashboard/Painel.tsx`, 458 linhas):** a ação primária do topo é
  "Disparar importação" — mas a captura é automática e roda em janelas oficiais; disparar à mão
  é exceção, não o gesto principal. O produto inclusive desencoraja consulta fora da janela.
  A ação primária de uma home operacional é **resolver pendências**, não disparar máquina.
- **Ordem de leitura do Painel:** hoje KPIs → gráficos → atenção → execuções. O operador quer:
  saúde → **o que preciso decidir** → números do mês → infra (último). "Precisa da sua atenção"
  e "Execuções agora" precisam subir acima dos gráficos decorativos ("Evolução", "Documentos
  por tipo", "Maiores emitentes" descer).
- **Importações (`Importacoes.tsx`, 615 linhas):** o cartão "Importar notas por XML" (o caminho
  manual, de arquivos exportados de outro sistema) renderiza **acima** do fluxo principal
  numerado ("1 · Período e tipos", "2 · Empresas"). O caminho secundário apareceu antes do
  principal — hierarquia invertida no primeiro scroll da tela.
- **Documentos (`Documentos.tsx`):** 12 botões na mesma superfície. Exportar XML, Exportar CSV,
  Importar, Completar XMLs, exclusão em lote, filtros, colunas, densidade… tudo visível o tempo
  todo. Nenhuma ferramenta real de mesa de operação tem 12 alvos simultâneos de mesma altura.

### 2.3 Corrigir — ruído e excesso

- **Empresas:** 9 botões. Importação em massa de certificados + importação XML + consulta CNPJ
  + novo cadastro + ações por linha competem na mesma altura visual.
- **Passos numerados** ("1 ·", "2 ·") em tela que é operada todo dia: numeração ensina na
  primeira semana e vira ruído na centésima. Um formulário bem ordenado não precisa de passos.
- **Títulos de cartão que repetem o óbvio** ("Estado do sincronismo" num cartão da tela
  Importações). Quando a tela só tem um assunto, o `CabecalhoPagina` já disse ele.
- **Igualdade visual entre o rotineiro e o raro:** "Importar lote", "Importar XML", "testar
  webhook", "executar backup" têm o mesmo peso visual de "Exportar o mês".

### 2.4 Corrigir — integrações externas expostas demais

Audição de onde o caminho "de fora" aparece hoje:

| Local | Hoje | Problema |
|---|---|---|
| `Importacoes.tsx:381` | `<ImportarXmls />` como cartão inteiro no topo da tela | É o caminho de exceção (nota que veio de outro sistema) com o melhor lugar da tela |
| `ImportarXmls.tsx` ("Importar notas por XML") | Cartão + drag-and-drop sempre visível | Idem |

**Diretiva:** importação de fora é o **rodapé da hierarquia**, não o topo. Ver §7.

### 2.5 Corrigir — manutenção de verdade

- `package.json` ainda diz `notasflow-frontend`; o produto se chama Fluxa em 27 arquivos.
  Unifique: o `name` vira `fluxa-frontend`.
- Comentários que descrevem a paleta antiga (ex.: "verde do carimbo" em `Botao.tsx`) já foram
  corrigidos na última rodada — reconfira durante a reescrita; comentário errado é bug de
  documentação.

---

## 3. A lei visual — Papel & Grafite em uma página

`design/SISTEMA.md` é a autoridade. O resumo abaixo é o que você vai tocar todo dia; divergência
entre este resumo e o SISTEMA.md, o SISTEMA.md vence.

- **Cor:** um acento (índigo `--acento`) e cinco semânticas (`ok`, `espera`, `erro`, `info`,
  grafite). Nenhum hex em componente. Estado = ícone + palavra + cor, nunca só cor. Espera
  oficial da SEFAZ é âmbar, nunca vermelho.
- **Tipografia:** Inter + JetBrains Mono (self-hosted). Escala `2xs`→`2xl`, `text-sm` padrão de
  dados densos, nada útil abaixo de 12 px. Pesos 400/500/600 — a config trava os outros.
  Números sempre tabulares, alinhados à direita em coluna.
- **Forma:** espaçamento múltiplo de 4; raios 4/6/8/12; elevação em três níveis semânticos
  (0 = borda; `nivel1` = camada flutuante; `nivel2` = modal). Cartão não levanta no hover.
- **Movimento:** 120/180/240 ms, só `opacity` e `transform`. Sem entrada de página. Dois
  movimentos contínuos, ambos significando trabalho: `pulso` e `progresso`.
- **Estados:** carregando (esqueleto que reproduz a tela real), vazio (instrução + próxima
  ação), vazio-com-filtro (outro desenho), erro (o que aconteceu, por quê, o que fazer),
  conteúdo. Refetch não pisca.
- **O que não existe aqui (§16 do SISTEMA.md):** emoji · copy de marketing · segundo acento ·
  KPI com ícone em círculo pastel · hero section · ilustração de vazio · `window.confirm` ·
  peso 700+ · card que levanta no hover · cor sem significado · botão sem verbo · erro sem
  próximo passo · gradiente/sombra colorida fora do vidro controlado.

**A exceção do vidro (§17)** permanece exatamente como está: Header, Sidebar e camadas
flutuantes. Não expanda o vidro para superfície de leitura.

---

## 4. Padrões colhidos de produtos reais — e o que cada um vira aqui

Estes padrões vêm de produtos que são referência mundial de interface de operação — Linear,
Stripe, Ramp, Attio, Mercury — traduzidos em regras executáveis para o Fluxa. **Copie o
padrão de interação, nunca a pele** — "clone do Linear" é tão genérico quanto template de IA.

1. **Linear — o teclado é o primeiro cidadão.** Toda ação comum tem atalho; a paleta
   `Ctrl/⌘K` é o caminho universal. No Fluxa: a paleta já existe — **alimente-a com as ações
   de superfície que você esconder** (§6). Botão que some do tela vira comando da paleta com
   `hint` de atalho. Nada se perde, tudo se aquieta.
2. **Linear — densidade com ritmo.** Linhas de tabela 40–44 px, mesma cadência em lista e
   formulário. No Fluxa: um único ritmo de linha por tela; não misturar linha de 32 com cartão
   de 200 na mesma coluna visual.
3. **Linear — estado vazio com uma frase.** Uma sentença seca, sem ilustração, sem festa.
   O Fluxa já faz (`EstadoVazio`); reprove qualquer copy que "comemore" o vazio.
4. **Stripe — divulgação em camadas.** O topo mostra os três números que importam; cada
   camada adicional exige um clique intencional. No Fluxa: o Painel mostra saúde + pendências +
   3 KPIs; gráficos, rankings e infra ficam um clique abaixo (aba, painel lateral ou seção
   recolhida).
5. **Stripe — número com contexto.** Todo número carrega a comparação que o interpreta:
   "−8% vs. mês anterior", "de 214 empresas". No Fluxa: cada KPI do Painel ganha delta da
   competência anterior (o backend já devolve o histórico de 12 meses — `evolucao`).
6. **Stripe — hierarquia antes do visual.** Decida o que se vê primeiro, segundo, terceiro,
   **antes** de desenhar. Uma tela com tudo enfatizado não enfatiza nada.
7. **Ramp — tamanho é hierarquia.** No bento do Ramp, o tamanho do bloco codifica a
   prioridade. No Fluxa: o cartão de pendências é o maior bloco do Painel; infra é o menor.
8. **Attio — menu contextual em vez de barra de botões.** Ações raras moram no `⋮` da linha
   ou da tabela. No Fluxa: exclusão, recibo, completar XML de uma nota, recarregar — tudo no
   menu da linha; a barra do topo fica com uma ação primária e nada mais.
9. **Mercury/Stripe — dinheiro com tipografia de precisão.** Valor monético em tabular,
   negativo e cancelado tratados pelo `ValorMoeda`, sem cor decorativa.
10. **O teste do "sem tour"** (o melhor dashboard não precisa de walkthrough): se a primeira
    tela precisa de explicação para ser entendida, a hierarquia está errada — não o conjunto
    de features.

---

## 5. As regras de hierarquia (o mais importante no topo)

Estas regras valem para **todas** as telas e prevalecem sobre preferências locais.

1. **Uma tela responde a uma pergunta.** Painel: "está tudo funcionando e o que eu decido
   agora?" Documentos: "onde está a nota que procuro e como eu a entrego?" Importações: "a
   captura está em que pé?" Tudo que não responde à pergunta da tela desce de nível.
2. **Ordem vertical fixe:** estado que exige decisão → números que resumem → ferramenta de
   trabalho → contexto/infra. Se um gráfico aparecer acima de um alerta, está errado.
3. **Uma ação primária por tela, e ela é condicional.** No Painel: existem pendências →
   primária é "Ver N pendências" (rota Atenção); zero pendências → **não existe botão
   primário** (uma home saudável não oferece botão; oferece silêncio). "Disparar importação"
   desce para a tela Importações, como ação secundária.
4. **Frequência define altura visual:** diário no topo, semanal no meio, mensal no rodapé,
   raro no menu.
5. **Progressão de detalhe em três profundidades:** (1) visível de cara; (2) um clique —
   painel lateral `Painel`, linha expansível, aba; (3) dois cliques — menu `⋮`, rota dedicada.
   O detalhe de NSU, recibo e XML já está no nível certo; rebaixe junto a ele o que competir.
6. **Um número domina.** Em cada grade de KPI, o número mais decisivo é o maior (o `destaque`
   do `Kpi`); os demais acompanham. Se todos os KPIs têm o mesmo tamanho, nenhum foi escolhido.
7. **Espaço agrupa, borda separa só quando precisa.** Prefira afastar a afivelar: dois blocos
   relacionados se separam por espaço; blocos de assuntos diferentes por um divisor.
   Reduzir contêiner é a forma mais barata de reduzir ruído.

---

## 6. Dieta de botões e superfícies

**Meta numérica da reconstrução** (meça no fim; os números vêm da auditoria de hoje):

| Tela | Botões visíveis hoje | Teto aceitável |
|---|---|---|
| Painel | 2 | 2 (sendo 1 primária condicional) |
| Atenção | — | 0 botões novos; itens já navegam |
| Execuções | — | 1 (atualizar) |
| Documentos | 12 | **≤ 5** na barra (busca, filtros, 1 exportar, `⋮` tabela) + resto em menu |
| Importações | 5 + cartão XML | **≤ 2** na barra; caminho XML some do corpo (§7) |
| Empresas | 9 | **≤ 3** na barra (busca, novo, `⋮` com importações) |
| Certificados | 3 | 2 (enviar, atualizar; "Importar lote" vai para o `⋮`) |
| Empresa (detalhe) | — | 1 primária por aba |

**Regras da dieta:**

- **Menu `⋮` é cidadão de primeira classe.** Ações raras, destrutivas e de configuração moram
  nele — com `title` explicativo, teclado navegável e `aria-expanded` (o `MenuSuspenso` já dá
  isso pronto). Esconder não é negar: é ordenar.
- **Toda ação removida da superfície precisa existir em algum lugar alcançável:** paleta de
  comandos, menu da linha, ou aba da tela. Antes de remover, escreva numa linha do PR para onde
  a ação foi.
- **Botão primário tem verbo específico e objeto** ("Baixar XMLs do mês"), nunca "OK",
  "Aplicar", "Enviar".
- **Atualizar não é botão em toda tela.** O polling já atualiza; `atualizar` vira ícone 40×40
  (`BotaoIcone`) ao lado do timestamp, ou item da paleta. Animação de "carregando" em botão
  que refetcha conteúdo em segundo plano é contradição com §6 do SISTEMA.
- **Badge/etiqueta não é botão.** Se a etiqueta de status não leva a lugar nenhum, ela é
  `<Etiqueta>`; se leva, é link discreto sublinhado no hover.

---

## 7. Diretiva específica: importações de fora ficam escondidas

O princípio: **o Fluxa captura sozinho pela SEFAZ/ADN**. Importar arquivo de outro sistema é o
caminho de exceção — e aparece como exceção. Nenhum nome de ferramenta de terceiro, portal
de prefeitura ou "outro sistema" tem lugar no primeiro scroll de qualquer tela.

Regra aplicada:

1. **Tela Importações:** o cartão "Importar notas por XML" **sai do corpo da tela**. O corpo é
   o fluxo de captura (período, tipos, empresas, estado do sincronismo). A importação de XML
   vira **um item no menu `⋮` do cabeçalho da tela** — "Importar XMLs de outro sistema…" — que
   abre o `ModalImportarXmls` (que já existe, com drag-and-drop e resultado por arquivo).
   Nenhuma perda de função, todo o ganho de silêncio.
2. **Tela Documentos:** o atalho de importar XML continua existindo — no `⋮` da barra da
   tabela, ao lado de "Completar XMLs", não na barra.
3. **Linguagem:** o nome de uma ferramenta externa só aparece em ajuda contextual quando
   isso é necessário para identificar a origem de um arquivo importado.

---

## 8. Copy em português de escritório contábil (e o fim do tom de IA)

A interface fala a língua de quem fecha mês: seca, concreta, sem exclamação. Regras:

1. **Verbos operacionais, objetos concretos:** "Baixar XMLs de setembro", "Substituir
   certificado", "Ver 7 pendências". Nunca "Gerenciar", "Explorar", "Começar".
2. **Sem saudação, sem festa:** "Bem-vindo", "Perfeito!", "Tudo pronto! 🎉" não existem.
   Sucesso de operação é um toast de uma linha que se vai: "24 XMLs importados".
3. **Números no formato do país:** 1.234,56 · datas 18/09/2026 · "há 12 min" (relativo) com
   "18/09 14:32" (absoluto) juntos.
4. **Erro conta uma história em três partes:** o que aconteceu, por que, o que fazer.
   "Algo deu errado" é proibido (§1.4 do SISTEMA já garante — reprove regressões).
5. **Pergunta retórica não é descrição.** A `descricao` do `CabecalhoPagina` responde à
   pergunta da tela (§5.1) em uma frase afirmativa, não "Quer saber como está sua operação?".
6. **Sentence case** em tudo (título de cartão, botão, etiqueta). Nenhum Título Com Todas As
   Palavras Grandes, nenhum TODO MAIÚSCULO fora de sigla (NF-e, CT-e, SEFAZ).
7. **Sigla da comunidade contábil vem por extenso na primeira vez por tela:** "NFS-e (nota de
   serviço)", "A1 (certificado digital)". Depois, só a sigla.
8. **Comentário de código explica decisão, não traduz o código.** Um comentário por decisão não
   óbvia, na voz de quem decidiu ("não disparamos fora da janela oficial da SEFAZ; esperamos"). Sem cabeçalho
   de banner, sem "Este componente faz…" acima de um componente chamado `CabecalhoPagina`.

---

## 9. Especificação tela a tela

O que muda em cada rota. O que não está listado aqui, não muda.

### 9.1 `/dashboard` — Painel
- Remover a `BotaoLink` primária "Disparar importação" do cabeçalho.
- Primária condicional: `pendências > 0` → "Ver N pendências" (href Atenção); senão, nenhuma.
- Reordenar o corpo: (1) faixa de saúde (`Aviso` global que já existe); (2) cartão
  **"Precisa da sua atenção"** — agora o bloco maior da tela, lista as 5 pendências mais
  graves com ação de resolução em cada linha; (3) "Execuções agora" ao lado, compacto;
  (4) grade de KPIs (3 números com delta vs. mês anterior — §4.5); (5) gráficos e rankings
  em seção recolhível "Mês em números"; (6) "Componentes"/infra vira linha de rodapé
  compacta ("Infra: 3/3 componentes no ar · backup há 2 h"), com link para Saúde.
- "Maiores emitentes" desce para a seção recolhível — é análise, não operação.

### 9.2 `/dashboard/atencao` — Precisa da sua atenção
- Já está no formato certo (fila por gravidade). Revisão apenas de copy (§8) e conferir que
  cada item carrega ação de resolução como link, não botão.

### 9.3 `/dashboard/execucoes` — Execuções
- Trocar botões de refresh por `BotaoIcone` + timestamp. Fila em `LinhaExecucao` permanece.

### 9.4 `/dashboard/documentos` — Documentos (a maior dieta)
- Barra da tabela: Busca · Filtros (popover consolidado — tipo, direção, status, leiaute,
  valor) · **Exportar** (menu: "XMLs (ZIP)", "Relação (CSV)") · `⋮` (Importar XMLs…, Completar
  XMLs, Colunas, Densidade).
- Seleção em massa: barra de contexto que **substitui** a barra padrão enquanto houver seleção
  (o `Tabela` já tem o gancho) com: "Baixar N XMLs", "Excluir N…" — nada mais.
- Ações por linha migram para `⋮` da linha: detalhe (Enter), copiar chave, baixar XML, recibo.
- Exportação continua com estimativa prévia (`estimarExportacao`) — não mexa, é regra.

### 9.5 `/dashboard/importacoes` — Importações
- Corpo: estado do sincronismo no topo (a pergunta da tela), depois o formulário de disparo —
  **sem numeração de passos** ("1 ·", "2 ·" saem; a ordem dos campos já ensina).
- Importação de XML: item do `⋮` do cabeçalho (§7.1), abrindo o modal existente.
- Botões do cabeçalho: "Prévia" e "Disparar" só; um é secundário e um primário.

### 9.6 `/dashboard/empresas` — Empresas
- Barra: Busca · **Nova empresa** (primária) · `⋮` (Importar certificados em lote…, Importar
  XMLs…). Tudo o que era 9 botões cabe em 3 + menu.
- Resumo por empresa permanece tabela densa com status em `IndicadorEstado`.

### 9.7 `/dashboard/empresa?id=` — Detalhe da empresa
- Abas existentes (dados, documentos, execuções, certificado) permanecem. Uma primária por
  aba ("Salvar" na de dados, "Substituir certificado" na de certificado), ações destrutivas no
  `⋮` do canto — DialogoConfirmacao continua obrigatório (§12 do SISTEMA).

### 9.8 `/dashboard/certificados` — Certificados
- "Importar lote" migra para `⋮`; ficam "Enviar certificado" (primária) e Atualizar (ícone).
- O botão "Testar" (adicionado recentemente) permanece — é o exemplo do que deve ficar:
  ação real, frequente, com resultado imediato.

### 9.9 `/dashboard/relatorios` — Fechamento
- Tabela dupla impressão (virtualizada + folha plana) é decisão registrada (§9 do SISTEMA):
  **não mexa**. Revisar apenas header: competência à esquerda, "Conferir" e "Baixar" à direita.

### 9.10 `/dashboard/saude` — Saúde
- Diagnóstico e backup permanecem. "Executar backup agora" / "Testar restauração" agrupam-se
  num único bloco "Manutenção" com confirmação — ações de risco juntas e explicitamente raras.

### 9.11 `/dashboard/configuracoes` — Configurações
- Zona de risco (reset geral) fica isolada no fim, atrás de `exigirTexto` (já é assim).
- Nada de novo aqui além da dieta padrão.

### 9.12 `/dashboard/auditoria` e `/dashboard/usuarios`
- Somente leitura / CRUD simples já corretos. Dieta de botões padrão.

### 9.13 `/login`
- Sem alterações estruturais. Conferir copy (§8) e o toggle de senha (ícone de olho, se ainda
  textual).

---

## 10. O que não muda de jeito nenhum

1. **Contrato com a API:** `lib/api.ts`, `lib/types.ts`, rotas, parâmetros e tipos — 1:1.
   Nenhum endpoint novo, nenhum parâmetro inventado. Se a hierarquia pede um dado que não vem
   (ex.: delta de KPI), calcule no cliente a partir do que já chega (`evolucao`), ou anote como
   pendência de backend no PR — não finja.
2. **Backend, workers, importadores.** Este é um trabalho de front-end.
3. **Piso de acessibilidade:** WCAG 2.2 AA inteiro, foco visível, teclado, `prefers-*`.
4. **Segurança do front-end:** cookie HttpOnly só, nada de token em JS, credencial escrita
   nunca lida, `noindex`.
5. **Zero dependência nova.** `next`, `react`, `react-dom` e nada mais. Tabela, virtualização,
   gráfico e paleta são do produto.
6. **Decisões registradas do SISTEMA.md §14** — todas as 16 continuam valendo.

---

## 11. Plano de execução (nesta ordem, um PR por fase)

1. **Fase 0 — inventário e fix de verdade:** `package.json` → `fluxa-frontend`; conferir
   comentários de paleta e atualizar o inventário de rotas.
2. **Fase 1 — shell e navegação:** Sidebar com grupos e contagem silenciosa (badge numérico
   só onde há pendência), Header com timestamp do último refresh global. Nenhuma mudança de
   rota/caminho.
3. **Fase 2 — Painel e Atenção** (§9.1, §9.2): a nova hierarquia do topo.
4. **Fase 3 — as duas telas de dieta pesada:** Documentos e Importações (§9.4, §9.5) —
   inclui a mudança do §7 (XML import para modal via `⋮`).
5. **Fase 4 — Empresas/Certificados/detalhe** (§9.6–9.8).
6. **Fase 5 — telas de sistema** (§9.10–9.12) e revisão de copy geral (§8).
7. **Fase 6 — QA e fechamento:** checklist do §12 completo, `typecheck`, `vitest`, `next
   build`, atualização do `CHANGELOG-FRONTEND.md` e do SISTEMA.md.

Cada fase termina verde (`npm run typecheck && npm run test && npm run build`) e sem
`console.*`, `any`, `@ts-ignore`, `TODO` — os mesmos padrões de verificação de sempre.

---

## 12. Critérios de aceitação — a obra está pronta quando…

- [ ] A primeira dobra do Painel responde "está saudável? o que decido?" sem nenhum scroll.
- [ ] Nenhuma tela tem duas ações de acento simultâneas; a home saudável não tem botão primário.
- [ ] Nenhum gráfico aparece acima de um alerta em nenhuma tela.
- [ ] Documentos ≤ 5 controles na barra; Importações ≤ 2 no cabeçalho; Empresas ≤ 3.
- [ ] "Importar XMLs de outro sistema" não é visível em nenhuma tela sem abrir menu — e abre
      o modal com drag-and-drop e resultado por arquivo, igual aos de hoje.
- [ ] Todo botão removido tem linha no PR dizendo para onde foi (paleta, menu `⋮`, aba).
- [ ] Os KPIs do Painel mostram delta vs. competência anterior ao lado do valor.
- [ ] Passos numerados "1 ·"/"2 ·" não existem mais.
- [ ] `package.json` diz `fluxa-frontend`; §13 do SISTEMA.md lista todas as rotas reais.
- [ ] Zero: emoji, exclamação de copy, "Bem-vindo", ilustração de vazio, peso 700+, segunda
      cor de acento, sombra colorida, animação de entrada de página, `window.confirm`.
- [ ] `typecheck`, `vitest` (suíte existente + testes das telas reescritas) e `next build`
      passam sem erro e sem warning novo.
- [ ] Navegação inteira por teclado continua funcionando: `g`+letra, `⌘K`, `j/k/x/Enter`,
      `/` foca o filtro, `Esc` fecha a camada de cima.
- [ ] Um operador que nunca viu a tela consegue dizer o que ela responde em um olhar — sem
      tour, sem tooltip obrigatório, sem legenda.

---

## 13. Anti-padrões que denunciam geração por IA (rejeite na revisão)

A lista §16 do SISTEMA.md já bane os sintomas visuais. Esta é a lista dos **sintomas de tom e
estrutura** — o que faz uma interface "parecer de IA" mesmo seguindo o design system:

- Copy que explica o óbvio ("Aqui você pode gerenciar seus documentos").
- Título genérico de seção ("Visão geral", "Resumo", "Atividades recentes") em tela que tem
  um assunto só.
- Botões "Explorar", "Descobrir", "Saiba mais" dentro de um instrumento de trabalho.
- Três cards iguais lado a lado explicando recursos (padrão landing page) dentro de um app.
- Microcopy simpático em estado vazio ("Nada por aqui! 🎉", "Tudo limpo por agora!").
- Toda tabela embrulhada em card com título, descrição e ícone — tabela boa se sustenta sozinha.
- Consistência forçada: cada tela com exatamente a mesma anatomia (KPI → gráfico → tabela)
  mesmo quando a pergunta da tela é outra.
- Nomes de variável/componente descritivos demais (`BotaoPrimarioDeExportacaoDeXml`) ou
  genéricos demais (`Componente`, `Container`, `Wrapper`).
- Comentário que repete o nome do elemento ("// botão de fechar" acima de `<Botao>Fechar`).
- Zero decisões: se o PR não tem nenhuma escolha discutível, nenhuma was tomada — interface
  sem opinião é interface de template.

---

## 14. Verificação final (comandos)

```bash
cd frontend
npm run typecheck   # zero erro
npm run test        # vitest — suíte existente + novas telas
npm run build       # next build — standalone, sem warning novo
```

E a revisão humana: abra o Painel, o Documentos e o Importações no navegador. Se em qualquer
uma delas a primeira dobra não responder à pergunta da tela (§5.1), a reconstrução não
terminou.

---

*Documento escrito sobre a auditoria de `frontend/` em 01/10/2026 (122 arquivos, 20.440
linhas). Se o código divergir do descrito aqui, o código vence — e este documento precisa ser
corrigido junto.*
