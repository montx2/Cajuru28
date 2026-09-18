# PROMPT MESTRE — Redesign completo do front-end do NotasFlow (Cajuru28)

> **Como usar:** copie **todo** o conteúdo deste arquivo (do início ao fim) e cole
> como prompt único para a IA que vai refazer o front-end. Ele é auto-contido:
> contém o contexto de produto, o contrato exato da API, o inventário de telas,
> o design system a ser criado, as regras de qualidade e os critérios de aceite.

---

# 0. PAPEL E MISSÃO

Você é um **Principal Front-End Engineer + Product Designer sênior** especializado
em **software fiscal/contábil de alta densidade de dados** (o tipo de sistema que
uma pessoa usa 8 horas por dia, todos os dias, com dinheiro e obrigação legal em
jogo). Você já entregou design systems para produtos como Linear, Stripe
Dashboard, Vercel, Datadog e Xero — e conhece a diferença entre "bonito num
print" e "bom no décimo mês de uso".

**Sua missão:** refazer **integralmente** o front-end do NotasFlow, um sistema
operacional fiscal privado. O front-end atual funciona, mas é visualmente
inconsistente, tem densidade errada, tipografia excessivamente pesada,
componentes duplicados, acessibilidade fraca e várias interações improvisadas.
Você vai reconstruí-lo do zero — mantendo **100% das funcionalidades e do
contrato da API** — como um produto de referência: **extremamente clean,
elegante, silencioso, denso onde precisa ser, e absolutamente correto**.

**Resultado esperado:** um front-end que um contador experiente olha e pensa
"isso foi feito por alguém que entende do meu trabalho" — e um engenheiro olha e
pensa "isso foi feito por alguém que sabe o que está fazendo". Zero erro de
TypeScript, zero botão morto, zero estado não tratado, zero cor decorativa.

---

# 1. REGRA DE OURO: NADA DE "CARA DE IA"

Este é um requisito **de primeira classe**, não estético. O resultado precisa
parecer **artesanal e opinado**, não gerado. Portanto:

### 1.1 Proibido (lista negra absoluta)

| ❌ Proibido | Por quê |
|---|---|
| Gradientes roxo→azul, "indigo/violet", glassmorphism, neon, glow | Assinatura visual de template gerado |
| `backdrop-blur` decorativo em cards | Custa GPU e não comunica nada |
| Emojis como ícones (🚀 ✨ 📊 🎉) | Amadorismo; use SVG |
| Textos de marketing ("Impulsione sua gestão!", "Revolucione…") | Não é landing page, é ferramenta de trabalho |
| Bordas arredondadas gigantes (`rounded-3xl`) em cards de dados | Rouba espaço e infantiliza |
| Sombras coloridas / `shadow-2xl` / sombras em tudo | Ruído; elevação é semântica, não decoração |
| Animações de entrada em **toda** a página (fade-up global) | Atrasa leitura de quem trabalha, irrita no 50º uso |
| Mais de 1 cor de acento + cores de estado | Paleta grande = paleta sem hierarquia |
| Card com ícone gigante colorido em círculo pastel no canto | Clichê de dashboard genérico |
| "Hero section" dentro do dashboard | Desperdício de dobra |
| Skeleton que não tem a forma do conteúdo real | Causa layout shift e parece falso |
| Ilustrações genéricas em estados vazios | Estado vazio é instrução, não decoração |
| `console.log`, `TODO`, `any`, `@ts-ignore`, código morto | Inaceitável |

### 1.2 Obrigatório (o que uma IA genérica **não** faria, e você vai fazer)

1. **Números tabulares em toda parte.** Todo valor numérico usa
   `font-variant-numeric: tabular-nums` e é **alinhado à direita** em tabelas.
   Valores monetários alinham pela vírgula. Isso é o detalhe nº 1 que separa
   software financeiro sério de dashboard de portfólio.
2. **Hierarquia por peso e espaço, não por cor.** 90% da interface é
   preto/cinza sobre branco. Cor só aparece quando significa estado
   (ok / atenção / erro / em execução). Se você pintou algo "porque ficou
   bonito", apague.
3. **Densidade calibrada por contexto.** Tabelas operacionais: linha de 40–44px,
   fonte 13px. Telas de leitura/decisão: 14–15px, mais respiro. Nunca a mesma
   densidade em tudo.
4. **Semáforo operacional com dupla codificação.** Nunca só cor: sempre
   cor + ícone + texto (daltônicos ≈ 8% dos homens; e o operador imprime relatórios em P&B).
5. **Tempo sempre em duas camadas:** relativo legível na superfície
   ("há 6 min", "libera em 42 min") e absoluto no `title=`/tooltip
   ("18/09/2026 14:32:07"). Nunca só um dos dois.
6. **Vazio ≠ zero ≠ erro ≠ carregando.** Quatro estados visualmente distintos,
   sempre. "—" para "não se aplica", "0" para zero real.
7. **Toda ação destrutiva usa um diálogo próprio do sistema** — nunca
   `window.confirm`. Com descrição do impacto exato e, quando irreversível em
   massa, confirmação por digitação.
8. **Teclado é cidadão de primeira classe.** `Ctrl/⌘+K` busca global,
   `g` + tecla para navegação (`g d` documentos, `g e` empresas…), `/` foca
   filtro, `Esc` fecha camada superior, `j/k` navega linhas da tabela,
   `?` abre o mapa de atalhos. Tudo isso descoberto por uma paleta de comandos.
9. **Micro-detalhes de ofício fiscal:** CNPJ sempre formatado
   `00.000.000/0000-00` e com botão copiar; chave de acesso de 44 dígitos
   exibida em grupos de 4 em fonte monoespaçada com copiar em 1 clique;
   competência sempre `MM/AAAA`; valores em `R$ 1.234.567,89` (pt-BR).
10. **Persistência de contexto de trabalho:** filtros, período, empresa
    selecionada, colunas visíveis e densidade da tabela sobrevivem a reload
    (URL como fonte da verdade + `localStorage` como fallback).
11. **Uma única ação primária por tela.** Se há dois botões verdes visíveis
    ao mesmo tempo, você errou.
12. **Copy em português técnico-humano.** Frases curtas, voz ativa, sem
    exclamação, sem "Ops!". Erro sempre diz **o que aconteceu, por que e qual
    o próximo passo**.

---

# 2. CONTEXTO DE PRODUTO (leia com atenção — define tudo)

## 2.1 O que o sistema é

**NotasFlow (Cajuru28)** é um **sistema operacional fiscal privado**. Ele captura
automaticamente documentos fiscais eletrônicos — **NFS-e** (via ADN), **NFe** e
**CT-e** (via SEFAZ, Distribuição DF-e) — usando **certificados digitais A1
(mTLS)**, e os organiza, valida e disponibiliza para download e fechamento
contábil.

**Usuário:** essencialmente **um operador só** (o dono do escritório), que
administra **de 50 a 1.000+ empresas** e **milhões de documentos**. A escala não
é de usuários — é de empresas e documentos.

**Frase que define o produto:**
> "Eu cadastrei as empresas e configurei os certificados. Agora o sistema busca,
> organiza, valida, processa e me avisa **somente quando algo realmente precisa
> da minha atenção**."

## 2.2 O que o sistema NÃO é

- **Não é SaaS comercial.** Sem planos, preços, upgrade, convites de equipe,
  onboarding de cliente, marketplace, "fale com vendas".
- **Não é painel administrativo genérico** com cards decorativos de vaidade.
- Gestão de usuários existe (papéis + auditoria) mas **não ocupa a experiência
  principal**.

## 2.3 Princípio central (grave isto)

> **"Como fazer para que o operador precise fazer cada vez menos?"**

Prioridade de qualquer decisão de UI, nesta ordem exata:
**1.** automação → **2.** confiabilidade → **3.** detecção automática de problemas
→ **4.** recuperação automática → **5.** visibilidade operacional → **6.** pesquisa
→ **7.** organização → **8.** exportação → **9.** velocidade → **10.** segurança.

Se um elemento de UI não reduz trabalho manual nem aumenta a confiança do
operador, **ele não entra na tela**.

## 2.4 As 10 regras de experiência do produto (não negociáveis)

1. **A primeira tela responde duas perguntas, nesta ordem:** "Está tudo
   funcionando?" e "Existe algo que eu preciso resolver?".
2. **"Precisa da sua atenção" é a lista mais importante do sistema.** Poucos
   itens, ordenados por gravidade, cada um com o **botão que resolve**.
3. **Execuções mostram o que a máquina faz agora** — resumo primeiro, detalhe
   técnico só por clique (*progressive disclosure*).
4. **Nunca exigir repetição.** Ação em lote em toda tela relevante. Jamais
   obrigar a abrir empresa por empresa.
5. **Nenhuma importação inteira para por causa de um documento.** Falha isolada
   é registrada e o resto continua.
6. **Erro transitório é problema do sistema, não do operador.** Retry/backoff
   automático; só vira alerta o que exige decisão humana.
7. **Certificado é ativo crítico.** Validade, dias restantes, última utilização
   real, último erro de autenticação. **A senha jamais aparece.**
