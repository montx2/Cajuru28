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
- docZip gzip+base64 → resNFe / procNFe (eventos ignorados)
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

## Fase 5 — Multiempresa self-service (futuro)
- Onboarding de novo escritório sem intervenção manual
- Cobrança/planos
- Isolamento de fila por escritório

## Pendências técnicas conhecidas (não bloqueiam o uso interno)

1. **Manifestação do destinatário (NFe)** — `RecepcaoEvento` para receber
   `procNFe` completo em vez de só `resNFe`.
2. **Alembic** — trocar `create_all` por migrations versionadas antes de
   produção com dado real de cliente.
3. **Validação ponta-a-ponta com certificado A1 real** — só possível na
   máquina do escritório (este ambiente não tem cert nem rede SEFAZ).
