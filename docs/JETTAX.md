# Integração Jettax 360 / Morfeu

A Jettax é uma fonte complementar de captura e agora também funciona como
trilha automática de **fallback/conferência**. O NotasFlow continua sendo a
camada operacional que guarda, deduplica, audita e exporta os documentos;
ADN/SEFAZ diretos não são substituídos nem recebem os cursores da Jettax. Quando
a fonte oficial bloqueia o CNPJ, fica indisponível, falha antes de concluir ou
conclui uma varredura, a empresa marcada como ativa/registrada na Jettax ganha
uma execução paralela para verificar/importar o que a Morfeu entregar. A
primeira vertical implementa NFS-e e NF-e; CT-e permanece separado até que a
resposta do endpoint público seja documentada, em vez de assumir que ela é
idêntica à resposta de NF-e.

## Contrato pesquisado

A implementação foi baseada exclusivamente na coleção pública
[Morfeu API — Jettax](https://documenter.getpostman.com/view/259141/SW7c2Sg7).
Exemplos históricos do documento não são usados como credenciais, dados de
teste ou configuração.

## Configuração segura

Configure o token autorizado **somente** no ambiente seguro do servidor ou no
gerenciador de segredos do deploy:

```dotenv
JETTAX_API_BASE_URL=https://morfeu-api.jettax.com.br
JETTAX_API_TOKEN=... # segredo: não versionar, não enviar por chat
JETTAX_TIMEOUT_SEGUNDOS=30
JETTAX_MAX_PAGINAS_POR_EXECUCAO=50
```

O endpoint `GET /integracoes/jettax` informa apenas se o token está
configurado; ele nunca o devolve. O cliente HTTP usa o header
`Authorization` esperado pela Morfeu, timeout estrito, não segue redireções e
recusa links de paginação que saiam do host configurado — o token não pode ser
vazado para outro domínio.

### Diagnóstico: "A Jettax recusou a autenticação do conector"

O contrato público da Morfeu (coleção Postman) autentica por **API Key**: o
header é `Authorization: <token>` com o token **puro, sem o prefixo
`Bearer`**.

**Comportamento observado na API de produção (verificado em 2026-09):** os
dois endereços respondem `HTTP 401` com mensagens curtas e genéricas —
`"Token inválido."` quando o middleware não aceita a credencial (inclusive o
formato `Bearer` com valor que não seja um JWT válido) e `"Dados de acesso
inválidos."` quando a requisição atravessa o middleware e a aplicação não
reconhece a credencial. Ou seja, **não é possível distinguir pelo corpo da
resposta** "token errado" de "token de outro ambiente" ou "conta sem API
liberada", e é por isso que o conector investiga ativamente em vez de só
repassar o erro. Na prática, o formato documentado (token puro) é o que
chega mais fundo na validação.

O que o NotasFlow faz hoje, automaticamente:

1. **Tenta o formato documentado primeiro** (`Authorization: <token>`). Se a
   resposta for 401/403, repete a mesma requisição com
   `Authorization: Bearer <token>`. Repetir é seguro porque um 401 garante que
   nada foi executado do outro lado. O formato aceito é **memorizado** na
   credencial (coluna `esquema_autenticacao`), então a descoberta acontece uma
   vez, não a cada chamada.
2. **Ao salvar a credencial e ao testar a conexão**, sonda as combinações
   `endereço × formato` — `morfeu-api.jettax.com.br` e `morfeu.jettax.com.br`,
   com token puro e com `Bearer` — usando sempre o `GET /api/nfse/cities`
   (leitura). Se alguma funcionar, o endereço/formato correto é **gravado
   sozinho**; o operador não precisa mais adivinhar a URL.
   A sondagem só envia o token para hosts `*.jettax.com.br` em HTTPS.
3. **Mostra a resposta literal da Jettax** na mensagem de erro
   (ex.: `Resposta da Jettax: "Token inválido."`), junto do status e do host.
   Qualquer sequência longa sem espaços na mensagem remota é substituída por
   `[redigido]`, para o caso de o fornecedor ecoar o próprio token.

Se, mesmo após essa varredura, todas as tentativas voltarem 401/403, a
conclusão é objetiva e o sistema a exibe: **o problema está na credencial, não
no conector** — token inexistente, revogado, emitido para outro ambiente ou
conta sem acesso liberado à API Morfeu. Nesse ponto, a ação é com o suporte da
Jettax: peça um token de API ativo e a confirmação de que a API está habilitada
para a conta.

Para confirmar por fora do sistema:

```bash
curl -i "https://morfeu-api.jettax.com.br/api/nfse/cities" -H "Authorization: SEU_TOKEN"
curl -i "https://morfeu.jettax.com.br/api/nfse/cities"     -H "Authorization: SEU_TOKEN"
# e, se ambos recusarem, o mesmo par com: -H "Authorization: Bearer SEU_TOKEN"
```

### O painel mostra a chave com cara de hash (`$2y$10$…`) — ela é a credencial

Caso real confirmado (2026-09): na caixa **API Token Jettax** (Jettax 360 →
Geral > Configurações > Integrações), a chave aparece no formato
`$2y$10$` + 53 caracteres — visual de hash bcrypt. **Use esse valor como
está**: a Jettax emite/exibe a chave assim e outro sistema do escritório
autenticou com exatamente esse valor. O NotasFlow o transmite byte a byte,
sem nenhuma alteração.

Quando a Morfeu responde ao teste com este par de mensagens:

- token **puro** → `HTTP 401 "Dados de acesso inválidos."` (o formato
  documentado atravessa o middleware e a aplicação não reconhece a
  credencial **para a Morfeu**);
- `Bearer <token>` → `HTTP 401 "Token inválido."` (recusa do middleware);

o diagnóstico é: endereço e formato estão certos — **a credencial não está
reconhecida pela API Morfeu**. Explicação mais comum quando a mesma chave
funciona em outro programa: ela está autorizada em **outra** API da Jettax
(Jettax 360, Box J, sincronização…), e a Morfeu é um serviço separado, com
habilitação própria. Também vale considerar token rotacionado após a cópia
ou restrição por IP.

Ação: peça ao suporte da Jettax para **habilitar a API Morfeu para o seu
token** ou **emitir o token específico da Morfeu**. O NotasFlow reconhece
esse padrão de resposta no teste de conexão e já exibe essa orientação na
mensagem de erro (o valor colado nunca é ecoado em resposta, auditoria ou
log). O conector nunca barra a colagem por formato: quem decide se a
credencial serve à Morfeu é o teste autenticado.

Outros pontos de atenção:

- **Use o token de API, não a senha do painel** da Jettax 360.
- Cole o token sem `Bearer ` — prefixo, aspas, espaços e quebras de linha são
  removidos automaticamente ao salvar, e colagens que ficam vazias são
  recusadas.
- O log do servidor (`docker compose logs api`) registra método, rota, formato
  tentado, status e a mensagem do fornecedor de cada chamada recusada.
- Se `GET /api/nfse/cities` aceitar o token mas as importações falharem, o
  problema é posterior à autenticação (permissão do cliente, CNPJ não
  registrado etc.).

Para receber notificações, gere um valor longo e aleatório e o guarde também
como segredo de infraestrutura:

```dotenv
JETTAX_WEBHOOK_SECRET=valor-longo-aleatorio
```

Cadastre na Jettax a URL completa:

```text
https://SEU-DOMINIO/api/integracoes/jettax/webhooks/VALOR-DO-SEGREDO

> No Compose de desenvolvimento, sem o proxy `/api`, a rota é
> `http://localhost:8000/integracoes/jettax/webhooks/...`. Não cadastre uma
> URL HTTP/local na Jettax de produção.
```

A documentação pública descreve o payload (`type`, `ticket`, `status`,
`message`) e retries quando a URL não responde 2xx, mas não descreve uma
assinatura criptográfica. Por isso o NotasFlow não aceita webhook se esse
segmento secreto não estiver configurado. O recebimento é idempotente para as
reentregas documentadas.

## Sequência de operação

1. Cadastre/atualize a empresa local com **CNPJ**, `codigo_ibge` de sete
dígitos e `inscricao_municipal` (CCM).
2. Configure preferências locais em
   `PUT /integracoes/jettax/empresas/{empresa_id}` e defina `ativa: true` para
   liberar capturas. Isso não chama a Jettax.
3. Um administrador cria o cliente remoto explicitamente em
   `POST /integracoes/jettax/empresas/{empresa_id}/registrar`; atualizações
   explícitas usam `PUT` na mesma rota.
4. `enviar_certificado` é `false` por padrão. Se o administrador o ativa, o A1
   já guardado no volume protegido e sua senha cifrada são usados somente em
   memória para a requisição de registro; senha, PFX e base64 nunca aparecem
   na API, na auditoria ou no banco de integração.
5. Dispare a importação necessária pela fonte oficial. A partir daí a Jettax é
   acionada automaticamente como conferência/fallback nos eventos relevantes;
   importações manuais continuam disponíveis para teste ou operação assistida.
6. Acompanhe `GET /integracoes/jettax/empresas/{empresa_id}/execucoes` ou o
   cartão “Jettax 360 como fallback” no cadastro da empresa.

Excluir uma empresa **localmente não chama** `DELETE /api/clients/{cnpj}`. A
API pública avisa que esse DELETE também remove as notas remotas; essa decisão
nunca é implícita no NotasFlow.

## Contratos implementados

Somente endpoints presentes na coleção pública Morfeu foram implementados:

| Recurso | Endpoint Morfeu | Uso no NotasFlow |
| --- | --- | --- |
| Cliente | `POST /api/clients` | Registro explícito de empresa |
| Cliente | `PUT /api/clients/{cnpj}` | Atualização explícita |
| Teste de saúde | `GET /api/nfse/cities` | `POST /integracoes/jettax/testar` (somente leitura) |
| NFS-e | `GET /api/nfse/invoices/{cnpj}` | Importação incremental e filtros documentados |
| NF-e saída | `GET /api/nfes/clients/{cnpj}/sales/` | XML gzip+base64, importação incremental |
| NF-e entrada | `GET /api/nfes/clients/{cnpj}/purchases/` | XML gzip+base64, importação incremental |
| CT-e saída | `GET /api/ctes/clients/{cnpj}/sales/` | Endpoint público identificado; resposta ainda sem exemplo/descrição pública suficiente para ingestão segura |

A coleção pública só identifica CT-e `sales` e não documenta sua estrutura de
resposta. O produto não presume um endpoint `purchases` nem reutiliza por
analogia o decoder de NF-e. Também não há contrato público de download XML/PDF
da NFS-e: ela é salva como **metadados normalizados**, com
`leiaute=metadados`, sem criar um arquivo que pareça ser XML. Um XML só é
exportado quando a fonte entregou XML de fato.

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
