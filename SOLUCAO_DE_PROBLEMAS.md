# Solução de problemas — NotasFlow

## `failed to solve: write /var/lib/desktop-containerd/.../meta.db: read-only file system`

**Esse erro não vem do NotasFlow.** É o Docker Desktop que não conseguiu
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

> ⚠️ Isso apaga imagens, containers **e volumes**. Os dados do NotasFlow
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

## `port is already allocated`

Alguma porta usada pelo projeto (3000, 8000, 5432 ou 6379) já está ocupada —
geralmente um Postgres/Redis instalado direto no Windows, ou uma execução
anterior do próprio NotasFlow.

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