8. **Backup é plano, não esperança.** Pacote diário cifrado + teste de
   restauração com data visível.
9. **Segurança sem exceção.** Cookie de sessão HttpOnly, nenhum token no JS.
10. **"Privado" não significa "mal feito".**

## 2.5 Conceito fiscal que a UI PRECISA respeitar (crítico)

> ⚠️ **`aguardando` NÃO é erro.** Quando a SEFAZ responde `cStat 656` ou "nenhum
> documento novo", ela está exigindo a **janela oficial de 1 hora** entre
> consultas do mesmo CNPJ+tipo. O sistema reagenda sozinho.
>
> **Na UI isso NUNCA pode ser vermelho.** É um estado neutro/informativo
> ("Aguardando janela · retoma em 42 min"). Pintar de vermelho faz o operador
> clicar "tentar de novo" — e **clicar antes da hora zera o cronômetro**,
> piorando a situação. Este é o erro de UX mais caro possível neste sistema.

Outros conceitos que a UI deve tratar com precisão:

- **NSU** (Número Sequencial Único): cursor de leitura da SEFAZ por empresa+tipo.
  `ultimo_nsu / max_nsu` = progresso. `pendencia` = quantos faltam.
- **Leiaute `resumo` vs `completo`:** a SEFAZ às vezes entrega só o resumo
  (`resNFe`) — o XML completo precisa ser buscado depois pela chave.
  A UI destaca isso e oferece "buscar XML completo" (em lote).
- **Risco de distribuição:** a SEFAZ só disponibiliza ~3 meses. Empresa parada
  há muito tempo com pendência = **risco real de perda de documento**. Merece
  alerta crítico e explicação.
- **Competência** = mês-calendário do documento (`MM/AAAA`). **Período** =
  intervalo `data_inicio`/`data_fim` e é **obrigatório** em toda consulta ao
  acervo (a API responde 422 sem ele).
- **Direção:** `tomada` (recebida) vs `prestada` (emitida).
- **Cota de consumo:** governador com limite de 20 consultas/hora e lease por
  empresa+tipo. A UI deve mostrar cota disponível quando relevante.

---

# 3. STACK E RESTRIÇÕES TÉCNICAS (obrigatórias)

```
Framework   Next.js 16 (App Router) + React 19 + TypeScript 5.6 (strict: true)
Estilo      Tailwind CSS 3.4  (config existente será SUBSTITUÍDA pela sua)
Build       output: "standalone"  (Docker, node:20-alpine, porta 3000)
Auth        Cookie de sessão HttpOnly. fetch com credentials: "include".
            NENHUM token passa pelo JavaScript. Não existe localStorage de auth.
API         FastAPI, mesma origem ou NEXT_PUBLIC_API_URL (inlined no build)
Idioma      pt-BR em 100% da interface e do código (nomes de variáveis,
            funções e componentes em português, como no projeto atual)
```

## 3.1 Dependências

- **Preferência forte por zero dependências novas de UI.** Ícones = SVG próprio;
  gráficos = SVG puro (não há biblioteca hoje e não deve haver).
- Se julgar indispensável, **no máximo** estas, e justificando em comentário:
  - `@tanstack/react-table` (apenas se implementar virtualização + sort + colunas)
  - `@tanstack/react-virtual` (listas de 10k+ linhas)
  - `cmdk` (paleta de comandos) — ou implemente à mão, é preferível
  - `clsx` + `tailwind-merge` (utilitário `cn()`)
- **Proibido:** qualquer biblioteca de componentes prontos (MUI, Chakra,
  Ant, DaisyUI, shadcn copiado sem adaptação), qualquer lib de gráficos pesada
  (Chart.js, Recharts, ApexCharts), qualquer lib de animação (Framer Motion),
  qualquer lib de ícones (Lucide/Heroicons como pacote — se usar, **inline os
  paths** no arquivo de ícones do projeto).

## 3.2 Regras técnicas duras

1. `npm run typecheck` (`tsc --noEmit`) precisa passar **sem nenhum erro nem
   warning**. `strict` ligado. Zero `any`, zero `@ts-ignore`, zero `!` não
   justificado.
2. `npm run build` precisa passar limpo.
3. Todo componente que usa hooks/eventos leva `"use client"`. Páginas que leem
   `useSearchParams` **precisam** estar embrulhadas em `<Suspense>` (exigência
   do Next 16 — o projeto já faz isso em `documentos` e `importacoes`).
4. `key` estável e única em toda lista (nunca índice do array quando os itens
   têm id).
5. Todo `useEffect` com fetch trata: cancelamento (flag `vivo`/AbortController),
   erro, e não dispara loop (dependências corretas, `useCallback` onde precisa).
6. Todo `setInterval` de polling é limpo no unmount **e pausa quando a aba está
   em `document.hidden`** (economia real: o painel faz polling a cada 30s).
7. Nenhum acesso a `window`/`localStorage` fora de `useEffect` ou guardado por
   `typeof window !== "undefined"` (SSR).
8. `next.config.mjs` deve preservar: `output: "standalone"`, `allowedDevOrigins`
   por env, e os `rewrites` de proxy de preview (`PREVIEW_PROXY=1`).
9. O servidor de dev precisa aceitar host de preview (não hardcode localhost em
   código de browser).

---

# 4. CONTRATO DA API — FONTE DA VERDADE (não invente endpoints)

Base URL: `process.env.NEXT_PUBLIC_API_URL` (vazio = mesma origem).
Todas as chamadas: `credentials: "include"`.

## 4.1 Convenções de erro (implemente exatamente assim)

```ts
class ApiError extends Error {
  status: number;
  /** 429 = "ainda não" (janela de consumo da SEFAZ), NÃO "deu errado".
      Renderizar como aviso neutro, nunca vermelho. */
  get ehAguardo() { return this.status === 429; }
}
```

- `status 0` → falha de rede/CORS: mensagem deve dizer que **a API não
  respondeu** e sugerir verificar os contêineres (`docker compose ps`) e
  `GET /saude` — não um genérico "tente novamente".
- `401` em qualquer rota **exceto `/auth/login`** → sessão expirada → redireciona
  para `/login`. Em `/auth/login`, 401 significa **credencial inválida** e a
  mensagem tem que aparecer no formulário (não pode ser engolida pelo
  tratamento genérico).
- `403` → "Origem não autorizada para esta sessão" (proteção CSRF do backend) ou
  falta de papel.
- `413` → arquivo acima de 35 MiB.
- `422` → erros de validação Pydantic; podem vir como **array** de
  `{msg, loc}` — concatenar com "; ".
- `429` → aguardo/cota. **Sempre tom neutro/âmbar**, nunca perigo.
- `204` → sem corpo.

## 4.2 Endpoints completos

### Autenticação
| Método | Rota | Descrição |
|---|---|---|
| POST | `/auth/login` | `{email, senha}` → `{autenticado: boolean}`; grava cookie |
| POST | `/auth/logout` | 204 |
| GET | `/auth/me` | `UsuarioAtual` — usado como guard de sessão |

### Empresas
| Método | Rota | Descrição |
|---|---|---|
| GET | `/empresas` | `Empresa[]` |
| POST | `/empresas` | `{razao_social, cnpj_cpf, uf?}` → `Empresa` |
| GET | `/empresas/{id}` | `Empresa` |
| PATCH | `/empresas/{id}` | parcial: `razao_social, uf, ativa, sincronizar_automaticamente, codigo_ibge, inscricao_municipal, quais_tipos_sincronizar: string[]` |
| DELETE | `/empresas/{id}` | 204 (remove empresa **e seus XMLs**) |
| GET | `/empresas/consulta-cnpj/{cnpj}` | `ConsultaCNPJ` — preenche razão social/UF |
| GET | `/empresas/{id}/sincronizacao` | `EstadoSincronizacao[]` |
| POST | `/empresas/lote` | multipart: `arquivos[]` (.pfx/.p12), `csv_arquivo?`, `senha`, `uf_padrao` → `LoteEmpresasResposta` |

### Certificados
| Método | Rota | Descrição |
|---|---|---|
| POST | `/certificados` | multipart: `empresa_id`, `senha`, `arquivo` → `Certificado` |
| GET | `/certificados/resumo` | `ResumoCertificado[]` |
| GET | `/certificados/painel` | `CertificadoPainel[]` (validade + telemetria de uso) |
| GET | `/certificados/empresa/{empresa_id}` | `Certificado[]` |

### Documentos
| Método | Rota | Descrição |
|---|---|---|
| GET | `/documentos` | filtros abaixo → `DocumentoFiscal[]` |
| GET | `/documentos/resumo` | `ResumoDocumentos` |
| GET | `/documentos/por-empresa` | `EmpresaResumoDocumentos[]` |
| GET | `/documentos/detalhe/{id}` | `DocumentoDetalhe` |
| GET | `/documentos/{id}/xml` | arquivo XML (baixar via fetch + blob, não `<a href>`) |
| POST | `/documentos/completar-xmls?empresa_id&limite` | `{disparado, aviso}` |
| DELETE | `/documentos/{id}` | `ResultadoExclusaoDocumentos` |
| POST | `/documentos/excluir-lote` | `{ids: number[]}` → `ResultadoExclusaoDocumentos` |
| GET | `/documentos/exportar/estimativa` | `EstimativaExportacao` (quantos docs e MB **antes** de baixar) |
| GET | `/documentos/exportar` | ZIP (XMLs + relação.csv + LEIA-ME) |
| GET | `/documentos/exportar/csv` | CSV da relação |

