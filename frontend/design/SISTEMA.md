# Papel & Grafite

Sistema visual e arquitetura do front-end do Fluxa. Três critérios, nesta ordem: **silencioso, preciso, confiável**.

A interface é um instrumento de operação contínua, não uma vitrine. Hierarquia vem de espaço, peso e alinhamento; cor existe apenas para indicar ação ou estado. Tudo que vale regra está implementado — este documento descreve o código, não uma intenção.

---

## 1. Arquitetura

### 1.1 Stack e build

| Item | Valor | Por quê |
|---|---|---|
| Framework | Next.js 16 App Router | roteamento por arquivo, `redirect()` de servidor, `output: standalone` |
| UI | React 19 + TypeScript 5.6 `strict` | `noUnusedLocals` e `noUnusedParameters` ligados: código morto não compila |
| Estilo | Tailwind 3.4 (config substituída) | tetos de raio, peso e sombra aplicados na configuração, não na disciplina |
| Dependências novas | **nenhuma** | `next`, `react`, `react-dom` e mais nada. Tabela, virtualização, camadas e paleta são do produto |
| Fontes | `next/font/local` (`fontes/*.woff2`) | o build não depende de rede; nenhum `@import` bloqueia a primeira pintura |
| Saída | `output: "standalone"` | imagem Docker mínima, sem `node_modules` completo |

`next.config.mjs` preserva três coisas obrigatórias: `output: "standalone"`, `allowedDevOrigins` lido de `NEXT_ALLOWED_DEV_ORIGINS` (o dev server precisa aceitar o host do preview) e as `rewrites` de `PREVIEW_PROXY=1` (o navegador fala com um host só; o Next encaminha `/empresas`, `/documentos`, `/saude` etc. ao backend).

### 1.2 Pastas

```
app/                     rotas; cada tela é page.tsx (servidor) + Componente.tsx (cliente)
  globals.css            tokens, base, utilitários de produto, impressão
  layout.tsx             <html lang="pt-BR">, fontes locais, script anti-flash do tema
components/
  ui/                    primitivos sem domínio: Botao, Tabela, Modal, Toast, Kpi…
  fiscal/                domínio: CartaoAlerta, LinhaExecucao, MedidorNSU, PainelDocumento…
  shell/                 ProvedorSessao, ProvedorAlertas, Sidebar, Header, PaletaComandos…
lib/                     api.ts, types.ts, estados.ts, format.ts + hooks de estado/URL
fontes/                  Inter e JetBrains Mono (woff2, latin) + LEIA-ME.md
design/                  este documento e RESUMO-PRODUTO.md
```

Regra de dependência: `ui/` não importa de `fiscal/` nem de `app/`; `fiscal/` importa de `ui/` e `lib/`; `shell/` importa de ambos. Nada em `ui/` conhece endpoint.

### 1.3 Fronteira servidor/cliente

`page.tsx` é servidor: define `metadata` (título via template `%s · Fluxa`) e envolve o componente de tela em `<Suspense>` com esqueleto equivalente. Toda lógica de dados é cliente (`"use client"`), porque o produto é operado com filtros vivos e polling.

`app/dashboard/layout.tsx` também é servidor e **não** verifica sessão: quem manda é a API. Se o cookie expirou, a primeira chamada responde 401 e `lib/api.ts` faz `window.location.replace("/login?destino=…")`. Não existe middleware nem espelho de autenticação no front-end — dois julgamentos divergentes sobre "quem está logado" é o tipo de bug que esta decisão elimina.

### 1.4 Contrato com a API

`lib/api.ts` é a única porta de saída: `chamar<T>()` com `credentials: "include"`, e um objeto `api` com um método por endpoint. Nenhum componente escreve `fetch`. O contrato foi preservado 1:1 no rebuild — mesmos caminhos, mesmos parâmetros, mesmas respostas.

Tipos e mapas de rótulos vivem em `lib/types.ts` (`TIPOS`, `ROTULO_TIPO`, `ROTULO_STATUS_LOTE`, `ROTULO_STATUS_SELECAO`, `ROTULO_PAPEL`, `ROTULO_ACAO`, `ROTULO_CATEGORIA_ALERTA`). Podem ser reorganizados, nunca redefinidos: dois dicionários de rótulo produzem duas verdades sobre o mesmo código.

Erros são traduzidos uma vez, em `lib/erros.ts` (`descreverErro` + `mensagemDoErro`), sobre `ApiError { status, ehAguardo }`:

