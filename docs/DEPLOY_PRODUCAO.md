# Implantação de produção endurecida

> `docker-compose.yml` é **somente desenvolvimento local**. Ele expõe portas
> de banco/fila por conveniência. Para dados fiscais reais use exclusivamente
> `docker-compose.production.yml` atrás de um domínio DNS público.

## 1. Prepare segredos fora do Git

Crie os arquivos a partir dos modelos e limite a leitura ao usuário de deploy:

```bash
cp deploy/production.app.env.example deploy/production.app.env
cp deploy/production.database.env.example deploy/production.database.env
cp deploy/production.redis.env.example deploy/production.redis.env
cp deploy/production.proxy.env.example deploy/production.proxy.env
chmod 600 deploy/production*.env
```

Em ambiente gerenciado, injete o mesmo conteúdo por secret manager/identity
federation em vez de manter arquivos no servidor. Nunca cole `JETTAX_API_TOKEN`,
senhas, chaves Fernet ou URLs com credenciais em tickets, chat ou Git.

Preencha todos os placeholders, usando valores independentes e aleatórios:

- `SECRET_KEY`: ao menos 32 caracteres aleatórios;
- `VAULT_MASTER_KEY` e `BACKUP_ENCRYPTION_KEY`: duas chaves Fernet distintas;
- senha do PostgreSQL e `REDIS_PASSWORD`: ao menos 20 caracteres;
- `NOTASFLOW_DOMAIN` e `CORS_ORIGINS`: o **mesmo domínio HTTPS**; em
  `TRUSTED_HOSTS`, inclua esse domínio e `api` para o health check interno;
- bucket privado, versionado, com retenção apropriada e, de preferência, KMS.

A aplicação recusa iniciar em `APP_ENV=production` se faltar segredo, se CORS
for aberto, se banco/Redis não tiverem credencial forte, se o diretório de
backup não for exclusivo, se Redis/rate limit estiver desativado ou se não
houver destino S3 para backup ativo.

## 2. Suba a pilha

```bash
docker compose -f docker-compose.production.yml \
  --env-file deploy/production.proxy.env up -d --build
```

Só o Caddy publica `80` e `443`; API, PostgreSQL e Redis ficam apenas na rede
Docker. Caddy entrega o painel e encaminha `/api/*` internamente para FastAPI.
Isso mantém a sessão HttpOnly em uma única origem (`https://SEU-DOMINIO`) e
sobrescreve `X-Forwarded-For` para impedir que o cliente escolha a chave de
rate limiting.

A API, o worker e o job de backup compartilham os volumes persistentes de XML,
certificados A1 cifrados e `/backups`; o código não é bind-mounted em produção.
O filesystem da imagem é somente leitura, com `/tmp` em tmpfs, capacidades Linux
removidas e `no-new-privileges`. API, worker e beat executam como usuário sem
privilégios; o job transitório `volume-init` é o único processo que prepara a
permissão dos volumes antes deles iniciarem. Mantenha **uma** instância de
`beat`; workers podem ser escalados conforme a fila.

## 3. Backups e recuperação

Cada backup contém, em um pacote `tar.gz.enc`:

1. dump lógico JSONL compactado e `pg_dump` adicional quando disponível;
2. cópia integral de cada XML e certificado do momento da execução;
3. manifesto v2 com tamanho e SHA-256 de todo payload e objeto fiscal;
4. SHA-256 do pacote no banco e cópia confirmada em S3, com SSE-S3 ou KMS.

O endpoint **Saúde do sistema → Testar restauração** só decifra e extrai em pasta
temporária segura, confere checksum/hashes e carrega o dump em banco de prova.
Ele nunca sobrescreve produção. Faça esse teste após a primeira implantação e
periodicamente.

Para desastre, preserve a `BACKUP_ENCRYPTION_KEY` em cofre externo. Em uma
rotação, mantenha a chave anterior em `BACKUP_PREVIOUS_ENCRYPTION_KEYS` até que
os pacotes que dependem dela expirem. Sem ela, criptografia correta significa
que o pacote histórico não pode ser aberto.

A restauração operacional deve ser feita em ambiente isolado/novo, testada e
aprovada antes de trocar o serviço. Use o utilitário que exige confirmação e
recusa banco/pasta de dados não vazios:

```bash
# apenas cifra, manifesto e hashes
python backend/scripts/restaurar_backup.py --arquivo /backups/backup-....tar.gz.enc --validar

# somente no ambiente NOVO de recuperação
python backend/scripts/restaurar_backup.py --arquivo /backups/backup-....tar.gz.enc \
  --checksum SHA256_DO_REGISTRO_OU_METADATA_S3 \
  --destino-dados /restore-data --database-url "$DATABASE_URL_DO_BANCO_NOVO" \
  --confirmar RESTAURAR
```

Não há endpoint HTTP para sobrescrever o banco vivo deliberadamente.

## 4. Controles do storage externo

Conceda à identidade da aplicação somente `PutObject`, `HeadObject` e, quando
for necessário recuperar, `GetObject` no prefixo do NotasFlow. Não use bucket
público, ACL pública ou chave IAM ampla. A aplicação confirma `ContentLength` e
o metadado `sha256` depois do upload; se falhar, o backup fica `erro`, nunca
`ok`.

## 5. Atualização e verificação

```bash
docker compose -f docker-compose.production.yml --env-file deploy/production.proxy.env pull
docker compose -f docker-compose.production.yml --env-file deploy/production.proxy.env up -d --build
docker compose -f docker-compose.production.yml --env-file deploy/production.proxy.env ps
```

Antes de atualizar, valide em ambiente de homologação com os mesmos arquivos de
configuração (valores distintos). Depois, confira `GET /api/saude` pelo domínio
público e o status de backup. Não use `down -v`: ele apaga volumes.