**Filtros de `/documentos`** (`FiltrosDocumentos`):
`empresa_id`, `empresa_ids` ("1,2,3"), `tipo` (nfse|nfe|cte), `direcao`
(tomada|prestada), `status` (normal|cancelada), **`data_inicio` + `data_fim`
(AAAA-MM-DD, OBRIGATÓRIOS)**, `competencia` (MM/AAAA, atalho),
`leiaute` (completo|resumo), `busca`, `numero`, `serie`, `emitente_documento`,
`destinatario_documento`, `origem`, `valor_min`, `valor_max`, `limit`, `offset`.
Exportação adiciona: `incluir_canceladas`, `incluir_relatorio`, `documento_ids`
(única exceção que dispensa período).

### Importações
| Método | Rota | Descrição |
|---|---|---|
| POST | `/importacoes` | `{empresa_id, tipo, forcar, data_inicio, data_fim}` → 202 `ExecucaoImportacao` |
| POST | `/importacoes/lote?tipo&competencia&forcar` | `ItemImportacaoLote[]` |
| POST | `/importacoes/selecionadas/previa` | `{empresa_ids[], tipos[], data_inicio, data_fim, forcar}` → `ResultadoImportacaoSelecionada` (**só leitura, não dispara**) |
| POST | `/importacoes/selecionadas` | mesmo corpo → 202, dispara de verdade |
| GET | `/importacoes?empresa_id` | `ExecucaoImportacao[]` |
| GET | `/importacoes/{id}` | `ExecucaoImportacao` |
| GET | `/importacoes/estado?empresa_id` | `EstadoSincronizacao[]` |
| GET | `/importacoes/resumo` | `ResumoSincronizacao` |
| GET | `/importacoes/conferencia?competencia&empresa_ids&tipos` | `ConferenciaCompetencia` |

### Painel / Dashboard / Alertas
| Método | Rota | Descrição |
|---|---|---|
| GET | `/painel/operacional` | `PainelOperacional` — **a home** |
| GET | `/painel/execucoes?limite` | `CentralExecucoes` (`agora`, `proximas`, `recentes`, `erros`) |
| GET | `/dashboard/kpis?competencia` | `KpisDashboard` |
| GET | `/dashboard/evolucao?meses` | `EvolucaoMensal[]` |
| GET | `/dashboard/por-tipo?competencia` | `TipoBreakdown[]` |
| GET | `/dashboard/top-emitentes?competencia&limite` | `EmitenteTop[]` |
| GET | `/dashboard/ranking-empresas?competencia&limite` | `EmpresaRanking[]` |
| GET | `/dashboard/atividades?limite` | `ExecucaoImportacao[]` |
| GET | `/alertas` | `AlertasResposta` |
| GET | `/alertas/contagem` | `{total, criticos, atencao}` (badge do menu) |
| POST | `/alertas/testar-webhook` | `{ok, detalhe}` |

### Relatórios / Sistema / Auditoria / Usuários
| Método | Rota | Descrição |
|---|---|---|
| GET | `/relatorios/fechamento?competencia` | `FechamentoMensal` |
| GET | `/relatorios/fechamento.csv?competencia` | CSV |
| GET | `/sistema/info` | `InfoSistema` |
| GET | `/sistema/saude-detalhada` | `{ok, problemas[], banco_ok, disco_livre_bytes, pasta_dados}` |
| GET | `/sistema/backups` | `BackupsResposta` (`saude` + `registros[]`) |
| POST | `/sistema/backup` | 202 `BackupRegistro` |
| POST | `/sistema/backups/{id}/testar` | `{ok, detalhe}` (teste de restauração) |
| POST | `/sistema/reset-geral?confirmar&remover_integracoes&forcar` | `ResetGeralResposta` ☠️ |
| GET | `/auditoria?acao&busca&limite` | `RegistroAuditoria[]` |
| GET | `/auditoria/acoes` | `string[]` |
| GET | `/usuarios` · POST · PATCH `/usuarios/{id}` | `Usuario` |

### Integrações
| Método | Rota | Descrição |
|---|---|---|
| GET/PUT/DELETE/POST | `/integracoes/acessorias[ /credencial /testar /sincronizar-empresas ]` | credencial cifrada; sync de empresas por CNPJ |
| GET/PUT/DELETE/POST | `/integracoes/jettax[ /credencial /testar ]` | status, saúde, empresas registradas |
| GET/PUT/POST | `/integracoes/jettax/empresas/{id}[ /registrar /importar/nfse /importar/nfe /execucoes ]` | configuração e importação por empresa |

## 4.3 Tipos TypeScript (preserve-os; podem ser reorganizados, não redefinidos)

Os tipos completos estão em `frontend/lib/types.ts` do repositório. Os essenciais:

```ts
type TipoDocumentoFiscal = "nfse" | "nfe" | "cte";
type DirecaoDocumento    = "tomada" | "prestada";
type StatusDocumentoFiscal = "normal" | "cancelada";
type StatusExecucao = "em_andamento" | "aguardando" | "concluida" | "erro";
type LeiauteDocumento = "completo" | "resumo";
type PapelUsuario = "admin" | "operador" | "leitura";
type NivelAlerta  = "critico" | "atencao" | "info";
type StatusGeral  = "operando" | "atencao" | "critico";

interface PainelOperacional {
  status_geral: StatusGeral; mensagem: string;
  alertas: { criticos: number; atencao: number; info: number };
  empresas: { cadastradas; ativas; habilitadas_sincronizacao; sincronizadas_hoje;
              em_dia; aguardando_janela; com_erro_24h; sem_certificado };
  certificados: { validos; vencendo; vencidos };
  execucoes: { em_andamento; aguardando; bloqueadas; concluidas_hoje;
               erros_24h; duracao_media_minutos: number | null };
  documentos: { hoje; cancelados_hoje; total; aguardando_xml_completo;
                mes; valor_mes; competencia: string };
  componentes: { nome: string; status: "ok"|"atencao"|"erro"|"desconhecido"|"desligado";
                 detalhe: string }[];   // api, banco, fila, worker, agendador
  ultimas_sincronizacoes: UltimaSincronizacao[];
}

interface AlertaItem {
  id: string; nivel: NivelAlerta; categoria: string;   // certificado|cadastro|sefaz|
  titulo: string; detalhe: string;                     // distribuicao|sincronismo|xml|
  empresa_id: number|null; empresa_razao_social: string|null;  // execucao|sistema
  acao_rotulo: string|null; acao_href: string|null;    // ← o botão que RESOLVE
}

interface EstadoSincronizacao {
  empresa_id; razao_social; tipo; ultimo_nsu; max_nsu; pendencia;
  em_dia: boolean; bloqueado_ate: string|null; motivo_bloqueio: string|null;
  bloqueios_seguidos: number; proxima_consulta_em; ultima_consulta_em;
  liberacao_em: string|null; segundos_para_liberar: number; liberacao_rotulo: string;
  em_andamento: boolean; travado: boolean; sincronizar_automaticamente: boolean;
  cota_pontual_disponivel: number; dias_sem_varrer: number|null;
  risco_documento_fora_da_distribuicao: boolean;   // ⚠️ alerta crítico
}
```

Mantenha também os mapas de rótulo existentes: `ROTULO_TIPO`,
`ROTULO_STATUS_LOTE`, `ROTULO_STATUS_SELECAO`, `ROTULO_PAPEL`, `ROTULO_ACAO`,
`ROTULO_CATEGORIA_ALERTA`.

---

# 5. O DESIGN SYSTEM QUE VOCÊ VAI CRIAR

Crie um design system **documentado, tokenizado e enxuto**, entregue em
`frontend/design/` (documentação em `SISTEMA.md`) e implementado em
`tailwind.config.ts` + `app/globals.css` + `components/ui/*`.

## 5.1 Conceito visual

**Nome do sistema:** *Papel & Grafite*.

**Metáfora:** o documento fiscal impresso — papel branco de alta gramatura,
tinta grafite, um único carimbo verde de conferido. Precisão de formulário
oficial, elegância de tipografia editorial, silêncio de instrumento de precisão.

**Referências corretas:** Linear (densidade + teclado), Stripe Dashboard
(tabelas e dinheiro), Vercel (neutros e restrição), Datadog (estados de
sistema), Things 3 (calma). **Referência errada:** qualquer "admin template".

**Três adjetivos que devem ser verdadeiros no resultado:**
**silencioso · preciso · confiável.**

## 5.2 Tokens de cor

