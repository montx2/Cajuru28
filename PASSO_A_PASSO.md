# NotasFlow — Passo a passo (do zero até importar notas)

Repositório: https://github.com/montx2/Cajuru28

---

## Passo 1 — Baixar o projeto

Abra o **Prompt de Comando** ou **PowerShell** e rode:

```bat
cd %USERPROFILE%\Desktop
git clone https://github.com/montx2/Cajuru28.git
cd Cajuru28
```

Se preferir baixar ZIP pelo GitHub:

1. Abra https://github.com/montx2/Cajuru28
2. Botão verde **Code** → **Download ZIP**
3. Extraia numa pasta (ex.: `Desktop\Cajuru28`)

> Não tem Git? Sem problema — baixe o ZIP, extraia, e siga o Passo 2:
> o `INSTALAR_TUDO.bat` instala o Git (e todo o resto) sozinho.

---

## Passo 2 — Instalar tudo e subir o sistema (1 clique)

**Windows:** dê dois cliques em **`INSTALAR_TUDO.bat`**

Ele faz **tudo** sozinho, num PC que não tem nada:

1. Instala o **Git** (se não tiver)
2. Instala o **Python 3** (se não tiver)
3. Instala o **Docker Desktop** + **WSL2** (se não tiver)
4. Gera suas **chaves de segurança** e o **login** (`CREDENCIAIS.txt`)
5. Sobe o sistema (containers) e **abre o painel no navegador**

Pontos importantes:

- Se pedir **permissão de Administrador**, clique **Sim**.
- Se o Windows pedir **reiniciar** (para habilitar o WSL2), reinicie e
  dê dois cliques em `INSTALAR_TUDO.bat` de novo — ele continua de onde parou.
- Pode rodar quantas vezes quiser: o que já está instalado é pulado.
- A primeira vez demora vários minutos (baixa imagens e compila o frontend).

**Linux / macOS:**

```bash
./INSTALAR_TUDO.sh                  # instala tudo e sobe
./INSTALAR_TUDO.sh --so-verificar   # só checa o que falta
```

Pronto — quando terminar, o navegador abre em http://localhost:3000

| O que | Endereço |
|-------|----------|
| Painel | http://localhost:3000 |
| API / Swagger | http://localhost:8000/docs |

---

## Passo 3 — Entrar no painel

1. Abra http://localhost:3000
2. Email e senha do **`CREDENCIAIS.txt`** (gerado na instalação)
3. Clique em **Entrar**

O usuário admin é criado **sozinho** na primeira subida da API (não precisa de script extra).

---

## Passo 4 — Cadastrar uma empresa

1. Menu **Empresas** → **Nova empresa**  
2. Preencha:
   - Razão social  
   - CNPJ (só números ou com máscara)  
   - UF (ex.: MG, SP)  
3. Salve e clique em **abrir** na empresa

---

## Passo 5 — Enviar o certificado A1

Na tela da empresa:

1. Escolha o arquivo **`.pfx`** (ou `.p12`) da empresa  
2. Digite a **senha do certificado**  
3. Clique em **Enviar certificado**

A senha é cifrada no banco (cofre). Não aparece de novo na tela.

Repita para as outras empresas (pode cadastrar ~30).

---

## Passo 6 — Importar as notas

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

## Passo 7 — (Recomendado) primeira rodada com poucas empresas

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
| `docker` não é reconhecido | Rode `INSTALAR_TUDO.bat` — ele instala o Docker sozinho |
| Docker instalado mas "não ligou" | Abra o Docker Desktop e espere a baleia parar de animar; ou rode `INICIAR.bat` (ele liga sozinho) |
| Pediu reinício do Windows | Normal ao habilitar WSL2 — reinicie e rode `INSTALAR_TUDO.bat` de novo |
| Painel abre mas login falha | Espere ~30s a API subir; confira `docker compose logs api` |
| “Sem certificado ativo” | Envie o `.pfx` na tela da empresa |
| “Certificado inacessível; restaure a chave…” | A `VAULT_MASTER_KEY` foi alterada ou a senha cifrada corrompeu. Restaure no `backend/.env` a chave usada quando o certificado foi enviado e reinicie `api` e `worker`; se não a tiver, envie novamente o `.pfx` com a senha. |
| `duplicate key` / `uq_documento_por_empresa` | Atualize pelo `ATUALIZAR.bat` e importe outra vez. A versão atual ignora a mesma nota de forma atômica; não apague documentos do banco. |
| Erro 429 / cStat 656 | Cooldown de 1h do governo — aguarde, não force em loop |
| Porta 3000 ou 8000 em uso | Feche o outro programa ou mude as portas no `docker-compose.yml` |
| Esqueci a senha do painel | Rode de novo `python scripts\gerar_env.py --forcar` e `docker compose down -v` (apaga o banco local) + `INICIAR.bat` |
| Quero a versão mais recente | Rode `ATUALIZAR.bat` (baixa o código novo e reconstrói) |

---

## Checklist rápido

- [ ] Baixou o projeto (`git clone` ou ZIP)  
- [ ] `INSTALAR_TUDO.bat` (instalou tudo e gerou `CREDENCIAIS.txt`)  
- [ ] Painel abrindo em http://localhost:3000  
- [ ] Login no painel  
- [ ] Empresa + certificado A1  
- [ ] Importar NFS-e  

---

## Segurança (quando for usar de verdade)

Troque depois no `backend\.env` e no painel:

- Senha do admin (`BOOTSTRAP_SENHA` só vale na **primeira** criação; depois altere no banco ou recrie o volume)  
- `SECRET_KEY`  
- `VAULT_MASTER_KEY` — **não a troque** enquanto houver certificados salvos. O `gerar_env.py --forcar` a preserva automaticamente. Para uma rotação planejada, configure temporariamente a chave anterior em `VAULT_PREVIOUS_MASTER_KEYS`, reenvie os certificados e só então remova a chave antiga.
- Senha do PostgreSQL no `docker-compose.yml`  

Nunca envie o arquivo `CREDENCIAIS.txt` ou o `backend\.env` para o Git ou para terceiros.
