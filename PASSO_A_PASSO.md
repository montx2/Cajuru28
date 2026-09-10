# NotasFlow — Passo a passo (do download até as notas no seu computador)

Guia para quem vai **usar** o programa no dia a dia do escritório.
Repositório: https://github.com/montx2/Cajuru28

> **O que mudou:** o NotasFlow agora é um **programa instalado no seu
> computador** (Windows), e não um site hospedado. Você baixa um `.exe`, instala
> com dois cliques e pronto — os XMLs ficam no seu disco, no seu banco, e o
> certificado A1 nunca sai da máquina. Você não precisa de Docker, Python, Node
> nem internet fixa para trabalhar com o que já baixou.

---

## Passo 1 — Baixar o instalador

Abra a página de versões e baixe o arquivo **`NotasFlow-Setup-….exe`** (o maior,
que tem "Setup" no nome):

https://github.com/montx2/Cajuru28/releases/latest

Se preferir não instalar (máquina sem permissão de administrador, por exemplo),
baixe o **`NotasFlow-…-portatil.zip`**, extraia em `C:\NotasFlow` e abra o
`NotasFlow.exe` de dentro da pasta.

---

## Passo 2 — Instalar

Dê **dois cliques** no arquivo baixado.

- **Não pede senha de administrador.** O programa é instalado só para o seu
  usuário, em `%LOCALAPPDATA%\Programs\NotasFlow`.
- Na tela final, deixe marcado **"Abrir o NotasFlow junto com o Windows"**. É o
  que garante que o sistema continue consultando a SEFAZ nos dias em que você
  nem abrir o programa.
- Se o Windows mostrar o aviso azul *"O Windows protegeu o seu PC"*, clique em
  **Mais informações → Executar assim mesmo**. Isso aparece em qualquer programa
  novo sem assinatura digital paga; depois da primeira vez, não aparece mais.

Ao terminar, o NotasFlow abre sozinho, já com a sua tela de login, e passa a
ficar também **ao lado do relógio** (o ícone verde/NF — clique nele para abrir,
ver o log ou sair).

---

## Passo 3 — Entrar no painel

Na **primeira abertura** o programa criou sozinho:

- a sua pasta de dados: `%APPDATA%\NotasFlow`
- o arquivo **`CREDENCIAIS.txt`** com o e-mail e a senha gerados para este
  computador;
- as chaves de segurança que cifram a senha do seu certificado.

Abra `CREDENCIAIS.txt` (há um atalho **"Abrir a pasta de dados"** em
**Configurações**), copie e-mail e senha e entre.

Esqueceu a senha depois? Clique com o botão direito no ícone ao lado do relógio →
**Redefinir senha do administrador**. Não precisa chamar ninguém.

---

## Passo 4 — Cadastrar as empresas e os certificados

### Jeito rápido (30 empresas de uma vez)

1. Menu **Empresas** → **Importar em massa**
2. Selecione **todos os arquivos `.pfx`/`.p12`** de uma vez
3. Informe a senha (a mesma para todos, ou uma por empresa num CSV
   `razao_social;cnpj_cpf;uf;senha`)
4. Confira o relatório linha a linha

O sistema lê o **CNPJ e a razão social de dentro do certificado** (campo
ICP-Brasil do X.509) e cria a empresa já com o certificado vinculado. Um arquivo
com senha errada aparece como erro e **não** impede os outros.

### Jeito manual

Menu **Empresas** → **Nova empresa** (razão social, CNPJ, UF) → abrir a empresa
→ enviar o `.pfx` + senha do certificado A1.

> A senha do certificado é cifrada no cofre local e **nunca** volta para a tela.
> Só a senha que você digitar é usada — o sistema não tenta senhas "comuns".

---

## Passo 5 — Importar as notas (escolhendo as empresas)

Este é o passo que importa para o dia a dia: **você escolhe de quais empresas
quer puxar as notas agora**. Não faz sentido varrer as 30 quando o cliente pediu
as notas de duas.