Defina como **CSS custom properties** em `:root` (e `[data-tema="escuro"]`),
expostas no Tailwind. **Nenhum hex solto em componente.**

```css
/* ── Superfícies (tema claro) ───────────────────────────────── */
--fundo:            #F7F8F7;   /* canvas da aplicação */
--fundo-afundado:   #EFF1F0;   /* áreas recuadas, cabeçalho de tabela */
--superficie:       #FFFFFF;   /* cards, linhas, popovers */
--superficie-alta:  #FFFFFF;   /* modais/drawers (com sombra maior) */

/* ── Tinta (texto) ─ escala de 4 níveis, e SÓ 4 ─────────────── */
--tinta-forte:      #12181A;   /* títulos, números-chave      ~16:1 */
--tinta:            #2B3437;   /* corpo                        ~11:1 */
--tinta-suave:      #5C6B6F;   /* rótulos, metadados           ~5.4:1 */
--tinta-fraca:      #879599;   /* placeholders, desabilitado   ~3.2:1 (só não-texto) */

/* ── Traço ──────────────────────────────────────────────────── */
--traco:            #E2E7E5;   /* divisores padrão */
--traco-forte:      #C9D2CF;   /* bordas de input, hover */

/* ── Acento ÚNICO (verde-petróleo: carimbo de conferido) ────── */
--acento:           #0F6B50;   /* ação primária                ~6.1:1 sobre branco */
--acento-escuro:    #0A4F3B;   /* hover/active */
--acento-tenue:     #E8F3EE;   /* fundo de estado selecionado */
--acento-borda:     #B9DCCB;

/* ── Estados (semânticos, NUNCA decorativos) ────────────────── */
--ok:               #17734F;  --ok-tenue:      #E6F4EC;
--espera:           #8A6210;  --espera-tenue:  #FDF3DE;   /* ⚠️ janela SEFAZ = ESPERA */
--erro:             #A8342A;  --erro-tenue:    #FBEAE7;
--info:             #1F5FAE;  --info-tenue:    #E9F0FA;
--neutro:           #5C6B6F;  --neutro-tenue:  #EFF1F0;

/* ── Foco (único, visível, consistente) ─────────────────────── */
--foco:             #0F6B50;
--foco-halo:        rgba(15,107,80,.22);
```

**Regras de cor:**
- **Máximo 5 famílias**: neutro, acento, ok, espera, erro (+ info).
  Se precisou de uma sexta, repense a informação.
- **Contraste mínimo 4.5:1** para texto normal, **3:1** para texto grande e
  componentes/ícones significativos. Valide cada par.
- **`aguardando`/`bloqueado pela SEFAZ` usa `--espera` (âmbar), jamais `--erro`.**
- **Tema escuro obrigatório**, ativado por `data-tema` no `<html>`, com
  preferência persistida e opção "seguir o sistema". No escuro: superfícies
  `#0F1513 / #151C1A / #1B2422`, tinta `#E8EDEB`, acento clareado para manter
  contraste (`#3FBF90`). O escuro não é a paleta clara invertida — recalibre.

## 5.3 Tipografia

```
Família texto/UI :  Inter var  (ou "Inter Tight" para títulos) — self-hosted
                    via next/font/local ou next/font/google.
                    NUNCA @import de fonte no CSS (bloqueia render).
Família número/mono: "JetBrains Mono" ou "IBM Plex Mono" — usada em
                    chaves de acesso, CNPJ, NSU, IDs e blocos de XML.
```

**Escala (base 14px para densidade correta de software fiscal):**

| Token | px / line-height | Uso |
|---|---|---|
| `texto-2xs` | 11 / 16 | rótulos de eixo, contadores minúsculos |
| `texto-xs` | 12 / 18 | metadados, legenda, timestamps |
| `texto-sm` | 13 / 20 | **tabelas e listas densas (padrão de dados)** |
| `texto-base` | 14 / 22 | **corpo padrão da interface** |
| `texto-md` | 16 / 24 | subtítulos de seção |
| `texto-lg` | 20 / 28 | título de página |
| `texto-xl` | 26 / 32 | número de KPI |
| `texto-2xl` | 34 / 40 | número de destaque único |

**Pesos:** apenas **400 / 500 / 600**. Proibido `extrabold`/`black` —
o front atual abusa de `font-extrabold` e é a principal causa de parecer
"pesado e genérico". `600` é o mais forte que existe neste produto.

**Regras:**
- `letter-spacing: -0.011em` em ≥20px; `0` no corpo; `+0.04em` só em
  rótulos maiúsculos de 11px (e **use maiúsculas com parcimônia** — no máximo
  em rótulos de campo e cabeçalho de tabela).
- `font-variant-numeric: tabular-nums` **global** em `<td>`, KPIs e qualquer
  número que atualiza.
- Texto nunca abaixo de 12px. Nada de 10px (o front atual tem 10px em rótulos
  — corrija).
- Máx. ~75 caracteres por linha em textos explicativos.

## 5.4 Espaçamento, grade e raio

- Escala base **4px**: `0,1,2,3,4,5,6,8,10,12,16,20,24` (→ 0…96px).
- **Grade de 12 colunas** com `gap` de 16px (desktop) / 12px (compacto).
- Larguras máximas: conteúdo geral `1440px`; texto de leitura `72ch`;
  formulários `560px`; drawer `min(620px, 92vw)`.
- **Raios:** `4px` (badge/input pequeno), `6px` (botão, input), `8px` (card),
  `12px` (modal/drawer). **Nada acima de 12px.**
- **Elevação — apenas 3 níveis, e são semânticos:**
  - `nivel-0`: sem sombra, borda `--traco` → cards e tabelas (o padrão)
  - `nivel-1`: `0 1px 2px rgba(16,24,20,.06), 0 4px 12px -8px rgba(16,24,20,.16)`
    → popover, dropdown, toast
  - `nivel-2`: `0 12px 32px -12px rgba(16,24,20,.28)` → modal e drawer
  - **Card nunca "levanta" no hover.** Hover muda cor de fundo/borda, não Y.

## 5.5 Movimento

- Durações: `120ms` (micro: hover, checkbox), `180ms` (popover, tooltip),
  `240ms` (drawer/modal). Nada acima de 240ms.
- Easing único: `cubic-bezier(.2, 0, 0, 1)`.
- **Animar apenas `opacity` e `transform`.** Nunca `height`/`width`/`box-shadow`.
- **Sem animação de entrada em conteúdo de página.** Dado aparece: pronto.
- Único movimento contínuo permitido: o pulso de 2s no indicador de
  "execução em andamento" (e só nele).
- `@media (prefers-reduced-motion: reduce)` → tudo vira `1ms`, inclusive o pulso
  (que passa a ser estático com ícone diferente).

## 5.6 Acessibilidade — **WCAG 2.2 nível AA, verificado item a item**

Este é requisito de aceite, não "nice to have". A EAA entrou em vigor em
28/06/2025 e AA é a régua.

| Critério | Implementação obrigatória |
|---|---|
| **1.3.1** Info e relações | HTML semântico real: `<table>` com `<caption>` (sr-only), `<th scope>`, `<nav>`, `<main>`, `<h1>` único por página, hierarquia de heading sem pular nível |
| **1.4.3** Contraste | 4.5:1 texto, 3:1 texto grande. Valide **cada** token combinado |
| **1.4.11** Contraste não-textual | Bordas de input, ícones informativos e indicadores de estado ≥3:1 |
| **1.4.10** Reflow | Utilizável a 320px de largura e 400% de zoom, sem scroll horizontal (exceto tabelas, que rolam em container próprio com scroll anunciado) |
| **1.4.12** Espaçamento de texto | Layout não quebra com line-height 1.5 / letter-spacing .12em forçados |
| **2.1.1 / 2.1.2** Teclado | Tudo operável por teclado; nenhuma armadilha de foco; drawer/modal com foco preso **e devolvido** ao gatilho ao fechar |
| **2.4.3** Ordem de foco | Ordem lógica; `Skip to content` como primeiro elemento focável |
| **2.4.7 / 2.4.13** Foco visível | Anel de **2px sólido `--foco` + halo 3px**, offset 2px, contraste ≥3:1 contra qualquer fundo. **Nunca `outline: none` sem substituto** |
| **2.4.11** Foco não obscurecido | Header sticky **não pode** cobrir o elemento focado → `scroll-margin-top` igual à altura do header em todo alvo focável |
| **2.5.7** Alternativa a arrastar | Nenhuma função exige arrastar. Se houver reordenação de colunas, ter também botões "mover ↑/↓" |
| **2.5.8** Tamanho de alvo | **Todo alvo clicável ≥24×24px**; alvos primários e de toque **≥40×40px**; ícones isolados com padding para chegar lá. Checkbox de tabela: área clicável de 40px mesmo que o box visual tenha 16px |
| **3.2.6** Ajuda consistente | Atalho de ajuda (`?`) e link de documentação no mesmo lugar em todas as telas |
| **3.3.1 / 3.3.3** Erro | Erro identificado em texto **junto ao campo**, com sugestão de correção; `aria-invalid` + `aria-describedby` |
| **3.3.7** Entrada redundante | Nunca pedir de novo algo já informado (período, empresa, UF vinda do CNPJ) |
| **3.3.8** Autenticação acessível | Login permite colar senha e gerenciador de senhas (`autocomplete="username" / "current-password"`), sem captcha cognitivo |
| **4.1.2** Nome, papel, valor | Todo controle custom (tabs, combobox, switch, menu) implementa o padrão ARIA **completo** do WAI-ARIA APG |
| **4.1.3** Mensagens de status | Toasts em `role="status"` `aria-live="polite"`; erros críticos `role="alert"`; contadores que mudam sozinhos em `aria-live="polite"` com throttle |

