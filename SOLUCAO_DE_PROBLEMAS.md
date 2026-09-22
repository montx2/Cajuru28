# Solução de problemas — Fluxa

## `ports are not available: ... listen tcp 0.0.0.0:3000: bind: An attempt was made to access a socket in a way forbidden by its access permissions`

**Esse erro é do Windows, não do Fluxa.** Ele aparece ao subir o
container do frontend (porta 3000) e tem duas causas comuns:

1. **Faixa de porta reservada pelo Hyper-V/WinNAT** (a mais comum): a cada
   boot o Windows reserva faixas dinâmicas de portas TCP para si, e a 3000
   cai nelas com frequência. Nada está *usando* a porta — ela está
   *proibida* para qualquer programa.
2. Outro programa já está escutando na porta (Node, outro Docker, etc).

Confira qual é o seu caso:

```powershell
netstat -ano | findstr :3000        # vazio = ninguém usando; provável reserva
netsh interface ipv4 show excludedportrange protocol=tcp   # faixas reservadas
```

### O sistema já se protege sozinho

O `INICIAR.bat` / `INSTALAR_TUDO` **testam as portas antes de subir** e,
se a 3000 estiver ocupada ou reservada, escolhem automaticamente a próxima
livre (3001, 3002, …) e gravam no `.env` da raiz — o docker-compose lê de
lá. O endereço do painel passa a ser, por exemplo,
`http://localhost:3001` (o script mostra qual foi usado e o abrevia no
navegador). A escolha é estável: gravada no `.env`, vale até o dia em que
deixar de funcionar.

### Como usar a porta 3000 de volta (opcional)

Se você *quer* a 3000 (ex.: favorito salvo), num PowerShell **como
administrador**:

```powershell
net stop winnat
net start winnat
```

Isso libera as reservas dinâmicas (o Hyper-V re-reserva outras na próxima
reinicialização). Para reservar a 3000 permanentemente para o Docker:

```powershell
net stop winnat
netsh int ipv4 add excludedportrange protocol=tcp startport=3000 numberofports=1
net start winnat
```

Depois apague a linha `FRONTEND_PORT` do `.env` da raiz e rode
`INICIAR.bat` de novo.

### Como fixar qualquer porta manualmente

Crie/edite o arquivo `.env` **na raiz do projeto** (o mesmo que o script
gera) e defina:

```
FRONTEND_PORT=3030
API_PORT=8080        # opcional; se mudar, o frontend é reconstruído sozinho
```

> Porta do painel e do navegador: trocar `FRONTEND_PORT` muda só o
> endereço no navegador. Trocar `API_PORT` exige reconstruir o frontend
> (o `INICIAR.bat` já faz com `--build`).

---

## `failed to solve: write /var/lib/desktop-containerd/.../meta.db: read-only file system`

**Esse erro não vem do Fluxa.** É o Docker Desktop que não conseguiu
escrever no próprio banco interno de metadados (`meta.db`), dentro da máquina
virtual dele. Nenhuma linha de código ou de `docker-compose.yml` do projeto
influencia isso.

Causas típicas, em ordem de frequência:

1. A VM do Docker Desktop travou e remontou o disco como somente-leitura
   (acontece muito depois de o Windows hibernar ou desligar na tesoura).
2. Disco cheio — quando falta espaço, o sistema de arquivos da VM vira
   somente-leitura para se proteger.
3. Corrupção do disco virtual (`ext4.vhdx` no WSL2) após um desligamento
   abrupto.

### Como resolver (faça na ordem, parando quando funcionar)

**1. Reiniciar o Docker Desktop**

Clique com o botão direito na baleia na bandeja do Windows →
`Quit Docker Desktop`. Espere fechar de verdade, abra de novo, aguarde a
baleia ficar estável e rode `INICIAR.bat`.

**2. Restart pelo Troubleshoot**

Docker Desktop → ícone de bug (Troubleshoot) → **Restart**.

**3. Reiniciar o WSL (backend padrão no Windows)**

Em um PowerShell **como administrador**:

```powershell
wsl --shutdown
```

Depois abra o Docker Desktop de novo.

**4. Liberar espaço em disco**

Deixe pelo menos **10 GB livres** no disco C:. Depois:

```powershell
docker system prune -a
docker builder prune -a
```

**5. Reiniciar o Windows**

Resolve boa parte dos casos em que a VM ficou em estado inconsistente.

**6. Último recurso: limpar os dados do Docker**

Docker Desktop → Troubleshoot → **Clean / Purge data** (ou reinstalar o
Docker Desktop).

