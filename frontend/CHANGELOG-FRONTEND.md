# Changelog do front-end

## Reconstrução integral — Papel & Grafite

Rebuild completo da interface do Fluxa: 14 rotas, primitivos, shell e camada de estado reescritos do zero. O contrato com a API **não mudou** — nenhum endpoint, parâmetro ou tipo foi alterado, e o backend não precisa de ajuste.

Escala da mudança: 41 arquivos reescritos, 12 removidos, 75 criados. O front-end passa de ~8,7 mil para ~17,2 mil linhas em 108 arquivos, com **zero dependência nova** (`next`, `react`, `react-dom` e nada além).

O documento de referência é `design/SISTEMA.md`: tokens, regras, decisões e a receita para acrescentar uma tela.

---

### Contrato preservado

- `lib/api.ts` mantém um método por endpoint, `credentials: "include"` e tradução única de erro (`ApiError { status, ehAguardo }`).
- `lib/types.ts` mantém tipos e rótulos canônicos (`TIPOS`, `ROTULO_TIPO`, `ROTULO_STATUS_LOTE`, `ROTULO_STATUS_SELECAO`, `ROTULO_PAPEL`, `ROTULO_ACAO`, `ROTULO_CATEGORIA_ALERTA`). Nenhuma tela redeclara dicionário de rótulo.
- Sessão continua exclusivamente em cookie HttpOnly: nada de token em JavaScript, `localStorage` ou URL.
- Downloads continuam por `fetch` + blob (ZIP, CSV, XML, fechamento), com progresso e erro no botão.

### Fundação visual

- Tokens semânticos reescritos em `app/globals.css`: papel neutro, tinta em quatro níveis, um único acento verde e cores de estado estritamente semânticas. Nenhum componente escreve cor por valor.
- Tema claro e escuro calibrados separadamente (não é paleta invertida): no escuro o acento clareia e o texto sobre ele escurece para manter 8,0:1. Contraste medido e registrado — todo texto útil acima de 4,5:1.
- `--tinta-fraca` rebaixado a papel decorativo/desabilitado (3,1:1); placeholder passa a usar `tinta-suave`.
- `tailwind.config.ts` substituída com tetos que tornam o erro impossível: `rounded-2xl`/`rounded-3xl` resolvem para 12 px, `font-bold`/`font-black` resolvem para 600, `shadow-sm`…`shadow-2xl` resolvem para `none` (só `nivel1` e `nivel2` elevam).
- Escala tipográfica fechada (11/16 a 34/40), pesos 400/500/600, nenhum texto útil abaixo de 12 px.
- Números tabulares em toda célula de tabela e em `.nums`; valores numéricos alinhados à direita.
- Fontes self-hosted (`fontes/*.woff2`, Inter + JetBrains Mono) via `next/font/local`, com procedência em `fontes/LEIA-ME.md`. O build não depende mais de rede — `next/font/google` estava bloqueado em ambiente offline.
- Movimento restrito a camadas (120/180/240 ms, `cubic-bezier(.2,0,0,1)`); sem animação de entrada de página. `prefers-reduced-motion` derruba tudo para 1 ms e `prefers-contrast: more` reforça traços.
- Script inline anti-flash de tema no `app/layout.tsx` (aplica `data-tema` antes da primeira pintura).

### Primitivos novos (`components/ui/`)

`Icone` (paths inline, sem pacote de ícones) · `Botao`/`BotaoLink`/`BotaoIcone` · `Spinner` · `Dica` · `Campo` (`Entrada`, `Area`, `Selecao`, `Caixa`, `Radio`, `GrupoRadio`, `Alternador`, `Busca`) · `CampoArquivo` (arrastar e soltar, limite de tamanho) · `Combobox` (padrão APG `combobox` + `listbox`) · `SeletorData`/`SeletorMes` · `Etiqueta` · `IndicadorEstado` · `Aviso` · `Cartao` · `Dado` · `Kpi`/`GradeKpis` · `Esqueleto` (`EsqueletoTabela`, `EsqueletoLista`) · `EstadoVazio` · `EstadoErro` · `Migalhas` · `BarraProgresso` · `Paginacao` · `CopiavelMono` · `Formatadores` (`DataHora`, `ValorMoeda`, `Truncado`, `Ausente`) · `Modal` · `Painel` (drawer) · `DialogoConfirmacao` · `Popover` · `MenuSuspenso` · `Abas` · `Toast` · `Tabela`.

`Dado` unifica o par rótulo/valor de lista de descrição: eram nove componentes locais com quatro nomes (`Dado`, `DadoLote`, `Campo`, `Bloco`) além de blocos `<dt>`/`<dd>` escritos à mão, cada um com peso e tom próprios para a mesma informação — o operador via a mesma contagem com corpo diferente conforme a tela. Passa a existir um componente com `mono`, `destaque`, `tom`, `contexto`, `quebrar`, `linhas`, `largo`, `compacto`, `href` e `dica`, sempre com números tabulares.

