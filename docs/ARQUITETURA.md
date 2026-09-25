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
                                  |
                                  +-> Cajuru Agent (HMAC) -> estação Windows
                                        certificados A1 + Assinador SERPRO
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

O módulo **Procurações RFB** acrescenta um quarto participante que não roda em
container: o **Cajuru Agent**, instalado na máquina Windows do escritório onde
estão os certificados A1 e o Assinador Digital SERPRO. Ele não recebe chave
privada nem senha — o servidor emite uma ordem de trabalho com identificadores,
e a assinatura acontece no ambiente oficial da Receita, conduzida por uma
pessoa. A razão dessa divisão está em [`PROCURACOES_CONFORMIDADE.md`](PROCURACOES_CONFORMIDADE.md);
o desenho completo, em [`PROCURACOES_RFB.md`](PROCURACOES_RFB.md).

Os certificados, XMLs e pacotes de backup ficam em volumes persistentes
compartilhados apenas pelos processos que precisam deles. O backend nunca grava
a senha do certificado em texto puro; ela e o PFX são protegidos pelo cofre
Fernet. Cada pacote de backup é cifrado com uma chave Fernet **separada** e
replicado para storage S3 configurado em produção.

A captura é feita exclusivamente contra as fontes oficiais (ADN para NFS-e e a
Distribuição DFe da SEFAZ para NF-e/CT-e), com mTLS pelo certificado da própria
empresa. Não há intermediário de terceiros no caminho do documento fiscal.

Para NF-e que chega apenas como **resumo** (`resNFe`), o XML completo só é
liberado após a Ciência da Operação (evento 210210). Isso é feito pelo worker,
mas apenas para empresas que ativaram a opção — a Ciência é irreversível e faz
correr o prazo da manifestação conclusiva.

## Operação

A API, workers e agenda usam a mesma imagem do backend. Escale workers conforme
a quantidade de empresas, mantendo apenas uma instância de `beat` para evitar
disparos duplicados.
