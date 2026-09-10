# Roadmap

## Fase 0 — Fundação (pronta)
Banco multiempresa, autenticação JWT, cofre de segredos, CRUD de
escritórios/empresas/certificados, estrutura de fila (Celery) e worker.

## Fase 1 — Importador de NFS-e (pronta e corrigida)
Porta a lógica validada do `Importarnotas` + Manual oficial do ADN:

- Endpoint correto: `GET /contribuintes/DFe/{NSU}` (DFe maiúsculo)
- Params: `cnpjConsulta` / `cpfConsulta` + `lote=true`
- 404 `NENHUM_DOCUMENTO_LOCALIZADO` tratado como "nada novo" (não é erro)
- Retry em 429/5xx, cooldown de 1h, checkpoint por NSU entre execuções
- Parser de XML namespace-agnóstico (leiaute nacional)

## Fase 2 — Importador de NFe (pronta)
`NFeDistribuicaoDFe` / `nfeDistDFeInteresse` (SOAP 1.2 + mTLS):

- cStat 137 (nada novo) / 138 (docs) / 656 (consumo indevido)
- docZip gzip+base64 → resNFe / procNFe / resEvento / procEventoNFe
- Campo UF obrigatório na empresa (`cUFAutor`)

**Antes de produção com certificado real:** rode primeiro em
`AMBIENTE_FISCAL=homologacao`. Sem manifestação do destinatário, o que chega
geralmente é o **resumo** (`resNFe`), não a NFe completa.

## Fase 3 — Importador de CT-e (pronta)
`CTeDistribuicaoDFe` / `cteDistDFeInteresse`:

- URLs AN: `www1.cte.fazenda.gov.br` (prod) / `hom1.cte.fazenda.gov.br` (hom)
- Mesmo módulo compartilhado `_distribuicao_dfe.py` da NFe
- Parser de resCTe/procCTe (`chCTe`, `vTPrest`)

Fontes: portal CT-e, nfephp-org/sped-cte, TadaSoftware/PyNFe.

## Fase 4 — Frontend web (pronta)
Next.js + Tailwind: login, visão geral (lote), empresas/certificado,
importações com polling, documentos com download de XML.

## Fase 4.5 — Operação automática (pronta)

Objetivo: chegar perto de 100% de automatismo — o operador cadastra a empresa,
manda uma vez e **não toca mais nisso**. Ver
[`SINCRONIZACAO.md`](SINCRONIZACAO.md) para as regras completas.

- **Estado de sincronização por empresa+tipo** (`sincronizacoes_dfe`): cursor,
  maxNSU, janela de 1h, bloqueios, cota de consultas pontuais e `lease`
- **656 deixou de ser erro**: execução `AGUARDANDO` + retomada automática depois
  da janela oficial, com realinhamento de cursor pelo `ultNSU` devolvido
- **Beat** com duas tasks: `sincronizar_tudo` (round-robin) e
  `completar_xmls_pendentes` (gap-fill do XML completo pela chave, 20/h)
- **Commit por lote** = checkpoint de verdade; teto de páginas com reagenda da
  mesma execução; `acks_late` + `visibility_timeout` para a fila não duplicar
- **API de estado**: `GET /importacoes/estado`, `GET /importacoes/resumo`,
  `GET /empresas/{id}/sincronizacao`, `PATCH /empresas/{id}` (liga/desliga o
  automático e escolhe os tipos por empresa)
- **Competência (mês)** em importação, listagem, resumo, relatório e ZIP — com
  a descarga sempre completa por NSU (o mês filtra o que está no banco)
- **Download em massa**: `GET /documentos/exportar` (ZIP com todos os XMLs do
  filtro, `relacao.csv` e `LEIA-ME.txt`) + `/exportar/estimativa` antes do clique

## Fase 5 — Programa instalado com atualização automática (pronta)

Um programa por computador, sem servidor no meio:

- **PyInstaller (onedir) + Inno Setup**: instalador por usuário (sem UAC, nem
  na instalação nem na atualização), ZIP portátil para máquina sem permissão de
  administrador;
- **fila em processo** (`MiniCelery`) no lugar de Redis + Celery, com a mesma
  interface — as tasks não sabem quem executa;
- **painel servido pela própria API** (export estático), o que elimina Node,
  CORS e a pergunta "qual é o IP do servidor?";
- **atualização automática**: manifesto `latest.json` na Release do GitHub
  (ou pasta de rede), SHA-256 conferido, instalador silencioso, programa
  reaberto na versão nova — a faixa avisa e o usuário decide quando;
- **dados fora do programa** (`%APPDATA%\NotasFlow`): atualizar, reinstalar ou
  desinstalar não toca em banco, certificados e XMLs;
- **configurações de campo**: backup com um clique, "abrir junto com o Windows",
  redefinir senha, ver registros, verificar atualização, encerrar o programa;
- **bandeja do sistema**: fechar a janela não interrompe o sincronismo.

## Fase 6 — Importação por seleção de empresas (pronta)

- `POST /importacoes/selecionadas` (+ `/previa`): o usuário marca as empresas e
  dispara só para elas, com o motivo de cada linha (`pode rodar agora`, janela
  de 1 h da SEFAZ, sem certificado, já varrendo);
- seleção preservada entre sessões; painel único reaproveitado na Visão geral e
  em Importações (uma regra, uma tela);
- aviso de certificado vencido/perto de vencer, com os dias restantes.

## Fase 7 — Multiempresa self-service (futuro)
- Onboarding de novo escritório sem intervenção manual
- Cobrança/planos
- Isolamento de fila por escritório
- Assinatura de código (Authenticode) e assinatura TUF do manifesto

## Pendências técnicas conhecidas (não bloqueiam o uso interno)

1. **Manifestação do destinatário (NFe)** — `RecepcaoEvento` para receber
   `procNFe` completo em vez de só `resNFe`. Hoje o buraco já é tapado pelo
   gap-fill por chave (`consChNFe`); a manifestação é o caminho oficial de
   quem precisa do XML integral imediatamente.
2. **Alembic** — trocar `create_all` por migrations versionadas antes de
   produção com dado real de cliente.
3. **Validação ponta-a-ponta com certificado A1 real** — só possível na
   máquina do escritório (este ambiente não tem cert nem rede SEFAZ).
