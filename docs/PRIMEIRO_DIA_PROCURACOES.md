# Procurações: do zero à operação automática

Este é o único roteiro para colocar o módulo em funcionamento. Não é preciso
ler a arquitetura para começar.

## O que fica automático — e o único ponto que não pode ser robô

Depois da configuração inicial, o sistema faz sozinho:

- lê a carteira e identifica quem está sem autorização, vencido ou perto de
  vencer;
- mantém uma fila idempotente: rodar duas vezes não cria duas outorgas;
- encontra a estação que possui o A1 correto, valida validade e o Assinador
  SERPRO antes de abrir qualquer portal;
- abre a página oficial, monta dados de outorgado, vigência e serviços;
- registra protocolo, monitora os 30 dias para o aceite e alerta vencimentos;
- sincroniza a situação por Integra Contador quando esse canal oficial estiver
  configurado.

A **outorga, assinatura e validação** no Portal da Receita continuam feitas por
uma pessoa no portal oficial. Não é limitação técnica: em 2026 a IN RFB nº
2.320/2026, art. 13, veda automatizar/encapsular esses atos. O Cajuru Agent
elimina toda a preparação e deixa para a pessoa apenas a conferência e a
confirmação jurídica. Não há CAPTCHA, sessão, senha ou clique automático.

## Antes de começar

Separe em uma máquina Windows que será usada para assinar:

1. uma pasta com todos os certificados `.pfx` ou `.p12`;
2. uma ou mais planilhas com as colunas **CNPJ/CPF ou Cliente**, **Senha** e,
   quando houver, **Validade/Vencimento**;
3. o CNPJ/CPF e o nome da sua contabilidade (o outorgado);
4. o Assinador Digital SERPRO instalado nessa máquina.

As planilhas podem ser `.xlsx`, `.xlsm`, `.csv`, `.txt` ou `.tsv`. Duas
planilhas complementares são esperadas: por exemplo, uma com senha e outra com
validade.

> **Não envie certificados nem planilhas de senha por chat, e-mail ou Git.**
> Eles são processados localmente na estação Windows. PFX e senha não sobem para
> o Cajuru28 no fluxo de procurações.

## Faça nesta ordem

### 1. Cadastre a estação

No painel, abra **Procurações RFB → Estações → Matricular estação**. Dê um nome
fácil de reconhecer, como `PC Fiscal 01`, e copie o comando que a tela monta.
No PowerShell **como Administrador** da máquina que tem os certificados, execute
o comando. Ao finalizar, confira:

```powershell
cajuru-agent diagnostico
```

Só avance quando o diagnóstico disser que o Assinador está instalado, em
execução, com a porta local respondendo.

### 2. Instale todos os A1 usando suas planilhas

Ainda nesse Windows, rode primeiro a prévia. Ela não altera nada:

```powershell
cajuru-agent importar-certificados `
  --pasta "D:\Certificados" `
  --planilha "D:\Planilhas\senhas.xlsx" `
  --planilha "D:\Planilhas\validade.xlsx"
```

Corrija apenas as linhas marcadas como pendência:

- **sem associação:** renomeie o PFX incluindo o CNPJ, por exemplo
  `12345678000195 - Cliente.pfx`;
- **sem senha:** complete a senha na linha daquele cliente;
- **nome semelhante:** não escolha no chute; inclua o CNPJ no nome do arquivo.

Quando todos os itens necessários estiverem `PRONTO`, execute a importação e
sincronize o inventário público:

```powershell
cajuru-agent importar-certificados `
  --pasta "D:\Certificados" `
  --planilha "D:\Planilhas\senhas.xlsx" `
  --planilha "D:\Planilhas\validade.xlsx" `
  --executar --sincronizar
```

A senha passa apenas pela memória local e pelo `stdin` do PowerShell. Ela não
fica em argumento de comando, log, banco, API ou Credential Manager. A validade
que está dentro do certificado é a fonte de verdade; o comando avisa se ela
divergir da planilha.

### 3. Configure a contabilidade uma vez

No painel, abra **Procurações RFB → Configurar** e preencha:

- **CNPJ/CPF da contabilidade**;
- **nome da contabilidade**;
- ative **Montar a fila automaticamente**;
- mantenha **Sincronizar com as fontes configuradas** ligado;
- confira o modelo padrão (vigência e serviços).

Quando o Agent inventariar o certificado cujo CNPJ é o da contabilidade, o
Cajuru28 o classifica automaticamente para a fase de **aceite**. Não marque
certificados manualmente como “da contabilidade”.

### 4. Traga a situação da carteira

Há dois caminhos, que podem coexistir:

- **Integra Contador (SERPRO):** em **Configurar**, grave a credencial e clique
  em **Testar**. Esta é a fonte oficial para consultar situação e validade;
- **Jettax 360:** não há API pública documentada para a tela de procurações.
  Abra `Prevenção → e-CAC → Procurações`, copie a tabela ou exporte CSV e use
  **Procurações RFB → Importar lista**. Se a origem for a aba **Sem procuração**,
  selecione essa aba no campo “Situação da aba”.

A importação é idempotente. Pode importar página por página e repetir uma
página: o CNPJ é a chave, portanto não surgem duplicatas. A lista do Jettax é
só uma fotografia mensal; quando Integra Contador estiver disponível, ele tem
precedência.

### 5. Rode um piloto e ligue a rotina

Na tela **Procurações RFB**, clique em **Processar pendências**. O sistema cria
jobs para todos que precisam de ação e informa imediatamente se algum A1 está
vencido, ausente ou ambíguo.

No primeiro dia, processe **um cliente piloto**:

1. o Agent abre o portal oficial com os dados já prontos;
2. a pessoa confere e pratica a outorga com o A1 do cliente;
3. informe o protocolo ou a confirmação exibida pelo portal;
4. quando a fila pedir o aceite, a pessoa valida com o A1 da contabilidade;
5. confirme que o painel passou a mostrar **Ativa**.

Só então deixe o agendador processar a carteira. A partir daí, sua rotina é
olhar **Procurações RFB → Precisa de você**: itens em amarelo aguardam um ato
humano normal; vermelho indica certificado, estação ou dado que precisa de
correção.

## Quando parar e corrigir

- **Assinador indisponível:** não force job; abra **Estações** e siga o item
  apontado no diagnóstico.
- **Certificado vencido, ausente ou ambíguo:** substitua/instale o A1 correto e
  rode a prévia novamente. O sistema não escolhe por conta própria entre dois
  A1 válidos.
- **Tela da Receita diferente do roteiro, CAPTCHA ou desafio adicional:** pare.
  O Agent registra intervenção; não tente automatizar nem contornar segurança.
- **Jettax sem dados recentes:** importe a lista atual ou configure Integra
  Contador. Nunca trate a fotografia antiga como confirmação de outorga.

Para detalhes técnicos e recuperação, consulte
[`AGENT_CAJURU.md`](AGENT_CAJURU.md) e
[`PROCURACOES_OPERACAO.md`](PROCURACOES_OPERACAO.md).