1. Abra **Visão geral** (ou **Importações**)
2. Escolha a **competência** (o mês que o cliente pediu) — opcional
3. Escolha **o que puxar**: NFS-e, NFe, CT-e ou os três
4. **Marque as empresas** na lista (há busca por nome/CNPJ; a seleção fica
   guardada para a próxima vez)
5. Clique em **Importar N empresas**

Antes de disparar, a lista já mostra o que vai acontecer com cada empresa:

| Situação na lista | O que significa |
| --- | --- |
| Pode rodar agora | Janela da SEFAZ livre: a consulta sai na hora |
| Na janela de 1 h da SEFAZ | Esse CNPJ já foi consultado há pouco. A continuação está agendada — o sistema retoma sozinho |
| Já está varrendo | Há uma importação em andamento para essa empresa/tipo |
| Sem certificado A1 | Falta enviar o `.pfx` (o link leva para a tela da empresa) |

Uma empresa bloqueada **não** impede as outras: cada linha é tratada
separadamente, com o motivo escrito.

> **Por que não "importar todas" de uma vez?** Cada consulta gasta a janela de 1
> hora *daquele CNPJ* na SEFAZ. Varrer quem não foi pedido atrasa quem foi pedido
> — e consumo indevido é o único jeito de o CNPJ ser bloqueado. Ainda existe um
> botão para **forçar a janela**, mas ele é exceção e está marcado como tal.

### Se você não fizer nada

Depois de cadastrar empresa + certificado, o **sincronismo automático** entra em
ação: o programa consulta cada CNPJ no ritmo que a SEFAZ permite (1 hora por
empresa e tipo de documento) enquanto o computador estiver ligado. A tela
**Importações** mostra de onde cada empresa está:

- **em dia ✔** — nada a fazer;
- **varrendo…** — descendo os lotes agora;
- **bloqueada pela SEFAZ · tenta sozinha 14:37** — é o protocolo, não uma falha;
  esperar é o que preserva o CNPJ;
- **⚠ N dias sem varrer com documento faltando** — este é o caso que exige
  atenção: a distribuição oficial só guarda os últimos ~3 meses. Sem
  importação nesse período, o que ficou para trás pode ter saído da
  distribuição — nesse caso o XML precisa ser pedido no portal da SEFAZ.

---

## Passo 6 — Ver e entregar as notas

Menu **Documentos**:

- filtre por **empresa**, **tipo** e **competência (mês)**;
- **Baixar todos os XMLs** gera um ZIP com os XMLs, um `relacao.csv` (abre
  direto no Excel, com `;` e acentuação) e um `LEIA-ME.txt`;
- dá para marcar linhas e baixar só a seleção;
- notas **canceladas** aparecem marcadas, com motivo e data;
- quem chegou só em resumo tem o **XML completo** buscado pela chave no botão
  de completar (dentro da cota oficial de 20 consultas/hora).

---

## Passo 7 — Backup (2 minutos que salvam o escritório)

**Configurações → Gerar backup agora** cria um ZIP com o banco de notas, os
certificados e a configuração. Guarde no pendrive ou na nuvem.

O que acontece se o computador quebrar **sem** backup: os XMLs podem ser baixados
de novo da SEFAZ (dentro dos ~3 meses da distribuição) e os certificados você já
tem — mas reenviar 30 certificados com senha não é um dia agradável.

O programa também gera um backup sozinho por dia e mantém os 10 últimos na pasta
de dados.

---

## Passo 8 — Atualizações (você não faz nada)

Quando o autor publica uma correção, o programa lê o aviso, baixa e instala
sozinho — sem pedir arquivo, sem pedir senha de administrador, sem perder nada
do que está no banco.

- aparece uma faixa no topo: **"Versão 1.1.0 disponível"** com as notas e
  **Atualizar agora**;
- se você estiver no meio de um fechamento, clique em **depois** — a faixa volta
  depois (e a atualização obrigatória não oferece essa opção);
