# Passo a passo — NotasFlow com Docker

## 1. Instalar e iniciar

- **Windows:** execute `INSTALAR_TUDO.bat`.
- **Linux/macOS:** execute `./INSTALAR_TUDO.sh`.

A instalação prepara o ambiente e inicia todos os serviços via Docker Compose.

## 2. Entrar no painel

Abra http://localhost:3000 e use as credenciais gravadas em `CREDENCIAIS.txt`.
A API e sua documentação ficam em http://localhost:8000/docs.

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

Faça backup regular dos volumes Docker `db_data`, `certificados` e `xml_saida`.
Não copie apenas o código-fonte: os dados persistentes estão nesses volumes.

## Problemas

Se algo falhar ao subir (ex.: `read-only file system`, porta ocupada, disco
cheio), veja [SOLUCAO_DE_PROBLEMAS.md](SOLUCAO_DE_PROBLEMAS.md).
