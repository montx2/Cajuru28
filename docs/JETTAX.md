# Integração Jettax / Morfeu

A Jettax é uma fonte complementar de captura e uma trilha de
**fallback/conferência**. O NotasFlow continua sendo a camada que guarda,
deduplica, audita e exporta documentos; ADN/SEFAZ diretos não são substituídos
nem recebem os cursores da Jettax. Quando a fonte oficial bloqueia o CNPJ, fica
indisponível, falha antes de concluir ou conclui uma varredura, uma empresa
ativa e vinculada à Jettax pode receber uma execução paralela. Esta integração
implementa NFS-e e NF-e; CT-e permanece fora até que a resposta pública tenha
contrato suficiente para importação segura.

## Contrato pesquisado

A implementação se baseia na coleção pública
[Morfeu API — Jettax](https://documenter.getpostman.com/view/259141/SW7c2Sg7).
Essa é uma API Morfeu legada: uma chave usada em outro produto da Jettax, no
Domínio/Onvio ou no painel administrativo não é automaticamente uma credencial
válida para ela. Exemplos históricos daquela coleção podem conter dados
sensíveis publicados por terceiros: **não os use como token, certificado,
CNPJ de teste ou configuração**.

O contrato publicado cobre:

- `GET /api/clients/{cnpj}` para consultar o cliente remoto;
- `POST /api/clients` e `PUT /api/clients/{cnpj}` para criar/atualizar;
- `GET /api/nfse/invoices/{cnpj}` com `lastId`, `numero`, `notaSituacao`,
  `tipoNota` e `period`;
- `GET /api/nfes/clients/{cnpj}/sales|purchases/` com `ultimoId`, `chave`,
  `dataInicial`, `dataFinal`, `cnpjDestinario` e `cnpjEmitente`.

A grafia `cnpjDestinario` (sem “ta”) é a grafia do fornecedor e é enviada
assim pelo adaptador. NF-e chega com XML gzip codificado em base64; NFS-e tem
apenas metadados no contrato público, portanto o NotasFlow não inventa uma URL
de XML/PDF para ela. Na exportação ZIP, essas NFS-e seguem no `relacao.csv` e
ganham um JSON normalizado em `metadados/`, claramente marcado como **sem XML
original**.

## Configuração segura e diagnóstico

A URL padrão é `https://morfeu-api.jettax.com.br`. O contrato usa API Key no
header exatamente como abaixo, **sem** `Bearer`:

```text
Authorization: TOKEN_MORFEU
```

Configure o token emitido para a API Morfeu no gerenciador de segredos do
deploy ou, para cada escritório, em **Configurações → Jettax / Morfeu**. O
painel cifra o valor no cofre do servidor e nunca o retorna ao navegador.
Também remove um prefixo `Bearer`, aspas, espaços acidentais e o rótulo de uma
linha copiada do Postman/cURL (`Authorization: Bearer …`) antes de guardar a
chave. A base aceita somente os dois hosts Morfeu publicados
(`morfeu-api.jettax.com.br` e `morfeu.jettax.com.br`): uma URL de outro produto
Jettax não é tratada como “token inválido”.

```dotenv
JETTAX_API_BASE_URL=https://morfeu-api.jettax.com.br
JETTAX_API_TOKEN=... # segredo: não versionar nem enviar por chat
JETTAX_TIMEOUT_SEGUNDOS=30
JETTAX_MAX_PAGINAS_POR_EXECUCAO=50
```

O teste de conexão usa `GET /api/nfse/cities`, que é documentado e somente de
leitura. Ele começa pelo header publicado e, por compatibilidade com instalações
legadas, pode testar uma variação de header somente nos dois hosts HTTPS
oficiais (`morfeu-api.jettax.com.br` e `morfeu.jettax.com.br`). Isso não torna
uma chave de outro produto uma chave Morfeu. A combinação que responder com
sucesso é persistida para evitar novas tentativas redundantes.

Quando o endpoint de cidades recusa a autenticação em todos os formatos, o
diagnóstico ainda sonda `GET /api/clients` — o contrato-base documentado — no
mesmo par de hosts. Um 2xx ali prova que o **token é válido para a Morfeu**, e
a saúde do conector passa a apontar a limitação real: o módulo de NFS-e não
está habilitado na conta, o que bloqueia apenas as importações de NFS-e até a
Jettax liberar. Sem esse desempate, uma conta assim era reportada como "token
inválido", que é a pista errada.

Um `401` ou `403` confirma apenas que aquela autenticação foi recusada. A
coleção pública não permite deduzir pelo texto da resposta se o valor foi
revogado, pertence a outro produto, se a conta não contratou a API ou se há
outra regra de autorização. Nessa situação, copie o token novamente no painel
da Jettax (somente o valor, sem o rótulo da linha) e, persistindo a recusa,
solicite ao suporte da Jettax a confirmação de um **token Morfeu ativo** e das
permissões da conta. Nunca copie uma senha, hash ou valor extraído de log/banco
como se fosse token de API.

Se a `VAULT_MASTER_KEY` do servidor for trocada sem manter
`VAULT_PREVIOUS_MASTER_KEYS`, a credencial Jettax guardada (e as senhas dos
A1) deixam de abrir. Rotas, testes e execuções passam a responder com a
orientação explícita "salve o token novamente" em vez de uma falha interna
genérica — o mesmo vale para reenviar os certificados `.pfx`.

O cliente HTTP não segue redirecionamentos e não envia a credencial a domínios
externos. A paginação pode atravessar somente entre os dois hosts oficiais,
pois a coleção publica um `next` nesse formato.

## Sequência de operação

1. Cadastre/atualize a empresa local com **CNPJ**, `codigo_ibge` de sete
dígitos e `inscricao_municipal` (CCM). Os quatro campos CNPJ, razão social,
IBGE e CCM são exigidos pelo `POST /api/clients`.
2. Salve as preferências da integração e marque **Ativar integração**. Sem essa
marcação, a empresa pode ser registrada, mas consultas manuais e fallback ficam
bloqueados intencionalmente.
3. Use **Registrar na Jettax** ou **Atualizar cadastro remoto**. Ambas as rotas
fazem reconciliação por CNPJ: primeiro consultam `GET /api/clients/{cnpj}`;
se ele existir, fazem `PUT`, e se não existir, fazem `POST`. Isso corrige o
caso comum de banco local restaurado/novo com cliente já cadastrado remotamente,
sem tentar criar o CNPJ duas vezes. Se outro operador criar o cliente durante
a operação, o conector confirma a existência e atualiza de forma idempotente.
4. No painel da empresa, **Enviar certificado A1 ao registrar** começa marcado
para não deixar a captura de NFS-e sem credencial por engano. Desmarque-o só
quando a credencial municipal já estiver configurada no painel da Jettax. A1 e
senha cifrada são usados apenas em memória para o registro; PFX, senha e
base64 nunca aparecem em resposta, auditoria ou modelo de integração.
5. Após o registro, use os botões **Importar NFS-e**, **Importar NF-e
recebidas** ou **Importar NF-e emitidas** na aba Integrações da empresa, ou
aguarde o fallback automático. Uma resposta sem documentos é uma consulta bem-
sucedida sem itens novos, não um sinal de que o worker parou. A execução mostra
esse aviso para orientar a conferência de cadastro/captura.

A captura também depende da habilitação operacional na Jettax. As orientações
atuais da fornecedora indicam certificado A1 ou credencial municipal e módulo
de Serviços para NFS-e, e certificado A1/módulo Federal para NF-e; a captura de
NF-e emitida possui configuração adicional. Consulte as páginas oficiais da
Jettax sobre [NFS-e](https://jettax360-help.freshdesk.com/support/solutions/articles/151000057592-como-configurar-captura-de-nfse)
e [NF-e de saída](https://jettax360-help.freshdesk.com/support/solutions/articles/151000057221-como-configurar-captura-de-nfe-de-sa%C3%ADda).
Assim, um teste de token aprovado não garante sozinho que já existam documentos
disponíveis para baixar.

Excluir uma empresa **localmente não chama** `DELETE /api/clients/{cnpj}`. A
API pública avisa que esse DELETE também remove as notas remotas; essa decisão
nunca é implícita no NotasFlow.

## Webhook opcional

Para receber notificações, gere um valor longo e aleatório e o guarde como
segredo de infraestrutura:

```dotenv
JETTAX_WEBHOOK_SECRET=valor-longo-aleatorio
```

Cadastre na Jettax a URL pública completa:

```text
https://SEU-DOMINIO/api/integracoes/jettax/webhooks/VALOR-DO-SEGREDO
```

A coleção descreve o payload (`type`, `ticket`, `status`, `message`) e retries,
mas não uma assinatura criptográfica. Por isso o NotasFlow exige o segmento
secreto na URL, não recebe eventos sem ele e trata reentregas de modo
idempotente.

## Contratos implementados

| Recurso | Endpoint Morfeu | Uso no NotasFlow |
| --- | --- | --- |
| Consulta de cliente | `GET /api/clients/{cnpj}` | Reconciliação segura por CNPJ antes de registrar |
| Cliente | `POST /api/clients` | Criação quando o cliente não existe remotamente |
| Cliente | `PUT /api/clients/{cnpj}` | Atualização de cliente já existente |
| Teste de saúde | `GET /api/nfse/cities` | `POST /integracoes/jettax/testar` (somente leitura) |
| NFS-e | `GET /api/nfse/invoices/{cnpj}` | Importação incremental e filtros documentados |
| NF-e saída | `GET /api/nfes/clients/{cnpj}/sales/` | XML gzip+base64, importação incremental |
| NF-e entrada | `GET /api/nfes/clients/{cnpj}/purchases/` | XML gzip+base64, importação incremental |
| CT-e saída | `GET /api/ctes/clients/{cnpj}/sales/` | Identificado publicamente, sem resposta documentada para ingestão segura |

## Acionamento automático

A integração deixa de depender apenas do botão manual quando a empresa está
`ativa` e com `status` `registrada`/`atualizada`:

- `fallback_656` — cStat 656/HTTP 429/consumo indevido na fonte oficial. A
  execução oficial fica aguardando a janela correta e uma execução Jettax roda
  em paralelo.
- `fallback_cooldown` — o operador ou o agendador encontra a empresa ainda
  bloqueada pela fonte oficial. A fila oficial não força a SEFAZ/ADN, mas pede
  uma conferência Jettax se não houver outra recente.
- `fallback_erro` — queda de ambiente/rede ou erro antes da conclusão da
  importação oficial; a retentativa direta continua agendada.
- `fallback_check` — varredura oficial concluída; a Jettax confere como segunda
  fonte sem alterar NSU/cooldown oficial.

Para evitar duplicidade operacional, o acionamento automático reaproveita a
execução Jettax em andamento e não repete o mesmo motivo/fluxo dentro de uma
janela curta. NF-e automática usa o fluxo recebido (`purchases`) quando
`baixar_nfes` está habilitado ou quando nenhuma direção foi marcada; se somente
`baixar_nfes_enviadas` estiver habilitado, usa o fluxo emitido (`sales`).

## Deduplicação e cursores

- A paginação segue `meta.pagination.links.next`. A coleção tem exemplo real
  em que a resposta veio de `morfeu-api.jettax.com.br` com `next` apontando
  para `morfeu.jettax.com.br`, então o conector aceita a troca **entre os dois
  hosts oficiais** e continua recusando qualquer outro host.

- A identidade de cada documento é única por empresa. NF-e usa a chave fiscal
  do XML; NFS-e sem chave retornada recebe a identidade estável
  `jettax-nfse-{id}` baseada no id da própria Jettax. Sem uma chave fiscal
  comum, o sistema deliberadamente não funde NFS-e de fontes diferentes só por
  número/valor — evitar falso positivo é mais importante que deduplicar demais.
- `documentos_fiscais_fontes` guarda a origem e o identificador do fornecedor.
  Se uma mesma nota vier por Jettax e pela distribuição oficial, há uma nota
  só e as duas proveniências permanecem visíveis no detalhe.
- `lastId` (NFS-e) e `ultimoId` (NF-e) vivem em cursores Jettax próprios.
  Eles só avançam na mesma transação que persistiu todos os itens da resposta.
  Um item inválido segura o cursor para a próxima tentativa, porque repetir
  duplicatas é seguro; pular documento não é.
- Consultas com filtro (número, status/tipo/período ou chave/data/CNPJ) são
  pontuais e **não avançam** o cursor incremental.

## Rotas do NotasFlow

Todas as rotas abaixo exigem sessão do NotasFlow. Configuração remota e teste
de conexão exigem perfil `admin`; importações exigem perfil de escrita.

```text
GET  /integracoes/jettax
POST /integracoes/jettax/testar
GET  /integracoes/jettax/empresas/{id}
PUT  /integracoes/jettax/empresas/{id}
POST /integracoes/jettax/empresas/{id}/registrar
PUT  /integracoes/jettax/empresas/{id}/registrar
POST /integracoes/jettax/empresas/{id}/importar/nfse
POST /integracoes/jettax/empresas/{id}/importar/nfe
GET  /integracoes/jettax/empresas/{id}/execucoes
GET  /integracoes/jettax/webhooks/eventos
```