- enquanto a tela de Configurações estiver aberta, você pode conferir
  **Versão** verificado naquele momento, e forçar **Verificar agora**.

Quem atualiza são os computadores; o **código do repositório não precisa ser
baixado** por ninguém.

---

## Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| Quero saber onde ficam meus dados | **Configurações → Abrir a pasta de dados** (é `%APPDATA%\NotasFlow`) |
| "Não foi possível verificar atualização agora" | Sem internet ou a release ainda não foi publicada. O programa funciona normalmente; ele tenta de novo depois |
| Esqueci a senha do painel | Ícone ao lado do relógio → **Redefinir senha do administrador** → nova senha em `CREDENCIAIS.txt` |
| "Sem certificado A1" na lista de importação | Envie o `.pfx` da empresa (Passo 4) |
| "Certificado vencido/perto de vencer" | Renove o A1 (a faixa mostra os dias que faltam) e envie o novo arquivo — o A1 leva alguns dias para sair, então vale olhar essa faixa |
| Erro `cStat 656` / "Aguardando a SEFAZ" | Isso **não é erro**: é a janela de 1 h que a SEFAZ exige por CNPJ. A retomada está agendada; não force (insistir antes da hora zera o cronômetro) |
| Tela travada / algo estranho | **Configurações → Ver registros**: as últimas linhas explicam o que aconteceu — é isso que se manda para o suporte |
| O programa não abre | Veja `%APPDATA%\NotasFlow\logs\notasflow.log`; no menu Iniciar há **NotasFlow** de novo |
| Quero instalar em outro computador | Baixe o instalador de novo e cadastre as empresas/certificados por lá (cada máquina tem o seu banco). **Não** instale duas cópias no mesmo escritório sincronizando os mesmos CNPJs: as duas consultariam a SEFAZ e o CNPJ seria bloqueado |
| Quero desinstalar | Configurações do Windows → Aplicativos. Os **dados continuam** lá (é a pergunta que a desinstalação faz) |

---

## Segurança

- O painel escuta **só no seu computador** (`127.0.0.1`). Nenhuma outra máquina da
  rede alcança o NotasFlow — nem os certificados, nem o banco.
- O certificado fica em `%APPDATA%\NotasFlow\dados\certificados\…`, com permissão
  restrita ao seu usuário; a senha dele é cifrada com a `VAULT_MASTER_KEY`
  gerada no seu computador.
- **Não mexa na `VAULT_MASTER_KEY`** do `.env` (na pasta de dados): trocá-la
  torna indecifráveis as senhas dos certificados já cadastrados. Se isso
  acontecer, restaure a chave anterior ou reenvie os `.pfx`.
- Nunca envie `CREDENCIAIS.txt`, o `.env` ou a pasta de certificados para
  ninguém.

---

## Apêndice — Modo servidor (Docker), para quem preferir

O mesmo sistema continua tendo o modo servidor com PostgreSQL + Redis + Celery,
para uso em uma máquina só do escritório com vários usuários no navegador:

```bash
git clone https://github.com/montx2/Cajuru28.git && cd Cajuru28
./INSTALAR_TUDO.sh        # Windows: dois cliques em INSTALAR_TUDO.bat
```

| Serviço | Endereço |
| --- | --- |
| Painel | http://localhost:3000 |
| API / Swagger | http://localhost:8000/docs |

Nesse modo, o crescimento horizontal é `docker compose up --scale worker=3` e o
`beat` mantém o sincronismo. É a opção certa para quem quer **um banco só** e
vários contadores acessando — e a opção errada para internet aberta sem TLS.

Se o painel precisar ser acessível de outras máquinas do escritório a partir do
programa instalado, existe a chave `NOTASFLOW_PERMITIR_REDE=true` (o painel passa
a escutar em `0.0.0.0`) — mas aí os outros computadores usam o painel **no
navegador**, sem instalar o programa: duas instalações sincronizando os mesmos
CNPJs fazem a SEFAZ bloquear por consumo indevido.