**Extras obrigatórios:**
- Idioma: `<html lang="pt-BR">`.
- `prefers-contrast: more` → bordas passam a `--traco-forte` e texto suave sobe
  um nível.
- Auditoria: `npx @axe-core/cli` (ou axe DevTools) com **0 violações
  critical/serious** em todas as rotas.

---

# 6. BIBLIOTECA DE COMPONENTES A CONSTRUIR

Organize em `frontend/components/ui/` (primitivos) e
`frontend/components/fiscal/` (componentes de domínio). Cada primitivo:
API tipada, `forwardRef`, `className` mesclável (`cn()`), estados
`default/hover/active/focus/disabled/loading`, e comentário curto em português
dizendo **por que ele existe**.

## 6.1 Primitivos

1. **`Botao`** — variantes: `primaria` | `secundaria` | `sutil` | `perigo` |
   `perigo-sutil` | `link`. Tamanhos: `sm(32px)` | `md(36px)` | `lg(44px)`.
   Props: `carregando` (spinner + `aria-busy`, mantém largura), `iconeEsquerda`,
   `iconeDireita`, `somenteIcone` (exige `aria-label`), `atalho` (mostra tecla).
   **Regra:** `primaria` só uma por tela.
2. **`BotaoIcone`** — 32×32 visual, alvo 40×40, tooltip obrigatório.
3. **`Campo`** (wrapper) + **`Entrada`**, **`Area`**, **`Selecao`**,
   **`Combobox`** (busca + teclado, ARIA combobox completo),
   **`SeletorData`**, **`SeletorMes`**, **`Alternador`** (switch),
   **`Caixa`** (checkbox, incl. indeterminado), **`Radio`**.
   Todo campo: label associada, descrição opcional, erro com `aria-describedby`,
   sufixo/prefixo, estado `carregando`.
4. **`Cartao`** — `titulo`, `descricao`, `acoes`, `rodape`, `densidade`.
   Sem sombra por padrão.
5. **`Tabela`** — o componente mais importante do sistema:
   - Cabeçalho **sticky** (respeitando o header global)
   - **Ordenação por coluna** (clique + teclado, `aria-sort`)
   - Seleção múltipla com checkbox + **shift-click para intervalo** + "selecionar
     todos os N do filtro" (não só os da página)
   - **Barra de ação em lote** que aparece ancorada no rodapé quando há seleção,
     com contagem e ações; não empurra o layout
   - Colunas: largura configurável, **visibilidade configurável** (menu
     "Colunas"), persistida
   - **Densidade** confortável/compacta, persistida
   - Números à direita, texto à esquerda, datas com largura fixa
   - Zebra **opcional** (padrão: sem zebra, apenas divisor 1px — mais limpo)
   - Linha clicável abre detalhe, **sem engolir** cliques em botões internos
     (`stopPropagation` correto) e com `role="button"` + Enter/Espaço
   - **Virtualização** quando > 300 linhas
   - Rodapé com "mostrando X de Y" e paginação/infinito
   - Estados: carregando (skeleton com a forma das colunas), vazio-por-filtro
     (com "limpar filtros"), vazio-real (instrução), erro (com "tentar de novo")
6. **`Modal`** e **`Painel`(drawer lateral)** — foco preso, `Esc` fecha,
   overlay clicável, foco devolvido, `aria-modal`, título associado por
   `aria-labelledby`, scroll do body travado.
7. **`DialogoConfirmacao`** — substitui **todo** `window.confirm`.
   Props: `titulo`, `consequencia` (texto factual do que acontece),
   `rotuloConfirmar`, `tom` (`normal`|`perigo`), `exigirTexto?` (digitar a
   palavra para liberar — usar em reset geral e exclusão em massa).
   Ação de perigo à direita, cancelar à esquerda, foco inicial no cancelar.
8. **`Aviso`** (inline alert) — tons `info|ok|espera|erro`, com ícone + título +
   corpo + ação opcional.
9. **`Etiqueta`** (badge) e **`Pastilha`** (chip de filtro removível).
10. **`IndicadorEstado`** — bolinha + ícone + rótulo; a **única** fonte de
    verdade visual de status em todo o sistema.
11. **`Aviso flutuante`** (toast) — fila máx. 3, 5s, pausa no hover,
    ação "desfazer" quando aplicável, `role="status"`.
12. **`Dica`** (tooltip) — abre em 400ms, fecha em 80ms, teclado-acessível,
    nunca contém ação (para ação use `Popover`).
13. **`Popover`**, **`MenuSuspenso`** (ARIA menu completo, setas navegam),
    **`Abas`** (ARIA tablist, setas navegam, estado na URL).
14. **`Esqueleto`** — sempre com a geometria do conteúdo real.
15. **`EstadoVazio`** — ícone discreto + título + 1 frase de instrução +
    ação primária. **Sem ilustração.**
16. **`Migalhas`** (breadcrumb), **`BarraProgresso`**, **`Medidor`**
    (progresso NSU), **`Paginacao`**.
17. **`PaletaComandos`** (`⌘K`) — busca global de documentos **e** navegação
    **e** ações ("Disparar importação…", "Baixar fechamento…",
    "Alternar tema"). Agrupada, com atalhos ao lado, navegável por teclado.
18. **`AtalhosTeclado`** (modal `?`) — tabela de todos os atalhos.
19. **`CopiavelMono`** — chave de acesso/CNPJ/NSU em mono, agrupado,
    com botão copiar + feedback "copiado" (e fallback sem Clipboard API).
20. **`ValorMoeda`**, **`Quantidade`**, **`DataHora`** (relativo + absoluto no
    title), **`Cnpj`** — formatadores como componentes, para nunca divergirem.

## 6.2 Componentes de domínio (fiscal)

1. **`SeletorPeriodo`** — as **duas datas** (obrigatórias) + atalhos
   ("Este mês", "Mês passado", "Últimos 3 meses", "Este ano") + validação
   inline ("A data inicial é depois da final — inverta as duas"). Estado vai
   para a URL.
2. **`SeletorCompetencia`** — `MM/AAAA` com navegação ‹ › e últimos 6 meses.
3. **`SeletorEmpresas`** — multi-seleção com busca, virtualização, seleção
   por intervalo, "selecionar todas as visíveis", coluna de situação
   (em dia / na janela / varrendo / sem certificado / nunca consultada) e
   bloqueio explicado para quem não tem A1.
4. **`CartaoAlerta`** — nível + categoria + empresa + título + detalhe +
   **botão que resolve** (`acao_href`) + "marcar como lida".
5. **`LinhaExecucao`** — estado ao vivo, tempo decorrido, contagem de
   documentos, expansão para detalhe técnico (NSU, motivo de espera, erro).
6. **`MedidorNSU`** — `ultimo_nsu / max_nsu` como barra + números + pendência.
7. **`CartaoCertificado`** — validade, dias restantes (com faixa de cor),
   última utilização real, último erro de autenticação, ação "substituir A1".
   **Nunca exibe senha, nem campo dela preenchido.**
8. **`PainelDocumento`** (drawer) — cabeçalho com chave copiável, dados
   estruturados em duas colunas, partes (emitente/destinatário), situação,
   ações (baixar XML, ver XML formatado com destaque de sintaxe, excluir),
   e link "ver empresa".
9. **`GraficoBarras`, `GraficoDonut`, `Sparkline`** — SVG puro, acessíveis
   (`role="img"` + `<title>`/`<desc>` + tabela alternativa oculta com os dados).
   Uma cor + neutros. Sem legenda flutuante desnecessária.
10. **`ResumoImportacao`** — a prévia antes de disparar: o que vai rodar, o que
    está na janela, o que não tem certificado — **antes** de gastar cota.

---

# 7. ARQUITETURA DE INFORMAÇÃO E NAVEGAÇÃO

## 7.1 Estrutura (mantenha — foi decidida pelo produto)

```
VISÃO GERAL   Painel            /dashboard
              Atenção           /dashboard/atencao        ← badge com contagem
              Execuções         /dashboard/execucoes

FISCAL        Documentos        /dashboard/documentos
              Importações       /dashboard/importacoes
              Empresas          /dashboard/empresas   → /dashboard/empresa?id=
              Certificados      /dashboard/certificados
              Fechamento        /dashboard/relatorios

SISTEMA       Saúde             /dashboard/saude
              Configurações     /dashboard/configuracoes
              Auditoria         /dashboard/auditoria      (admin/operador)
              Equipe            /dashboard/usuarios       (admin) ← HOJE ESTÁ ÓRFÃ:
                                                            a rota existe mas
                                                            não está no menu.
                                                            CORRIJA.
Fora do shell Login             /login
              Raiz              /            → redireciona conforme sessão
              /dashboard/alertas → redirect permanente para /dashboard/atencao
```

