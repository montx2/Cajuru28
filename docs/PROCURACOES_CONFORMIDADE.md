# Procurações RFB — conformidade

O que pode, o que não pode, e por quê. Este documento existe para que a decisão
de **não** construir um robô de outorga seja auditável — por quem assina pelo
escritório, por quem mantém o código e, se for o caso, pela própria Receita.

---

## 1. A norma

**Instrução Normativa RFB nº 2.320, de 6 de abril de 2026**, que consolida as
regras do Portal de Serviços da Receita Federal (substituindo a Portaria RFB
nº 410/2024).

O dispositivo que decide a arquitetura deste módulo é o **art. 13**, que veda
aplicativo, *webview*, *iframe*, camada de intermediação ou sistema próprio
que, por **automação ou encapsulamento** do ambiente digital da Receita,
possibilite **outorga, alteração ou revogação** de autorizações de acesso.

Sanções previstas: interrupção do acesso, bloqueio do representante e
cancelamento das autorizações já concedidas. O prejuízo, note-se, não recai
sobre o fornecedor do software — recai sobre o escritório e sobre cada cliente
cuja autorização for cancelada.

A norma também prevê bloqueio por irregularidade cadastral e a possibilidade de
limite de autorizações por representante.

A leitura predominante entre especialistas é que a vedação alcança a
intermediação não oficial do ambiente da RFB; **permanecem viáveis** as APIs
oficiais e as ferramentas de gestão interna que não acessam diretamente aquele
ambiente.

---

## 2. Classificação de cada operação

Esta é a tabela que responde "por que isto é automatizado e aquilo não é".

| Operação | Classificação | O que o módulo faz |
|---|---|---|
| Consultar existência e validade de autorização | **API oficial** (Integra Contador, `OBTERPROCURACAO41`) | automatizado, é a fonte da verdade |
| Listar a carteira de clientes | **integração interna** | automatizado (Jettax/planilha/cadastro) |
| Decidir quem precisa de autorização | **gestão interna** | automatizado |
| Montar fila, modelos, prazos, alertas, auditoria | **gestão interna** | automatizado |
| Validar certificado A1 (existe? vence quando? é do CNPJ certo?) | **depende do certificado**, local | automatizado no Agent |
| Verificar o Assinador SERPRO | **depende do Assinador**, local | automatizado no Agent |
| Abrir o navegador na URL oficial | **navegação**, sem encapsulamento | automatizado |
| Autenticar-se no Portal com certificado | **interação humana obrigatória** | conduzido, nunca executado |
| Preencher "Nova Autorização" | **vedado automatizar** (art. 13) | operador preenche; sistema dita os dados |
| Assinar no Portal de Assinatura gov.br | **interação humana obrigatória** + Assinador | operador assina |
| Validar a autorização recebida (aceite) | **vedado automatizar** (art. 13) | operador valida |
| Registrar protocolo e resultado | **gestão interna** | automatizado, com prova |
| Monitorar validade, expiração e prazo de 30 dias | **gestão interna** | automatizado |
| Cancelar/revogar autorização | **vedado automatizar** (art. 13) | fora do escopo do módulo |

### Hipóteses a validar em ambiente controlado

Registradas aqui porque **não** foram tratadas como fato:

- se a Receita passar a oferecer serviço oficial de outorga por API, a camada
  3 deixa de ser necessária — o ponto de extensão está documentado em §4;
- se o escritório obtiver autorização formal da RFB como intermediário, o
  flag `autorizacao_formal_rfb` registra o documento na auditoria. Mesmo
  assim, **nenhum executor não assistido está embarcado**: a flag destrava a
  documentação do ponto de extensão, não um robô.

---

## 3. Como a decisão está codificada

Conformidade que depende de alguém lembrar não é conformidade. Por isso ela é
executável:

```python
# app/procuracoes/estados.py
avaliar_modo(ModoOperacao.NAO_ASSISTIDO, autorizacao_formal_rfb=False)
# → AvaliacaoPolitica(permitido=False,
#                     modo_efetivo=ModoOperacao.ASSISTIDO,
#                     fundamento=FUNDAMENTO_IN_2320)
```

Onde isso é aplicado:

1. **Validação de entrada** — `ConfiguracaoEntrada` recusa `modo_padrao =
   "nao_assistido"` sem `autorizacao_formal_rfb`, devolvendo `422` com a
   citação da norma. O operador não consegue configurar o proibido.
2. **Criação do job** — o modo efetivo é carimbado no job e aparece na trilha.
3. **Ordem de trabalho** — o Agent recebe `modo` e o exibe ao operador.
4. **Roteiro** — cada passo declara `executor: "operador" | "sistema"`. Os
   passos de outorga, assinatura e validação são, todos, `operador`.
5. **Adaptador do portal** — `app/procuracoes/portal.py` **não contém
   seletores de clique** para outorga, alteração ou revogação. A ausência é
   deliberada e está documentada no cabeçalho do arquivo: não há o que
   "reativar" mais tarde.

Testes que travam isso: `test_procuracoes_dominio.py::test_modo_nao_assistido_e_rebaixado_sem_autorizacao_formal`
e `test_procuracoes_seguranca.py::test_modo_nao_assistido_e_recusado_na_borda`.

---

## 4. Ponto de extensão

Se a situação jurídica mudar — serviço oficial de outorga, ou autorização
formal específica —, o caminho está preparado:

1. `ModoOperacao` já prevê o valor `nao_assistido`;
2. `avaliar_modo()` já é a porta única de decisão;
3. `portal.PassoRoteiro.executor` já distingue quem executa cada passo;
4. faltaria apenas implementar o executor e mudar `executor` para `"sistema"`
   nos passos correspondentes.

O que **não** existe e não deve ser criado sem respaldo documental: código de
clique automático em "Nova Autorização", "Assinar" ou "Validar".

---

## 5. Proteção de dados

| Dado | Onde vive | Proteção |
|---|---|---|
| Chave privada do A1 | estação Windows | CryptoAPI/CNG; nunca sai da máquina |
| Senha do A1 | não existe no módulo | nenhum campo, nenhum endpoint |
| Credencial da estação | Credential Manager (DPAPI) | Argon2id no servidor |
| Credencial de integração | banco | Fernet (`VAULT_MASTER_KEY`) |
| Evidências (tela/HTML) | disco do servidor | cifradas, `chmod 600`, retenção configurável, senha redigida antes de gravar |
| Trilha de auditoria | banco | append-only, **sem rota de exclusão** |

Evidência é dado pessoal com finalidade operacional: tem prazo
(`PROCURACOES_EVIDENCIA_RETENCAO_DIAS`, padrão 180 dias). Trilha de auditoria é
registro de responsabilidade: não é expurgada em operação normal.

---

## 6. Prática vedada — lista explícita

O módulo não implementa, e nenhuma contribuição futura deve implementar:

- burlar CAPTCHA ou contornar MFA;
- quebrar proteção anti-bot ou usar técnica de evasão;
- explorar vulnerabilidade, contornar autenticação;
- ocultar a automação de sistemas de segurança;
- roubar ou interceptar sessão/credencial;
- extrair chave privada de forma insegura;
- gravar senha em texto puro;
- falsificar resposta do portal;
- dar operação por concluída sem confirmação real;
- usar seletores frágeis que "adivinham" a tela;
- embutir certificado ou senha no código;
- automatizar sem deixar log.

Ao encontrar desafio de segurança, o comportamento correto — e implementado —
é parar com `MANUAL_INTERVENTION` e entregar a sessão ao operador.
