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

## O que fica para depois de propósito

- **Alembic (migrations versionadas)**: hoje o banco sobe via
  `Base.metadata.create_all` no start da API. Funciona bem para uso interno.
  Antes de ter mais de uma pessoa mexendo no schema ao mesmo tempo, ou antes
  de ir para produção com dado de cliente real, trocar para Alembic é o
  próximo passo natural — deixei o ponto de troca já isolado em
  `app/db/base.py`.
- **Vault externo (HashiCorp/KMS)**: ver seção acima.
- **Frontend**: a API já está pronta para qualquer frontend (Swagger em
  `/docs` funciona como painel de teste enquanto isso). Recomendo Next.js
  (React + Tailwind) quando for a hora — converso sobre isso na Fase 4.