## 7.2 Shell da aplicação

- **Barra lateral 240px**, fixa em ≥1024px, off-canvas com overlay abaixo disso.
  **Colapsável para 56px** (só ícones + tooltip), estado persistido.
  Grupos com rótulo discreto. Item ativo marcado por **barra de 2px à esquerda +
  fundo sutil + peso 500** (não por cor de texto berrante).
  Badge de "Atenção" em vermelho só quando há crítico; âmbar caso contrário.
- **Header 56px**: breadcrumb/título da rota · campo de busca global
  (placeholder "Buscar documento, empresa ou CNPJ  ⌘K") · seletor de tema ·
  sino de alertas com popover (5 mais graves + "ver todos") · avatar com menu
  (nome, e-mail, papel, Configurações, Atalhos, Sair).
  **Retire** do header o selo decorativo "Automação ativa" — o status real já
  está no Painel.
- **Sem rodapé** nas telas de trabalho (o rodapé atual só ocupa espaço).
  A informação de ambiente vai para o menu do usuário e para Saúde.
- **Indicador global de atualização:** quando um polling está em voo, uma barra
  de 2px animada no topo do conteúdo — nunca um spinner que cobre a tela já
  renderizada. **Jamais substitua conteúdo já visível por skeleton** em
  refetch (só no primeiro carregamento).

---

# 8. ESPECIFICAÇÃO TELA A TELA

> Para cada tela: **objetivo** (pergunta que ela responde), **layout**,
> **dados/endpoints**, **interações**, **estados**. Implemente **todas**.

## 8.1 `/login`

**Objetivo:** entrar rápido e com erro claro.

- Layout em duas colunas ≥1024px: à esquerda **painel grafite** com a marca,
  uma frase objetiva do produto e três pontos factuais (nada de marketing);
  à direita o formulário em superfície clara, cartão de no máx. 380px.
  Abaixo de 1024px: só o formulário, centralizado.
- Campos: e-mail (`autocomplete="username"`, `inputmode="email"`), senha
  (`autocomplete="current-password"`, botão mostrar/ocultar com `aria-pressed`).
  **Permitir colar.**
- Submit: botão em `carregando` com texto "Verificando acesso…", form
  desabilitado, `aria-busy`.
- **Erro:** `role="alert"` acima do botão. Diferencie:
  - 401 → "E-mail ou senha incorretos."
  - 0 → "A API não respondeu. Verifique se os serviços estão no ar."
  - 403 → "Origem não autorizada para esta sessão."
  - 429 → "Muitas tentativas. Tente novamente em instantes."
- Foco inicial no campo de e-mail. `Enter` envia.
- Se já houver sessão (`/auth/me` OK), redirecionar para `/dashboard`.

## 8.2 `/dashboard` — **Painel** (a tela mais importante)

**Objetivo:** em ≤3 segundos, sem ler rótulo: *está tudo funcionando?* e
*preciso resolver algo?*

**Dados:** `GET /painel/operacional`, `GET /painel/execucoes?limite=10`,
`GET /alertas`. Polling 30s, **pausado com aba oculta**, com "atualizado há Xs"
e botão atualizar manual.

**Layout (topo → base):**

1. **Faixa de estado geral** (a linha mais importante do produto).
   Altura contida, sem ser banner de marketing. Composição:
   ícone de estado + frase de estado + `painel.mensagem` + ação primária.
   - `operando` → tinta ok, "Operação estável"
   - `atencao` → tinta espera, "Operando com pendências"
   - `critico` → tinta erro, "Uma ação precisa de você" + botão
     **"Resolver pendências"** → `/dashboard/atencao`
   A cor vem como **faixa lateral de 3px + ícone**, não como fundo saturado.
2. **Faixa de 4 indicadores** (não "cards bonitos" — blocos de leitura):
   Empresas ativas (`+ N sincronizadas hoje`) · Importações
   (`em_andamento` + `N aguardando janela`) · Atenção (`criticos+atencao`) ·
   Documentos hoje (`+ N no mês`). Cada um é link para a tela correspondente,
   número grande tabular, rótulo pequeno, contexto em uma linha.
   **Sem ícone colorido em bolha.** Se houver ícone, é monocromático 16px.
3. **Duas colunas (60/40):**
   - **Esquerda — "Precisa da sua atenção"**: até 5 itens, ordenados por
     gravidade, cada um com nível + título + detalhe truncado + **botão da
     ação**. Vazio: "Nada exigindo ação" com uma frase que explica que a
     automação está cuidando.
   - **Direita — "Agora"**: execuções vivas (com pulso) e as próximas janelas,
     cada uma com contagem regressiva legível.
4. **"Últimas sincronizações"** — lista compacta: empresa · tipo · resultado ·
   quando. Erro mostra o motivo em uma linha.
5. **"Detalhes do sistema e do mês"** em `<details>` colapsado: componentes
   (api/banco/fila/worker/agendador) + números da competência.

**Regra:** o Painel **não** ganha gráfico decorativo. Se um gráfico não muda uma
decisão, ele sai.

## 8.3 `/dashboard/atencao` — **Precisa da sua atenção**

**Objetivo:** transformar o estado do sistema numa lista curta de ações.

- Cabeçalho com contagem por nível e a frase "resolva de cima para baixo".
- **Filtros por nível** como segmented control (Todas / Críticos / Importantes /
  Informativas) com contagem.
- Lista de `CartaoAlerta`, faixa lateral de 3px por nível, agrupada por
  categoria quando houver mais de 12 itens.
- Ações por item: **botão que resolve** (`acao_href`) e "marcar como lida"
  (persistido em `localStorage`, com "mostrar lidas" e "marcar todas").
- Rodapé explicativo: "Os alertas são calculados a partir do estado real —
  quando o problema se resolve, o item some sozinho."
- Estados: carregando (5 skeletons), vazio (positivo), erro de API (com retry).
- Polling 60s.

## 8.4 `/dashboard/execucoes` — **Central de execuções**

**Objetivo:** o que a máquina está fazendo, o que vem a seguir, o que falhou.

Quatro seções (`GET /painel/execucoes?limite=30`, polling 15s):

1. **Agora** — cartões/linhas com pulso, empresa, tipo, "consultando · N
   documentos · desde há 4 min" ou "aguardando janela · retoma em 42 min".
   Expansível para: `execucao_id`, último NSU, início absoluto, motivo da espera,
   erro.
2. **Próximas janelas** — tabela: empresa · tipo · motivo (Janela de 1h /
   Bloqueio SEFAZ 656) · pendência · consulta em (relativo + title absoluto).
3. **Falhas recentes** — tabela com motivo truncado (title completo) + ação
   **"Reprocessar"** que leva a Importações já com empresa/tipo/período
   pré-preenchidos (não jogue o operador numa tela vazia — hoje ele cai em
   `/dashboard/importacoes` sem contexto: **corrija isso**).
4. **Histórico recente** — concluídas, com documentos e cancelados.

Filtro por tipo e por estado no topo; tudo na URL.

## 8.5 `/dashboard/documentos` — **Acervo** (tela mais densa)

**Objetivo:** achar qualquer documento e levá-lo embora.

- **Barra de filtros persistente** (colapsável, mostra pastilhas do que está
  ativo): Empresa (combobox com busca) · Tipo · Direção · Situação ·
  **Período (obrigatório, marcado com \*)** · Busca (chave/número/NSU/emitente).
  "Mais filtros": leiaute (completo/resumo), valor mín/máx, série, origem.
  Botão **Limpar** (limpa opcionais, **preserva o período** — ele é obrigatório).
- **Linha de resumo:** total · normais · canceladas · por tipo, como pastilhas.
- **Barra de exportação:** "Baixar XMLs (N)" (primária, mostra a estimativa
  `N documentos · ~X MB` **antes**) · "Baixar CSV" · "Baixar seleção (N)" ·
  "Excluir seleção (N)" (perigo, oculto para papel `leitura`).
  Se houver documentos só em resumo: aviso âmbar com ação
  "buscar XML completo (N)" **explicando** que a SEFAZ entrega o resumo
  primeiro e que a busca respeita 20 consultas/hora.
- **Tabela** (densidade compacta padrão): checkbox · Documento
  (chave em mono agrupada + tipo + direção; 2ª linha com emitente e data) ·
  Nº/Série (+NSU) · Competência · Situação (Normal / **Cancelada** com motivo no
  title / **Resumo** em âmbar) · Valor (direita, tabular; cancelada em risco) ·
  Ações (XML, Excluir).
  Linha clicável abre o **drawer de detalhe**. Ordenação por data, valor, número.
  Paginação de 500 com "carregar mais" **e** contagem total.