| Situação | Mensagem | Próximo passo oferecido |
|---|---|---|
| `status === 0` | API fora do ar | `docker compose ps` / verificar `NEXT_PUBLIC_API_URL` |
| 401 (fora do login) | sessão encerrada | redireciona preservando `destino` |
| 403 | origem bloqueada | recarregar; se persistir, abrir o backend no navegador |
| 413 | arquivo acima de 35 MiB | conferir o `.p12` / reduzir o CSV |
| 429 | aguardando (`ehAguardo`) | continuar automaticamente — **nunca** é apresentado como falha |
| 204 | `undefined` | sem corpo, sem alerta de sucesso vazio |

Toda mensagem de erro diz **o que aconteceu, por que e o que fazer**. "Erro ao carregar" não existe no produto.

### 1.5 Autenticação e privilégio

Cookie HttpOnly definido pela API. Zero token em JavaScript: nada em `localStorage`, nada em estado, nada em URL. `ProvedorSessao` lê `/auth/me` **uma vez** por sessão e publica `{ usuario, papel, ehAdmin, podeOperar, somenteLeitura }`. Antes, cada tela lia por conta própria — cinco requisições iguais no primeiro carregamento e papéis divergentes entre menu e botões.

`lib/papel.ts` é puro (funções sobre a string do papel). A decisão de acesso é da API; o front-end apenas **esconde o que não se pode fazer** e desabilita com motivo (`title={MOTIVO_SOMENTE_LEITURA}`), nunca finge sucesso.

### 1.6 Estado: URL primeiro

| Estado | Onde vive | Exemplo |
|---|---|---|
| Filtro, ordenação, aba, página, seleção de competência | **URL** (query) | `/dashboard/documentos?de=…&ate=…&tipo=55&ordem=valor&sentido=desc` |
| Busca textual | URL, com debounce de 300 ms | `?busca=padaria` |
| Tema, densidade da tabela, colunas visíveis, sidebar colapsada | `localStorage`, prefixo `notasflow:` | preferência de trabalho, nunca credencial |
| Dados do servidor | `useRecurso` | cache por tela, sem camada global |

URL é a fonte da verdade porque o operador trabalha por link: manda o filtro do mês para o contador, volta amanhã e encontra a mesma tela, recarrega sem perder contexto. Consequência técnica: toda página que lê `useSearchParams` fica dentro de `<Suspense>` — sem isso o Next 16 recusa o build estático.

Hidratação é o detalhe que quebra esse padrão: `usePeriodoUrl` e `useCompetenciaUrl` aplicam o valor padrão **depois** do mount, para que servidor e cliente renderizem a mesma URL inicial.

`useUrlEstado` expõe `ler`, `lerNumero`, `lerBooleano` e `definir(mudancas, { preservar })` — trocar um filtro limpa a paginação (regra de produto: `pagina` só sobrevive quando a mudança não afeta o conjunto de linhas).

### 1.7 Hooks do produto

| Hook | Contrato |
|---|---|
| `useRecurso(carregar, deps, { automatico })` | `{ dados, erro, carregando, atualizando, atualizar, definir, ultimaAtualizacao }`. `carregando` só é verdadeiro sem dados; refetch liga `atualizando`, que **não** substitui conteúdo por esqueleto. Virar `automatico` de falso para verdadeiro dispara a primeira carga. |
| `usePolling(acao, intervaloMs \| null, ativo)` | `setInterval` limpo no unmount e **pausado com `document.hidden`**; retoma e executa imediatamente ao voltar. |
| `useDebounced(valor, 300)` | busca não dispara requisição por tecla. |
| `usePeriodoUrl` / `useCompetenciaUrl` / `useBuscaUrl` | URL como estado, seguros para hidratação. |
| `useCamada(tipo?, aoAbrir?)` | popover/menu/drawer: click-outside e Esc internos, `propsGatilho` com ARIA correta, sem portal. |
| `useFocoPreso` | foco preso em modal/drawer e devolvido ao gatilho no fechamento. |
| `usePreferencia(chave, padrao)` | `localStorage` com fallback silencioso (navegador em modo privado não quebra a tela). |
| `useAgora` (`ProvedorAgora`) | um único relógio de 30 s para toda a árvore: tempo relativo não multiplica timers. |

`lib/estados.ts` é o tradutor único de estado → `{ tom, rotulo, icone }`: `estadoDaExecucao`, `estadoDaSelecao`, `estadoDoLote`, `estadoDoCertificado`, `estadoDaSincronizacao`, `estadoDoDocumento`, `estadoDaConferencia`, `estadoDoBackup`, `estadoDaIntegracao`. `compararPorGravidade` e `PESO_NIVEL` ordenam alertas. Nenhuma tela decide cor por `if` próprio.

---

## 2. Cor

