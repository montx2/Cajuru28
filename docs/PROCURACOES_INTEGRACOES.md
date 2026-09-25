# Procurações RFB — integrações externas

Três dependências externas, com graus muito diferentes de maturidade. Este
documento diz exatamente o que é oficial, o que é observado e o que falta.

---

## 1. Integra Contador (SERPRO) — canal oficial de consulta

**Status:** API oficial, contratual, documentada. É a fonte da verdade sobre a
situação das autorizações.

### Contratação

Loja SERPRO, com e-CNPJ ICP-Brasil. O contratante é o escritório.

### Autenticação

OAuth2 `client_credentials` **com mTLS** (TLS 1.2), usando o certificado do
contratante:

```http
POST https://gateway.apiserpro.serpro.gov.br/token
Authorization: Basic base64(consumerKey:consumerSecret)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
```

Resposta: `{"access_token": "...", "token_type": "Bearer", "expires_in": ...}`.

### Consulta de procuração

```http
POST https://gateway.apiserpro.serpro.gov.br/integra-contador/v1/Consultar
Authorization: Bearer <access_token>
jwt_token: <token do Autentica Procurador, quando aplicável>
Content-Type: application/json

{
  "contratante":     {"numero": "<CNPJ do escritório>", "tipo": 2},
  "autorPedidoDados":{"numero": "<CNPJ do escritório>", "tipo": 2},
  "contribuinte":    {"numero": "<CNPJ do cliente>",    "tipo": 2},
  "pedidoDados": {
    "idSistema": "PROCURACOES",
    "idServico": "OBTERPROCURACAO41",
    "versaoSistema": "1",
    "dados": "{\"outorgante\":\"…\",\"tipoOutorgante\":2,\"outorgado\":\"…\",\"tipoOutorgado\":2}"
  }
}
```

`tipo`: `1` = CPF, `2` = CNPJ. O campo `dados` é **uma string JSON**, não um
objeto — detalhe que costuma custar algumas horas de depuração.

Retorno: quantidade de sistemas autorizados, nome de cada sistema e **data de
expiração**. É exatamente o que o módulo precisa para responder "esta empresa
tem autorização vigente?".

### Autentica Procurador

Para serviços que exigem procuração eletrônica, o fluxo
`AUTENTICAPROCURADOR` / `ENVIOXMLASSINADO81` recebe um termo XML assinado em
**XMLDSig (W3C)**, em base64, e devolve um token válido até a meia-noite do dia
seguinte, usado no cabeçalho `autenticar_procurador_token`.

### O que **não** existe

Não há, no Integra Contador, serviço de **criação, assinatura ou validação** de
autorização de acesso. Só consulta. É por isso que a execução do módulo é
assistida — não por escolha de arquitetura, mas por ausência de canal.

### Ambiente de demonstração

Existe `integra-contador-trial/v1/Consultar`, com Bearer fixo e dados fixos.
Serve para conferir o formato do payload; **não** serve para testar a situação
real de um cliente.

### Como o módulo usa

`app/procuracoes/integracoes/integra_contador.py`:

- allowlist do host oficial no construtor — endereço diferente é recusado;
- credenciais no cofre Fernet, por escritório;
- token em cache até expirar;
- consulta em lote pelos CNPJs ativos da carteira;
- resposta normalizada em `RegistroProcuracao`;
- precedência máxima na reconciliação: o que a API oficial diz **não** é
  sobrescrito por planilha nem por Jettax.

---

## 2. Assinador Digital SERPRO Desktop — componente oficial local

**Status:** componente oficial, com manual público. O módulo o **verifica**;
nunca o substitui.

| Item | Valor |
|---|---|
| Servidor local | `https://127.0.0.1:65156` |
| Nome esperado pelo navegador | `assinador-desktop.serpro.gov.br` → `127.0.0.1` no `hosts` |
| Versões | linha 4.x (manual de nov/2025 documenta a 4.3.3) |
| Formatos | CAdES `.p7s` (AD-RB, política 2.3), XAdES, PAdES |
| Teste oficial | <https://www.frameworkdemoiselle.gov.br/v3/signer/demo/> |
| Manual | <https://artefatos-assinador.serpro.gov.br/downloads/Manual_Usuario_Assinador_Desktop.pdf> |

