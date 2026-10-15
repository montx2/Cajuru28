# Jettax Morfeu 360 — configurar e testar NFS-e

## O que está pronto

- Token puro em `Authorization`, host fixo `https://morfeu.jettax360.com.br`.
- Token por escritório, cifrado no mesmo cofre Fernet usado pela Acessórias.
- Importação por empresa e competência, emitidas e recebidas, sem criar ou
  alterar clientes no Jettax. Até 30 empresas por pedido.
- Paginação por `page` e `meta.pagination`, sem presumir `limit`.
- Download imediato do XML, pipeline existente, proveniência `jettax`,
  duplicatas reconhecidas e cancelamento informado pela listagem aplicado.
- Celery, tarefa por empresa, intervalo compartilhado por escritório e
  acompanhamento em Configurações → Integrações → Jettax Morfeu 360.
- Empresa ausente no Jettax é ignorada com mensagem, sem derrubar outras.

**Não foi feita importação real com seu token neste ambiente.** A validação
local usa HTTP simulado e banco SQLite de testes. O diagnóstico executado por
você confirmou autenticação, nomes/tipos das respostas e três XMLs nacionais;
isso não substitui o primeiro teste operacional na sua instalação PostgreSQL.

## 1. Aplicar a atualização

Estas alterações estão na branch da sessão, não foram publicadas na `main`.
Primeiro aplique/integre a versão revisada ao seu checkout. Não basta executar
`git pull` da `main` enquanto ela não contiver estas alterações.

Antes de atualizar, faça um backup pela tela Saúde e guarde a versão anterior.
Na pasta que contém `docker-compose.yml`, para a instalação **local**:

```sh
docker compose up -d --build api worker beat frontend
docker compose restart api worker
docker compose ps
```

A reconstrução do frontend é necessária: somente reiniciar não recompila o
botão novo. Não use `docker compose down -v` e não apague volumes.
As duas tabelas novas são criadas automaticamente quando a API inicia.

Para produção, use a pilha de produção já configurada, não a pilha local:

```sh
docker compose -f docker-compose.production.yml --env-file deploy/production.proxy.env up -d --build api worker beat frontend
docker compose -f docker-compose.production.yml --env-file deploy/production.proxy.env restart api worker
```

## 2. Configurar o token

1. Entre como administrador.
2. Abra **Configurações → Integrações → Jettax Morfeu 360**.
3. Cole o token no campo **Token Jettax** e clique **Salvar token Jettax**.
4. O servidor faz um GET autenticado antes de cifrar e salvar.
5. Clique **Testar conexão Jettax**.

Não coloque token no Git, na conversa ou em prints. O campo é limpo depois
de tentar salvar. O valor antigo nunca volta para o navegador. Não é preciso
colocar o token no `.env`; o token de produção fica cifrado no banco.

O `VAULT_MASTER_KEY` existente precisa ser o mesmo na API e no worker.
**Não gere outra chave para esta integração**, pois isso pode tornar os
segredos antigos inacessíveis. Preserve a chave e seu backup seguro.

Configurações opcionais em `backend/.env` (padrões em `backend/.env.example`):

```env
JETTAX_BASE_URL=https://morfeu.jettax360.com.br
JETTAX_TIMEOUT_SEGUNDOS=30
JETTAX_INTERVALO_SEGUNDOS=2
JETTAX_MAX_PAGINAS=500
```

A URL não pode ser trocada por outro host. O worker mantém intervalo mínimo
local de 0,5 segundo mesmo se configurado abaixo disso. A cota do fornecedor
não foi documentada; não há promessa de que um intervalo específico evitará
429. Se ocorrer, a execução para e o escritório fica em pausa por uma hora.

## 3. Primeiro teste operacional