`Tabela` concentra o que antes estava espalhado pelas telas: ordenação ligada à URL (`ordem`/`sentido`), seleção por linha e em massa com barra de ações (Shift seleciona intervalo), densidade e colunas visíveis persistidas, linha expansível, cabeçalho fixo, virtualização acima de 300 linhas (linha de 40/44 px, espaçadores `aria-hidden`, margem de 8 linhas), os quatro estados e teclado `j`/`k`/`x`/`Enter`/`Home`/`End`.

### Domínio (`components/fiscal/`)

`SeletorPeriodo` (com atalhos de mês atual, mês passado, últimos 3/6/12) · `SeletorCompetencia` · `SeletorEmpresas` · `MedidorNSU`/`ResumoNSU` · `CartaoAlerta` · `LinhaExecucao` · `CartaoCertificado` · `PainelDocumento` · `ResumoImportacao` · `Graficos` (`GraficoBarras`, `GraficoDonut`, `Sparkline` — SVG puro, sem biblioteca de gráfico).

### Shell

- `Shell` compõe os provedores em ordem fixa: `ProvedorSessao` → `ProvedorAlertas` → `Toast` → `ProvedorAgora` → `ProvedorProgresso` → `ProvedorComandos`.
- `ProvedorSessao` centraliza `/auth/me`: antes cada tela chamava por conta (cinco requisições iguais no carregamento e papéis divergentes entre menu e botões).
- `ProvedorAlertas` alimenta o sino com `contagemAlertas` a cada 60 s, com popover que só busca ao abrir.
- `ProvedorAgora` é o único relógio do produto (30 s) para todo tempo relativo.
- `ProvedorComandos` + `PaletaComandos` (`Ctrl/⌘K`), `AtalhosTeclado` (`?`), navegação `g + letra` e `/` para o filtro da tela — todos lendo do registro único `lib/atalhos.ts`.
- `Sidebar` de 240 px com colapso para 56 px persistido, grupos por `lib/rotas.ts`, visibilidade por papel (Equipe só para admin, Auditoria não aparece em leitura) e contador de atenção com tom correto.
- `Header` reduzido a 56 px; `BarraAtualizacao` sinaliza refetch sem substituir conteúdo; "Pular para o conteúdo" é o primeiro focoável.
- `lib/rotas.ts` passa a ser o registro único de navegação: menu, trilha, título, descrição na paleta, atalho `g` e visibilidade por papel saem do mesmo array.

### Dados, estado e erros

- URL vira a fonte da verdade para filtros, ordenação, aba, página e competência (`useUrlEstado`, `usePeriodoUrl`, `useCompetenciaUrl`, `useBuscaUrl`), com debounce de 300 ms na busca e hidratação segura (padrão aplicado depois do mount).
- Preferências visuais (tema, densidade, colunas, sidebar) ficam em `localStorage` sob o prefixo `notasflow:`.
- `useRecurso` separa `carregando` de `atualizando`: **refetch nunca troca conteúdo visível por esqueleto**.
- `usePolling` pausa com `document.hidden`, retoma ao voltar e limpa o intervalo no unmount; intervalos proporcionais (5 s com execução em andamento, 30 s em repouso, 60 s em Saúde/Importações/alertas).
- `lib/erros.ts` traduz status em mensagem acionável: API fora do ar (`status 0`) sugere `docker compose ps`; 401 fora do login redireciona preservando `destino`; 403 explica origem; 413 aponta o limite de 35 MiB; 429 é `ehAguardo` e nunca vira falha.
- `lib/estados.ts` é o tradutor único estado → `{ tom, rotulo, icone }` com ordenação por gravidade: `aguardando`, janela oficial da SEFAZ, cota e cStat 656 são **âmbar (espera)**, nunca vermelho.
- `lib/csv.ts` para exportações locais; `lib/uf.ts` com as 27 UFs; `lib/competencia.ts` e `lib/periodo.ts` sem duplicidade de helper.

### Telas

