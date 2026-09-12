# Integração com o Sistema Acessórias

A integração usa exclusivamente a API oficial documentada em
<https://api.acessorias.com/documentation>.

## Configuração

Um administrador abre **Configurações → Sistema Acessórias**, cola o token
gerado em **engrenagem → API Token** no Acessórias e salva. O token é enviado
com `Authorization: Bearer`, cifrado pelo cofre do NotasFlow e nunca devolvido
ao navegador. Por segurança, somente o host oficial HTTPS é aceito.

## Empresas

O botão **Buscar e cadastrar todas as empresas ativas** percorre
`GET /companies/ListAll/?ativa=S&Pagina=N` até a página vazia (20 registros por
página), respeitando o contrato e tratando explicitamente autenticação, limite
de 100 requisições/minuto e erros que o fornecedor retorna com HTTP 200.

A identidade é sempre o CNPJ/CPF normalizado:

- inexistente localmente: cria a empresa;
- existente: atualiza razão social, UF e situação, sem duplicar;
- documento ou UF inválidos: ignora e contabiliza no resultado;
- nenhum cadastro local é removido automaticamente.

As ações e quantidades são registradas na auditoria.
