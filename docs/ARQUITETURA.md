# Arquitetura

O Fluxa é executado por Docker Compose. O arquivo padrão é o ambiente
local de desenvolvimento; dados fiscais reais usam a pilha isolada de
[`DEPLOY_PRODUCAO.md`](DEPLOY_PRODUCAO.md).

```text
Navegador -> Frontend Next.js -> API FastAPI -> PostgreSQL
                                  |
                                  +-> Redis -> Celery workers
                                             Celery Beat
                                  |
                                  +-> ADN / SEFAZ (mTLS)
```

## Serviços

| Serviço | Responsabilidade |
|---|---|
| `frontend` | Interface web |
| `api` | Autenticação, cadastro, consultas e comandos |
| `worker` | Importações fiscais assíncronas |
| `beat` | Sincronismo e retomadas agendadas |
| `db` | Persistência PostgreSQL |
| `redis` | Broker e resultados da fila |

Os certificados, XMLs e pacotes de backup ficam em volumes persistentes
compartilhados apenas pelos processos que precisam deles. O backend nunca grava
a senha do certificado em texto puro; ela e o PFX são protegidos pelo cofre
Fernet. Cada pacote de backup é cifrado com uma chave Fernet **separada** e
replicado para storage S3 configurado em produção.

A inicialização não remove tabelas ou registros que não fazem parte do schema
carregado pela versão atual. A limpeza geral também para antes de excluir
empresas se encontrar referências em tabelas legadas; qualquer tratamento
desses dados exige um procedimento separado.

A captura é feita exclusivamente contra as fontes oficiais (ADN para NFS-e e a
Distribuição DFe da SEFAZ para NF-e/CT-e), com mTLS pelo certificado da própria
empresa. Não há intermediário de terceiros no caminho do documento fiscal.

Para NF-e que chega apenas como **resumo** (`resNFe`), o XML completo só é
liberado após a Ciência da Operação (evento 210210) — a consulta por chave
obedece à mesma regra, então não há atalho sem o evento. O worker registra a
Ciência e busca o `procNFe` sozinho; a chave `manifestar_automaticamente` da
empresa (ligada por padrão) permite desligar isso, porque a Ciência é
irreversível e faz correr o prazo da manifestação conclusiva. Nota que passou
dos 10 dias não aceita mais a Ciência (cStat 596): aí a saída é a manifestação
conclusiva, escolhida pelo operador na ficha da nota.

## Interface: hierarquia de ação

O desenho de ação do frontend sai de **um** módulo, `frontend/lib/acoes-documento.ts`.
Nenhuma tela decide sozinha qual botão é o principal — foi justamente isso que
levou a ficha lateral a empilhar três cartões de aviso e seis botões na mesma
coluna, com a mesma ação escrita de dois jeitos ("Tentar buscar XML completo na
SEFAZ" num cartão, "Buscar XML completo na SEFAZ agora" no outro) e aparecendo
duas vezes na tela de uma nota com erro e mais de 12 dias.

As regras que o módulo aplica:

1. **uma ação primária por documento**, decidida pelo estado dele: resumo sem
   manifestação → *Buscar XML completo*; `cStat 596` ou Ciência vencida →
   *Manifestar operação*; completo → *Baixar XML*;
2. **no máximo duas secundárias** ao lado; o resto vai para o menu `⋯`
   (`MenuSuspenso`);
3. **excluir nunca fica ao lado do botão principal** — destrutiva e rara, mora
   no `⋯` (na ficha, na barra de seleção do acervo e no `⋯` da empresa);
4. **um rótulo só por ação**: `ROTULO_ACAO` (singular) e `ROTULO_ACAO_LOTE`
   (lote) são a forma definitiva, usada na ficha, na lista, nos alertas, na
   paleta de comandos e nos diálogos;
5. **nada é desabilitado em silêncio** — toda ação indisponível carrega
   `motivo`, que vai no `title`/`aria-disabled`;
6. **um bloco de situação por documento**, com um parágrafo por fato. 596 +
   resumo + cancelamento são fatos do mesmo problema, não três cartões. O bloco
   cita o rótulo da ação, mas não repete o botão: a ação mora em um lugar só.

`frontend/testes/hierarquia-acoes-documento.test.tsx` trava as regras 1–5
(lógica pura + a ficha renderizada) e faz uma varredura de fonte que falha se um
rótulo antigo da mesma ação voltar em qualquer tela.

## Operação

A API, workers e agenda usam a mesma imagem do backend. Escale workers conforme
a quantidade de empresas, mantendo apenas uma instância de `beat` para evitar
disparos duplicados.