1. Selecione **uma empresa**, a mesma do diagnóstico com notas.
2. Informe a mesma competência, por exemplo `08/2026`.
3. Clique **Importar do Jettax**.
4. Acompanhe a execução logo abaixo; a tela atualiza a cada cinco segundos
   enquanto há pedidos na fila ou em andamento.
5. Confira a nota no acervo de documentos. Baixe um XML e confira empresa,
   chave, competência, emissão e valor antes de usar em fechamento fiscal.
6. Após terminar, repita a mesma importação. A segunda deve registrar
   duplicatas, não novas cópias das mesmas notas na mesma empresa.
7. Só depois faça o pedido para todas as empresas ativas (até 30 por pedido).

Não é necessário certificado local para esta importação. O cliente precisa
estar cadastrado e configurado no Jettax; as empresas locais são relacionadas
pelo CNPJ, nunca pela posição em uma lista ou por nome.

### Entender os resultados

- **Recebidos:** arquivos listados/processados nesta consulta.
- **Importados:** cópias novas/completadas no acervo por empresa.
- **Duplicados:** cópias que já existiam naquela empresa.
- **Cancelados:** cópias cujo status foi atualizado para cancelada.
- **Erros:** XML, link ou gravação que não puderam ser processados; os motivos
  seguros aparecem na execução. Nenhum link ou XML aparece na mensagem.
- **Sem empresa correspondente:** a empresa consultada não foi identificada
  como parte do XML. Não se grava em empresa presumida.
- **Ignorada:** empresa não localizada no Jettax.
- **Parcial:** há erro, casamento pendente ou a consulta não chegou a um fim
  verificável. Não trate como competência concluída.

Se prestador e tomador forem empresas cadastradas do mesmo escritório, ambas
recebem uma cópia e as contagens podem superar o número de arquivos recebidos.
Nenhuma cópia é gravada em escritório diferente.

As notas já gravadas ficam preservadas mesmo se a execução posterior falhar.
Links expirados exigem um novo pedido para obter links novos. Em caso de
limite, aguarde; não clique repetidamente para tentar contornar a pausa.

Se o worker cair abruptamente, uma execução pode ficar em andamento. Após o
limite da tarefa mais dez minutos (40 minutos no padrão atual), um novo pedido
pode substituir a execução antiga. A trava por escritório impede execução
paralela e a idempotência protege documentos já gravados.

## Limitações desta etapa

- Apenas NFS-e. **NFe, CT-e e fallback SEFAZ não foram ativados.**
- Não modifica as configurações atuais de captura oficial. Se o Jettax já
  captura NFe/CT-e com o A1, não mantenha o NotasFlow consultando os mesmos
  documentos em paralelo: risco de cStat 656 e bloqueio por cerca de uma hora.
- Não foi criado agendamento incremental Beat Jettax; primeiro valide o fluxo
  manual. O agendamento oficial existente permanece como estava.
- TXT e XMLs sem campos que o conversor existente reconheça ficam com erro,
  nunca são transformados em notas com chave, data ou empresa inventadas.
- PDF vazio não impede nada. Nenhum PDF é baixado nesta fase.
- A Jettax pode demorar até 48 horas para disponibilizar NFS-e. Notas anteriores
  à configuração/competência inicial podem não existir na base do fornecedor.
- Consulta concluída não prova captura completa na origem. Não há promessa de
  recuperação de todo histórico ou ausência absoluta de notas faltantes.
- `limit=1` não funcionou no diagnóstico real. `page` foi refletido pela API;
  a navegação com várias páginas preenchidas é coberta por testes simulados e
  deve ser acompanhada no primeiro lote real que ultrapasse uma página.
- Novos formatos ou mudanças de metadados geram erro/parcial explícito, não
  adaptação silenciosa por tentativa de nomes alternativos.

## Testes para desenvolvedores

Com ambiente Python e dependências de desenvolvimento instaladas:

```sh
cd backend
pytest -q
```