Todos os valores vivem em `app/globals.css` e chegam aos componentes por nomes semânticos do Tailwind. Nenhuma cor é escrita em componente — nem hex, nem `text-white/70`.

| Papel | Claro | Escuro | Uso |
|---|---|---|---|
| Fundo | `#EEF1F8` | `#0A0D1C` | canvas (com gradiente de vidro, §17) |
| Fundo afundado | `#E3E8F3` | `#0E1226` | cabeçalho de tabela, recessos |
| Superfície | `#FFFFFF` | `#161B34` | cartão e tabela (opaca) |
| Superfície alta | `#FFFFFF` | `#1C2240` | camada sobre superfície |
| Tinta forte | `#101425` | `#F2F3FB` | título, número-chave |
| Tinta | `#2A3050` | `#E2E4F5` | corpo |
| Tinta suave | `#565D80` | `#A8ADCF` | metadado, placeholder |
| Tinta fraca | `#8388A8` | `#767CA3` | **só** desabilitado e ornamento |
| Traço | `#DDE1EF` | `#262C4D` | divisor |
| Traço forte | `#C3C9E2` | `#3A4270` | divisor que precisa ser visto |
| Borda de controle | `#7D84AE` | `#7981AD` | input, botão secundário (1.4.11 pede 3:1) |
| Acento | `#4338CA` | `#8B85F0` | **única** cor de ação primária (índigo) |
| OK | `#157A5C` | `#5FD0A8` | operação confirmada |
| Espera | `#8A6210` | `#E1B958` | janela oficial SEFAZ, cota, `aguardando` |
| Erro | `#B23A45` | `#F19A94` | falha que exige ação humana |
| Informação | `#2F5FD6` | `#8FB3FB` | contexto não operacional |
| Grafite | `#0C1024` | `#060814` | sidebar, login, XML — superfície, não estado (grafite azulado, coerente com o acento) |

### 2.1 Contraste medido

Tema claro sobre superfície branca: tinta forte 17,3:1 · tinta 12,2:1 · tinta suave 5,7:1 · acento 7,3:1 · erro 6,1:1 · info 5,3:1 · ok 5,7:1 · espera 5,5:1 · borda de controle 3,5:1. Tema escuro sobre `#161B34`: tinta forte 15,1:1 · tinta 13,0:1 · tinta suave 7,3:1 · acento 7,1:1 · borda de controle 4,5:1 · texto sobre o acento 8,3:1 (o acento clareia e o texto sobre ele escurece — inverter a paleta quebraria o botão primário).

`--tinta-fraca` fica em 3,2:1 no claro (4,0:1 no escuro): por isso é reservado a placeholder de campo desabilitado e ornamento, e o placeholder ativo usa `tinta-suave`. Todo texto útil passa de 4,5:1.

Cada valor de `--acento`, `--ok`, `--espera`, `--erro`, `--info` e `--tinta-*` traz o contraste medido em comentário ao lado, em `globals.css` — este documento e o código nunca podem divergir.

### 2.2 Regras de cor

- Estados usam **ícone + palavra + cor**. Nunca só cor (1.4.1).
- `aguardando`, janela oficial da SEFAZ, cota e cStat 656 são sempre **espera** (âmbar), com previsão de retomada. Esperar não é falhar: vermelho aqui ensina o operador a ignorar vermelho.
- Um acento só (índigo). Duas ações de acento concorrentes na mesma tela é erro de design, não de estilo.
- Cor não é decoração: sem gradiente saturado, sem sombra colorida, sem ícone em círculo pastel. O gradiente sutil do `body` e o vidro (§17) são a única exceção, e têm função (dar ao vidro algo para "flutuar sobre").

---

## 3. Tipografia e números

Inter (self-hosted, `--fonte-sans`, fallback métrico Arial/system-ui) para interface; JetBrains Mono (`--fonte-mono`) para CNPJ, chave de acesso, NSU, competência e XML.

Escala (`tailwind.config.ts`, em `fontSize`): `2xs` 12/16 · `xs` 12/18 · `sm` 13/20 · `base` 14/22 · `md` 16/24 · `lg` 20/28 · `xl` 26/32 · `2xl` 34/40. `text-sm` (13/20) é o padrão de dados densos. **Nenhum texto útil abaixo de 12 px.**

Pesos permitidos: **400, 500, 600**. A config rebatiza `bold`/`extrabold`/`black` para 600 e `light`/`thin` para 400 — escrever `font-bold` não produz 700.

Números: `td`, `th` e `.nums` recebem `font-variant-numeric: tabular-nums lining-nums` na camada base, e valores numéricos são alinhados à direita na coluna. Valor que atualiza por polling não pode fazer a coluna dançar. Moeda usa `ValorMoeda` (negativo e cancelado tratados), contagem usa `numero()`, grandeza usa `moedaCompacta()` ("R$ 12 mil" em KPI, valor exato no `title`).

