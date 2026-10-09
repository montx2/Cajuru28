# Integração com o Sistema Acessórias

A integração usa exclusivamente a API oficial documentada em
<https://api.acessorias.com/documentation>.

## Configuração

Um administrador abre **Configurações → Sistema Acessórias**, cola o token
gerado em **engrenagem → API Token** no Acessórias e salva. O token é enviado
com `Authorization: Bearer`, cifrado pelo cofre do Fluxa e nunca devolvido
ao navegador. Por segurança, somente o host oficial HTTPS é aceito.

## Empresas

O botão **Buscar e cadastrar todas as empresas ativas** percorre
`GET /companies/ListAll/?ativa=S&Pagina=N` até a página vazia (20 registros por
página), respeitando o contrato e tratando explicitamente autenticação, limite
de 100 requisições/minuto e erros que o fornecedor retorna com HTTP 200.

A identidade é sempre o CNPJ/CPF normalizado:

- inexistente localmente: cria a empresa;
- existente: atualiza razão social, UF e situação, sem duplicar;
- `Razao` vazio ou repetindo o documento **não apaga** um nome verdadeiro já
  digitado no Fluxa — só substitui o placeholder `Empresa <CNPJ>`; o resultado
  diz quantos nomes locais foram preservados;
- empresa nova sem razão social nenhuma entra como `Empresa <CNPJ>` (antes
  entrava com o próprio CNPJ no campo do nome, indistinguível de um dado real);
- documento ou UF inválidos: ignora e contabiliza no resultado;
- nenhum cadastro local é removido automaticamente.

As ações e quantidades são registradas na auditoria.

## Nome e UF pelo CNPJ, durante a importação

O mesmo token alimenta `GET /companies/{CNPJ}` (identificador sem máscara),
usado por `app/services/cadastro.py` para completar razão social e UF de um
certificado importado sem nome — a fonte pública da Receita é chamada só quando
o Acessórias não tem aquele CNPJ, respondeu incompleto, ou quando o chamador
quer o código IBGE do município, que o Acessórias não expõe.

- resultados (inclusive "não está no escritório") são cacheados por
  escritório + CNPJ: um lote de 203 certificados faz uma requisição por empresa
  desconhecida, não três;
- 429/timeout/erro de transporte pausam o Acessórias pelo resto da rodada e a
  importação segue pela fonte pública, em vez de travar;
- `empresa.nome` continua sendo editable: o reparo nunca sobrescreve um nome
  verdadeiro;
- salvar ou remover a credencial limpa o cache, para um token novo responder na
  hora.

## Consertar os cadastros que entraram sem nome

**Configurações → Integrações → Acessórias → Completar nomes pendentes**
(`POST /empresas/completar-cadastros`) repassa ao Acessórias — e, para o que não
está lá, às fontes públicas — as empresas cuja razão social é ruído
(`ICP-Brasil`) ou placeholder (`Empresa <CNPJ>`), ou que estão sem UF. Um clique
substitui reenviar certificado por certificado.
