# Importação de empresas + certificados por lote

Tela: **Empresas → Importar em massa**. O fluxo começa somente pela pasta de
certificados no computador. Ele não pede uma senha única para o lote nem uma UF
padrão: esses dois campos levavam a escolhas que não valem para todas as
empresas.

> O PFX é enviado ao backend privado para que os serviços fiscais possam
> consultá-lo depois; arquivo e senha são armazenados cifrados.

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
2. **Planilha de apoio (opcional)** — anexe a relação de certificados que o
   escritório já tem. Cada linha entrega a senha do certificado daquele CNPJ;
   a coluna `uf` é aceita como apoio pontual, sem obrigar uma UF padrão para
   todo o lote.
   - São aceitos `.xlsx`, `.xlsm`, `.xls`, `.csv` e `.txt`, com `;`, `,` ou
     tabulação.
   - **As colunas são descobertas pelo conteúdo**, com ou sem linha de título.
     Estes layouts funcionam:
     - `cnpj;senha`
     - `razao_social;cnpj_cpf;uf;senha`
     - **inventário de A1** — o que a maioria dos controles de certificado
       exporta, com o nome do arquivo na frente:

       ```
       arquivo;cnpj;emissor;senha;validade
       21260898000107.pfx;21.260.898/0001-07;ICP-Brasil;7cs19Pfi;09/03/2027
       22912077000170.pfx;22.912.077/0001-70;ICP-Brasil;F R F25;29/10/2026
       ```

       A linha de título é opcional; `ICP-Brasil` (a autoridade certificadora)
       é reconhecida e ignorada.
   - **Como o certificado acha a linha dele:** pelo CNPJ que está no nome do
     `.pfx` (`21260898000107.pfx`) e, se o nome não tiver CNPJ, pelo nome de
     arquivo que a própria planilha cita (`certificado-novo.pfx`).
   - **CNPJ digitado errado na planilha não perde a linha:** se a coluna CNPJ
     veio com um dígito a menos (`34.304.74/0001-33`) mas o arquivo é
     `34304074000133.pfx`, a senha ainda é usada.
   - **Senha com `;` dentro** (`ou;tra`) não quebra a linha: o pedaço é
     reagrupado.
   - Linhas em branco entre registros são ignoradas.
   - **Lotes grandes:** inclua a coluna `uf` na planilha. Sem ela, cada
     certificado depende de uma consulta pública de CNPJ para descobrir o
     estado — com centenas de empresas o lote fica mais lento e sujeito ao
     limite dessas fontes.
3. **Importar lote** — um clique. O CNPJ vem do certificado; a razão social
   obedece a esta ordem e para no primeiro nome de empresa aproveitável:

   1. a coluna de nome da **planilha de apoio**, se houver;
   2. o **cadastro do escritório no Acessórias**, consultado pelo CNPJ — a
      mesma fonte sincronizada em Configurações;
   3. as **fontes públicas da Receita** (BrasilAPI → MinhaReceita → CNPJ.ws);
   4. o **subject do certificado** (o `CN`/`O` do X.509);
   5. `Empresa <CNPJ>` — placeholder visível e corrigível, nunca um nome falso.

   Consultar custa tempo, então o 2º e o 3º só são chamados quando falta nome
   **ou** falta UF: um certificado que já diz "ALFA SERVICOS LTDA" no subject
   e tem UF na planilha não gera nenhuma requisição externa.

   O que nunca vale como nome: a marca da cadeia. O subject de um A1 traz
   `O = ICP-Brasil` (e às vezes `OU = AC Soluti`, `AC Certisign`…) — é a
   autoridade certificadora, não o titular. Um lote de 203 certificados lidos
   sem essa régua criou 203 empresas chamadas "ICP-Brasil". Nome de cadeia,
   rótulo de coluna ("Razão social: …"), nome de arquivo e o próprio CNPJ são
   descartados antes de gravar — na planilha e no certificado.

   A UF é consultada pelo CNPJ quando não vem da planilha nem do cadastro. Como
   a mesma consulta entrega as duas coisas, um lookup resolve nome e estado.

## Faltou nome? O lote avisa e conserta no mesmo lugar

Quando alguma empresa entra sem razão social (nem o certificado, nem a
planilha, nem o Acessórias, nem a Receita disseram o nome), o resultado do lote
mostra **quantas** foram e oferece **"Completar nomes agora"** — uma rodada que
reconsulta o CNPJ em todas as fontes, sem reenviar arquivo nenhum. É o botão
que resolve o "203 empresas chamadas ICP-Brasil".

O mesmo reparo, para o escritório inteiro, está em **Configurações →
Integrações → Acessórias → Completar nomes pendentes** (`POST
/empresas/completar-cadastros`), e vale também para cadastros antigos criados
antes dessa régua. Ele nunca sobrescreve um nome verdadeiro: só substitui o
ruído e o placeholder. Reimportar o `.pfx` de uma empresa específica também a
conserta, porque um nome já digitado à mão não é perdido no processo.

## O resultado confirma a planilha

O resumo do lote mostra quantas linhas a planilha rendeu e quantas traziam
senha. Se você anexou a planilha e o resultado diz **0 linhas lidas**, o
arquivo não foi entendido — confira se ele tem o CNPJ (ou o nome do `.pfx`) e a
senha de cada certificado e importe de novo. Sem esse aviso, uma planilha lida
no formato errado só apareceria como certificado que não abriu.

## Senhas e UF sem suposições

- **Envio individual (tela de certificados):** a senha digitada é palavra
  final. Se ela não abrir o .pfx, o envio é recusado na hora com mensagem
  clara — sem cair para padrão nenhum. O campo vazio é que dispara os padrões.
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
