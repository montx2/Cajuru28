# NotasFlow

Importação automática de documentos fiscais (NFS-e, NFe, CT-e) direto das
fontes oficiais — **ADN nacional** (NFS-e) e **SEFAZ estadual/AN** (NFe/CT-e) —
usando o certificado A1 de cada empresa, sem portal, sem clique, sem robô de
navegador.

Evolução do `Importarnotas`: mesma ideia (API oficial + mTLS), agora em
arquitetura de sistema — pronta para crescer de uso interno do escritório
para produto multiempresa sem reescrever nada.

## Dois modos, um código

| | **Programa instalado** (recomendado) | **Servidor** |
| --- | --- | --- |
| Como se usa | Baixa um `.exe`, instala com dois cliques | `docker compose up`, painel no navegador |
| Banco | SQLite, um arquivo por computador | PostgreSQL |
| Fila | Em processo (threads) | Redis + Celery + beat |
| Painel | Servido pela própria API, sem Node | Next.js em contêiner |
| Para quem | Cada contador na própria máquina | Um banco só, vários usuários |
| Atualização | O programa se atualiza pelas Releases | `git pull` + rebuild |

Os dois compartilham **os mesmos importadores, o mesmo governador de consumo da
SEFAZ, o mesmo cofre de certificados e as mesmas rotas** — o que muda é onde cada
peça roda (`MODO_DESKTOP=true`). É isso que permite corrigir um bug uma vez e as
duas implantações ficarem corrigidas.

> **Distribuir uma versão nova:** `versao.txt` + GitHub Actions →
> [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md).
> **Usar o programa:** [`PASSO_A_PASSO.md`](PASSO_A_PASSO.md).

## Por que não usar scraping de portal

Todo portal de nota fiscal no Brasil é só uma casca visual em cima de uma API
REST/SOAP oficial de distribuição de documentos (DF-e), autenticada pelo
próprio certificado digital A1 da empresa via mTLS. Ir direto na API:

- não quebra quando o layout do portal muda;
- não tem CAPTCHA, sessão de navegador ou rate limit de humano;
- é o único método realmente suportado pelo governo para grandes volumes.

## Arquitetura

**Programa instalado** (o modo principal: um computador por contador, dados
locais, nada exposto na rede):

```
NotasFlow.exe (PyInstaller)
   ├── API FastAPI (uvicorn em 127.0.0.1:8765)
   │      ├── serve o painel já compilado (export estático do Next.js)
   │      └── fala com ADN/SEFAZ via mTLS (certificado A1 da empresa)
   ├── fila em processo (threads) + relógio do sincronismo
   ├── SQLite  →  %APPDATA%\NotasFlow\notasflow.db
   ├── cofre Fernet  →  senha do certificado cifrada
   ├── ícone na bandeja  →  continua sincronizando com a janela fechada
   └── atualizador  →  lê o manifesto da Release, confere SHA-256, instala em silêncio
```

**Servidor** (um banco só, vários usuários no navegador):

```
Frontend web (Next.js)
     │
     ▼
API (FastAPI) ──────┬──────────────┬───────────────┐
                     ▼              ▼               ▼
              PostgreSQL      Cofre Fernet     Redis + Celery
                                                   │
                                     ┌─────────────┴─────────────┐
                                     ▼                           ▼
                              Workers (importação)          Beat (relógio)
                                     │                    sincroniza sozinho,
                                     │                    retoma o que a SEFAZ
                                     │                    pediu para esperar
                                     ▼
                          ┌──────────┴──────────┐
                          ▼                     ▼
                    ADN (NFS-e)            SEFAZ AN
                                          (NFe / CT-e)
```

