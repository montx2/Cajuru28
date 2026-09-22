# Passo a passo — Fluxa com Docker

## 1. Instalar e iniciar

- **Windows:** execute `INSTALAR_TUDO.bat`.
- **Linux/macOS:** execute `./INSTALAR_TUDO.sh`.

A instalação prepara o ambiente e inicia todos os serviços via Docker Compose.

## 2. Entrar no painel

Abra http://localhost:3000 e use as credenciais gravadas em `CREDENCIAIS.txt`.
A API e sua documentação ficam em http://localhost:8000/docs.

> Se a porta 3000 estiver ocupada/reservada no seu Windows (é comum: o
> Hyper-V reserva faixas de portas), o próprio instalador escolhe outra
> porta automaticamente e mostra o endereço certo no final. Anote-o.

## 3. Configurar empresas

1. Cadastre a empresa com CNPJ e UF.
2. Envie o certificado A1 (`.pfx` ou `.p12`) e informe a senha.
3. Em **Importações**, selecione as empresas e os tipos NFS-e, NFe ou CT-e.
4. Acompanhe a execução; o Celery Beat mantém o sincronismo automático.

## 4. Operação

```bash
docker compose ps
docker compose logs -f api worker beat frontend
docker compose down
docker compose up --build -d
```

No Windows, os atalhos equivalentes são `INICIAR.bat`, `PARAR.bat` e
`ATUALIZAR.bat`.

## 5. Backup

No ambiente local, configure `BACKUP_ENCRYPTION_KEY` (o `SETUP` a gera) e o
job diário grava pacotes cifrados no volume `backups_local`; cada um já inclui
banco, XMLs e certificados cifrados. Ainda é prudente preservar os volumes
Docker `db_data`, `certificados`, `xml_saida` e `backups_local` antes de uma
operação destrutiva. Não copie apenas o código-fonte.

Para servidor exposto ou dados fiscais reais, use a pilha e o S3 obrigatório de
[`docs/DEPLOY_PRODUCAO.md`](docs/DEPLOY_PRODUCAO.md).

## Atualizar

Para pegar uma versão nova **sem reinstalar nada** e sem perder dados, rode
`ATUALIZAR.bat` (ou `./ATUALIZAR.sh`). Detalhes em
[COMO_ATUALIZAR.md](COMO_ATUALIZAR.md).

## Problemas

Se algo falhar ao subir (ex.: `read-only file system`, porta ocupada, disco
cheio), veja [SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md).
