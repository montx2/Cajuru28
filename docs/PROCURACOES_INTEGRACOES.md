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

**Status:** **não há documentação pública** de API REST. O material do
fornecedor menciona "API aberta" em linguagem de marketing; a central de ajuda
documenta integração com a Acessórias por `apiToken`, não um contrato de
consulta de procurações.

### Consequência de projeto

Inventar endpoint seria criar dependência fictícia que quebra no primeiro
contato com a realidade. Em vez disso:

- `app/procuracoes/integracoes/jettax.py` é um **adaptador dirigido por
  configuração**: base URL, token e rotas vêm do cofre e do campo `opcoes`;
- sem credencial, ele **falha fechado** com mensagem explícita — não finge
  sucesso, não devolve lista vazia silenciosa;
- a base URL passa por validação: HTTPS obrigatório, sem credencial embutida na
  URL, sem endereço de rede interna (defesa contra SSRF);
- o mapeamento de campos é configurável, porque o formato só será conhecido
  quando houver documentação.

### O que falta, exatamente

1. documentação oficial do endpoint de listagem de clientes/procurações;
2. formato de autenticação (header? query? OAuth?);
3. contrato de resposta (nomes de campo, formato de data, paginação);
4. limites de uso e política de retentativa;
5. credenciais do escritório.

Com esses cinco itens, a integração é uma edição no adaptador — nenhuma outra
parte do módulo muda.

### O caminho que funciona hoje

**Importação de planilha CSV**, sem credencial nenhuma:

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
- documento fora da carteira vira `ignorado` com motivo, nunca empresa
  fantasma.

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