Detalhes em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md).
**Como o sistema conversa com a SEFAZ sem queimar o CNPJ** — cooldown de 1h,
cStat 656, cursor por NSU, cota de consultas pontuais, competência e download
em massa — está em [`docs/SINCRONIZACAO.md`](docs/SINCRONIZACAO.md).
Fases em [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Stack

| Camada         | Escolha              | Por quê |
| -------------- | -------------------- | ------- |
| Backend        | Python 3.11 + FastAPI | X.509/mTLS/XML fiscal |
| Banco          | SQLite (instalado) / PostgreSQL (servidor) | Um arquivo por computador, ou um banco central |
| Fila           | Threads em processo (instalado) / Redis + Celery (servidor) | Retomada automática e lease por CNPJ nos dois modos |
| Cofre          | Fernet (AES)         | Senha de certificado nunca em texto puro |
| Auth           | JWT                  | Multiusuário + `escritorio_id` |
| Frontend       | Next.js 16 + Tailwind | Export estático no programa; servidor no modo Docker |
| Distribuição   | PyInstaller + Inno Setup + Releases | `.exe` instalável que se atualiza sozinho |
| Deploy servidor| Docker Compose       | Sobe em qualquer máquina com Docker |

## Rodando localmente

**Guia de quem usa:** [`PASSO_A_PASSO.md`](PASSO_A_PASSO.md)
**Guia de quem publica:** [`docs/DISTRIBUICAO.md`](docs/DISTRIBUICAO.md)

### Programa instalado (Windows)

Baixe e instale a versão mais recente — sem Docker, sem Python, sem
administrador:

https://github.com/montx2/Cajuru28/releases/latest

Para gerar o instalador você mesmo (precisa de Python 3.11, Node 20+ e,
opcionalmente, [Inno Setup](https://jrsoftware.org/isdl.php)):

```bat
pip install -r backend\requirements-desktop.txt
npm ci --prefix frontend
python scripts\empacotar.py                  :: dist\NotasFlow-Setup-<versão>.exe
```

Para rodar do código-fonte, sem empacotar nada:

```bat
cd backend
python desktop_main.py                       :: abre o programa
python desktop_main.py --diagnostico         :: mostra pastas, banco e versão
python desktop_main.py --redefinir-senha     :: nova senha do administrador
```

### Modo servidor — PC zerado (Docker)

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

1. **Empresas** → razão social, CNPJ e UF (ou **Importar em massa**, abaixo)  
2. Abrir empresa → enviar `.pfx` + senha do certificado A1  
3. **Visão geral / Importações** → **marcar as empresas** que você quer e
   importar só elas (NFS-e / NFe / CT-e, com competência opcional).
   A lista já mostra, antes de disparar, quem pode rodar agora, quem está na
   janela de 1 h da SEFAZ e quem está sem certificado  
4. **Importações** → acompanhar; depois do primeiro ciclo você para de clicar:  
   o agendador mantém todo CNPJ em dia e retoma sozinho quem ficou na  
   janela de espera da SEFAZ  
5. **Documentos** → escolher o mês (**competência**), marcar o que quiser e  
   **baixar todos os XMLs** num ZIP (XMLs + `relacao.csv` + `LEIA-ME.txt`)  

### Importar por empresa, não "todas de uma vez"

Cada consulta gasta a **janela de 1 hora daquele CNPJ** na SEFAZ. Varrer 30
empresas quando o cliente pediu duas atrasa quem foi pedido — e consumo
indevido é o único jeito de o CNPJ ser bloqueado. Por isso o fluxo principal é a
**seleção**: marque as empresas, veja a prévia (`pode rodar agora`, `na janela de
1 h`, `sem certificado`) e dispare. A seleção fica guardada no navegador entre
as sessões, e o botão **Forçar janela** existe para o caso de certeza (está
marcado como exceção porque insistir antes da hora zera o cronômetro do
bloqueio).

Endpoints: `POST /importacoes/selecionadas` e
`POST /importacoes/selecionadas/previa`.

### Importar empresas em massa (estilo JetTax360)

Em **Empresas → Importar em massa** você seleciona vários `.pfx`/`.p12` de uma
vez, informa a senha (comum a todos ou por empresa no CSV) e o sistema:

- lê o **CNPJ** e a **razão social** de dentro de cada certificado A1
  (campo ICP-Brasil do X.509, com fallback pelo nome do arquivo);
- cria a empresa automaticamente, grava o `.pfx` e cifra a senha no cofre;
- se o CNPJ já existe, apenas vincula/atualiza o certificado;
- mostra um relatório linha a linha: criada, certificado vinculado, já
  existia ou erro (senha incorreta, arquivo inválido…) — um arquivo com
  problema **não** impede os demais.

O CSV é opcional: `razao_social;cnpj_cpf;uf[;senha]` (UTF-8, `;` como
separador). Serve para cadastrar empresas sem certificado e/ou informar senha
individual por CNPJ.

> Importante: o sistema usa **somente a senha que você informa**. Não há
> tentativa automática de senhas "comuns" — se a senha de um arquivo não
> bater, ele aparece como erro no relatório e você reenvia com a senha certa.

### Sincronização quase automática (o que mudou nesta versão)

Depois de cadastrar empresa + certificado, **não existe mais clique obrigatório**:

- o `beat` consulta cada CNPJ no ritmo que a SEFAZ permite (janela de 1h por
  documento, round-robin entre as empresas do escritório);
- `cStat 656 – Consumo Indevido` deixou de ser "Erro" vermelho na tela: vira
  **Aguardando a SEFAZ**, com a hora em que a continuação já está marcada;
- quem consulta o mesmo CNPJ em outro sistema não derruba o cursor — o
  `ultNSU` devolvido na própria rejeição realinha o checkpoint;
- nota que chegou só em `resumo` (resNFe) tem o XML completo buscado pela chave
  numa rodada própria, dentro da cota oficial de 20 consultas/h;
- cancelamentos e eventos continuam entrando pela mesma varredura.

Regras, ajustes e diagnóstico estão em [`docs/SINCRONIZACAO.md`](docs/SINCRONIZACAO.md).

### Competência (mês) e download em massa

Tanto a importação quanto a tela de documentos entendem `competencia=08/2026`
(o navegador usa o seletor nativo de mês):

- a **descida** do lote é por NSU — baixar tudo é o que garante que nenhuma
  nota se perca, e é por isso que o mês não limita a consulta;
- a **contagem, a lista, o resumo e o ZIP** são recortados pelo mês declarado no
  próprio XML (`competencia` indexada), então trocar de mês custa zero requests;
- `GET /documentos/exportar` gera um ZIP com **todos os XMLs do filtro** para
  todas as empresas do escritório, com `relacao.csv` (`;` + BOM, abre no Excel
  brasileiro) e um `LEIA-ME.txt`; `GET /documentos/exportar/estimativa` diz
  quantos arquivos/MB antes de você clicar;
- a seleção da tela vira `documento_ids=1,2,3` no mesmo endpoint — dá para
  baixar só o que está marcado, ou o mês inteiro.

### Notas canceladas

Os importadores agora reconhecem os **eventos de cancelamento** misturados na
distribuição (ADN e SEFAZ) e:

- marcam a nota como **CANCELADA** (com motivo e data) em **Documentos**;
- se o cancelamento chegar **antes** da nota, ele fica guardado e é aplicado
  automaticamente quando a nota chegar — nada se perde;
- a coluna **Canceladas** em **Importações** mostra quantas foram detectadas
  em cada execução;
- itens que não são nota nem cancelamento (ex.: CC-e) são contabilizados em
  **não reconhecidos** e exibidos como aviso — nunca somem sem rastro;
- `GET /documentos/resumo?empresa_id=N` devolve total / normais / canceladas.

### Migração automática de banco

Colunas novas (status de cancelamento, contadores, avisos) são adicionadas
**sozinhas** no startup — quem já tem banco criado não precisa rodar SQL
manual. Também dá para rodar antes:

```bash
docker compose exec api python scripts/migrar.py
```

### Muitas empresas de uma vez (modo servidor)

`POST /importacoes/lote?tipo=nfse` continua existindo para quem tem um banco só
e quer disparar para todas — no programa instalado o caminho é a seleção (acima).
Uma empresa travar não puxa as outras. Para mais paralelismo:

```bash
docker compose up --scale worker=3
```

O serviço `beat` roda uma única instância de propósito (é o relógio do
sincronismo — escalar duplicaria os disparos na SEFAZ).

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
- [x] Fase 5 — Programa instalado (.exe) com atualização automática
- [x] Fase 6 — Importação por seleção de empresas
- [ ] Fase 7 — Assinatura de código (Authenticode) e primeiro uso fora do escritório

## Testes

```bash
cd backend
pip install -r requirements-dev.txt
pytest -q                     # 129 testes
```

Os testes cobrem os caminhos que **não podem falhar no computador do cliente**:
primeira abertura do programa com pasta de dados vazia (banco SQLite criado
sozinho, sem tocar no PostgreSQL do servidor), comparação de versão do
atualizador, conferência de SHA-256 do instalador baixado e escolha da porta do
painel.

## Recuperação de certificado e rotação da chave do cofre

A `VAULT_MASTER_KEY` do `backend/.env` não deve mudar depois que certificados
forem enviados. Se uma importação informar **“Certificado inacessível”**,
restaure a chave que estava no `.env` quando o certificado foi cadastrado e
reinicie `api` e `worker`. Se essa chave não existir mais, por segurança a
senha não é recuperável: envie o `.pfx` e a senha novamente pela tela da
empresa.

Para trocar a chave de propósito, configure a antiga temporariamente em
`VAULT_PREVIOUS_MASTER_KEYS`, reenvie os certificados e depois remova a chave
antiga. O comando `python scripts/gerar_env.py --forcar` preserva a chave do
cofre por padrão.

## Homologação com certificado real

No `.env`:

```
AMBIENTE_FISCAL=homologacao
```

Reinicie API, worker e beat (`docker compose restart api worker beat`), rode a
importação com 1–2 empresas primeiro, confira os logs do worker:

```bash
docker compose logs -f worker beat
```

Se aparecer cStat 656 / HTTP 429, **está funcionando**: é a janela oficial de
1 hora entre consultas do mesmo CNPJ, o sistema registrou `Aguardando a SEFAZ`
e vai retomar sozinho na hora certa. Não force em loop — repetir a consulta antes
da janela zera o cronômetro do bloqueio. `forcar=true` existe para o caso de
certeza (cursor preso, troca de autorizador) e fica registrado na execução.
