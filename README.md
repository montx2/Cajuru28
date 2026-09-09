# NotasFlow

Importação automática de documentos fiscais (NFS-e, NFe, CT-e) direto das
fontes oficiais — **ADN nacional** (NFS-e) e **SEFAZ estadual/AN** (NFe/CT-e) —
usando o certificado A1 de cada empresa, sem portal, sem clique, sem robô de
navegador.

Evolução do `Importarnotas`: mesma ideia (API oficial + mTLS), agora em
arquitetura de sistema — pronta para crescer de uso interno do escritório
para produto multiempresa sem reescrever nada.

## Por que não usar scraping de portal

Todo portal de nota fiscal no Brasil é só uma casca visual em cima de uma API
REST/SOAP oficial de distribuição de documentos (DF-e), autenticada pelo
próprio certificado digital A1 da empresa via mTLS. Ir direto na API:

- não quebra quando o layout do portal muda;
- não tem CAPTCHA, sessão de navegador ou rate limit de humano;
- é o único método realmente suportado pelo governo para grandes volumes.

## Arquitetura

```
Frontend web (Next.js)
     │
     ▼
API (FastAPI) ──────┬──────────────┬───────────────┐
                     ▼              ▼               ▼
              PostgreSQL      Cofre Fernet     Redis + Celery
                                                   │
                                                   ▼
                                              Workers
                                         ┌─────┴─────┐
                                         ▼           ▼
                                   ADN (NFS-e)   SEFAZ AN
                                                 (NFe / CT-e)
```

Detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).
Fases em [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Stack

| Camada         | Escolha              | Por quê |
| -------------- | -------------------- | ------- |
| Backend        | Python 3.11 + FastAPI | X.509/mTLS/XML fiscal |
| Banco          | PostgreSQL           | Multiempresa, concorrência |
| Fila           | Redis + Celery       | Importação em background com retry |
| Cofre          | Fernet (AES)         | Senha de certificado nunca em texto puro |
| Auth           | JWT                  | Multiusuário + `escritorio_id` |
| Frontend       | Next.js 16 + Tailwind | Painel operacional clean |
| Deploy         | Docker Compose       | Sobe em qualquer máquina com Docker |

## Rodando localmente

**Guia completo:** [`PASSO_A_PASSO.md`](PASSO_A_PASSO.md)

### Instalação automática — PC zerado (recomendado)

**Windows:** dê dois cliques em **`INSTALAR_TUDO.bat`**

Ele instala sozinho tudo o que faltar (Git, Python 3, Docker Desktop com
WSL2), gera as chaves de segurança, cria o login, sobe o sistema e abre o
painel no navegador. Pode rodar quantas vezes quiser — o que já está
instalado é detectado e pulado. Se pedir permissão de Administrador, clique **Sim**.

**Linux / macOS:**

```bash
./INSTALAR_TUDO.sh          # instala tudo e sobe o sistema
./INSTALAR_TUDO.sh --so-verificar   # só mostra o que falta, sem instalar
```

| Script | O que faz |
| ------ | --------- |
| `INSTALAR_TUDO.bat` / `.sh` | Instala TUDO num PC zerado e sobe o sistema |
| `INICIAR.bat` | Liga o sistema (liga o Docker sozinho; oferece instalar se faltar) |
| `PARAR.bat` | Para o sistema (`docker compose down`) |
| `ATUALIZAR.bat` / `.sh` | Atualiza o código (`git pull`) e reconstrói |
| `SETUP.bat` | Só gera as chaves e o `CREDENCIAIS.txt` |

### Resumo manual (alternativa)

```bat
git clone https://github.com/montx2/Cajuru28.git
cd Cajuru28
SETUP.bat          :: gera chaves + CREDENCIAIS.txt
INICIAR.bat        :: sobe Docker e abre o painel
```

Login: abra `CREDENCIAIS.txt` (email + senha gerados no seu PC).

| Serviço | URL |
| ------- | --- |
| Painel web | http://localhost:3000 |
| API + Swagger | http://localhost:8000/docs |

### Uso no painel

1. **Empresas** → razão social, CNPJ e UF  
2. Abrir empresa → enviar `.pfx` + senha do certificado A1  
3. **Visão geral** → importar NFS-e / NFe / CT-e de todas  
4. **Importações** → acompanhar (atualiza sozinho)  
5. **Documentos** → consultar e baixar XML

### 30 empresas de uma vez

`POST /importacoes/lote?tipo=nfse` (ou o botão da Visão geral) dispara uma
task por empresa. Uma travar não puxa as outras. Para mais paralelismo:

```bash
docker compose up --scale worker=3
```

## Fontes oficiais usadas

- [Manual dos Contribuintes — APIs do ADN](https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual/manual-contribuintes-apis-adn-sistema-nacional-nfse.pdf) — `GET /DFe/{NSU}`
- [Swagger ADN contribuintes](https://adn.nfse.gov.br/contribuintes/docs/index.html)
- [NT 2014.002 / NFeDistribuicaoDFe](https://www.nfe.fazenda.gov.br/) + [sped-nfe DistDFe](https://github.com/nfephp-org/sped-nfe/blob/master/docs/metodos/DistDFe.md)
- [Portal CT-e — CTeDistribuicaoDFe](http://www.cte.fazenda.gov.br/portal/webServices.aspx) + [sped-cte](https://github.com/nfephp-org/sped-cte) + [PyNFe](https://github.com/TadaSoftware/PyNFe)
- Repositório original validado: [montx2/Importarnotas](https://github.com/montx2/Importarnotas)

## Status

- [x] Fase 0 — Fundação
- [x] Fase 1 — NFS-e via ADN (corrigida contra manual oficial)
- [x] Fase 2 — NFe via SEFAZ AN
- [x] Fase 3 — CT-e via SEFAZ AN
- [x] Fase 4 — Frontend web
- [ ] Fase 5 — Multiempresa self-service

## Testes

```bash
cd backend
pip install -r requirements-dev.txt
pytest -q
```

## Homologação com certificado real

No `.env`:

```
AMBIENTE_FISCAL=homologacao
```

Reinicie API + worker (`docker compose restart api worker`), rode a importação
com 1–2 empresas primeiro, confira os logs do worker:

```bash
docker compose logs -f worker
```

Se aparecer cStat 656 / HTTP 429, o cooldown de 1h já protege — não force em
loop. Só use `forcar=true` (ou o equivalente na API) com consciência.