Tempo tem **duas camadas**: relativo para decidir ("há 12 min", "em 3 h") e absoluto para registrar ("18/09 14:32"). Sempre juntos — só relativo envelhece mal em tela aberta por horas; só absoluto exige conta mental.

---

## 4. Forma, espaço e elevação

Espaço em múltiplos de 4 px. Raios: 4 px (badge/etiqueta), 6 px (controle), 8 px (cartão), 12 px (camada). A config resolve `rounded-2xl` e `rounded-3xl` para 12 px: nada no produto é mais arredondado que um modal.

Elevação tem **três níveis**, todos semânticos: nível 0 = borda sem sombra (cartão, tabela, campo); `shadow-nivel1` = popover, menu, toast; `shadow-nivel2` = modal e drawer. `shadow-sm` a `shadow-2xl` resolvem para `none` na config. Cartão não sobe no hover — nada aqui é clicável por inteiro.

Larguras: conteúdo até 1440 px, formulário até 560 px, leitura até 72ch, painel lateral `min(620px, 92vw)`. Geometria do shell: header sticky de 56 px (`--altura-cabecalho`) define `scroll-padding-top` de todo alvo; sidebar de 240 px colapsa para 56 px e persiste a preferência.

`z-index` é vocabulário fechado: `cabecalho` 30 · `camada` 40 · `overlay` 60 · `modal` 70 · `aviso` 80 · `pulo` 90.

---

## 5. Movimento

120 ms para microinteração, 180 ms para camada leve (popover, toast), 240 ms para modal/drawer; easing `cubic-bezier(.2,0,0,1)`. Só `opacity` e `transform` são animados. Não existe animação de entrada de página nem `fade-up` global: conteúdo que aparece dançando atrasa a leitura.

Movimentos contínuos são dois e ambos significam "trabalho em andamento": `pulso` (execução rodando) e `progresso` (barra indeterminada). Com `prefers-reduced-motion: reduce` tudo cai para 1 ms e o pulso é substituído por estado estático.

---

## 6. Estados da interface

Toda região de dados tem quatro estados distinguíveis — e eles não compartilham representação:

| Estado | Componente | Regra |
|---|---|---|
| Carregando | `EsqueletoTabela` / `EsqueletoLista` | reproduz colunas e linhas reais da tela; nunca um bloco genérico |
| Vazio | `EstadoVazio` | título + instrução curta + próxima ação real; sem ilustração |
| Erro | `EstadoErro` | ocorrência, causa provável, `aoTentarNovamente` |
| Conteúdo | tabela/lista/cartão | — |

Vazio com filtro ativo é outro estado: `filtroAtivo` + `aoLimparFiltro` oferecem "limpar filtros" — vazio de acervo e vazio de busca pedem ações diferentes.

**Refetch não pisca.** `atualizando` liga um sinal fino no topo (`BarraAtualizacao` via `useSinalizarAtualizacao`) e mantém o conteúdo visível. Substituir uma tabela lida por esqueleto a cada 30 s faz o operador perder a linha em que estava.

---

## 7. Componentes

### 7.1 `components/ui/` (primitivos)

`Icone` (paths inline, sem pacote de ícones) · `Botao`/`BotaoLink`/`BotaoIcone` · `Spinner` · `Dica` (tooltip) · `Campo`: `Entrada`, `Area`, `Selecao`, `Caixa`, `Radio`, `GrupoRadio`, `Alternador`, `Busca` · `CampoArquivo` (arrastar e soltar, limite de tamanho) · `Combobox` (busca com lista filtrável) · `SeletorData`/`SeletorMes` · `Etiqueta` · `IndicadorEstado` · `Aviso` · `Cartao` · `Dado` (par rótulo/valor de `<dl>`) · `Kpi`/`GradeKpis` · `Esqueleto*` · `EstadoVazio` · `EstadoErro` · `Migalhas` · `BarraProgresso` · `Paginacao` · `CopiavelMono` · `Formatadores` (`DataHora`, `ValorMoeda`, `Truncado`, `Ausente`) · `Modal` · `Painel` (drawer) · `DialogoConfirmacao` · `Popover`/`MenuSuspenso` · `Abas` · `Toast` (`useToast`) · `Tabela`.

### 7.2 `components/fiscal/` (domínio)

