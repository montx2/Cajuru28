# NotasFlow — Passo a passo (do zero até importar notas)

Repositório: https://github.com/montx2/Cajuru28  
Branch com tudo pronto: **`arena/01a086ba-cajuru28`**

---

## O que você precisa ter instalado

1. **Git** — https://git-scm.com/downloads  
2. **Docker Desktop** — https://www.docker.com/products/docker-desktop/  
   - No Windows: instale, reinicie o PC se pedir, e deixe o Docker Desktop **aberto** (ícone de baleia na bandeja).  
3. **Python 3** (só para gerar as chaves no setup) — https://www.python.org/downloads/  
   - Na instalação do Windows, marque **"Add Python to PATH"**.

---

## Passo 1 — Baixar o projeto

Abra o **Prompt de Comando** ou **PowerShell** e rode:

```bat
cd %USERPROFILE%\Desktop
git clone https://github.com/montx2/Cajuru28.git
cd Cajuru28
git checkout arena/01a086ba-cajuru28
```

Se preferir baixar ZIP pelo GitHub:

1. Abra https://github.com/montx2/Cajuru28  
2. Botão verde **Code** → mude a branch para `arena/01a086ba-cajuru28` → **Download ZIP**  
3. Extraia numa pasta (ex.: `Desktop\Cajuru28`)

---

## Passo 2 — Gerar as chaves e o login

**Windows:** dê dois cliques em `SETUP.bat`

**Ou no terminal:**

```bat
python scripts\gerar_env.py
```

Isso cria:

- `backend\.env` — chaves do sistema  
- `frontend\.env.local` — URL da API  
- `CREDENCIAIS.txt` — **seu email e senha de login**

Abra o arquivo **`CREDENCIAIS.txt`** e anote:

```
Email:  admin@notasflow.local
Senha:  (a que o script gerou)
```

> As chaves secretas **não** ficam no Git de propósito (segurança).  
> Por isso cada máquina gera as próprias no setup.

---

## Passo 3 — Subir o sistema

1. Abra o **Docker Desktop** e espere ficar “Running”.  
2. Dê dois cliques em **`INICIAR.bat`**

Na primeira vez demora vários minutos (baixa imagens e compila o frontend).  
Quando terminar, o navegador abre em http://localhost:3000

**Pelo terminal (alternativa):**

```bat
docker compose up --build
```

Deixe essa janela aberta enquanto usar o sistema.

| O que | Endereço |
|-------|----------|
| Painel | http://localhost:3000 |
| API / Swagger | http://localhost:8000/docs |

Para parar: `PARAR.bat` ou `Ctrl+C` no terminal + `docker compose down`.

---

## Passo 4 — Entrar no painel

1. Abra http://localhost:3000  
2. Email e senha do **`CREDENCIAIS.txt`**  
3. Clique em **Entrar**

O usuário admin é criado **sozinho** na primeira subida da API (não precisa de script extra).

---

## Passo 5 — Cadastrar uma empresa

1. Menu **Empresas** → **Nova empresa**  
2. Preencha:
   - Razão social  
   - CNPJ (só números ou com máscara)  
   - UF (ex.: MG, SP)  
3. Salve e clique em **abrir** na empresa

---

## Passo 6 — Enviar o certificado A1

Na tela da empresa:

1. Escolha o arquivo **`.pfx`** (ou `.p12`) da empresa  
2. Digite a **senha do certificado**  
3. Clique em **Enviar certificado**

A senha é cifrada no banco (cofre). Não aparece de novo na tela.

Repita para as outras empresas (pode cadastrar ~30).

---

## Passo 7 — Importar as notas

### Uma empresa

Na tela da empresa, botões **NFSE** / **NFE** / **CTE**.

### Todas de uma vez

1. Menu **Visão geral**  
2. Escolha o tipo (NFS-e, NFe ou CT-e)  
3. Clique em **Importar … de todas**

Empresas sem certificado ou em “cooldown” de 1h aparecem na lista com o motivo.

### Acompanhar

Menu **Importações** — atualiza sozinho a cada 4 segundos.  
Se der erro, a mensagem aparece em vermelho na linha.

### Ver e baixar XML

Menu **Documentos** → filtre por empresa/tipo → botão **XML**.

---

## Passo 8 — (Recomendado) primeira rodada com poucas empresas

1. Cadastre **1 ou 2** empresas com certificado válido  
2. Importe só **NFS-e** primeiro  
3. Veja os logs se algo falhar:

```bat
docker compose logs -f worker
```

4. Se estiver ok, libere para as 30  

Para mais paralelismo:

```bat
docker compose up --scale worker=3
```

---

## Homologação (teste antes de produção)

No arquivo `backend\.env`, mude:

```env
AMBIENTE_FISCAL=homologacao
```

Reinicie:

```bat
docker compose restart api worker
```

Depois volte para `producao` quando validar.

---

## Problemas comuns

| Sintoma | O que fazer |
|---------|-------------|
| `docker` não é reconhecido | Instale/abra o Docker Desktop e reinicie o terminal |
| Painel abre mas login falha | Espere ~30s a API subir; confira `docker compose logs api` |
| “Sem certificado ativo” | Envie o `.pfx` na tela da empresa |
| Erro 429 / cStat 656 | Cooldown de 1h do governo — aguarde, não force em loop |
| Porta 3000 ou 8000 em uso | Feche o outro programa ou mude as portas no `docker-compose.yml` |
| Esqueci a senha do painel | Rode de novo `python scripts\gerar_env.py --forcar` e `docker compose down -v` (apaga o banco local) + `INICIAR.bat` |

---

## Checklist rápido

- [ ] Git + Docker Desktop + Python instalados  
- [ ] `git clone` + `git checkout arena/01a086ba-cajuru28`  
- [ ] `SETUP.bat` (gerou `CREDENCIAIS.txt`)  
- [ ] Docker Desktop aberto  
- [ ] `INICIAR.bat`  
- [ ] Login no painel  
- [ ] Empresa + certificado A1  
- [ ] Importar NFS-e  

---

## Segurança (quando for usar de verdade)

Troque depois no `backend\.env` e no painel:

- Senha do admin (`BOOTSTRAP_SENHA` só vale na **primeira** criação; depois altere no banco ou recrie o volume)  
- `SECRET_KEY`  
- `VAULT_MASTER_KEY` (só se ainda não houver certificados salvos)  
- Senha do PostgreSQL no `docker-compose.yml`  

Nunca envie o arquivo `CREDENCIAIS.txt` ou o `backend\.env` para o Git ou para terceiros.
