# Como atualizar o NotasFlow sem reinstalar tudo

**Resposta curta:** rode `ATUALIZAR.bat`. Só isso.

```
ATUALIZAR.bat
```

No Linux/macOS: `./ATUALIZAR.sh`

Leva 1–3 minutos. Você **não** precisa rodar `INSTALAR_TUDO.bat` de novo —
esse é só para a primeira vez, num PC que ainda não tem Docker e Python.

---

## Seus dados não se perdem

Esta é a dúvida mais comum. O código e os dados moram em lugares diferentes:

| Onde | O que guarda | O que acontece ao atualizar |
|---|---|---|
| Pasta do projeto | Código-fonte | Substituído pela versão nova |
| Volume `db_data` | Banco: empresas, notas, usuários | **Intacto** |
| Volume `certificados` | Certificados A1 | **Intacto** |
| Volume `xml_saida` | XMLs baixados | **Intacto** |
| `backend/.env` | Suas chaves e senhas | **Intacto** (não vai para o Git) |

Volumes Docker são independentes dos contêineres. Atualizar destrói e recria
os contêineres, mas os volumes continuam onde estão e são reconectados.

Seu **login continua o mesmo** — inclusive a senha.

---

## O que o `ATUALIZAR.bat` faz

1. `git pull --ff-only` — baixa o código novo.
2. `docker compose up --build -d` — reconstrói só o que mudou e reinicia.

O passo 2 aproveita o cache do Docker: se as dependências não mudaram, ele
não baixa nada de novo. Por isso é rápido, diferente da primeira instalação.

As migrações do banco rodam sozinhas quando a API sobe.

---

## Atualizar sem Git (baixando o ZIP)

Se você baixou o projeto como ZIP em vez de clonar:

1. Baixe o ZIP novo do GitHub e extraia numa pasta **separada**.
2. Copie da pasta antiga para a nova:
   - `backend/.env`
   - `frontend/.env.local`
   - `CREDENCIAIS.txt`
3. Rode `INICIAR.bat` na pasta nova.

> Os volumes Docker são globais na máquina, não ficam dentro da pasta. Desde
> que o nome da pasta seja o mesmo de antes, o Compose reencontra os dados.
> Se você renomear a pasta, o Compose cria volumes novos e o sistema parece
> "vazio" — os dados antigos continuam lá, só desconectados (`docker volume ls`).

---

## Comandos equivalentes, se preferir o terminal

```bash
git pull --ff-only
docker compose up --build -d
```

Ver se subiu:

```bash
docker compose ps
docker compose logs -f api
```

---

## Problemas comuns ao atualizar

### "Não foi possível atualizar o código automaticamente"

O `git pull --ff-only` recusa quando há alterações locais nos arquivos.

```bash
git status          # ver o que mudou
git stash           # guardar as alterações de lado
git pull --ff-only
```

O sistema sobe mesmo assim, só que com a versão antiga do código.

### O painel abre com a aparência velha

Cache do navegador. `Ctrl + Shift + R` força o recarregamento.

### Mudei o `frontend/.env.local` e nada aconteceu

`NEXT_PUBLIC_*` é embutido no build do Next. Precisa reconstruir:

```bash
docker compose up --build -d frontend
```

### Não consigo mais entrar depois de atualizar

Rode `RESETAR_SENHA.bat`. Veja também a seção de login em
[SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md).

---

## Quando (raramente) vale recomeçar do zero

Só se o ambiente estiver realmente corrompido:

```bash
docker compose down
docker compose up --build -d
```

Isso recria os contêineres **mantendo** os dados.

> ⚠️ **Nunca** use `docker compose down -v` para atualizar. O `-v` apaga os
> volumes — banco, certificados e XMLs vão junto.

Faça backup antes de qualquer operação destrutiva (comandos em
[SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md)).
