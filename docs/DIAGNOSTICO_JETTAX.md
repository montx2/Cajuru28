# Diagnóstico independente Jettax

Não exige integrar ou publicar código na main. Baixe somente o arquivo
`diagnostico_jettax.py` e execute no seu computador com Python 3.11 ou superior.
Não há dependências para instalar.

No Windows, abra o Terminal na pasta onde salvou o arquivo:

```powershell
py --version
py diagnostico_jettax.py
```

No Linux/macOS:

```sh
python3 --version
python3 diagnostico_jettax.py
```

Informe token e CNPJ nas entradas ocultas (não aparecem ao digitar).
Use uma competência MM-AAAA que tenha pelo menos duas notas na Jettax.
Confirme com SIM. Envie somente `relatorio_jettax_seguro.json`.
Nunca envie token, XMLs, links ou arquivo .env. Não use o "Try it out"
do Swagger com token em imagens compartilhadas.

O script faz no máximo 11 GETs, sem retry, com intervalo mínimo de 2 segundos.
Verifica acesso sem token e com token puro, estrutura de clientes filtrados,
NFS-e por competência, sondagens page/limit, filtros emitidas/recebidas/
canceladas e download de até três arquivos. Não baixa PDF, não segue
redirecionamentos, não envia Authorization ao storage e interrompe diante
de 429 ou token recusado. TLS é validado. O token fica apenas na memória.
O relatório mostra estrutura e conclusões, não valores fiscais ou links.

Limitações são explicitadas no relatório: não garante completude, não testa
NFe/CTe nem altera captura oficial, não provoca bloqueios para testar falhas,
não percorre todo o acervo e não testa banco/worker/frontend locais.
Idempotência, isolamento e tratamento de falhas serão testados com mocks.
Se não houver duas notas na competência, paginação pode ficar inconclusiva.

Para desfazer, apague o script e o relatório. Nada é instalado ou modificado
no NotasFlow ou no cadastro Jettax por esse script.