- **Painel** (`/dashboard`): estado geral primeiro, decisões pendentes depois. KPIs de competência com variação, gráficos `evolucao`/`porTipo`/`topEmitentes`, central de execuções e últimas sincronizações. Sem gráfico decorativo.
- **Precisa da sua atenção** (`/dashboard/atencao`): alertas ordenados por gravidade com ação de resolução em cada cartão; filtro por nível na URL; vazio distingue "nada pendente" de "nada com este filtro".
- **Execuções** (`/dashboard/execucoes`): agora/recentes/erros via `centralExecucoes`, lista completa com filtro por empresa e estado, disparo de importação com prévia.
- **Documentos** (`/dashboard/documentos`): período obrigatório, passo de 500 com "carregar mais", contagem por `resumoDocumentos`, seleção em massa, ZIP/CSV com estimativa prévia, painel lateral com detalhe e XML, exclusão com impacto explícito, complemento de resumos (`completar-xmls`). Ordenação é client-side — o endpoint não aceita parâmetro de ordenação e a interface diz isso em vez de fingir.
- **Importações** (`/dashboard/importacoes`): prévia antes do disparo, seleção por empresa/competência, resumo de sincronização com NSU e `tick_a_partir_de`, janela SEFAZ tratada como espera operacional.
- **Empresas** (`/dashboard/empresas`): cadastro por CNPJ com consulta à Receita, importação em massa por arquivo, situação e certificado por linha, filtros de situação na URL.
- **Empresa** (`/dashboard/empresa?id=&aba=`): abas (visão geral, documentos, execuções, certificados, integrações) na URL, edição, envio de certificado, complemento de XMLs, sincronização própria; exclusão exige digitar `EXCLUIR`.
- **Certificados** (`/dashboard/certificados`): painel com validade, último uso, último erro e CNPJ; substituição por arquivo com senha; vencido/vencendo em tom correto.
- **Fechamento** (`/dashboard/relatorios`): seletor de competência, fechamento + conferência, KPIs, donut por tipo e barras de maiores empresas, tabela virtualizada em tela e **folha de impressão própria** em A4 paisagem com totais e assinatura; `Imprimir fechamento` e `Baixar CSV`.
- **Saúde** (`/dashboard/saude`): diagnóstico detalhado, componentes, informações do sistema, backups com atraso tratado como erro e teste/backup manual restritos a admin; polling de 60 s.
- **Configurações** (`/dashboard/configuracoes`): abas Ambiente (somente leitura), Integrações (Acessórias — credencial escrita e nunca lida, com testar/sincronizar e remoção confirmada), Alertas (webhook, teste e categorias) e Dados (reset geral exigindo `APAGAR TUDO`).
- **Auditoria** (`/dashboard/auditoria`): filtro por ação alimentado por `acoesAuditoria`, busca na URL, carregamento incremental de 100 em 100, leitura explícita de que a trilha não é editável.
- **Equipe** (`/dashboard/usuarios`): restrita a admin, com criação/edição em modal; não existe exclusão — desativa-se (`ativo = false`) para preservar a trilha; admin não edita a própria conta.
- **Login** (`/login`): formulário próprio, erro específico para credencial inválida, retorno ao `destino`.
- **Rotas curtas**: `/` → `/dashboard`; `/dashboard/alertas` → redirect permanente para `/dashboard/atencao`.

### Acessibilidade

- Foco visível com traço de 2 px + halo em qualquer superfície; `scroll-margin-top` evita que o header sticky cubra o alvo focado (2.4.11).
- Modais, drawers e diálogos com foco preso e devolvido ao gatilho (`useFocoPreso`), fechamento por Esc e ação destrutiva fora do foco inicial.
- Padrões APG em `combobox`/`listbox`, `dialog`, `tablist`, `switch`, `progressbar` e `status`.
- Anúncios por `aria-live="polite"` (paginação, contagens, cópia, refetch) e `aria-busy` em controle ocupado; ícones decorativos com `aria-hidden`.
- Alvos de 40 px em controles isolados, linhas de 40–44 px, reflow a 320 px com sidebar em drawer.
- Estados sempre com ícone + palavra + cor; erros ligados ao campo por `aria-describedby`.

### Segurança

- Confirmações nativas (`window.confirm`/`alert`/`prompt`) eliminadas: `DialogoConfirmacao` com consequência, impacto e, em ações irreversíveis em massa, texto digitado.
- Credenciais de integração nunca voltam ao navegador; remoção exige confirmação.
- Ações administrativas (backup, teste de backup, reset, equipe) gated por papel com controle desabilitado e motivo, nunca ocultas pela metade.
- `robots: noindex, nofollow` no metadata.

### Removido

`components/ui.tsx`, `components/icons.tsx`, `Topbar.tsx`, `Sidebar.tsx` (versão antiga), `StatusDot.tsx`, `Toast.tsx` (versão antiga), `DocumentoDrawer.tsx`, `PainelImportacao.tsx`, `PeriodoPicker.tsx`, `CompetenciaPicker.tsx`, `SeletorEmpresas.tsx` (versão antiga) e `lib/auth.ts` (o papel vinha de cache próprio e divergia da sessão).

Saem junto: gradientes, blur decorativo, brilho/glow, cartões que levantavam no hover, ícone em círculo pastel, pesos 700/800, rótulos de 10 px, animação global de página, esqueleto genérico, ilustração de vazio, segunda cor de acento, selo redundante de automação, rodapé operacional e qualquer cor sem significado.

### Verificação

- `npm run typecheck` (`tsc --noEmit`, `strict` + `noUnusedLocals` + `noUnusedParameters`): sem erro.
- `npm run build`: sem erro; 18 rotas geradas, `output: "standalone"`.
- Sem `console.*`, `any`, `@ts-ignore`/`@ts-expect-error`, `TODO`/`FIXME`, `window.confirm|alert|prompt` ou `@import` de fonte.
- Toda página que lê `useSearchParams` está dentro de `<Suspense>`.

### Operação

Variáveis preservadas: `NEXT_PUBLIC_API_URL` (vazio no preview com proxy), `PREVIEW_PROXY=1` + `PREVIEW_API` (o Next encaminha as chamadas de API), `NEXT_ALLOWED_DEV_ORIGINS` (hosts aceitos pelo dev server — necessário para o preview). `next.config.mjs` mantém `output: "standalone"` e as `rewrites`.
