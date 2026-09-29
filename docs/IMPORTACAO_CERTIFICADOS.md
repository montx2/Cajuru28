# Importação de empresas + certificados por lote

Tela: **Empresas → Importar em massa**. O fluxo começa somente pela pasta de
certificados no computador. Ele não pede uma senha única para o lote nem uma UF
padrão: esses dois campos levavam a escolhas que não valem para todas as
empresas.

## Como importar

1. **Escolher pasta** — selecione a pasta onde estão os certificados
   (`.pfx`/`.p12`). Só esses dois tipos são lidos; todo o resto da pasta
   (PDFs, planilhas e atalhos) é contado como *ignorado* e **nunca sai da
   máquina**. O limite é de 600 certificados por lote.
   - Chrome, Edge e Safari abrem o seletor de pastas. No Firefox, ou se
     preferir, use **"Ou arquivos individuais"**.
   - Se houver certificado antigo e atualizado do mesmo CNPJ, a versão com
     maior validade real (X.509) é a escolhida; a outra aparece no resultado
     como *Versão antiga*.
2. **Planilha de apoio (opcional)** — anexe-a apenas quando o escritório já
   possui uma relação de certificados. Ela pode conter `cnpj;senha` para abrir
   arquivos cuja senha não foi identificada automaticamente. A coluna `uf` é
   aceita como apoio pontual, sem obrigar uma UF padrão para todo o lote.
   - São aceitos `.xlsx`, `.xlsm`, `.xls`, `.csv` e `.txt`, com `;`, `,` ou
     tabulação.
   - Exemplos: `cnpj_cpf;senha` ou `cnpj_cpf;senha;uf`. Razão social é
     opcional.
3. **Importar lote** — um clique. O CNPJ e a razão social vêm do certificado;
   a UF é consultada automaticamente pelo CNPJ.

## Senhas e UF sem suposições

- O sistema tenta padrões seguros conhecidos e as senhas declaradas na
  planilha, na ordem em que as planilhas foram anexadas. A primeira que abre o
  certificado é a guardada de forma cifrada no cofre.
- Se um certificado não abrir, inclua sua senha na planilha de apoio e importe
  novamente o arquivo. Não há uma "senha global" na tela porque ela pode estar
  errada para as demais empresas do lote.
- A UF é necessária internamente para a consulta NF-e/CT-e, mas não é inferida
  como `SP`. Se a consulta pública não encontrá-la, o item informa o problema;
  nesse caso inclua `CNPJ` e `UF` na planilha de apoio e importe apenas aquele
  certificado outra vez.

## Resultado e segurança

- O resultado é exibido por arquivo: empresas criadas, certificados vinculados,
  versões antigas e falhas com o motivo. Uma falha não interrompe os outros
  itens do lote.
- Certificados vencidos entram com aviso explícito e não são usados na captura.
- O certificado sai da máquina somente no envio, é cifrado no armazenamento e
  sua senha nunca vai para logs.
