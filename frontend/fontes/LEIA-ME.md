# Fontes self-hosted

Inter Variable (UI) e JetBrains Mono Variable (números, chaves, XML) em `.woff2`,
subsetting `latin`, servidas pelo próprio Next via `next/font/local`.

Por que estão no repositório em vez de `next/font/google`:

- O build precisa ser **hermético**. `next/font/google` baixa a fonte na hora do
  `next build`; num build Docker sem saída de internet isso quebra a imagem.
- `@import` de fonte no CSS é proibido no projeto (bloqueia o primeiro render).

Arquivos:

| Arquivo | Eixos | Uso |
|---|---|---|
| `inter-latin-wght-normal.woff2` | `wght 100–900` | toda a interface (só 400/500/600 são usados) |
| `jetbrains-mono-latin-wght-normal.woff2` | `wght 100–800` | CNPJ, chave de acesso, NSU, IDs, XML |

Ambas são SIL Open Font License 1.1 — veja `LICENCA.txt`.