Chrome e Edge exigem a permissão **"Acesso à rede local"** para que a página do
portal alcance `127.0.0.1`.

### Por que não implementar a assinatura por conta própria

Tecnicamente seria possível assinar CAdES com biblioteca criptográfica. Não é o
que se faz aqui, por três razões:

1. o fluxo oficial do portal aciona o Assinador — uma assinatura produzida por
   fora não é o que a página espera;
2. exigiria manipular a chave privada do cliente, justamente o que este desenho
   evita;
3. seria substituir componente oficial homologado por implementação própria —
   prática explicitamente fora de escopo.

### Sobre a biblioteca `demoiselle/signer`

`github.com/demoiselle/signer` é biblioteca Java LGPL para assinatura digital
no padrão ICP-Brasil. Ela **não documenta a API HTTP local do Assinador
Desktop**. Portanto, o módulo não presume endpoints dessa API: verifica
disponibilidade (porta viva, respondendo HTTPS) e deixa o portal fazer o resto.

### Como o módulo usa

`app/procuracoes/servicos/assinador.py` avalia o diagnóstico enviado pela
estação. **Falha fechada**: diagnóstico ausente, incompleto ou com item
bloqueante pendente reprova, e nenhum job é entregue. Cada pendência vem com
a ação de correção — é o que transforma "não funciona" em tarefa.

---

## 3. Jettax 360 — sem API pública documentada

**Status (verificado em setembro de 2026): não existe API REST pública
documentada para a tela de procurações.** A busca cobriu o site do fornecedor,
a central de ajuda e os artefatos de API que ele publica. O que existe:

| Artefato | O que é | Serve para procurações? |
|---|---|---|
| Coleção Postman "Morfeu" (`morfeu-api.jettax.com.br`, 2020) | Único contrato público: DAS, captura de NFS-e/NF-e, header `Authorization` | **Não.** Nenhuma rota de procuração. |
| Integrações por `apiToken` (Acessórias, SIEG) | Terceiros **enviando** dados *para* a Jettax | **Não.** Sentido oposto ao necessário. |
| "API aberta" no material comercial | Linguagem de marketing, sem contrato publicado | **Não.** |

A tela em questão é `admin.jettax360.com.br/prevention/ecac/procurations`.
A [documentação oficial do menu][ajuda] descreve **o que ela mostra**, nunca
como obtê-la por programa:

- colunas **EMPRESA · CLIENTE · INÍCIO · VENCIMENTO · SITUAÇÃO**, onde EMPRESA é
  o nome tal como consta no e-CAC e CLIENTE indica se o outorgante também é
  cliente cadastrado na Jettax;
- quatro totalizadores — Ativas de Clientes, Expiradas de Clientes, Ativas não
  Clientes, Expiradas não Clientes — que correspondem ao parâmetro `tab` da URL;
- filtros por Empresa, Situação, "É Cliente na Jettax" e Vencimento (30/60/90);
- a relação cobre apenas os outorgantes ligados ao **certificado principal** e é
  **reprocessada mensalmente, no dia 25**.

Duas consequências práticas: a lista não é tempo real (reprocessada no dia 25),
e ela inclui outorgantes que **não são clientes do escritório** — daí a coluna
CLIENTE e a regra de pendência descrita adiante.

[ajuda]: https://jettax360-help.freshdesk.com/support/solutions/articles/151000009202-como-funciona-o-menu-procurações

### Consequência de projeto

Inventar endpoint seria criar dependência fictícia que quebra no primeiro
contato com a realidade. Em vez disso o módulo tem **dois caminhos**, e o que
está ligado por padrão é o que não depende de contrato nenhum.

