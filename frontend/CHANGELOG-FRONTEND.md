# Changelog do front-end

## Papel & Grafite

- Substituída a linguagem visual promocional por tokens semânticos claros e escuros, pesos 400–600, raios contidos e três níveis de elevação.
- Removidos gradientes, glow, blur decorativo, entrada global de página, cards que levantavam e textos de 10 px.
- Padronizados foco WCAG, redução de movimento, contraste reforçado e impressão.

## Shell

- Sidebar agora mede 240 px, recolhe para 56 px e persiste a preferência; Equipe foi incluída para administradores.
- Header foi reduzido a 56 px. O selo redundante “Automação ativa” e o rodapé operacional foram removidos.
- Adicionados tema claro/escuro/sistema, paleta `Ctrl/⌘K`, mapa `?`, navegação `g+d/e/i/p` e link “Pular para o conteúdo”.
- Polling de alertas pausa com a aba oculta.

## Segurança e ações

- Confirmações nativas foram substituídas por diálogo com foco controlado; exclusão em massa e reset exigem texto.
- Redefinição de senha saiu de prompt nativo para modal próprio.
- Sessão continua exclusivamente em cookie HttpOnly e downloads continuam usando `fetch` + blob.

## Telas operacionais

- As 14 rotas existentes foram preservadas e receberam a fundação Papel & Grafite sem mudar contratos da API.
- Painel mantém estado geral, atenção, execuções e sincronizações como hierarquia de decisão.
- Documentos preserva período obrigatório, seleção, ZIP/CSV, detalhe e complemento de resumos; exclusões agora explicitam o impacto.
- Importações mantém prévia antes do disparo e trata janela SEFAZ como espera operacional.
- Empresas preserva cadastro por CNPJ e importação em massa; sua exclusão agora exige confirmação explícita.
- Certificados, Fechamento, Saúde, Configurações, Auditoria e Equipe mantêm seus fluxos e recebem semântica visual unificada.
