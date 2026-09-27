# Importação de empresas + certificados por lote

Tela: **Empresas → Importar lote**. O fluxo inteiro cabe em duas escolhas:
a **pasta dos certificados** no computador e a **planilha de senhas** que o
escritório já mantém.

## Como importar

1. **Escolher pasta** — seleciona a pasta onde estão os certificados
   (`.pfx`/`.p12`). Só esses dois tipos são lidos; todo o resto da pasta
   (PDFs, planilhas, atalhos) é contado como *ignorado* e **nunca sai da
   máquina**. Limite de 200 certificados por lote — acima disso o envio fica
   bloqueado com o motivo na tela.
   - Chrome, Edge e Safari abrem o seletor de pastas. No Firefox (e em
     qualquer dúvida) use **"Ou arquivos individuais"** e selecione os
     arquivos — o caminho garantido.
2. **Planilha de senhas** (opcional, `.csv`/`.txt`) — anexe a planilha que já
   existe no escritório. Formatos aceitos, com ou sem acento no cabeçalho,
   separados por `;`, `,` ou tabulação:
   - Com cabeçalho: `cnpj_cpf;senha` (aceita também `cnpj`, `cpf`,
     `documento`, `doc` na primeira coluna; `razao` e `uf` são opcionais).
   - Sem cabeçalho: `documento;senha` ou `documento;senha;uf`.
3. **UF padrão** — obrigatória, usada quando o certificado/planilha não
   informa a UF.
4. **Importar lote** — um clique.

### Senhas: individual > global

- A **senha individual** da planilha casa com o certificado pelo **CNPJ no
  nome do arquivo** (ex.: `12345678000195.pfx`). Sem casamento, a senha
  global assume — não há tentativa em loop.
- A **senha global** só é exigida quando não há planilha. Com planilha
  anexada o campo fica opcional.
- Planilha em Excel (`.xlsx`)? Salve como CSV antes — o sistema lê texto.

### Sem surpresas

- Prévia antes do envio: quantos certificados, quantos ignorados, o que
  falta para habilitar o botão (o título do botão diz o motivo).
- Resultado por item: criadas, certificados anexados, falhas com motivo —
  uma nota que falha nunca para as demais.
- Certificado sai da máquina apenas no momento do envio, cifrado no
  descanso (Fernet) e com senha guardada em cofre — nunca em log.