#### Caminho A — importação da lista (disponível, é o que se usa hoje)

`POST /procuracoes/importar-lista`, tela **Procurações → Importar lista**:

```json
{"texto": "…colagem da tela…", "fonte": "jettax360", "situacao_padrao": ""}
```

O leitor vive em `app/procuracoes/integracoes/planilha.py` — **a mesma peça que
já lia CSV**, estendida em vez de duplicada. `FontePlanilha` (arquivo) e
`FonteColagem` (texto) entregam o mesmo tipo de registro ao
`servicos/sincronizacao.py`, então idempotência, precedência, auditoria e
histórico de job são exatamente os mesmos dos outros canais. O que o leitor
aguenta, porque é o que a tela real produz:

- **nome numa linha, documento na seguinte** (o recorte vertical do navegador);
- tudo na mesma linha, separado por `;`, `,`, tabulação ou espaços;
- CNPJ e CPF misturados, com ou sem máscara;
- linha de cabeçalho (`EMPRESA CLIENTE INÍCIO VENCIMENTO SITUAÇÃO`), rodapé de
  paginação (`1 2 3 … 12`), contadores e o `Sim`/`Não` da coluna CLIENTE;
- a **barra de filtros** que o recorte traz entre uma página e outra
  (`Empresa / Situação=Expirado / Todos / Gerar Relatório`) é ruído
  descartado — o valor do filtro não é atribuído à linha anterior;
- duas datas na linha = início + vencimento (invertidas, são corrigidas); uma
  só = vencimento;
- `situacao_padrao` declara de qual aba do painel veio a colagem —
  "" (detectar), `expirada` (filtro Expirado), `ativa` (filtro Na validade)
  ou `sem_procuracao` (aba **Sem procuração**) — e só se aplica às linhas
  em que a situação não aparece no texto: a aba "Sem procuração" é
  afirmação do painel de que o outorgante não autorizou, e vira
  `sem_autorizacao`, nunca "situação indeterminada";
- **vencimento no passado vence o rótulo**: "ativa" com data vencida entra como
  `expirada`.

Rodar duas vezes não duplica: a chave é o documento normalizado, e páginas
sobrepostas convergem para o mesmo registro. O mesmo vale para o arquivo
exportado, em `POST /procuracoes/importar-planilha` (campos `fonte_declarada` e
`situacao_padrao` no multipart).

Cada execução grava um `procuracao_integracao_job` (`origem="colagem"`) e, para
cada linha não aproveitada, um `procuracao_integracao_erro` com documento, nome
lido, código e motivo:

| Código | Quando | O que fazer |
|---|---|---|
| `EMPRESA_NAO_CADASTRADA` | Documento não está na carteira | Cadastrar em Empresas (com UF) e reimportar |
| `DOCUMENTO_INVALIDO` | Dígito verificador não fecha num valor sem máscara | Conferir o valor na origem |
| `SITUACAO_INDETERMINADA` | A linha não trazia situação nem data | Reimportar declarando a aba de origem |
| `FONTE_MENOR_PRECEDENCIA` | Já havia dado de fonte superior | Nada; é o comportamento correto |

**Documento sem empresa correspondente não cria empresa.** A decisão é
deliberada: a lista do Jettax mistura clientes e não clientes, e `Empresa` é
entidade fiscal que exige UF e cadastro completo para entrar em apuração,
obrigações e emissão. Criar um registro pela metade contaminaria relatórios e
rotinas a jusante. O documento vira pendência **com o nome lido**, que é o que
permite reconhecer o cliente e decidir.

#### Caminho B — API remota (removido do produto, deliberadamente)

A regra vigente é **zero chamada remota ao Jettax 360 em código, tela e
documentação, e zero credencial do fornecedor no banco**. A migração de
referência (`app/db/migracoes.py`, `_apagar_credenciais_jettax`) apaga da
tabela de credenciais qualquer registro `jettax360` que exista de instalações
antigas — segredo que não se usa não fica no cofre. O `jettax360` que ainda
aparece no código é **rótulo de procedência** na reconciliação (de quem veio o
dado importado), nunca fonte remota: `FONTES_REMOTAS` contém apenas
`integra_contador`.

