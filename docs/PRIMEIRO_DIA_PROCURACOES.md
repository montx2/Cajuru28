# Procurações: do zero à operação automática

Comece pelo **modo simples**. Não é preciso instalar Agent, abrir PowerShell ou
configurar uma estação para fazer uma procuração no computador atual.

1. em **Procurações RFB**, pesquise a empresa;
2. clique em **Fazer procuração**;
3. a página oficial da Receita abre no mesmo computador; confirme o ato com o
   certificado e, ao terminar, cole a mensagem/protocolo no painel.

O painel guarda o processo, evita duplicidade, controla o aceite e alerta os
prazos. A seção **Automação avançada**, mais abaixo, é opcional: serve apenas
para quem quiser uma máquina dedicada organizando uma carteira grande em fila.

## O que fica automático — e o único ponto que não pode ser robô

No modo simples, o sistema faz sozinho:

- guarda o processo e evita duplicidade para a mesma empresa;
- mostra no roteiro o CNPJ/CPF da contabilidade, a vigência e os serviços que
  devem ser conferidos no portal;
- registra o protocolo, monitora os 30 dias para o aceite e alerta vencimentos;
- sincroniza a situação por Integra Contador quando esse canal oficial estiver
  configurado.

A automação avançada acrescenta uma fila e a conferência local de certificados
em uma máquina dedicada. Ela não é necessária para abrir e concluir uma
procuração pelo modo simples.

A **outorga, assinatura e validação** no Portal da Receita continuam feitas por
uma pessoa no portal oficial. Não é limitação técnica: em 2026 a IN RFB nº
2.320/2026, art. 13, veda automatizar/encapsular esses atos. O Cajuru28
elimina a gestão em volta e deixa para a pessoa somente a conferência e a
confirmação jurídica no portal oficial. Não há CAPTCHA, sessão, senha ou clique automático.

No modo simples, o navegador que você já usa abre o Portal de Serviços. Se o
portal não enxergar o certificado, instale o A1 no Windows antes de tentar
novamente. Não entregue o PFX nem a planilha de senhas ao painel.

## Antes da primeira procuração

No computador Windows que você usará, deixe o certificado A1 já disponível ao
Windows e tenha o Assinador Digital SERPRO instalado. Para a fase de outorga,
é o certificado do **cliente**; para o aceite, o da **contabilidade**.

No primeiro clique em **Fazer procuração**, o sistema pergunta uma única vez o
CNPJ/CPF e o nome da sua contabilidade. Esse dado é indispensável: é a pessoa
jurídica que receberá a autorização no Portal da Receita, por isso não pode ser
adivinhado. Não é uma configuração técnica e não pede estação, Agent, PFX ou
senha.

> **Não envie certificados nem planilhas de senha por chat, e-mail ou Git.**
> PFX, senha e a sessão do portal não sobem para o Cajuru28.

Os arquivos `.pfx`/`.p12` e planilhas com **CNPJ/CPF ou Cliente**, **Senha** e
**Validade/Vencimento** só são usados na automação avançada abaixo. As planilhas
podem ser `.xlsx`, `.xlsm`, `.csv`, `.txt` ou `.tsv`; duas planilhas
complementares (uma de senha e outra de validade) são aceitas.

## Automação avançada — somente quando você quiser operar uma fila grande

O restante desta seção é opcional. Use-o apenas se quiser uma máquina dedicada
para verificar certificados e organizar trabalhos em segundo plano. Ele não é
necessário para o botão **Fazer procuração** do modo simples.

### 1. Cadastre uma máquina de automação

No painel, abra **Procurações RFB → Automação avançada → Configurar automação**. Dê um nome
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

### 3. Ajuste a fila, se desejar

Os dados da contabilidade já podem ter sido informados no primeiro clique em
**Fazer procuração**. Se for usar fila automática, abra **Procurações RFB →
Configurar** apenas para escolher as opções administrativas:

- ativar **Montar a fila automaticamente**;
- manter **Sincronizar com as fontes configuradas** ligado;
- conferir o modelo padrão (vigência e serviços).

Quando a automação inventariar o certificado cujo CNPJ é o da contabilidade, o
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
