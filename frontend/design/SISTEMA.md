# Papel & Grafite

Sistema visual do NotasFlow. Seus três critérios são **silencioso, preciso e confiável**. A interface é um instrumento de operação contínua: hierarquia vem de espaço, peso e alinhamento; cor existe apenas para indicar ação ou estado.

## Cor

Todos os valores vivem em `app/globals.css` e chegam aos componentes por nomes semânticos no Tailwind.

| Papel | Claro | Escuro | Uso |
|---|---:|---:|---|
| Fundo | `#F7F8F7` | `#0F1513` | canvas |
| Fundo afundado | `#EFF1F0` | `#151C1A` | cabeçalhos e recessos |
| Superfície | `#FFFFFF` | `#1B2422` | tabelas e cartões |
| Tinta forte | `#12181A` | `#F3F6F5` | título e número-chave |
| Tinta | `#2B3437` | `#E8EDEB` | corpo |
| Tinta suave | `#5C6B6F` | `#A9B6B2` | metadado |
| Traço forte | `#AAB7B3` | `#64736E` | inputs e controles |
| Acento | `#0F6B50` | `#3FBF90` | ação primária |
| OK | `#17734F` | `#65C99E` | operação confirmada |
| Espera | `#79550D` | `#E1B958` | janela oficial/cota |
| Erro | `#A8342A` | `#F18A80` | falha que exige ação |
| Informação | `#1F5FAE` | `#85B6F3` | contexto não operacional |

### Contraste calculado (tema claro)

| Par | Razão aproximada | Resultado |
|---|---:|---|
| tinta forte / superfície | 17.9:1 | AA/AAA |
| tinta / superfície | 12.8:1 | AA/AAA |
| tinta suave / superfície | 5.5:1 | AA |
| branco / acento | 6.6:1 | AA |
| erro / superfície | 6.8:1 | AA |
| espera / superfície | 7.0:1 | AA |
| info / superfície | 6.4:1 | AA |

`--tinta-fraca` é reservado a placeholder e elementos desabilitados. Estados usam ícone, palavra e cor. `aguardando`, cStat 656 e cota são sempre **espera**, nunca erro.

## Tipografia e números

Inter (com fallback de sistema métrico compatível) é a família de UI; JetBrains Mono/IBM Plex Mono é usada em CNPJ, chave, NSU e XML. Escala: 11/16, 12/18, 13/20, 14/22, 16/24, 20/28, 26/32 e 34/40. Nenhum texto útil fica abaixo de 12 px. Pesos permitidos: 400, 500 e 600. Células e indicadores usam números tabulares; valores numéricos ficam à direita.

## Forma, espaço e elevação

Espaço segue múltiplos de 4 px. Raios: 4 px para badge, 6 px para controle, 8 px para card e 12 px para camada. Conteúdo limita-se a 1440 px; formulários a 560 px. Nível 0 é borda sem sombra, nível 1 atende menu/toast e nível 2 atende modal/drawer. Card não sobe no hover.

## Movimento

120 ms para microinteração, 180 ms para popover e 240 ms para modal/drawer; easing `cubic-bezier(.2,0,0,1)`. Só opacidade e transformação são animadas. O único movimento contínuo é o pulso de execução. Com redução de movimento tudo passa a 1 ms.

## Componentes: faça / não faça

| Componente | Faça | Não faça |
|---|---|---|
| Botão | uma primária por tela; verbo específico | duas ações verdes concorrentes |
| Campo | label real, descrição e erro junto | placeholder como label |
| Tabela | caption, th/scope, 40–44 px, números à direita | cards para centenas de registros |
| Estado | ícone + texto + tom | depender só de cor |
| Alerta | explicar impacto e oferecer resolução | mostrar retry de janela SEFAZ |
| Modal | prender/devolver foco; cancelar inicialmente | confirmação nativa do navegador |
| Vazio | instrução curta e próxima ação | ilustração genérica |
| Skeleton | reproduzir colunas e linhas reais | trocar conteúdo durante refetch |
| Tooltip | complemento curto, sem ação | esconder informação necessária |
| Gráfico | SVG acessível que muda uma decisão | gráfico decorativo no Painel |

## Acessibilidade e operação

Há link para pular conteúdo; foco combina traço de 2 px e halo; controles isolados têm alvo de 40 px; tabelas podem rolar em container próprio. Modais fecham com Esc, prendem foco e o devolvem. A navegação oferece `Ctrl/⌘K`, `?`, `g` seguido de uma letra e Esc. `prefers-contrast` reforça bordas e `prefers-reduced-motion` remove movimento.