`SeletorPeriodo` (com atalhos: mês atual, mês passado, últimos 3/6/12) · `SeletorCompetencia` · `SeletorEmpresas` · `MedidorNSU`/`ResumoNSU` · `CartaoAlerta` (com `destinoDoAlerta` e `rotuloDaAcao`) · `LinhaExecucao` · `CartaoCertificado` · `PainelDocumento` (detalhe, XML, download) · `ResumoImportacao` · `Graficos` (`GraficoBarras`, `GraficoDonut`, `Sparkline` — SVG puro, sem biblioteca).

### 7.3 `components/shell/`

`Shell` compõe a árvore de provedores nesta ordem: `ProvedorSessao` → `ProvedorAlertas` → `Toast` → `ProvedorAgora` → `ProvedorProgresso` → `ProvedorComandos`. Depois `Sidebar`, `Header`, `PaletaComandos`, `AtalhosTeclado`, `SeletorTema`, `BarraAtualizacao`. A ordem importa: sessão alimenta o menu, alertas alimentam o sino, e `ProvedorComandos` precisa estar por último para enxergar todos os contextos.

### 7.4 Faça / não faça

| Componente | Faça | Não faça |
|---|---|---|
| Botão | uma primária por tela; verbo específico ("Baixar XMLs do mês") | duas ações de acento concorrentes; "OK", "Clique aqui" |
| Campo | `<label>` real, descrição e erro junto ao campo | placeholder como rótulo; erro só em vermelho |
| Tabela | `caption`, `th scope`, linhas de 40–44 px, números à direita | cards para centenas de registros; ordenação sem indicador |
| Estado | ícone + palavra + tom | depender só de cor |
| Alerta | impacto e ação de resolução | oferecer "tentar agora" dentro de janela oficial |
| Modal | prender e devolver foco; ação destrutiva à esquerda, cancelar focado | `window.confirm` |
| Vazio | instrução curta e próxima ação | ilustração genérica, "Nada por aqui!" |
| Esqueleto | mesmas colunas e linhas da tela | aparecer durante refetch |
| Tooltip | complemento curto, sem ação dentro | esconder informação necessária |
| Gráfico | SVG acessível que muda uma decisão | gráfico decorativo no Painel |

`Dado` é o único modo de escrever rótulo acima/valor abaixo dentro de um `<dl>`: `mono`, `destaque`, `tom`, `contexto`, `quebrar`, `linhas`, `largo`, `compacto`, `href` e `dica` cobrem todos os casos — NSU em mono, contagem de resumo em destaque, mensagem de erro em duas linhas, meta compacta dentro de linha de lista, valor que é link para a empresa. O valor é sempre tabular (`nums`). A grade `<dl>` continua montada pela tela, que é quem sabe quantas colunas cabem. Existiam nove componentes locais com quatro nomes (`Dado`, `DadoLote`, `Campo`, `Bloco`) mais blocos `<dt>`/`<dd>` escritos à mão, cada um com um tom e um peso diferentes para a mesma informação; todos viraram este componente. (A lista de totais do Fechamento é outro desenho — rótulo à esquerda, valor à direita — e por isso continua com `<dl>` próprio.)

`Tabela` é o componente mais denso do produto e resolve sozinho: ordenação (`ordem`/`sentido` na URL), seleção por linha e em massa com barra de ações, densidade (`confortavel`/`compacta` como preferência), colunas visíveis persistidas, linha expansível, cabeçalho fixo com `altura`, virtualização acima de 300 linhas, teclado `j`/`k`/`x`/`Enter`/`Home`/`End`, e os quatro estados.

---

## 8. Dados em escala

Escala real: centenas de empresas, milhões de documentos. As decisões seguem daí.

- **Paginação por passo, não por página.** Documentos usa passo 500 com "carregar mais"; Auditoria usa passo 100. Contagem total vem de endpoint próprio (`resumoDocumentos`), porque listar milhões de linhas para contar é caro.
- **Virtualização acima de 300 linhas** (`LIMITE_VIRTUALIZACAO` em `Tabela`): altura de linha fixa por densidade (40/44 px), espaçadores `aria-hidden` antes e depois da janela e margem de 8 linhas acima e abaixo para o rolamento não mostrar vazio. Telas que podem crescer passam `virtualizar` explicitamente; as outras herdam o limite.
- **Polling proporcional ao interesse.** Painel e Execuções: 5 s quando há execução em andamento, 30 s em repouso. Saúde, Importações e o sino de alertas: 60 s. Tudo pausado com a aba oculta.
- **Ordenação no cliente quando o backend não ordena.** `/documentos` não aceita parâmetro de ordenação e devolve array simples — a ordenação é client-side sobre a página carregada e o rótulo da coluna diz isso. Inventar `ordenar_por` produziria filtro silenciosamente ignorado.
- **Downloads via `fetch` + blob** (`baixarZip`, `baixarCsvDocumentos`, `baixarXmlDocumento`, `baixarFechamentoCsv`): o cookie HttpOnly não viaja em `<a download>` de outro host, e o botão precisa mostrar progresso e erro.
- **Estimativa antes do trabalho caro.** Exportar ZIP chama `estimarExportacao` e mostra tamanho/contagem antes de confirmar.
- **Uma escrita por vez.** Ações longas usam `ProvedorProgresso` (barra no topo) e desabilitam o gatilho; nada de double-submit.

