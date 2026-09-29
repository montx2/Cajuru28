# Auditoria e plano técnico — automação das Autorizações de Acesso RFB

Data da auditoria: 2026-09-29.

Este documento registra a investigação antes da implementação. O objetivo é
maximizar automação sem transformar o Cajuru28 em uma camada opaca que clica no
ambiente autenticado da Receita sem respaldo oficial.

---

## A. Arquitetura atual encontrada

### Frontend

- Next.js em `frontend/`.
- Tela principal de Procurações em `frontend/app/dashboard/procuracoes/`.
- Já existe painel de fila/job/intervenção (`Procuracoes.tsx`, `PainelJob.tsx`),
  importação de lista e configuração do outorgado.
- Tipos do módulo estão espelhados em `frontend/lib/types.ts`.

### Backend

- FastAPI em `backend/app/main.py`.
- Rotas humanas: `backend/app/api/routers/procuracoes.py`.
- Protocolo da estação: `backend/app/api/routers/procuracoes_agent.py`.
- Domínio puro: `backend/app/procuracoes/estados.py`.
- Roteiro/âncoras do portal: `backend/app/procuracoes/portal.py`.
- Serviços: `app/procuracoes/servicos/{fila,certificados,assinador,agentes,eventos,evidencias,sincronizacao,painel}.py`.
- Banco: 17 tabelas `procuracao_*` em `backend/app/procuracoes/modelos.py`, com
  eventos append-only, evidências cifradas e inventário de certificados sem
  material secreto.

### Agent local

- `agent/cajuru_agent/` roda na estação Windows com os A1.
- Inventaria `CurrentUser\My`/`LocalMachine\My` via PowerShell e extrai CNPJ/CPF
  por OID ICP-Brasil (`2.16.76.1.3.3`/`2.16.76.1.3.1`).
- Diagnostica Assinador SERPRO local (`https://127.0.0.1:65156`) e hosts.
- Protocolo HMAC com nonce e lease; não usa cookie.
- Fluxo operacional atual é assistido por console.

### Banco / segurança

- Não há coluna para PFX, senha de A1, chave privada, cookie ou token do portal
  no módulo de procurações.
- Credencial do Agent: Credential Manager/DPAPI na estação, Argon2id no servidor.
- Integra Contador guarda credenciais cifradas pelo cofre Fernet.
- Evidência tem hash, tamanho, caminho relativo e retenção; evento não tem rota
  de exclusão.

---

## B. Problemas e riscos encontrados

1. **Automação do portal ainda é majoritariamente assistida.** O Agent não usa
   Playwright; abre o navegador e depende de confirmação humana etapa a etapa.
2. **Seleção de certificado do navegador não era configurada.** O sistema
   escolhia corretamente o A1 no domínio, mas não gerava política do navegador
   para evitar o popup repetitivo.
3. **Human gates eram pouco granulares no Agent.** CAPTCHA/MFA/PIN caíam como
   texto genérico de desafio, dificultando métricas e reprocessamento dirigido.
4. **Diagnóstico único era limitado ao Assinador.** Faltava um `diagnose` que
   consolidasse Windows, Playwright, certificados, DNS, portal, políticas e
   Assinador.
5. **Playwright estava ausente das dependências do Agent.** Sem ele não há base
   para observabilidade DOM/trace/contextos isolados.
6. **Integração SERPRO local era verificada, mas não instrumentada por
   WebSocket.** A documentação pública do Assinador descreve WebSocket
   `/signer/`, porém o portal oficial controla o payload de assinatura; o
   Cajuru28 deve diagnosticar disponibilidade e não inventar endpoint de
   outorga/assinatura.
7. **Risco de duplicidade é bem tratado no backend, mas depende de
   reconciliação oficial.** O desenho correto é continuar usando Integra
   Contador/OBTERPROCURACAO41 como fonte pós-crash.
8. **Legal/conformidade está codificada.** `ModoOperacao.NAO_ASSISTIDO` é
   rebaixado para assistido sem autorização formal. Isso é intencional e deve
   permanecer até existir API oficial ou documento formal habilitante.

---

## C. Pesquisa técnica atualizada

### Fluxo de Autorizações de Acesso

A Receita publicou guia de usuário da nova versão: a antiga Procuração Digital
passou a **Autorizações de Acesso**, acessível pelo Portal de Serviços; a
autorização só vale depois da confirmação pela pessoa autorizada; a validação
deve ocorrer em até 30 dias ou é cancelada automaticamente.