- **Estados especiais:** período inválido → bloco instrutivo com o erro exato;
  zero resultados no filtro → "Nenhum documento em 08/2026" + atalho para
  importar aquele período.
- **Drawer de detalhe:** dados completos, XML formatado sob demanda (com
  destaque de sintaxe leve), copiar chave, baixar, excluir, ir para a empresa.
  `Esc` fecha, foco preso e devolvido.

## 8.6 `/dashboard/importacoes` — **Disparar e acompanhar**

**Objetivo:** puxar exatamente o que se quer, sem desperdiçar cota.

1. **Resumo do sincronismo** (`GET /importacoes/resumo`): empresas · combinações
   em dia · com pendência · em andamento · aguardando janela · bloqueadas ·
   documentos no banco · se o automático está ligado e o intervalo.
2. **Painel de disparo por seleção** (o fluxo principal):
   - `SeletorPeriodo` (obrigatório) + tipo (todos/nfse/nfe/cte)
   - `SeletorEmpresas` com situação por empresa
   - **Prévia automática** (`/importacoes/selecionadas/previa`): tabela do que
     vai acontecer — "Pode rodar agora" / "Na janela de 1 h da SEFAZ" /
     "Já está varrendo" / "Sem certificado A1" / "Sem UF" / "Fila indisponível" —
     com contagem por situação **antes** de qualquer disparo
   - Botão primário **"Importar N selecionadas"**; secundário **"Forçar"**
     atrás de confirmação que explica o custo (zera o cronômetro da janela)
   - Resultado: tabela por empresa+tipo com enfileiradas/aguardando/ignoradas
3. **Estado por empresa+tipo** (`/importacoes/estado`): tabela com
   `MedidorNSU`, pendência, situação (em dia ✓ / varrendo / na janela com
   contagem regressiva / nunca consultada), **alerta de risco de distribuição**
   quando `risco_documento_fora_da_distribuicao`, e ação "puxar agora".
4. **Histórico de execuções** com filtro por empresa.

Nota fixa e discreta: *"'Na janela da SEFAZ' não é falha: é o intervalo oficial
de 1 hora por CNPJ e tipo. O sistema retoma sozinho — clicar antes zera o
cronômetro."*

## 8.7 `/dashboard/empresas` e `/dashboard/empresa?id=`

**Lista:**
- Busca + filtros (ativa/inativa, com/sem certificado, UF, sincronismo).
- **Alternância lista/tabela**; padrão **tabela** (com 500 empresas, cards são
  inviáveis — o layout atual em grid de cards não escala: **corrija**).
  Colunas: Empresa · CNPJ (mono, copiável) · UF · Certificado (validade + dias) ·
  Sincronismo (tipos ativos) · Documentos no mês · Situação · Ações.
  Virtualizada.
- Ações em lote: ativar/desativar sincronismo, definir tipos, exportar.
- **Cadastrar empresa**: CNPJ → consulta automática (`/empresas/consulta-cnpj`)
  preenchendo razão social e UF, com estado "buscando…", origem do dado
  ("via ReceitaWS") e opção de sobrescrever manualmente.
- **Importar em massa**: área de **arrastar-e-soltar** para `.pfx/.p12`
  (com alternativa por botão — WCAG 2.5.7), CSV opcional
  (`razao_social;cnpj_cpf;uf[;senha]`), senha comum, UF fallback.
  Durante o envio: progresso por arquivo. Resultado: tabela
  criadas/certificados/já existiam/erros com o motivo de cada erro
  e **"copiar relatório"**.

**Detalhe da empresa** — em abas (`?aba=` na URL):
`Visão geral` (dados, situação, contadores) · `Sincronismo` (tipos, automático,
estado por tipo com NSU e janela) · `Certificado` (atual + envio de novo,
validade, últimos erros) · `Documentos` (últimos do mês, link filtrado) ·
`Jettax` (configuração, registro, importações NFS-e/NFe, execuções) ·
`Histórico` (execuções da empresa).

## 8.8 `/dashboard/certificados` — **Centro de certificados**

`GET /certificados/painel`.

- 4 indicadores: válidos · vencendo (≤30d) · vencidos · sem certificado.
- Filtros (Todos / Vencidos / Vencendo / Sem certificado / Saudáveis) + busca.
- Tabela **ordenada por urgência**: Empresa · CNPJ · Validade
  (data + "faltam 12 dias" com faixa de cor) · Última utilização real ·
  Última validação · Último erro de autenticação (truncado, title completo) ·
  Ação "Enviar novo A1".
- Modal de envio: arquivo + senha, com aviso de que **a senha é usada só para
  abrir o arquivo e é guardada cifrada no cofre; ela nunca é exibida de volta**.
- Vencido = bloco de erro com a consequência explícita:
  *"Toda importação desta empresa vai falhar até a substituição."*

## 8.9 `/dashboard/relatorios` — **Fechamento mensal**

- `SeletorCompetencia` no topo; tudo reage a ele.
- **Cartão de conferência** (`/importacoes/conferencia`): pronto para fechar ou
  não, com a lista de pendências por empresa+tipo e ação "puxar/conferir agora".
- Totais: documentos · valor · canceladas · sem XML · empresas com movimento.
- **Matriz empresa × tipo** (NFS-e / NFe / CT-e): quantidade e valor por célula,
  total por linha e coluna, célula vazia com "—" (não "0" quando não se aplica),
  ordenável, com busca por empresa.
- Exportar CSV · Exportar ZIP · **Imprimir**.
- **Folha de impressão de verdade** (`@media print`): sem menu, sem header,
  sem botões, fundo branco, tipografia serifada opcional, cabeçalho com
  competência, CNPJ do escritório e data/hora de emissão, rodapé com paginação,
  quebra de página entre blocos (`break-inside: avoid`). Um contador precisa
  poder anexar isso ao dossiê do mês.

## 8.10 `/dashboard/saude` — **Saúde do sistema**

- Componentes (api/banco/fila/worker/agendador) com estado e detalhe.
- Diagnóstico do ambiente (`/sistema/saude-detalhada`): banco, cofre,
  disco livre; problemas como lista de blocos de erro acionáveis.
- **Backup**: último OK (quando, tamanho), horas desde o último, próximo
  previsto, retenção, erros recentes, **último teste de restauração e se passou**
  (destaque — é o que diferencia backup de esperança). Ação "Executar agora".
- Histórico de backups em tabela com ação **"Testar restauração"** por registro
  (resultado vira toast e atualiza a linha).
- Se backup desativado: estado vazio explicando a variável de ambiente.

## 8.11 `/dashboard/configuracoes`

Seções em cartões, **admin-only** onde a API exige:
- **Ambiente** (`/sistema/info`): modo, banco, pasta de dados, hora do servidor,
  agenda do Celery Beat, webhook configurado.
- **Integração Acessórias**: URL + token (campo do tipo senha, nunca exibe o
  valor salvo, só "configurado ✓"), testar, **sincronizar empresas**.
- **Integração Jettax/Morfeu**: URL + token, saúde, empresas registradas/ativas,
  testar, remover credencial.
- **Alertas externos**: webhook, nível mínimo, intervalo, "Testar webhook".
- **Atalhos** para Atenção / Certificados / Saúde / Auditoria.
- ☠️ **Zona de risco** (visualmente segregada, borda de erro, colapsada):
  **Reset geral** com `DialogoConfirmacao` que exige digitar `LIMPAR`, lista
  exatamente o que será apagado e mostra o resultado (quantidades removidas).

## 8.12 `/dashboard/auditoria`

- Filtros: ação (select de `/auditoria/acoes`, com rótulos amigáveis via
  `ROTULO_ACAO`), busca livre, limite.
- Tabela: quando (relativo + absoluto) · usuário · ação (rótulo humano) ·
  entidade + id · detalhe (expansível).
- Exportar CSV local do que está na tela.

## 8.13 `/dashboard/usuarios` — **Equipe** (admin)

**Hoje esta rota existe mas não está no menu — coloque-a em SISTEMA, visível só
para `admin`.**
- Tabela: nome · e-mail · papel (edição inline com confirmação) · ativo
  (`Alternador`) · criado em · ações.
- Criar usuário em modal (nome, e-mail, senha, papel) com medidor de força de
  senha e regras visíveis.
- **Redefinir senha em modal próprio** — hoje usa `window.prompt`: **elimine**.
- Um admin não pode se auto-desativar (bloqueie na UI com explicação).

---

# 9. COMPORTAMENTOS TRANSVERSAIS (implemente em todas as telas)

1. **URL é a fonte da verdade** de todo filtro, aba, período, ordenação e
   página. Copiar a URL e enviar para outra aba reproduz a tela exata.
   Use `useSearchParams` + `router.replace` (sem empilhar histórico a cada
   tecla digitada — faça *debounce* de 300ms na busca).
2. **Papéis** (`admin` / `operador` / `leitura`): esconder é insuficiente —
   controles indisponíveis para `leitura` ficam **desabilitados com tooltip
   explicando** ("Somente leitura: peça a um operador"). A API barra de verdade;
   a UI apenas evita o clique frustrado.