> ⚠️ Isso apaga imagens, containers **e volumes**. Os dados do Fluxa
> ficam nos volumes `db_data`, `certificados` e `xml_saida`.
> **Faça backup antes** (veja abaixo).

### Backup antes de limpar o Docker

```powershell
docker run --rm -v cajuru28-main_db_data:/v -v "%CD%":/b alpine tar czf /b/backup_db.tar.gz -C /v .
docker run --rm -v cajuru28-main_certificados:/v -v "%CD%":/b alpine tar czf /b/backup_certificados.tar.gz -C /v .
docker run --rm -v cajuru28-main_xml_saida:/v -v "%CD%":/b alpine tar czf /b/backup_xml.tar.gz -C /v .
```

Confirme os nomes reais com `docker volume ls`.

Para restaurar:

```powershell
docker volume create cajuru28-main_db_data
docker run --rm -v cajuru28-main_db_data:/v -v "%CD%":/b alpine tar xzf /b/backup_db.tar.gz -C /v
```

---

## "Não foi possível entrar. Tente novamente." no login

Essa frase é o erro **genérico** da tela — ela aparece quando o navegador
não conseguiu nem falar com a API, ou quando a credencial não bate. Rode o
diagnóstico automático, que identifica qual dos casos é o seu:

```
RESETAR_SENHA.bat
```

(no Linux/macOS: `docker compose exec api python scripts/diagnosticar_login.py`)

Ele checa o banco, lista os usuários existentes e diz exatamente qual é a
causa. As três causas reais:

### Causa 1 — a senha do `CREDENCIAIS.txt` não é a que está no banco

A mais comum. O `.env` foi regerado (senha nova no arquivo), mas o banco
já existia com o hash da senha **antiga**. O bootstrap não sobrescreve
usuário existente, de propósito — então o arquivo e o banco divergem.

```
docker compose exec api python scripts/diagnosticar_login.py --redefinir admin@notasflow.local --senha "NovaSenha123"
```

### Causa 2 — o banco não tem nenhum usuário

O bootstrap só cria o admin quando a tabela está vazia **e** as variáveis
`BOOTSTRAP_*` já estão preenchidas no momento em que a API sobe. Se o
`backend/.env` foi criado depois do primeiro `up`, ninguém foi criado.

```
docker compose exec api python scripts/diagnosticar_login.py --criar-admin
```

### Causa 3 — o navegador não alcança a API

Se o diagnóstico disser que a senha confere, o problema é de rede. Teste:

1. `docker compose ps` — o serviço `api` precisa estar `running`.
2. Abra http://localhost:8000/saude — deve responder `{"status":"ok"}`.
3. Confira `NEXT_PUBLIC_API_URL` em `frontend/.env.local`.

> `NEXT_PUBLIC_*` é embutido no build do Next. Mudar o `.env.local` **não
> tem efeito** sem reconstruir a imagem:
>
> ```
> docker compose up --build -d frontend
> ```

Veja o motivo exato no console do navegador (F12 → aba Console/Network).

---

## Esqueci a senha do admin

```
docker compose exec api python scripts/diagnosticar_login.py --redefinir admin@notasflow.local --senha "NovaSenha123"
```

Funciona para qualquer usuário e reativa quem estiver inativo.

---

## `port is already allocated`

Alguma porta usada pelo projeto (3000, 8000, 5432 ou 6379) já está ocupada —
geralmente um Postgres/Redis instalado direto no Windows, ou uma execução
anterior do próprio Fluxa.

```powershell
PARAR.bat
netstat -ano | findstr :5432
```

Encerre o processo dono do PID mostrado, ou pare o serviço local do Postgres
em `services.msc`.

---

## `no space left on device`

```powershell
docker system prune -a --volumes
```

> `--volumes` apaga também os dados. Se quiser preservar o banco, rode sem
> essa opção primeiro.

---

## Docker Desktop não liga / fica em "starting"

- Verifique se a virtualização está ativada na BIOS.
- Atualize o WSL: `wsl --update` em PowerShell como administrador.
- Confira em Docker Desktop → Settings → General se **Use the WSL 2 based
  engine** está marcado.

---

## Os containers sobem mas o painel não abre

```powershell
docker compose ps
docker compose logs -f api
docker compose logs -f frontend
```

- Se a `api` reinicia em loop: quase sempre é `backend/.env` faltando ou
  inválido. Rode `SETUP.bat`.
- Se o `db` não fica saudável: aguarde ~30 s na primeira execução; ele precisa
  inicializar o cluster do Postgres.

---

## Recomeçar do zero (mantendo o código)

```powershell
PARAR.bat
docker compose down -v
INICIAR.bat
```

> `-v` apaga os volumes — o banco e os certificados vão junto.