Se um dia o fornecedor publicar contrato para essa tela, o caminho é o mesmo de
qualquer integração nova — e nada por adivinhação. Antes de qualquer linha de
código: captura real do painel (DevTools → aba Network → a requisição da tela →
*Copy as cURL* + o JSON de resposta) conferindo método, caminho, parâmetros
(`page`, `tab`), autenticação, forma dos campos, datas e paginação. A
implementação nasceria **rotulada como comportamento observado do painel, não
como API oficial publicada** — sujeita a mudar sem aviso, sem compromisso de
compatibilidade, com o caminho A permanecendo como via de contingência. O
acesso usaria a conta e os dados do próprio escritório: nada de sessão de
terceiro, CAPTCHA contornado ou automação disfarçada. E, por tocar o ambiente
RFB por intermediação, a IN RFB nº 2.320/2026 seria avaliada antes.

### O caminho que funciona hoje, em CSV

```csv
cnpj;razao_social;situacao;data_validade;servicos
12.345.678/0001-95;PADARIA AURORA LTDA;ativa;31/12/2030;ALL
98.765.432/0001-10;TRANSPORTES MIRIM ME;sem procuração;;
```

- aceita `;` ou `,`, com ou sem BOM;
- data em `dd/mm/aaaa` ou ISO;
- documento com ou sem máscara, validado por dígito verificador;
- **validade vencida vence o rótulo**: linha marcada "ativa" com data passada
  entra como `expirada`;
- documento fora da carteira vira pendência com motivo, nunca empresa fantasma.

---

## 4. Ambiente de testes

**A Receita Federal não oferece sandbox para o fluxo de autorizações de
acesso.** Não existe portal de homologação em que se possa criar uma outorga de
mentira. O Integra Contador tem *trial* apenas de consulta, com dados fixos.

O que isso significa na prática, e como o repositório lida:

| | |
|---|---|
| **Nenhum teste chama o portal** | nem em CI, nem localmente |
| **Nenhum teste simula resposta do portal como se fosse real** | dublês de fonte externa se chamam `FonteFalsa`, explicitamente |
| **O que é testado** | o contrato do nosso lado: estados, idempotência, lock, seleção de certificado, protocolo do Agent, e o ponto exato em que o sistema para |
| **Validação real** | só em produção, com uma empresa piloto, acompanhada por um operador |

Roteiro sugerido para o piloto:

1. matricular uma estação e conferir o diagnóstico do Assinador;
2. escolher **um** cliente cujo A1 esteja na máquina e vigente;
3. rodar "Processar pendências" e reivindicar o job;
4. percorrer o roteiro com atenção, comparando cada tela com as âncoras;
5. registrar protocolo e conferir a situação "Em análise" no portal;
6. fazer o aceite e conferir "Ativa";
7. rodar a consulta pelo Integra Contador e confirmar que ela enxerga a mesma
   coisa.

Divergência em qualquer passo é informação valiosa: significa que o roteiro em
`app/procuracoes/portal.py` precisa de ajuste. Ajuste-o antes de processar o
segundo cliente.

---

## 5. Precedência entre fontes

Quando duas fontes discordam sobre a mesma empresa:

```
integra_contador  >  jettax360  >  planilha  >  manual
```

Fonte mais fraca não sobrescreve confirmação de fonte mais forte: o registro é
marcado como visto (`sincronizado_em`) e contabilizado como `ignorado`. Sem
essa regra, uma planilha desatualizada poderia "apagar" o que a API oficial
acabou de confirmar.

Exceção: `origem_dado = "operacao"` — dado gravado pela própria execução
assistida, com protocolo em mãos. Ele é tratado como observação direta e cede
apenas ao canal oficial.
