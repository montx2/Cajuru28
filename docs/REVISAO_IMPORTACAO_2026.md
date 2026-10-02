# Revisão da importação fiscal — 02/10/2026

## Escopo e limite da verificação

Revisão do código de captura NFS-e/ADN, NF-e/SEFAZ e CT-e/SEFAZ, orquestração Celery, estado dos cursores, importação XML/ZIP e indicação de completude na interface e no fechamento.

Os testes usam bancos isolados, certificados fictícios e respostas fiscais simuladas. Não foi acessado o servidor de produção, nem foi efetuada consulta com certificado real. Portanto, os defeitos abaixo foram comprovados no código/testes, mas não é possível afirmar qual deles afetou uma execução específica do escritório sem seu histórico/log.

## Problemas corrigidos

| Área | Defeito | Correção |
|---|---|---|
| Paginação ADN | Página com menos de 50 itens encerrava a captura mesmo com `maxNSU` maior. | `maxNSU` tem prioridade; sem máximo conhecido, continua enquanto houver itens/progresso até resposta sem novidade. |
| Resposta inesperada | JSON sem lote podia parecer uma distribuição vazia bem-sucedida. | Registra erro de leitura e preserva a resposta; não inventa confirmação de acervo vazio. |
| Competência | `AAAA-MM` acessava a posição 7 de uma string de sete caracteres e falhava. | Normaliza o mês sem `IndexError`. |
| NFS-e inválida | XML malformado podia resultar em nota vazia, com emissão arbitrária. | Não cria esse documento; informa falha e conserva o lote para diagnóstico/reprocessamento. |
| Checkpoint | Itens ilegíveis eram ignorados e o cursor avançava sem conservar a entrega. | Resposta de lote preservada antes do processamento; só é removida depois do commit completo e sem falhas. |
| Completude | Cursor no máximo podia mostrar “em dia” e liberar fechamento mesmo com itens não lidos. | `lotes_pendentes` impede a confirmação; interface mostra “Importação parcial”. |
| Retomada | Checkpoint antigo de uma execução podia sobrepor o cursor global mais recente. | O cursor compartilhado é autoritativo, inclusive após realinhamento ou rebobinamento explicitamente autorizado. |
| Concorrência | Redelivery com lease ocupado marcava a execução como concluída sem importar. | Não altera o resultado do worker proprietário; programa reforço sem duplicar a consulta. |
| Lease e quedas | Lease de 25 min era menor que o limite da task; worker morto deixava execução bloqueando a fila. | Prazo acima do hard timeout, renovação por lote e retomada conservadora de execuções sem lease/worker ativo. |
| Fila automática | Empresas sem A1 ou em cooldown consumiam todos os slots antes das elegíveis. | O teto conta empresas efetivamente enfileiradas; configurações inválidas de um cliente não abortam o escritório. |
| Certificados | A1 ativo, porém vencido, passava pelo pré-voo. | Falha local antes de gastar consulta oficial. Replay local não depende de A1. |
| XML completo | XML integral de uma nota em resumo era descartado como duplicata. | Promove o registro existente, sem criar outra nota e sem apagar cancelamento. |
| Total de CT-e | O grupo `vPrest/vTPrest` não era lido; importação podia registrar valor zero. | Extrai o valor desse grupo e mantém compatibilidade com alternativas legadas. |
| Identidade | Conversores removiam letras de chaves de acesso. | Preserva a identidade completa do XML, sem reduzir uma chave alfanumérica a seus dígitos. |
| ZIP | Entradas com o mesmo nome eram lidas pelo nome e repetiam o último XML. | Lê cada `ZipInfo` individualmente. |
| Limites | Tamanho era conferido depois da descompactação. | Limita quantidade, tamanho individual, total descompactado e bytes do pedido antes de processar notas. |
| Lote manual | Falha de um XML podia desfazer outros válidos. | Savepoint por item e erro individual; insert idempotente compartilhado com o worker. |
| Empresa do XML | Nota entre dois clientes cadastrados aparecia só em um deles. | Registra o lado tomado/prestado por empresa, com isolamento do escritório e deduplicação por empresa/chave. |

