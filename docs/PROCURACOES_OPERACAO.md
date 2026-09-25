# Procurações RFB — operação, recuperação e manutenção

Guia do dia a dia: o que fazer quando algo trava, como recuperar, como atualizar
e o que entra no backup.

---

## 1. O dia típico

1. abrir **Procurações** e olhar o primeiro KPI: *sem autorização*;
2. clicar em **Processar pendências** — a fila é montada e o que já nasce
   travado (certificado ausente, vencido, ambíguo) aparece com o motivo;
3. nas estações, o Cajuru Agent pega os jobs e chama o operador;
4. acompanhar o KPI *precisa de você*: é o número que dimensiona o dia;
5. no fim, conferir *aguardando aceite* — cada um desses tem um relógio de 30
   dias correndo.

O que **não** precisa ser feito manualmente: vigiar validade, contar prazo,
descobrir qual certificado usar, lembrar de sincronizar.

---

## 2. Troubleshooting

### 2.1 A fila não anda

| Verificar | Onde | Correção |
|---|---|---|
| Existe estação online? | Procurações → Estações | iniciar o Agent na máquina |
| O Assinador está apto? | coluna "Assinador SERPRO" | `AGENT_CAJURU.md` §6 |
| A estação tem o A1 daquele CNPJ? | `cajuru-agent certificados` | importar o certificado |
| O módulo está ligado? | `PROCURACOES_ATIVO` | `true` e reiniciar worker/beat |
| Os limites estão apertados? | Configurar → Processos simultâneos | aumentar com parcimônia |

### 2.2 Job parado com código

| Código | Significado | Ação |
|---|---|---|
| `CERTIFICADO_EXPIRADO` | A1 vencido | renovar, importar, reprocessar |
| `CERTIFICADO_NAO_ENCONTRADO` | nenhuma estação tem esse A1 | importar na máquina certa |
| `CERTIFICADO_AMBIGUO` | dois A1 vigentes do mesmo CNPJ | fixar qual usar na tela da empresa |
| `ASSINADOR_NAO_INSTALADO` | diagnóstico reprovado | `AGENT_CAJURU.md` §6 |
| `PORTAL_ALTERADO` | a Receita mudou a tela | manutenção do adaptador (§5) |
| `DESAFIO_DE_SEGURANCA` | CAPTCHA/MFA/verificação | concluir no portal e registrar manualmente |
| `CONFIRMACAO_AUSENTE` | operador não informou protocolo nem texto | retomar e registrar |
| `JOB_DUPLICADO` | já havia processo ativo | usar o existente |
| `OUTORGADO_NAO_CONFIGURADO` | falta o CNPJ da contabilidade | Configurar |

Todo job tem a trilha completa no painel lateral: cada transição, com ator,
etapa, mensagem e código.

### 2.3 "O operador concluiu no portal, mas o sistema não sabe"

Acontece quando alguém resolve por fora (por exemplo, durante uma intervenção).
Caminho correto:

1. abrir o job;
2. **Registrar outorga** com o protocolo, ou **Registrar aceite** com o texto
   exibido pelo portal;
3. o sistema grava a autorização e arma/encerra o relógio.

Não existe botão "marcar como concluído" sem prova — e é proposital.

### 2.4 Números do painel parecem errados

O painel lê autorizações, não jobs. Se uma autorização foi concedida por fora e
nenhuma fonte foi sincronizada, ela não existe para o sistema. Rode
**Sincronizar** (Integra Contador, se contratado) ou importe a planilha.

---

### 2.5 Importação do Jettax trouxe menos do que a tela mostra

A tela **Procurações → Importar lista** devolve, ao fim de cada execução, o que
entrou e o que ficou de fora com o motivo de cada linha. O mesmo fica gravado em
`procuracao_integracao_jobs` / `procuracao_integracao_erros`.

| Sintoma | Causa | Conduta |
|---|---|---|
| Muitas linhas em "documento fora da carteira" | A lista do Jettax inclui outorgantes que não são clientes do escritório | Normal. Cadastre em **Empresas** só quem for cliente e reimporte |
| "Situação indeterminada" | A colagem não pegou a coluna SITUAÇÃO nem as datas | Reimporte escolhendo a aba de origem em **Situação da aba** |
| "Documento inválido" | Dígito verificador não fecha num valor sem máscara | Confira o valor no painel de origem |
| Contagem menor que a da tela | A tela é paginada | Cole uma página por vez; repetir página não duplica |
| Nada mudou (tudo "sem mudança") | Dado igual ao que já existia, ou fonte de precedência maior já tinha confirmado | Comportamento correto — veja a precedência em `PROCURACOES_INTEGRACOES.md` §5 |

A lista do Jettax é reprocessada pelo fornecedor **mensalmente, no dia 25**, e
cobre apenas os outorgantes ligados ao certificado principal. Importar todo dia
não traz novidade; o canal oficial para conferência pontual é o Integra
Contador.

---

## 3. Recuperação de falhas

### 3.1 O que se recupera sozinho

| Falha | Recuperação | Prazo |
|---|---|---|
| Estação desligada no meio | lease expira, job volta **no mesmo ponto** | `timeout_etapa_segundos` (padrão 15 min) |
| Estação revogada com job em mãos | `procuracoes_verificar_estacoes` devolve à fila | 15 min |
| Queda de rede no Agent | reconecta e reabre sessão sozinho | backoff até 5 min |
| Sessão do Agent expirada | renovada de forma transparente | imediato |
| Autorização vencida | marcada `expirada` + notificação | manutenção diária |
| Aceite não feito em 30 dias | cancelada localmente + notificação | manutenção diária |
| Certificado reinstalado | job travado volta a ser elegível | próxima triagem |

