# Cajuru Agent — instalação, contrato e operação

A estação é a máquina Windows do escritório que tem os certificados A1
instalados e o Assinador Digital SERPRO funcionando. O Agent roda nela.

---

## 1. O que ele faz e o que não faz

**Faz:** inventaria certificados (só metadados), diagnostica o Assinador, pede
trabalho ao Cajuru28, abre o navegador real do operador na página oficial da
Receita, conduz o roteiro passo a passo, registra evidências e resultados.

**Não faz:** ler chave privada, guardar senha de certificado, clicar em "Nova
Autorização", preencher formulário, assinar, validar, contornar CAPTCHA/MFA ou
dar operação por concluída sem confirmação real.

A razão está em [`PROCURACOES_CONFORMIDADE.md`](PROCURACOES_CONFORMIDADE.md).

---

## 2. Requisitos da máquina

| Item | Mínimo | Verificação |
|---|---|---|
| Windows | 10 / 11, 64 bits | — |
| Python | 3.11+ | o instalador confere |
| Assinador Digital SERPRO Desktop | 4.0.0+ (versão mínima é configurável) | `cajuru-agent diagnostico` |
| Certificados A1 | instalados em `CurrentUser\My` | `cajuru-agent certificados` |
| Rede | HTTPS de saída até o Cajuru28 | `cajuru-agent testar` |
| `hosts` | `127.0.0.1 assinador-desktop.serpro.gov.br` | o instalador adiciona |

O Assinador precisa estar **em execução** (ele fica na área de notificação) e
respondendo em `https://127.0.0.1:65156`. Chrome e Edge ainda exigem a
permissão **"Acesso à rede local"** para o portal — o teste oficial do SERPRO
está em <https://www.frameworkdemoiselle.gov.br/v3/signer/demo/>.

---

## 3. Instalação

### 3.1 No Cajuru28

**Procurações → Estações → Matricular estação.** Dê um nome que identifique a
máquina física ("PC Fiscal 01") — é o **único** campo do formulário. A tela
responde com o **identificador** e o **segredo**, e monta o comando pronto do
instalador com os dois já preenchidos.

**Quem gera o identificador é o servidor**, não o operador e não a estação:
`secrets.token_hex(16)` (32 caracteres hexadecimais), com unicidade garantida
no banco. O motivo é prático antes de ser teórico — ninguém tem como saber um
hash antes de a estação existir, e identificador escolhido à mão (`estacao01`)
colide entre escritórios e é palpitável. O campo `identificador` do
`POST /procuracoes/agentes` continua aceito quando enviado, e serve a um caso
só: **re-credenciar** a mesma máquina, mantendo o identificador e trocando o
segredo.

> O segredo aparece **uma única vez**. Não há tela, log ou endpoint que o
> recupere. Perdeu? Gere outra credencial — a anterior deixa de valer no mesmo
> instante, inclusive as sessões abertas.

### 3.2 Na estação

PowerShell **como Administrador**, na pasta `agent/`:

```powershell
.\instalar_agent.ps1 `
  -ServidorUrl   "https://cajuru.suaempresa.com.br" `
  -Identificador "<identificador da tela>" `
  -Segredo       "<segredo da tela>" `
  -NomeEstacao   "PC Fiscal 01"
```

O que o script faz, em ordem:

1. exige `https://` no endereço — credencial não trafega em claro;
2. confere Python 3.11+;
3. copia o Agent para `%LOCALAPPDATA%\Cajuru28\Agent`;
4. cria um venv isolado e instala as dependências (só `httpx`);
5. grava a credencial no **Windows Credential Manager**;
6. adiciona o mapeamento do Assinador no `hosts`;
7. registra a tarefa agendada "Cajuru28 - Agent Procuracoes" (inicia no logon);
8. roda diagnóstico, inventário e teste de conexão.

Apague em seguida a mensagem que continha o segredo: ele já está no cofre.

### 3.3 Carregar a pasta de A1 com as planilhas de senha e validade

Para o escritório que já guarda todos os `.pfx/.p12` e tem as duas planilhas
(nome/CNPJ + senha + validade), não é preciso cadastrar um por um no navegador.
No **mesmo Windows que rodará o Assinador**, execute primeiro a prévia:

```powershell
cajuru-agent importar-certificados `
  --pasta "D:\Certificados" `
  --planilha "D:\Planilhas\senhas.xlsx" `
  --planilha "D:\Planilhas\validade.xlsx"