---

## 9. Impressão

O Fechamento Mensal tem folha de verdade (`@media print` em `globals.css`): `.nao-imprimir` esconde shell e filtros, `.pagina-paisagem` define `@page { size: A4 landscape }`, `.evitar-quebra` impede corte de linha, cores viram fundo branco com tinta preta e o rodapé carrega competência, emissão e assinatura.

Decisão não óbvia: a tela usa `Tabela` virtualizada, e virtualização **corta linhas** fora da viewport — imprimir a tabela interativa produziria uma folha incompleta. Por isso a página renderiza duas tabelas: a virtualizada (`print:hidden`) e uma tabela plana com totais e todas as empresas (`hidden print:block pagina-paisagem`). Duplicação deliberada, documentada no componente.

---

## 10. Acessibilidade (WCAG 2.2 AA)

| Critério | Implementação |
|---|---|
| 1.4.3 / 1.4.6 Contraste | paleta medida (§2.1); `tinta-fraca` restrito a desabilitado |
| 1.4.4 Redimensionamento | `rem` em toda a escala; zoom 200% sem perda |
| 1.4.10 Reflow | `min-width: 320px`; sidebar vira drawer, tabela rola em container próprio e a linha ativa é focalizável (`tabindex` móvel), então o teclado alcança e rola o conteúdo |
| 1.4.11 Contraste não textual | borda de controle ≥ 3,5:1; foco com traço + halo |
| 1.4.12 Espaçamento | altura de linha e tracking acima do mínimo |
| 1.4.13 Conteúdo sobreposto | popover/menu fecham com Esc e click-outside; tooltip não intercepta ponteiro |
| 2.1.1 / 2.1.2 Teclado | tudo operável sem mouse; nenhum atalho prende o foco; `Esc` sempre sai |
| 2.4.1 Pular blocos | "Pular para o conteúdo" como primeiro focoável (`z-pulo`) |
| 2.4.3 Ordem de foco | DOM = ordem visual; camadas usam `useFocoPreso` |
| 2.4.7 Foco visível | anel de 2 px + halo em `:focus-visible`, em todas as superfícies |
| 2.4.11 Foco não obscurecido | `scroll-margin-top: calc(var(--altura-cabecalho) + 16px)` |
| 2.5.8 Alvo mínimo | controles isolados ≥ 40 px (`BotaoIcone` é 40×40); linhas de tabela 40–44 px; nada clicável abaixo de 24 px |
| 3.2.1 / 3.2.2 Sem surpresa | nada muda contexto em `onFocus`/`onChange`; filtros exigem ação explícita |
| 3.3.1 / 3.3.2 Erros e rótulos | erro ligado por `aria-describedby`, com texto de correção |
| 4.1.2 / 4.1.3 Nome, papel, estado | padrões APG: `combobox`, `listbox`, `dialog`, `tablist`, `switch`, `progressbar`, `status` em toast |

Outros compromissos: `prefers-contrast: more` reforça bordas; `prefers-reduced-motion` remove movimento; anúncio de carregamento por `aria-live="polite"` (e `aria-busy` em refetch); ícone decorativo com `aria-hidden` e ícone informativo com `titulo`; imagens inexistentes (o produto não tem ilustração).

---

## 11. Teclado

Registro único em `lib/atalhos.ts`: o mapa (`?`), a paleta (`Ctrl/⌘K`) e o ouvinte global leem da mesma lista — atalho que não está lá não existe, e a documentação não mente.

`Ctrl/⌘K` paleta de comandos (navegar, buscar empresa e documento, abrir o mapa) · `?` mapa de atalhos · `/` foca o filtro da tela (marcado com `data-atalho-filtro`) · `Esc` fecha a camada superior · `g` + letra navega (janela de 1200 ms) · `j`/`k` movem a seleção na tabela · `x` marca/desmarca · `Enter` abre a linha.

`ProvedorComandos` ignora atalhos quando há `[aria-modal="true"]` aberto ou quando o foco está em campo de texto — tecla de navegação dentro de modal é bug clássico. `g` prefixado exige confirmação de segunda tecla e expira.

---

## 12. Segurança no front-end