### 3.2 O que exige mão humana

- certificado vencido (renovar é ato do cliente);
- portal alterado (manutenção do adaptador);
- desafio de segurança (só uma pessoa resolve);
- dois certificados válidos do mesmo CNPJ (alguém decide qual).

### 3.3 Sequência de recuperação após incidente grave

```bash
# 1. desligar o agendamento enquanto se investiga
PROCURACOES_ATIVO=false   # reiniciar worker e beat

# 2. ver o que ficou preso
GET /procuracoes/jobs?status=intervencao_manual

# 3. devolver à fila o que estava em estações mortas
#    (a task faz isso sozinha, mas pode ser forçada)
celery -A app.worker.celery_app call procuracoes_manutencao

# 4. religar
PROCURACOES_ATIVO=true
```

Nenhum passo acima apaga trilha. Se a instrução for "limpar o histórico para
recomeçar", a resposta é não: a trilha é o que prova o que foi feito em nome do
cliente.

---

## 4. Backup e retenção

| Dado | No backup | Retenção |
|---|---|---|
| Tabelas `procuracao_*` | sim (dump do banco) | permanente |
| Trilha de eventos | sim | permanente, sem rota de exclusão |
| Evidências (imagem/HTML) | sim, cifradas | `PROCURACOES_EVIDENCIA_RETENCAO_DIAS` (180) |
| Credenciais de integração | sim, cifradas com `VAULT_MASTER_KEY` | enquanto configuradas |
| Segredo de estação | **não existe em lugar nenhum** | — só o hash Argon2id |
| Certificados A1 | **não estão no servidor** | ficam nas estações |

Consequência prática de restaurar um backup: as **estações continuam válidas**
(o hash foi restaurado junto), mas as **sessões abertas caem** — cada Agent
reabre a sua no próximo ciclo, sem intervenção.

O backup do módulo acompanha o backup geral do Cajuru28 (`docs/DEPLOY_PRODUCAO.md`).
Não há rotina separada: um banco restaurado traz o módulo inteiro consistente,
porque todo estado operacional está no banco — nada vive só em memória ou só no
Redis.

---

## 5. Manutenção do adaptador do portal

Quando aparecer `PORTAL_ALTERADO`:

1. abrir o job e ler a âncora que faltou (fica na mensagem do evento);
2. abrir a tela real no portal e comparar;
3. editar `app/procuracoes/portal.py` — o `ROTEIRO` é uma lista de
   `PassoRoteiro` com título, instrução, URL, âncoras e confirmação;
4. ajustar **texto visível** (vocabulário legal), nunca seletor CSS;
5. rodar `pytest tests/test_procuracoes_dominio.py -k portal`;
6. retomar os jobs parados.

As âncoras são frases como "Nova Autorização de Acesso", "Minhas Autorizações
de Acesso", "Validar". A comparação ignora acento e caixa. Esse vocabulário
muda em ciclo de anos; `div.css-1x2y3z` muda toda semana.

---

## 6. Atualização do módulo

### Servidor

```bash
git pull
docker compose build api worker beat frontend
docker compose up -d
```

Migrações são idempotentes (`app/db/migracoes.py`): `ALTER TABLE ADD COLUMN` e
`CREATE INDEX IF NOT EXISTS`. Tabelas novas nascem de `create_all`. Não há
Alembic — decisão anterior do projeto, mantida.

### Estações

Ver [`AGENT_CAJURU.md`](AGENT_CAJURU.md) §9. O instalador é idempotente e
preserva a credencial. Job em andamento volta para a fila sozinho.

### Ordem recomendada

1. atualizar o servidor (o contrato do Agent é retrocompatível dentro da mesma
   versão maior);
2. conferir o painel de Estações;
3. atualizar as estações uma a uma, em horário de baixa.

---

## 7. Desligar o módulo

Para manutenção prolongada do portal, ou período de apuração crítico:

```
PROCURACOES_ATIVO=false
```

Efeito: as tasks periódicas **saem do agendamento** (não ficam rodando e
retornando cedo — quem desliga não quer ver execução no log). As telas
continuam acessíveis em leitura; nada é perdido.

Para desligar só a montagem automática de fila, sem desligar o módulo:
**Configurar → Montar a fila automaticamente → desligado**. O operador continua
podendo clicar em "Processar pendências" quando quiser.

---

## 8. Checklist de produção

- [ ] `VAULT_MASTER_KEY` definida (obrigatória com o módulo ativo)
- [ ] CNPJ do outorgado configurado
- [ ] Modelo padrão revisado (vigência e serviços)
- [ ] Ao menos uma estação matriculada, online e com Assinador apto
- [ ] Certificados A1 importados nas estações certas
- [ ] Alertas de vencimento configurados (30/60/90)
- [ ] Integra Contador contratado (recomendado) ou planilha em uso
- [ ] Backup do banco verificado — inclui todo o estado do módulo
- [ ] Piloto com uma empresa concluído de ponta a ponta
      (ver [`PROCURACOES_INTEGRACOES.md`](PROCURACOES_INTEGRACOES.md) §4)
