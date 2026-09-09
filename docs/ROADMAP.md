# Roadmap

## Fase 0 — Fundação (pronta neste scaffold)
Banco multiempresa, autenticação JWT, cofre de segredos, CRUD de
escritórios/empresas/certificados, estrutura de fila (Celery) e worker.

## Fase 1 — Importador de NFS-e (pronta neste scaffold)
Porta a lógica validada do `Importarnotas`: mTLS com o `.pfx`, consulta ao
ADN por NSU, checkpoint por lote de 50, gravação de XML.

## Fase 2 — Importador de NFe (SEFAZ)

**Status: implementado, não testado contra o SEFAZ de verdade.**

`app/services/importadores/nfe_sefaz.py` foi construído sobre a Nota
Técnica 2014.002, os XSDs oficiais (`distDFeInt_v1.01.xsd`,
`retDistDFeInt_v1.00.xsd`) e exemplos reais de request/response de
produção replicados por bibliotecas open-source consolidadas (sped-nfe,
DFe.NET, Java_NFe, xml-nfe.io) — mas eu não tenho, neste ambiente, acesso
de rede a `nfe.fazenda.gov.br` nem um certificado A1 real para testar de
ponta a ponta. Antes de rodar em produção:

1. Rode em homologação (`ImportadorNFeSEFAZ(ambiente="homologacao")`)
   contra um certificado real primeiro.
2. Confirme que o schema do `docZip` que chega bate com `resNFe`/`procNFe`
   como documentado — se a empresa nunca fez "manifestação do
   destinatário", é bem provável que só chegue o resumo (`resNFe`), não a
   NFe completa (`procNFe`). Ver TODO no topo do arquivo.
3. Implemente o endpoint de manifestação do destinatário
   (`RecepcaoEvento`) se precisar do XML completo, não só do resumo.

## Fase 3 — Importador de CT-e (SEFAZ)
- Mesmo serviço de Distribuição DFe da NFe, schema XML diferente
  (`CTeDistribuicaoDFe` conceito equivalente).
- Depois da Fase 2, isso tende a ser mais rápido — a maior parte da
  integração SOAP/SEFAZ já vai estar resolvida.

## Fase 4 — Frontend web
- Next.js + Tailwind consumindo a API já pronta.
- Telas: empresas/certificados, painel de importação por período, execuções
  em andamento, exportação (Excel/CSV/ZIP) — o equivalente ao painel
  Streamlit atual, mas multiusuário e sem travar ao fechar o navegador.

## Fase 5 — Multiempresa self-service (se decidir virar produto)
- Onboarding de novo escritório sem intervenção manual.
- Cobrança/planos.
- Isolamento de fila por escritório (evitar um escritório grande atrasar os
  outros).

Cada fase é independente o suficiente para ser um projeto de algumas
semanas — não precisa (nem deveria) tentar entregar tudo de uma vez.