- Sessão só em cookie HttpOnly; nenhuma leitura/escrita de token em JS.
- 401 fora do login → `replace("/login?destino=<rota>")` (volta ao ponto exato).
- Credenciais de integração (Acessórias) são **escritas e nunca lidas**: a API não devolve segredo, e o campo mostra "credencial salva" sem conteúdo. Remoção exige `DialogoConfirmacao`.
- Ações destrutivas passam por `DialogoConfirmacao` com `consequencia` e `impacto`; irreversíveis em massa exigem texto digitado (`exigirTexto`): exclusão de empresa pede `EXCLUIR`, reset geral pede `APAGAR TUDO`.
- Exclusão de usuário não existe: desativa-se (`ativo = false`) para preservar a trilha de auditoria. Admin não edita a própria conta (evita auto-bloqueio).
- Auditoria é explicitamente somente leitura — não há botão de apagar trilha.
- `robots: noindex, nofollow` no metadata.

---

## 13. Rotas

| Rota | Título | Grupo | Atalho | Endpoints principais |
|---|---|---|---|---|
| `/login` | Entrar | — | — | `auth/login` |
| `/dashboard` | Painel | Visão geral | `g p` | `kpis`, `painelOperacional`, `alertas`, `centralExecucoes`, `evolucao`, `porTipo`, `topEmitentes` |
| `/dashboard/atencao` | Precisa da sua atenção | Visão geral | `g a` | `alertas`, `empresas` |
| `/dashboard/execucoes` | Execuções | Visão geral | `g x` | `centralExecucoes`, `execucoes`, `importacoes`, `empresas` |
| `/dashboard/documentos` | Documentos | Fiscal | `g d` | `documentos`, `resumoDocumentos`, `zip`, `csv`, `completar-xmls`, exclusões |
| `/dashboard/importacoes` | Importações | Fiscal | `g i` | `sincronizacao`, `resumoSincronizacao`, previa + `importarSelecionadas`, `certificados/resumo` |
| `/dashboard/empresas` | Empresas | Fiscal | `g e` | `empresas`, `consulta-cnpj`, `importar` (massa), `resumoPorEmpresa`, `certificados/resumo` |
| `/dashboard/empresa?id=` | Empresa | Fiscal | — | `obterEmpresa`, `atualizar`, `excluir`, `certificados` (+envio), `documentos`, `execucoes`, `sincronizacaoDaEmpresa` |
| `/dashboard/certificados` | Certificados | Fiscal | `g c` | `painelCertificados`, `enviarCertificado`, `empresas` |
| `/dashboard/relatorios` | Fechamento | Fiscal | `g f` | `fechamento`, `conferirCompetencia`, `fechamento/csv` |
| `/dashboard/saude` | Saúde | Sistema | `g s` | `saudeDetalhada`, `infoSistema`, `backups`, `executarBackup`, `testarBackup`, `painelOperacional` |
| `/dashboard/configuracoes` | Configurações | Sistema | `g o` | `infoSistema`, `saudeDetalhada`, Acessórias, `testarWebhook`, `resetGeral` |
| `/dashboard/auditoria` | Auditoria | Sistema | `g t` | `auditoria`, `acoesAuditoria` (visível para quem opera) |
| `/dashboard/usuarios` | Equipe | Sistema | `g u` | `usuarios` (criar/atualizar) — **só admin** |
| `/dashboard/alertas` | — | — | — | redirect permanente → `/dashboard/atencao` |
| `/` | — | — | — | redirect → `/dashboard` |

`lib/rotas.ts` é o registro único: menu, trilha de navegação, título do cabeçalho, descrição na paleta, atalho `g` e visibilidade por papel saem do mesmo array. Rota nova existe num lugar só.

---

## 14. Decisões registradas