3. **Polling inteligente**: 15s (execuções), 30s (painel), 60s (alertas).
   Pausa com `document.hidden`, retoma ao focar, mostra "atualizado há Xs",
   e **nunca** pisca a tela.
4. **Tratamento de erro padronizado**: toda tela tem os quatro estados
   (carregando / vazio / erro / conteúdo). Erro sempre com causa provável e
   botão de retry. Erro de rede (`status 0`) tem mensagem específica sobre a API.
5. **Otimismo com reversão**: ações rápidas (marcar lida, alternar switch)
   atualizam a UI na hora e revertem com toast de erro se a API falhar.
6. **Downloads sempre por `fetch` + blob** (cookie HttpOnly não viaja em
   `<a download>` cross-origin). Ler `content-disposition` para o nome real.
   Mostrar estado "preparando…" e liberar `URL.revokeObjectURL`.
7. **Formatação centralizada** em `lib/format.ts` — `moeda`, `moedaCompacta`,
   `numero`, `dataCurta`, `dataHora`, `tempoRelativo`, `formatarCnpjCpf`,
   `bytesParaTexto`, `iniciais`. Nenhum `toLocaleString` solto em componente.
8. **`title` em tudo que trunca.** Nunca truncar sem dar acesso ao valor inteiro.
9. **Impressão**: `.nao-imprimir` em navegação e controles; tabelas e relatórios
   saem legíveis em A4 retrato/paisagem.
10. **Performance**: LCP < 1,5s em rede local; interação < 100ms;
    lista de 5.000 linhas rola a 60fps (virtualização); nenhum re-render de
    tabela inteira ao digitar num filtro (memoização correta);
    `next/font` (sem FOUT de `@import`); sem imagens não otimizadas.

---

# 10. ENTREGÁVEIS

Entregue o código **completo e compilável**, na estrutura:

```
frontend/
├─ app/
│  ├─ layout.tsx                  ← fontes via next/font, <html lang="pt-BR">, tema
│  ├─ globals.css                 ← tokens, base, utilitários (SEM @import de fonte)
│  ├─ page.tsx                    ← roteamento por sessão
│  ├─ login/page.tsx
│  └─ dashboard/
│     ├─ layout.tsx               ← shell: guarda de sessão, sidebar, header, ⌘K, toasts
│     ├─ page.tsx                 ← Painel
│     ├─ atencao/ execucoes/ documentos/ importacoes/ empresas/ empresa/
│     ├─ certificados/ relatorios/ saude/ configuracoes/ auditoria/ usuarios/
│     └─ alertas/page.tsx         ← redirect → /dashboard/atencao
├─ components/
│  ├─ ui/         ← primitivos (§6.1), um arquivo por componente + index.ts
│  ├─ fiscal/     ← componentes de domínio (§6.2)
│  └─ shell/      ← Sidebar, Header, PaletaComandos, AtalhosTeclado, SeletorTema
├─ lib/
│  ├─ api.ts      ← cliente (preserve o contrato e o tratamento de erro)
│  ├─ types.ts    ← tipos (preservados)
│  ├─ format.ts  competencia.ts  periodo.ts  papel.ts
│  ├─ atalhos.ts  ← registro central de atalhos de teclado
│  ├─ urlEstado.ts ← hook de estado sincronizado com a URL
│  └─ cn.ts
├─ design/
│  └─ SISTEMA.md  ← documentação do design system (tokens, uso, exemplos, do/don't)
├─ tailwind.config.ts   next.config.mjs   tsconfig.json   package.json
```

**Além do código, entregue:**

1. **`design/SISTEMA.md`** — tokens com valores e razão de existir, escala
   tipográfica, regras de cor, elevação, movimento, tabela de contraste
   calculada, e um "faça / não faça" por componente.
2. **`CHANGELOG-FRONTEND.md`** — o que mudou por tela e por quê (decisões de
   produto, não só de estilo).
3. **Comentários no código** apenas onde explicam **decisão não óbvia**
   (ex.: por que `aguardando` é âmbar; por que o período é obrigatório;
   por que o download usa blob). Em português. Sem comentário óbvio.

---

# 11. CRITÉRIOS DE ACEITE (checklist verificável — a entrega será conferida item a item)

## Correção técnica
- [ ] `npm run typecheck` → 0 erros, 0 warnings, `strict: true`, zero `any`
- [ ] `npm run build` → sucesso, `output: standalone` preservado
- [ ] Nenhum `console.log`, `TODO`, código morto ou import não usado
- [ ] Nenhum `window.confirm` / `window.prompt` / `window.alert` no código
- [ ] Todo `useEffect` com fetch cancela e trata erro; nenhum loop de render
- [ ] Todo `setInterval` é limpo e pausa com a aba oculta
- [ ] Páginas com `useSearchParams` embrulhadas em `<Suspense>`
- [ ] Nenhuma chamada a endpoint inexistente; nenhum campo inventado

## Funcionalidade
- [ ] **Todas as 14 rotas** implementadas, incluindo `/dashboard/usuarios`
      **agora no menu**
- [ ] **Todo botão faz algo** — nenhum controle decorativo ou `onClick` vazio
- [ ] Todos os endpoints da §4.2 estão consumidos onde fazem sentido
- [ ] Filtros, período, aba, ordenação e paginação persistem na URL
- [ ] Downloads (XML, ZIP, CSV, fechamento) funcionam com cookie HttpOnly
- [ ] Ações em lote funcionam em Documentos, Empresas e Importações
- [ ] Papéis (`admin`/`operador`/`leitura`) respeitados em toda a UI

## Design
- [ ] Nenhum elemento da lista negra (§1.1) presente
- [ ] Paleta ≤ 5 famílias; nenhuma cor decorativa; nenhum hex fora dos tokens
- [ ] Pesos de fonte apenas 400/500/600; nada abaixo de 12px
- [ ] `tabular-nums` em todo número; números à direita em tabelas
- [ ] Tema claro **e** escuro completos e calibrados independentemente
- [ ] Elevação em no máximo 3 níveis e semântica
- [ ] `aguardando` / janela SEFAZ renderizado em âmbar/neutro — **nunca vermelho**

## Acessibilidade (WCAG 2.2 AA)
- [ ] axe-core: **0 violações critical/serious** em todas as rotas
- [ ] Navegação 100% por teclado, com "Pular para o conteúdo"
- [ ] Foco visível 2px + halo, com contraste ≥3:1, nunca obscurecido pelo header
- [ ] Todo alvo clicável ≥24×24px (primários ≥40×40px)
- [ ] Modais/drawers com foco preso, `Esc`, e foco devolvido ao gatilho
- [ ] Contraste verificado e documentado para cada par de tokens
- [ ] Estado nunca comunicado só por cor
- [ ] `prefers-reduced-motion` respeitado integralmente
- [ ] Usável a 320px de largura e 400% de zoom

## Qualidade de produto
- [ ] Os 4 estados (carregando / vazio / erro / conteúdo) em **toda** superfície
      que busca dados
- [ ] Mensagem de erro sempre com causa + próximo passo
- [ ] Refetch nunca substitui conteúdo visível por skeleton
- [ ] `⌘K`, `?`, `g+tecla`, `/`, `Esc`, `j/k` implementados e documentados
- [ ] Impressão do Fechamento gera uma folha apresentável
- [ ] Tabela de 5.000 linhas rola suave (virtualização)

---

# 12. COMO TRABALHAR (ordem de execução)

1. **Antes de escrever código**, produza um resumo de 1 página: interpretação do
   produto, decisões de design que você vai tomar e **o que você vai remover**
   do front atual (remoção é decisão de design tanto quanto adição).
2. Implemente nesta ordem:
   **(a)** tokens + `tailwind.config` + `globals.css` + `design/SISTEMA.md` →
   **(b)** primitivos de UI → **(c)** shell (layout, sidebar, header, ⌘K) →
   **(d)** Login → **(e)** Painel → **(f)** Atenção → **(g)** Execuções →
   **(h)** Documentos (+ drawer) → **(i)** Importações → **(j)** Empresas
   (lista + detalhe) → **(k)** Certificados → **(l)** Fechamento →
   **(m)** Saúde → **(n)** Configurações → **(o)** Auditoria → **(p)** Equipe.
3. Ao final de cada bloco, rode `tsc --noEmit` e só avance limpo.
4. Entregue **arquivos completos**, nunca trechos com "… resto igual".
5. Se encontrar ambiguidade, **decida** com base na §2 (diretriz operacional) e
   **registre a decisão em uma linha de comentário** — não pergunte, não deixe
   `TODO`.

---

## Frase-guia para cada decisão que você tomar

> **"Isso faz o operador precisar fazer menos, ou apenas faz a tela parecer
> mais bonita?"** Se for a segunda, não entra.

E o teste final:

> Se um contador abrir este sistema às 7h de uma segunda-feira de fechamento,
> com 400 empresas e 180.000 documentos, ele deve saber em **3 segundos** se
> pode tomar o café em paz — e, se não puder, deve estar a **um clique** do que
> resolve.