## Como funciona a recuperação

- Checkpoints ficam em `DADOS_DIR/xml/.lotes_pendentes/<empresa>/<tipo>/`. Esse caminho pertence ao volume `xml_saida` já compartilhado pela API e pelo worker no Compose de produção; não exige criar volume novo.
- Arquivos são gravados atomicamente, com permissão `0600`, identidade do escritório/empresa/tipo/ambiente e resposta integral do lote. Não contêm senha ou chave privada do A1, mas contêm dados fiscais: devem receber a mesma proteção dos XMLs.
- Se a leitura, escrita ou transação falhar, a resposta continua no volume. Os documentos válidos já confirmados permanecem no acervo.
- A próxima execução pode reprocessar a resposta localmente, sem pedir o mesmo NSU novamente. Parser ainda incompatível ou payload efetivamente corrompido continua visível como pendência; preservar não significa que seja possível reparar bytes corrompidos automaticamente.
- Com janela fechada ou sem A1, a fila pode criar execução `reprocessamento`, exclusivamente local. Tentativas automáticas locais com falha têm espera de uma hora; tentativas manuais continuam disponíveis.
- Quando a janela oficial abrir e houver A1 válido, uma pendência antiga não impede a captura de notas novas. As notas novas são guardadas e a falha antiga permanece sinalizada.
- Exclusão de empresa e limpeza geral autorizadas removem seus checkpoints. A árvore entra no backup já existente dos objetos XML. O replay valida escritório, empresa, CNPJ e ambiente; não mistura produção e homologação.

## O que foi preservado

- Nada de rebobinar cursor, forçar consultas ou manifestar Ciência da Operação automaticamente para “resolver” falta de notas.
- Regras de janela/cota, confirmação explícita de ações legais, sessão HttpOnly e isolamento por escritório.
- Tudo que a distribuição entregar continua sendo armazenado, mesmo fora do período pedido. O período é relatório/filtro de exibição, não descarte de documentos.
- Notas já descartadas por versões antigas não são recriadas por adivinhação. Sem XML/entrega original, a recuperação depende do que a origem ainda disponibiliza ou de XML válido obtido pelo escritório.
- O serviço oficial distribui por NSU e interesse do contribuinte, não uma busca arbitrária por data. Uma nota ausente pode exigir conferir período, empresa, tipo, origem ou as condições de liberação do XML; cursor atualizado não é prova de todas as notas emitidas no mundo.

## Validação executada

- Baseline do backend: **415 passaram**, um teste opcional de assinatura XML independente pulado.
- Depois das correções: **446 testes backend passaram**, um teste opcional pulado; **107 testes frontend passaram**.
- `python -m compileall`, `npm run typecheck`, `npm run build` e `git diff --check` passaram.
- Novas regressões cobrem paginação curta/sem máximo, replay sem HTTP/A1, falha de disco, cursor global, redelivery, lease/worker parado, justiça da fila, XML/ZIP, valores de CT-e, isolamento, exclusões e sinalização de importação parcial.

## Conferência após implantar a versão

1. Reinicie/recrie **API, worker, beat e frontend** com a versão atualizada. Recarregar só o navegador não atualiza o importador Celery.
2. Na prévia de Importações, confira empresa, tipos, validade do A1 e situação da janela. Execute apenas as empresas necessárias, sem marcar “forçar” como rotina.
3. Acompanhe a execução pelo ID e pelos contadores. `enfileirada` não significa `concluída`; `concluída` de replay local não significa que uma nova chamada à origem foi feita.
4. Compare cursor e máximo, mas confira também `lotes_pendentes`, mensagem de erro e quantidade de documentos dentro/fora do período.
5. Em Documentos, ajuste o período/tipo/empresa e verifique se há notas em resumo. Não ative manifestação automática sem autorização do responsável.
6. Se ainda faltar uma nota, reúna o **ID da execução, empresa/tipo, horário e mensagem/cStat**. Isso permite distinguir erro de captura, worker/beat indisponível, espera oficial e documento não disponibilizado pela origem. Não envie senha do certificado, arquivo A1 ou segredo de produção no chat.