Fluxo mapeado pelo guia:

1. Portal de Serviços → Controle de Acesso → Minhas Autorizações de Acesso.
2. Login gov.br/certificado.
3. `+ Nova Autorização`.
4. Pessoa autorizada: CPF/CNPJ + validade, máximo 5 anos.
5. Serviços: todos ou lista específica.
6. Revisão: se divergente, voltar; se correto, assinar.
7. Fica `Em Análise` até a pessoa autorizada validar.
8. Outorgado entra na aba `Recebidas`, localiza `Em Análise` e valida; passa a
   `Ativa`.

Fonte: <https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/passo-a-passo/autorizacoes-de-acesso-guia-do-usuario>

### Integra Contador / SERPRO

O catálogo do Integra Contador lista `PROCURACOES / OBTERPROCURACAO41` como
serviço de consulta em produção; também lista `AUTENTICAPROCURADOR /
ENVIOXMLASSINADO81` como apoio para token de procurador. Não foi encontrado
serviço oficial de **criação, assinatura ou validação** de Autorização de
Acesso.

Fontes:

- <https://apicenter.estaleiro.serpro.gov.br/documentacao/api-integra-contador/pt/catalogo_de_servicos/>
- <https://apicenter.estaleiro.serpro.gov.br/documentacao/api-integra-contador/pt/solucoes/integra-procuracoes/procuracoes/servicos/obter_procuracao/>

### Assinador SERPRO Desktop

A documentação pública do exemplo minimalista descreve comunicação do frontend
com o Assinador por WebSocket e API JS (`serpro-signer-client.js`,
`serpro-signer-promise.js`) com funções `sign`, `verify`, `attached`. O exemplo
de WebSocket usa `wss://127.0.0.1:65156/signer/`.

Conclusão: existe integração local, mas o payload de assinatura do portal deve
ser produzido pelo portal. O Cajuru28 pode diagnosticar e observar; não deve
fabricar assinatura fora do fluxo oficial sem contrato do serviço.

Fontes:

- <https://assinadorserpro.estaleiro.serpro.gov.br/minimalista/tutorial/index.html>
- <https://assinadorserpro.estaleiro.serpro.gov.br/minimalista/tutorial/websocket.html>

### Chrome/Edge Certificate Auto Selection

Microsoft Edge documenta `AutoSelectCertificateForUrls`: lista de strings JSON
`{"pattern":"$URL_PATTERN","filter":$FILTER}`; filtros podem incluir
`ISSUER` e `SUBJECT`; no Windows o caminho obrigatório é
`SOFTWARE\Policies\Microsoft\Edge\AutoSelectCertificateForUrls` com valores
`REG_SZ` numerados. Chrome/Chromium usam política equivalente. Isso resolve o
popup de seleção quando o servidor TLS pede certificado e há filtro único.

Fonte Edge: <https://learn.microsoft.com/en-us/deployedge/microsoft-edge-policies/autoselectcertificateforurls>

### Playwright

Playwright 1.46+ suporta `clientCertificates` por contexto, com `pfxPath` ou
cert/key e `origin` exato. Isso é útil para ambientes próprios/testes mTLS. Para
o portal RFB em estação Windows, o caminho preferencial continua sendo o store
do sistema + navegador real (Edge/Chrome) + política corporativa, porque o A1 já
está instalado no Windows e o Assinador/gov.br esperam o ambiente do usuário.

Fonte: <https://playwright.dev/docs/api/class-testoptions#test-options-client-certificates>

### Regra normativa

Notícia oficial da Receita sobre a IN RFB nº 2.320/2026 informa que a norma veda
sistemas automatizados ou intermediários não autorizados e prevê interrupção de
acesso/bloqueio/cancelamento se identificados. Fontes especializadas detalham o
art. 13 como vedação a aplicativo, webview, iframe, camada de intermediação ou
sistema próprio que, por automação/encapsulamento do ambiente da RFB, possibilite
outorga, alteração ou revogação.

Fontes:

- <https://www.gov.br/receitafederal/pt-br/assuntos/noticias/2026/abril/receita-federal-atualiza-regras-para-acesso-a-servicos-digitais>
- <https://www.contabeis.com.br/noticias/76072/receita-endurece-regras-de-acesso-digital-com-nova-in/>

---

## D. Gargalos e oportunidades de automação

