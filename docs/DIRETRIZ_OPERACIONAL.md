# Diretriz operacional do Cajuru28 (Fluxa)

Este documento é o **norte do produto**. Qualquer funcionalidade nova deve ser
avaliada contra ele — inclusive sugestões de ferramentas externas, IA e "boas
práticas de SaaS" que não servem ao uso real do sistema.

## O que este sistema É

Um **sistema operacional fiscal privado**, utilizado prioritariamente por
**uma única pessoa** (o operador/proprietário), cujo objetivo é:

> "Eu cadastrei as empresas e configurei os certificados. Agora o sistema
> busca, organiza, valida, processa e me avisa **somente quando algo
> realmente precisa da minha atenção**."

A escala que importa não é de usuários — é de **empresas e documentos**
(1 operador → 50 → 500 → 1.000 empresas → milhões de documentos).

## O que este sistema NÃO é

- Não é SaaS comercial: sem planos, cobrança, convites de equipe, marketplace
  ou onboarding de cliente na experiência principal.
- Não é um painel administrativo genérico cheio de cards decorativos.
- A gestão de usuários existe na arquitetura (papéis, auditoria), mas **não
  ocupa a experiência principal**. Login simples e seguro para o operador.

## Princípio central

**"Como fazer para que o operador precise fazer cada vez menos?"**

Prioridade de qualquer mudança, nesta ordem:

1. automação
2. confiabilidade
3. detecção automática de problemas
4. recuperação automática
5. visibilidade operacional
6. pesquisa
7. organização
8. exportação
9. velocidade
10. segurança

Funcionalidade que não reduz trabalho manual ou não aumenta a confiança do
operador não entra.

## Regras de experiência

1. **A primeira tela responde duas perguntas:** "Está tudo funcionando?" e
   "Existe alguma coisa que eu preciso resolver?" — nesta ordem.
2. **"Precisa da sua atenção" é a lista mais importante do sistema:** poucos
   itens, priorizados por gravidade (🔴 crítico / 🟠 importante / 🟡 atenção /
   🟢 resolvido sozinho), cada um com a ação que resolve.
3. **Execuções mostram o que a máquina faz agora** — resumo primeiro, detalhe
   técnico só por clique (progressive disclosure).
4. **Nunca exigir repetição:** ações em lote em toda tela relevante; nunca
   obrigar abrir empresa por empresa, clicar "importar" N vezes ou descobrir
   sozinho por que algo falhou.
5. **Nenhuma importação inteira para por causa de um documento:** isola o que
   falhou, registra onde/por quê/quantas tentativas, e continua.
6. **Erro transitório é problema do sistema, não do operador:** retry com
   backoff, reagendamento, idempotência, retomada após restart. Só vira
   alerta o que precisa de decisão humana (ex.: certificado vencido).
7. **Certificado é ativo crítico:** o centro de certificados mostra validade,
   dias restantes, última utilização real e o último erro de autenticação —
   a senha jamais aparece.
8. **Backup é plano, não esperança:** pacote diário cifrado (banco + XMLs +
   certificados + manifesto SHA-256), cópia externa, retenção e **teste de
   restauração** com data visível na Saúde do sistema.
9. **Segurança sem exceção:** sem SECRET_KEY padrão, sem segredo em código ou
   log, cofre para senhas de certificado, endpoints protegidos.
10. **"Privado" não significa "mal feito":** domínios separados, filas
    duráveis, migrations idempotentes, testes, observabilidade — prontos para
    crescer sem sacrificar a experiência do operador.

## Pipeline da importação (o motor)

```
Fonte fiscal → Consulta → Eventos → Download → RAW → STAGING → Validação
→ Normalização → Classificação → Persistência → Índices → Regras → Alertas
→ Exportação
```

Cada etapa é observável; quando algo falha, o sistema sabe dizer **em qual
etapa** — e recupera sozinho o que for recuperável.

## Navegação de referência

```
Visão geral   Painel · Atenção · Execuções
Fiscal        Documentos · Importações · Empresas · Certificados · Fechamento
Sistema       Saúde · Configurações · Auditoria
```

Itens só entram no menu se não puderem ser agrupados em algo existente.

## Métricas de sucesso do produto

- quantidade de trabalho manual eliminado;
- quantidade de documentos processados automaticamente;
- taxa de sucesso das importações;
- tempo de recuperação de falhas;
- velocidade para localizar qualquer documento;
- problemas detectados automaticamente (antes do operador perceber);
- confiabilidade do processamento;
- clareza das informações;
- segurança dos dados.