1. **Rebuild integral sem trocar contrato.** Toda a árvore de telas, primitivos e shell foi reescrita; `lib/api.ts` e `lib/types.ts` mantêm caminhos, parâmetros e tipos. O backend não muda por causa do front-end.
2. **Zero dependência nova.** Tabela, virtualização, camadas, paleta e gráficos são do produto. Cada dependência a mais é superfície de manutenção, versão e CVE num sistema que roda em máquina de cliente.
3. **Fontes locais.** `next/font/google` exige rede no build; o Docker de produção é offline. Woff2 latin commitado em `fontes/` com `LEIA-ME.md` de procedência.
4. **Autenticação é da API.** Sem middleware: um único juiz evita tela liberada com chamada 403 (ou o contrário).
5. **URL como estado, `localStorage` como preferência.** Link compartilhável e recarregável; tema/densidade/colunas por operador.
6. **Refetch mantém conteúdo.** `carregando` só sem dados; `atualizando` sinaliza no topo.
7. **Espera nunca é erro.** Janela SEFAZ, cota e `aguardando` são âmbar com previsão de retomada; vermelho fica para o que exige ação.
8. **Ordem dos provedores fixa.** Sessão → Alertas → Toast → Agora → Progresso → Comandos.
9. **Um relógio só.** `ProvedorAgora` (30 s) alimenta todo tempo relativo; sem timer por componente.
10. **Tabela plana para imprimir.** Virtualização cortaria linhas na folha (§9).
11. **Ordenação client-side em `/documentos`.** O endpoint não ordena; fingir que ordena é pior que o limite explícito.
12. **`noUnusedLocals`/`noUnusedParameters` ligados.** Import esquecido é sinal de código abandonado no meio de um rebuild.
13. **Rótulos canônicos em `types.ts`.** Nenhuma tela redeclara `TIPOS` ou mapa de status.
14. **Exclusão de usuário é desativação.** Auditoria exige histórico; apagar registro quebra trilha.
15. **Credencial escrita, nunca lida.** Segredo não volta ao navegador.
16. **Decisão sem pergunta.** Ambiguidade de produto é resolvida e registrada em comentário de uma linha no código — sem `TODO`, sem placeholder.

---

## 15. Como acrescentar uma tela

1. `app/dashboard/<rota>/page.tsx` — servidor: `metadata.title`, `<Suspense fallback={<Esqueleto…/>}>` envolvendo o componente.
2. `app/dashboard/<rota>/<Tela>.tsx` — `"use client"`: filtros por `useUrlEstado`/`usePeriodoUrl`, dados por `useRecurso`, polling por `usePolling` (sempre com intervalo condicionado e pausa em aba oculta).
3. `lib/rotas.ts` — título, grupo, ícone, tecla `g`, descrição e `visivelPara`.
4. `lib/atalhos.ts` — só se o atalho mudar (o menu e o mapa leem de `rotas.ts`).
5. Estados: quatro, com vazio de filtro tratado à parte; erros por `descreverErro`.
6. Verificação: `npm run typecheck` e `npm run build` sem erro; sem `console.*`, `any`, `@ts-ignore`, `window.confirm|alert|prompt` ou `TODO`.

---

## 16. O que não existe aqui

Emoji · copy de marketing · `rounded-3xl` real · sombra colorida · `fade-up` global de página · segundo acento · KPI com ícone em círculo pastel · hero section · esqueleto que não reproduz a tela · ilustração de vazio · `window.confirm`/`alert`/`prompt` · token em JavaScript · peso 700+ · texto útil abaixo de 12 px · card que levanta no hover · cor sem significado · botão sem verbo · erro sem próximo passo.

Exceção controlada: o vidro (§17) e o gradiente de fundo do `body` que o sustenta **existem de propósito** — não são o "glassmorphism decorativo" que esta lista sempre baniu (blur solto em qualquer superfície, sem função). Fora das duas classes `.vidro`/`.vidro-grafite` e do gradiente fixo do `body`, a regra permanece: nenhum outro componente aplica `backdrop-filter`, gradiente decorativo ou sombra colorida.

## 17. Vidro — regra de uso

A Fluxa é compartilhada com outro operador e precisa parecer um produto vendável, não uma tela genérica gerada por IA. A camada de navegação e as camadas flutuantes (nunca a leitura densa) usam um vidro sutil e funcional:

- **Onde**: `Header`, `Sidebar` (`.vidro-grafite`), `Modal`, `Popover`, `MenuSuspenso`, `Toast`, dropdown de `Combobox` e `Cartao` (o cartão de conteúdo, que soma leve elevação ao invés de ficar plano).
- **Onde não**: texto de corpo, tabela densa, formulário de captura, célula de dado — ali a leitura vem antes de qualquer textura, e a superfície continua opaca (`bg-superficie`).
- **Como**: classes `.vidro`/`.vidro-grafite` (`globals.css`, camada `utilities`), nunca `backdrop-filter` escrito à mão em componente. Cada uma já embute borda translúcida própria — não combine com `border-*` no elemento.
- **Variáveis**: `--vidro-rgb`, `--vidro-alpha`, `--vidro-borda-rgb/alpha`, `--vidro-blur` — um valor por tema (claro/escuro), recalibrados junto com o acento índigo.
- **Degradação**: `@supports not (backdrop-filter: blur(1px))` cai para a superfície opaca equivalente — nunca uma tela transparente sem fallback.
- **Acessibilidade**: `prefers-contrast: more` derruba a transparência do vidro para 0,94/0,90 — o texto por cima nunca depende do blur para ter contraste.
