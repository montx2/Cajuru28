# NotasFlow

Importação automática de documentos fiscais (NFS-e, NFe, CT-e) direto das
fontes oficiais — **ADN nacional** (NFS-e) e **SEFAZ estadual** (NFe/CT-e) —
usando o certificado A1 de cada empresa, sem portal, sem clique, sem robô de
navegador.

Este projeto é a evolução do `Importarnotas`: mesma ideia (API oficial +
mTLS), agora em arquitetura de sistema — pronta para crescer de "uso interno
do escritório" para "produto multiempresa" sem reescrever nada.

## Por que não usar scraping de portal

Todo portal de nota fiscal no Brasil é só uma casca visual em cima de uma API
REST/SOAP oficial de distribuição de documentos (DF-e), autenticada pelo
próprio certificado digital A1 da empresa via mTLS. Ir direto na API:

- não quebra quando o layout do portal muda;
- não tem CAPTCHA, sessão de navegador ou rate limit de humano;
- é o único método realmente suportado pelo governo para grandes volumes.

O `Importarnotas` (repositório original) já fazia isso para NFS-e via ADN.
Este projeto generaliza esse padrão para NFe e CT-e via SEFAZ, e troca a
base "script local + Streamlit" por um sistema de verdade.

## Arquitetura (visão geral)

```
Frontend web
     │
     ▼
API (FastAPI) ──────┬──────────────┬───────────────┐
                     ▼              ▼               ▼
              Banco de dados   Cofre de        Fila de
              (PostgreSQL)     segredos        importação
                               (senhas          (Redis + Celery)
                                cifradas)              │
                                                        ▼
                                                    Workers
                                                   ┌────┴────┐
                                                   ▼         ▼
                                            ADN nacional  SEFAZ
                                            (NFS-e)       (NFe / CT-e)
```

Detalhes de cada decisão em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).
Fases de construção em [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Stack

| Camada          | Escolha                        | Por quê |
| --------------- | ------------------------------- | ------- |
| Backend          | Python 3.11 + FastAPI           | Mesma linguagem da base atual; ecossistema forte para X.509/mTLS/XML fiscal |
| Banco            | PostgreSQL                      | Concorrência real, pronto para multiempresa desde o início (SQLite não escala para SaaS) |
| Fila             | Redis + Celery                  | Importação roda em background, com retry automático e não trava a interface |
| Cofre de senhas  | Criptografia simétrica (Fernet) | Senha de certificado nunca em texto puro, nunca em planilha |
| Autenticação     | JWT                             | Multiusuário, pronto para multiempresa (`escritorio_id` em cada tabela) |
| Deploy           | Docker Compose                  | Sobe em qualquer VPS ou Windows com Docker Desktop — nada de `.bat` |

## Rodando localmente

```bash
cp backend/.env.example backend/.env
# edite backend/.env com a SECRET_KEY e a VAULT_MASTER_KEY (veja o arquivo)
cp frontend/.env.example frontend/.env.local
docker compose up --build
```

- API + Swagger: `http://localhost:8000/docs`
- Painel web: `http://localhost:3000`

Crie o primeiro escritório e usuário antes de logar no painel:
```bash
docker compose exec api python scripts/criar_usuario_inicial.py
```

## O painel web

Next.js + Tailwind, direção visual de "caderno de protocolo oficial" — fundo
papel-frio, um único acento (verde institucional, evocando certificado
validado), números e códigos (CNPJ, chave de acesso, NSU, valores) sempre em
monoespaçada e alinhados à direita, tabelas com regra fina em vez de card
genérico de SaaS. Sem bibliotecas de UI pesadas — só o que a tela precisa.

Telas: **Visão geral** (dispara importação para todas as empresas de uma
vez), **Empresas** (cadastro + upload de certificado A1), **Importações**
(histórico com atualização automática) e **Documentos** (consulta com filtro
por empresa/tipo).


## Importando várias empresas de uma vez

`POST /importacoes/lote?tipo=nfse` dispara a importação de todas as
empresas ativas do escritório em uma chamada só — cada uma vira uma task
independente na fila, então uma travar ou dar erro não afeta as outras.
Empresas sem certificado ativo, ou que consultaram o ADN há menos de 1h sem
encontrar nada novo (proteção contra bloqueio de CNPJ), aparecem na
resposta como `sem_certificado` / `em_cooldown` em vez de serem enfileiradas
silenciosamente.

Para escalar além do padrão (4 importações em paralelo por container):
```bash
docker compose up --scale worker=3
```

## Status

- [x] Fase 0 — Fundação: banco multiempresa, cofre de segredos, autenticação, API de empresas/certificados
- [x] Fase 1 — Importador de NFS-e via ADN (portado do `Importarnotas`), com retry e cooldown de 1h
- [x] Fase 2 — Importador de NFe via SEFAZ (Distribuição DFe) — implementado, aguardando validação em homologação com certificado real
- [ ] Fase 3 — Importador de CT-e via SEFAZ (mesmo serviço de distribuição da NFe)
- [x] Fase 4 — Frontend web (Next.js + Tailwind)
- [ ] Fase 5 — Multiempresa self-service (onboarding, cobrança)

Veja o `docs/ROADMAP.md` para escopo e ordem de cada fase.