```

O comando aceita `.xlsx`, `.xlsm`, `.csv`, `.txt` e `.tsv`, inclusive duas ou
mais planilhas complementares. Ele une linhas pelo CNPJ e, quando a segunda
planilha só traz nome, pelo nome exatamente igual. Para cada PFX, a associação
é determinística: CNPJ no nome do arquivo vence; sem CNPJ, usa nome do cliente
se houver um único candidato. Empate ou falta de senha vira pendência visível —
nunca uma tentativa com senha aleatória ou de outro cliente.

Revise a prévia. Para instalar no repositório do usuário atual e sincronizar
somente metadados públicos ao painel, confirme explicitamente:

```powershell
cajuru-agent importar-certificados `
  --pasta "D:\Certificados" `
  --planilha "D:\Planilhas\senhas.xlsx" `
  --planilha "D:\Planilhas\validade.xlsx" `
  --executar --sincronizar
```

O PFX não é enviado ao servidor. A senha nunca entra em log, argumento de
linha de comando, variável de ambiente, arquivo temporário, banco ou
Credential Manager: ela é passada pela memória e pelo `stdin` ao PowerShell
somente para o Windows instalar o certificado em `CurrentUser\My`. A validade
lida do próprio certificado prevalece sobre a validade declarada na planilha;
divergência aparece como aviso no resultado.

### 3.4 Por que Credential Manager

| Alternativa | Por que não |
|---|---|
| Arquivo cifrado pelo próprio Agent | a chave ficaria ao lado do arquivo — criptografia decorativa |
| Variável de ambiente | vaza em dump de processo, log de tarefa agendada e para qualquer programa do mesmo usuário |
| Cofre próprio | criptografia caseira, explicitamente fora de escopo |
| **Credential Manager (DPAPI)** | é o mecanismo do sistema operacional, ligado à conta do usuário, mantido pela Microsoft |

Fora do Windows (desenvolvimento), o Agent cai para arquivo `600` em
`~/.cajuru-agent/` e **avisa no log** que aquilo não é produção.

---

## 4. Contrato do protocolo

Base: `POST /procuracoes/agente/*`. Sem cookie — portanto fora do CSRF por
`Origin`, que só se aplica a requisição com sessão de navegador.

### 4.1 Assinatura

Toda requisição autenticada leva:

```
X-Cajuru-Agente      <identificador da estação>
X-Cajuru-Chave       <chave de sessão>
X-Cajuru-Timestamp   <ISO-8601 UTC>
X-Cajuru-Nonce       <32 hex, uso único>
X-Cajuru-Assinatura  <hex HMAC-SHA256>
```

```
assinatura = HMAC-SHA256(
    chave_sessao,
    MÉTODO + "\n" + CAMINHO + "\n" + TIMESTAMP + "\n" + NONCE + "\n" + sha256(corpo)
)
```

O corpo entra na assinatura: um proxy no meio não consegue trocar o resultado
de um job. O nonce é de uso único dentro de 5 minutos — replay recebe `409`.
Relógio fora de 5 minutos recebe `401`; se isso aparecer, sincronize a hora da
estação.

### 4.2 Rotas

| Método | Rota | Corpo | Devolve |
|---|---|---|---|
| POST | `/sessao` | `{identificador, segredo}` | `{chave_sessao, expira_em_segundos}` |
| DELETE | `/sessao` | `{}` | `204` |
| POST | `/heartbeat` | `{versao_agente, versao_navegador, assinador:{...}}` | `{assinador_apto, assinador_detalhe, jobs_disponiveis}` |
| POST | `/inventario` | `{certificados:[...]}` | `{recebidos, novos, atualizados, indisponiveis, invalidos}` |
| POST | `/reivindicar` | `{capacidade}` | `{ordens:[OrdemDeTrabalho], intervalo_busca_segundos}` |
| POST | `/jobs/{id}/lease` | `{lease_token}` | lease renovado |
| POST | `/jobs/{id}/progresso` | `{lease_token, etapa, mensagem, detalhe}` | resumo do job |
| POST | `/jobs/{id}/resultado` | `{lease_token, resultado, protocolo?, confirmacao_portal?, codigo_erro?, mensagem?}` | resumo do job |
| POST | `/jobs/{id}/portal-alterado` | `{lease_token, etapa, ancoras_ausentes[], url}` | job em intervenção |
| POST | `/jobs/{id}/sessao-navegador` | `{lease_token, ...}` | registro da sessão |
| POST | `/jobs/{id}/evidencia` | **binário puro**; lease em `X-Cajuru-Lease` | metadados da evidência |

### 4.3 A ordem de trabalho

```jsonc
{
  "job_id": 42,
  "lease_token": "…",
  "lease_ate": "2026-09-25T18:30:00Z",
  "fase": "outorga",                       // ou "aceite"
  "etapa": "pre_requisitos",
  "modo": "assistido",
  "empresa_documento": "12345678000195",
  "empresa_nome": "PADARIA AURORA LTDA",
  "outorgado_documento": "11222333000181",
  "vigencia_ate": "2031-09-24",
  "escopo_servicos": "ALL",
  "certificado_thumbprint": "a1b2…",       // qual A1 usar
  "certificado_referencia": "CurrentUser\\My:a1b2…",
  "certificado_documento": "12345678000195",
  "certificado_tipo": "cliente",
  "url_portal": "https://servicos.receitafederal.gov.br",
  "roteiro": [ /* passos com título, instrução, url, confirmação, executor */ ],
  "timeout_etapa_segundos": 900,
  "intervalo_heartbeat_segundos": 60
}
```

Não há senha, não há PFX, não há chave. O certificado é referenciado por
`thumbprint` e por uma referência local que só a estação sabe resolver.

### 4.4 Progresso: a estação relata etapa, não estado

`/progresso` aceita `etapa`, **não** `status`. O estado do job é derivado no
servidor por `ESTADO_DA_ETAPA`. Se a estação pudesse declarar o status, poderia
pular de "atribuído" para "assinado" — e a máquina de estados viraria enfeite.
Etapa que implique transição inválida devolve `409` e nada muda.

### 4.5 Resultado: sem prova não conclui

`resultado: "outorga_registrada"` exige **protocolo ou texto de confirmação**
do portal. `resultado: "falha"` exige `codigo_erro`. A API recusa o resto.

---

## 5. Uso diário

```powershell
cajuru-agent executar        # laço principal (a tarefa agendada roda isto)
cajuru-agent diagnostico     # estação inteira, sem falar com o servidor (§6)
cajuru-agent certificados    # o que a máquina enxerga (--json para script)
cajuru-agent testar          # autentica e bate um heartbeat
```

Durante a condução, cada etapa oferece quatro respostas:

| Tecla | Significado | Efeito |
|---|---|---|
| `c` | confirmar e seguir | registra progresso, renova o lease |
| `n` | **não existe esse item na tela** | `PORTAL_ALTERADO`, job interrompido, equipe avisada |
| `d` | apareceu desafio/erro de segurança | `DESAFIO_DE_SEGURANCA`, intervenção manual |
| `x` | parar por aqui | job volta para a fila no ponto atual |

Ao final, o Agent pede o protocolo e/ou o texto exibido pelo portal. Se o
operador não informar nenhum dos dois, o job **não** é concluído — vira
intervenção com `CONFIRMACAO_AUSENTE`.

---

## 6. Diagnóstico da estação

```powershell
cajuru-agent diagnostico                # relatório legível
cajuru-agent diagnostico --json         # mesmo conteúdo, para script
cajuru-agent diagnostico --sem-rede     # só o que é local
```

`diagnostico` verifica a estação inteira, não só o Assinador, e é o **gate de
instalação**: enquanto ele não passar, a máquina não está pronta para conduzir
uma outorga.

### 6.1 O que é verificado

| Chave | Verifica | Bloqueante |
|---|---|---|
| `sistema` | Windows 10/11 — único ambiente homologado para o Assinador | aviso fora do Windows |
| `python` | versão mínima do interpretador | sim |
| `relogio` | desvio do relógio contra fonte externa | sim acima da tolerância |
| `dns` | resolução dos domínios oficiais | sim |
| `portal` | alcançabilidade do Portal de Serviços da RFB | sim |
| `navegador` | Edge/Chrome instalado | sim |
| `certificados` | repositório do Windows legível e com A1 utilizável | sim |
| `certificados_vencendo` | A1 perto do fim da validade | aviso |
| `assinador` | instalado, em execução, `hosts`, porta 65156, versão mínima | sim |

O relógio entra na lista por um motivo prático: a assinatura HMAC do protocolo
tem janela de tempo, e uma máquina com horário torto falha na autenticação com
uma mensagem que não parece ter nada a ver com relógio.

### 6.2 Os quatro níveis

| Nível | Significado |
|---|---|
| `PASS` | verificado e aprovado |
| `AVISO` | funciona, mas há algo para resolver (ex.: A1 vencendo em 20 dias) |
| `FALHA` | bloqueia a operação |
| `PULADO` | **não foi possível verificar** |

`PULADO` nunca é contado como aprovação. Com `--sem-rede`, as checagens de rede
saem como `PULADO` e o relatório diz isso na cara — um diagnóstico que finge ter
verificado o que não verificou é pior que nenhum diagnóstico.

### 6.3 Código de saída

`0` quando não há nenhuma `FALHA`; `1` caso contrário. Avisos não reprovam.
Isso torna o comando utilizável direto em script de instalação e em tarefa
agendada:

```powershell
cajuru-agent diagnostico
if ($LASTEXITCODE -ne 0) { throw "Estacao nao apta - resolva as falhas acima" }
```

Com `--json`, a saída traz `apto`, `pior_nivel`, `contagem` por nível e a lista
de `verificacoes` com `chave`, `nivel`, `detalhe`, `acao` e `dados` — cada falha
já vem com o conserto escrito, porque quem roda isso normalmente é quem está
instalando, não quem escreveu o sistema.

### 6.4 Detalhe do Assinador

Sete verificações, cada uma com conserto objetivo:

| Item | Bloqueante | Conserto |
|---|---|---|
| Instalado | sim | instalar pelo site oficial do SERPRO |
| Em execução | sim | abrir o Assinador (área de notificação) |
| `hosts` mapeado | sim | `127.0.0.1 assinador-desktop.serpro.gov.br` |
| Porta 65156 respondendo | sim | firewall/antivírus; reiniciar o Assinador |
| Versão mínima | sim | atualizar |
| Certificado visível | não | importar o A1 no repositório do usuário que roda o Agent |
| Permissão do navegador | não | autorizar "Acesso à rede local" e revalidar no teste oficial |

O veredito é do servidor (`servicos/assinador.py`), e é **falha fechada**:
diagnóstico ausente ou incompleto reprova. Sem aprovação, `/reivindicar`
devolve `409 ASSINADOR_NAO_INSTALADO` com a lista de pendências — nenhum job é
entregue, e o escritório recebe notificação.

Manual oficial:
<https://artefatos-assinador.serpro.gov.br/downloads/Manual_Usuario_Assinador_Desktop.pdf>
(seção 12: teste de conexão; seção 13: autorização nos navegadores).

---

## 7. Múltiplas estações

Cada máquina tem sua credencial. O roteamento é por certificado disponível: um
job só é oferecido à estação que tem o A1 daquele CNPJ. Duas estações **nunca**
trabalham o mesmo cliente ao mesmo tempo — a reivindicação é um `UPDATE`
condicional com verificação de `rowcount`; quem perde a corrida recebe fila
vazia, não erro.

Distribuição recomendada: os certificados ficam onde o operador responsável por
aquele grupo de clientes trabalha. Concentrar todos numa máquina só cria fila
humana; espalhar sem critério faz o job procurar certificado que não existe.

---

## 8. Quando algo dá errado

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `401 Credencial de estação recusada` | credencial rotacionada/revogada | matricular de novo e reinstalar |
| `401` em toda requisição, credencial certa | relógio fora de 5 min | sincronizar a hora do Windows |
| `409 REPLAY` | duas instâncias do Agent rodando | encerrar a duplicada |
| `409 ASSINADOR_NAO_INSTALADO` | diagnóstico reprovado | seguir §6 |
| Fila sempre vazia | nenhum A1 vigente da carteira nesta máquina | conferir `cajuru-agent certificados` |
| Job some do meio | lease expirou (queda de rede/reinício) | nada: ele volta sozinho, no mesmo ponto |
| `CERTIFICADO_AMBIGUO` | dois A1 vigentes do mesmo CNPJ | fixar qual usar na tela da empresa |
| `PORTAL_ALTERADO` | a Receita mudou a tela | manutenção do adaptador; ver `PROCURACOES_RFB.md` §14 |

Log da estação: `%LOCALAPPDATA%\Cajuru28\Agent\agent.log`. Ele registra o
identificador público da estação — nunca o segredo, nunca senha, nunca conteúdo
de certificado.

---

## 9. Atualização

O Agent é código Python num venv isolado. Para atualizar:

```powershell
# com a nova versão do repositório em mãos
.\instalar_agent.ps1 -ServidorUrl "…" -Identificador "…" -Segredo "…" -SemTarefaAgendada
```

O instalador é idempotente: recopia os arquivos, reinstala as dependências e
preserva a credencial. Encerre o Agent antes (`Ctrl+C` ou parar a tarefa) — job
em andamento volta para a fila sozinho, sem perda.

O servidor recusa estação abaixo da versão mínima configurada do Assinador; a
mesma disciplina vale para a versão do Agent quando houver quebra de contrato.