| Etapa | Automatizável? | Mecanismo | Limitação | Fallback |
|---|---:|---|---|---|
| Importar/listar clientes | Sim | API interna/importação | dados ruins | pendência de cadastro |
| Descobrir certificados | Sim | Windows Store/PowerShell | PFX não instalado | importar localmente |
| Associar A1 ao cliente | Sim | OID ICP-Brasil + thumbprint | ambiguidade | escolher thumbprint explicitamente |
| Selecionar certificado no navegador | Sim | `AutoSelectCertificateForUrls` | filtro não único/sem GPO | operador seleciona e gera diagnóstico |
| Login gov.br/certificado | Parcial | navegador real + política de cert + DOM observation | CAPTCHA/MFA/PIN | human gate |
| Verificar identidade autenticada | Sim, quando DOM expõe identidade | locators/texto acessível | portal muda ou oculta | parar `PORTAL_UI_CHANGED` |
| Buscar autorização existente | Sim por API oficial quando contratada; DOM assistido no portal | Integra Contador / roteiro | API não cria | reconciliação pós-ato |
| Preencher nova autorização | Tecnicamente viável com Playwright, mas bloqueado por conformidade sem autorização formal | locators/roles | art. 13 / canal não oficial | assistido; ponto de extensão documentado |
| Serviços e validade | Sim fora do portal; conferência antes de assinatura | `EXPECTED_AUTHORIZATION` | DOM do portal pode mudar | STOP + evidência |
| Assinatura | Parcial | Assinador SERPRO diagnosticado; portal aciona | payload/assinatura pertencem ao portal | human gate/local signer |
| Validação como outorgado | Tecnicamente viável com Playwright, mas bloqueado por conformidade sem autorização formal | locators/roles | art. 13 / canal não oficial | assistido; API oficial para reconciliar |
| Reconciliation | Sim | Integra Contador `OBTERPROCURACAO41` + estado local | contrato SERPRO necessário | importação de lista/portal assistido |

---

## E. Arquitetura proposta e alterações implementadas agora

### Implementado nesta revisão

1. **Política automática de certificado**
   - Novo `agent/cajuru_agent/politicas_navegador.py`.
   - Comando `cajuru-agent politica-certificado`.
   - Gera/aplica regras `AutoSelectCertificateForUrls` para Edge/Chrome/Chromium
     no HKCU, por certificado exato.

2. **Pré-flight completo**
   - Novo comando `cajuru-agent diagnose`.
   - Verifica Windows, Python, Playwright, certificados, DNS, Portal, Assinador,
     hosts e políticas de navegador.

3. **Human gates classificados**
   - Novo `agent/cajuru_agent/human_gate.py`.
   - `CAPTCHA_REQUIRED`, `TWO_FACTOR_REQUIRED`, `PIN_REQUIRED`,
     `CERTIFICATE_SELECTION_REQUIRED`, `MANUAL_REVIEW`.
   - O executor do Agent envia código específico ao backend e preserva estado.

4. **Taxonomia backend ampliada**
   - Códigos canônicos adicionais em `CodigoErro` com regras de retry/falha
     fechada: `CAPTCHA_REQUIRED`, `TWO_FACTOR_REQUIRED`, `PIN_REQUIRED`,
     `PORTAL_UI_CHANGED`, `SESSION_EXPIRED`, `AUTHORIZATION_EXISTS`, etc.

5. **Base Playwright determinística**
   - Novo `agent/cajuru_agent/browser_automation.py`.
   - Contexto persistente isolado por job/identidade, trace, screenshots, HTML
     redigido, verificação de âncoras por texto e detecção de human gates.
   - Sem coordenadas, sem imagem, sem IA, sem CAPTCHA solver.

6. **Instalador atualizado**
   - Instala dependência Playwright e tenta baixar Chromium.
   - Roda `cajuru-agent diagnose` no final.

7. **Testes novos**
   - Políticas de navegador e classificação de human gates.
   - Taxonomia backend para human gates e aliases canônicos.

### Próximos passos recomendados

1. Rodar em uma estação Windows real com 2–3 A1 de teste e confirmar
   `edge://policy`/`chrome://policy`.
2. Capturar DOM/trace do fluxo real, com dados fictícios quando possível, para
   mapear seletores estáveis **sem praticar ato jurídico em produção**.
3. Contratar/configurar Integra Contador e usar `OBTERPROCURACAO41` como
   reconciliação pós-crash.
4. Se houver autorização formal/API oficial de outorga no futuro, implementar um
   `AuthorizationProvider` não assistido atrás de `avaliar_modo()` e do flag
   documental já existente.