A dependência opcional `xmlsec` pode exigir bibliotecas do sistema. A suíte
funciona sem ela, com o teste de assinatura correspondente marcado como skip.
Os testes novos usam `httpx.MockTransport`, banco SQLite isolado e Redis/fila
simulados: não usam o seu token nem fazem consultas reais à Jettax.

Frontend:

```sh
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

## Rotas locais

Todas exigem login e usam o escritório da sessão, não um tenant no corpo:

| Método | Rota | Permissão |
|---|---|---|
| GET | `/integracoes/jettax` | leitura |
| PUT | `/integracoes/jettax/credencial` | admin |
| DELETE | `/integracoes/jettax/credencial` | admin |
| POST | `/integracoes/jettax/testar` | admin |
| POST | `/integracoes/jettax/importar` | operador/admin |
| GET | `/integracoes/jettax/execucoes` | leitura |

O PUT recebe `{"token": "..."}`. O POST de importação recebe
`{"empresa_ids": [1, 2], "competencia": "08/2026"}` e retorna 202 com um
resultado de fila por empresa. Os IDs acima são apenas exemplos do contrato;
use os IDs reais da sua instalação. Nenhum POST/PUT/DELETE é feito na API Jettax.

## Como desligar ou desfazer

- Para desligar: aguarde tarefas em andamento terminarem e clique **Remover
  token Jettax**. Não apaga notas; tarefas pendentes sem credencial falham com
  mensagem clara. Uma tarefa já iniciada pode continuar com seu token em memória.
- Para voltar o código: aguarde a fila terminar, aplique a versão anterior
  que você guardou e reconstrua/reinicie os serviços com os comandos acima.
- Não apague tabelas/volumes para desfazer. As tabelas adicionais podem ficar
  no banco; notas e proveniência já importadas devem ser preservadas.

## Arquivos desta entrega

Criados:
- `backend/app/services/jettax.py`: cliente, paginação e downloads seguros.
- `backend/app/services/importadores/jettax_nfse.py`: pipeline e contagens.
- `backend/app/api/routers/jettax.py`: credencial, fila e acompanhamento.
- `backend/app/worker/jettax.py`: tarefa por empresa e trava por escritório.
- `frontend/app/dashboard/configuracoes/JettaxIntegracao.tsx`: interface.
- `backend/tests/test_jettax.py`, `test_jettax_importacao.py`,
  `test_jettax_worker.py`, `test_diagnostico_jettax.py`: testes.
- `frontend/testes/jettax-integracao.test.tsx`: testes de interface.
- `diagnostico_jettax.py`, `docs/DIAGNOSTICO_JETTAX.md`, `docs/JETTAX.md`.

Alterados:
- `backend/app/models.py`: credenciais e execuções Jettax.
- `backend/app/core/config.py`, `backend/.env.example`: configurações sem token.
- `backend/app/main.py`, `backend/app/worker/celery_app.py`: registro de rota/task.
- `backend/app/services/importadores/xml_manual.py`: origem parametrizada,
  mantendo o padrão dos uploads antigos.
- `backend/app/api/routers/empresas.py`, `sistema.py`: exclusão/reset respeitam
  o histórico/tarefas Jettax e removem credencial quando solicitado. Corrigida
  referência antiga a `xml_path` em proveniência (os arquivos estão na nota).
- `frontend/app/dashboard/configuracoes/Configuracoes.tsx`,
  `frontend/lib/api.ts`, `frontend/lib/types.ts`: integração da interface.
- `.gitignore`, `README.md`, `docs/ARQUITETURA.md`.

Removido: `openapi.yaml`, conforme solicitado, após leitura do contrato.

### Validação executada nesta entrega

- Backend completo: **513 passaram, 1 ignorado** (assinatura com dependência opcional).
- Frontend completo: **244 passaram**, em 37 arquivos.
- `npm run typecheck`: passou.
- `npm run build`: passou.
- Nenhuma consulta à API real foi feita nesses testes.
