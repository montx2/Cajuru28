# Diagnóstico do front-end — auditoria antes do redesign

Auditoria de 108 arquivos (~17,2 mil linhas) em `frontend/`, feita antes de escrever
qualquer código de redesign, conforme combinado.

---

## 0. Achado que muda o plano de trabalho

O brief descreve o projeto como **"NotasFlow"**, com um front-end a ser reformulado do
zero. O que está no repositório hoje é outra coisa:

- O produto já se chama **Fluxa** em 27 arquivos (`app/layout.tsx`, favicons, títulos,
  `LogoFluxa.tsx`, `design/SISTEMA.md`). A string "NotasFlow" só sobrevive no
  `name` do `package.json`.
- O front-end **já passou por uma reconstrução integral** — o sistema de design
  "Papel & Grafite", documentado em `frontend/design/SISTEMA.md` e no
  `CHANGELOG-FRONTEND.md`. São 41 arquivos reescritos, 75 criados, 12 removidos.
- Boa parte do que o brief pede **já está implementada**, e em alguns pontos mais
  rigorosamente do que o pedido:

| Pedido do brief | Estado atual |
|---|---|
| Tokens de cor em CSS variables referenciados no Tailwind | Feito. `globals.css` + `tailwind.config.ts`; **nenhum** componente escreve hex. |
| Escala tipográfica de 5-6 tamanhos, pesos 400/500/600 | Feito, e travado: `font-bold`/`font-black` **resolvem para 600** no config. |
| Sombras discretas, nada exagerado | Travado: `shadow-sm`…`shadow-2xl` resolvem para `none`; só `nivel1`/`nivel2` elevam. |
| Raios contidos | Travado: `rounded-2xl`/`rounded-3xl` resolvem para 12px. |
| 1 acento só, semânticos restritos a status | Feito. Acento índigo único; `ok/espera/erro/info` só em badge e mensagem. |
| WCAG AA, contraste medido | Feito e **documentado com os valores** (ex.: tinta-forte 17,3:1, acento 7,3:1). |
| Label visível + `aria-describedby` + erro ligado ao campo | Feito em `components/ui/Campo.tsx`. |
| Light/dark mode | Feito, calibrado separadamente (não é paleta invertida), sem flash. |
| Empty states, skeletons, estados de erro | Feito: `EstadoVazio`, `EstadoErro`, `Esqueleto`, `EsqueletoTabela`. |
| Microinterações 150-200ms | Feito: 120/180/240ms + `prefers-reduced-motion`. |
| Grid de 8pt | Seguido na maior parte; ver desvios em §2. |
| Confirmação antes de ação destrutiva | Feito: `DialogoConfirmacao`. |
| Feedback de ação assíncrona | Feito: `Toast` + `carregando` no `Botao`. |

Ou seja: **o redesign completo que você pediu já foi feito** — só que sob outro nome
de produto e com uma paleta índigo própria, não a lista de hex do brief.

O bug crítico, por outro lado, era real. Ele foi diagnosticado, corrigido e coberto
por teste (§3).

---

## 1. Problemas de UI/UX encontrados

Poucos, e nenhum estrutural. O sistema de design está sólido; o que sobra é resíduo.

1. **Identidade dividida.** `package.json` diz `notasflow-frontend`; todo o resto diz
   Fluxa. Quem entra no projeto não sabe qual é o nome do produto.
2. **Comentário do código desalinhado da paleta.** `components/ui/Botao.tsx:24` diz
   *"`primaria` é o verde do carimbo"* — mas o acento virou índigo (`#4338ca`) na
   reconstrução. O comentário ficou do sistema antigo. Mesma coisa no
   `CHANGELOG-FRONTEND.md`, que fala em "um único acento verde".
3. **14 rotas no painel** contra as 6 telas que o brief lista. Existem
   `/atencao`, `/execucoes`, `/auditoria`, `/relatorios`, `/saude`, `/alertas`,
   `/configuracoes`, `/usuarios` além das 6. Não é defeito — mas é densidade de
   navegação bem acima do "menos é mais" pedido, e vale decidir o que fica.
4. **`ModalEnvioCertificado` duplicado.** Existem dois modais de upload de A1, com
   textos e validações diferentes:
   - `app/dashboard/certificados/Certificados.tsx:341` (com seletor de empresa),
   - `app/dashboard/empresa/Empresa.tsx:739` (empresa fixa).

   O segundo tem uma regra pior: o botão "Instalar certificado" só considera
   `disabled={arquivos.length === 0}`, ignorando a senha vazia — o usuário clica,
   o envio começa e só então recebe o erro. O primeiro já checa
   `senha.length > 0` antes de habilitar. Dois caminhos para a mesma ação, com
   prevenção de erro diferente, é a inconsistência mais concreta do sistema.
5. **Campo de senha sem toggle mostrar/ocultar no modal de certificado.** O login
   tem (`FormularioLogin.tsx`, sufixo "Mostrar"/"Ocultar"); os dois modais de A1
   não têm. Digitar uma senha de certificado às cegas, sem poder conferir, é
   justamente onde o erro de digitação custa caro.
6. **Toggle de senha do login é textual, não ícone.** O brief pede ícone de olho; hoje
   são as palavras "Mostrar"/"Ocultar" num botão de `min-w-12`. Funciona e é
   acessível (`aria-pressed`), mas destoa do resto da interface, que é iconográfica.
7. **Login: erro por campo derivado do erro global.** `erro && email.trim().length === 0`
   faz a mensagem "Informe o e-mail" aparecer *depois* de um 401, misturando
   validação de formulário com resposta do servidor. O correto é validar antes de
   submeter.

---

## 2. Inconsistências visuais

O sistema é muito consistente — as exceções são pontuais e todas mensuráveis.

1. **Fora do grid de 4/8px.** O `SISTEMA.md` adota grid de 4px, mas há usos de
   `.5` do Tailwind que caem em números ímpares:
   - `px-2.5` (10px) e `py-3.5` (14px) no cabeçalho do `Modal.tsx`,
   - `gap-2.5` (10px) na logo do login,
   - `py-2.5` no bloco de erro do login,
   - `mb-1.5` (6px) no rótulo de todo campo (`Campo.tsx`),
   - `-mr-1.5` no botão de fechar do modal.

   6px e 10px são múltiplos de 2, não de 4. São escolhas de ajuste ótico
   defensáveis, mas violam a regra literal do brief.
2. **Altura de botão.** O brief pede h-10 (40px) como padrão. O sistema usa
   `sm: h-8` (32px) e `md: h-9` (36px) — densidade mais alta que a pedida. É
   coerente **dentro** do sistema (o campo também é `h-9`), então não há
   desalinhamento entre botão e input; é só mais denso que o alvo do brief.
3. **Escala tipográfica deslocada.** O brief pede 12/14/16/20/24-32/32-40. O sistema
   usa 11/12/13/14/16/20/26/34. O corpo padrão é **13px**, não 16px, e existe um
   `2xs` de **11px** — abaixo do mínimo de 12px que o próprio brief define.
   `text-2xs` aparece em `Graficos.tsx` e em rótulos de tabela.
4. **Dois tamanhos de rótulo para a mesma função.** O rótulo de campo é
   `text-xs` (12px) no `Campo.tsx`, mas os títulos de bloco escritos à mão nos
   modais usam `text-xs font-medium` replicado manualmente
   (`Certificados.tsx:421`, `Empresa.tsx:707`) em vez do componente `Campo` —
   o mesmo pixel, por dois caminhos diferentes, que podem divergir na próxima edição.
5. **Seis variantes de botão** (`primaria`, `secundaria`, `sutil`, `perigo`,
   `perigo-sutil`, `link`) contra as quatro do brief. `perigo-sutil` e `link`
   engordam a superfície de decisão sem necessidade clara.
6. **Cor fora de token, 1 ocorrência.** `Botao.tsx:33` usa `text-white` literal na
   variante `perigo`, enquanto todo o resto passa por token
   (`acento-contraste`). No tema escuro isso não acompanha a calibragem.

---

## 3. Bug crítico — causa raiz confirmada e corrigida

**Nenhuma das quatro hipóteses do brief era a causa.** Verifiquei todas:

| Hipótese | Verificação | Veredito |
|---|---|---|
| 1. Modal declarado dentro de outro componente | `ModalEnvioCertificado` e `ModalCertificado` estão no escopo do módulo, fora de qualquer render | ❌ não era |
| 2. `key` dependente do valor digitado | Varri todo `key=` do projeto: todas derivam de `id`, índice ou rótulo estável. Nenhum `key={senha}`, nenhum `Math.random()` | ❌ não era |
| 3. Focus trap roubando o foco para o botão X | **Confirmado** — mas não por remount | ✅ **era isto** |
| 4. Estado levantado / render condicional desmontando o input | `senha` é `useState` local ao modal; o input nunca é condicional | ❌ não era |

### A causa real

`frontend/lib/useFocoPreso.ts` — o `useEffect` que move o foco tinha este array de
dependências:

```ts
}, [ativo, aoFechar, destino, travarRolagem]);
```

E todas as telas passam o handler inline:

```tsx
<ModalCertificado aberto={certificadoAberto} aoFechar={() => setCertificadoAberto(false)} … />
```

Uma arrow function escrita no JSX tem **identidade nova a cada render**. Então:

```
tecla digitada → setSenha → re-render do modal
  → novo objeto para `aoFechar`
  → dependência mudou → cleanup + reexecução do efeito
  → alvo.focus() roda de novo
  → alvo = primeiro focável do diálogo = botão "Fechar" (X)
  → cursor sai do input
```

A hipótese 3 do brief estava certa no **sintoma** ("o efeito dispara de novo a cada
caractere") e errada no **mecanismo**: não havia remount nenhum. O componente
permanecia montado o tempo todo; era a *identidade da prop* que invalidava o efeito.
Isso importa, porque as correções que o brief propunha — extrair o componente,
remover `key` dinâmica — não teriam resolvido nada: o código já estava correto nesses
três pontos.

O cleanup do efeito também rodava a cada tecla, o que significa que
`document.body.style.overflow` era restaurado e re-travado a cada caractere, e o
`gatilho.current.focus()` do cleanup disputava o foco junto.

### A correção

O efeito agora depende **só de `ativo`**. As três opções viraram refs espelho,
atualizadas a cada render e lidas de dentro dos handlers, para continuarem corretas
sem entrar no array de dependências:

```ts
const aoFecharRef = useRef(aoFechar);
aoFecharRef.current = aoFechar;   // sempre atual
…
}, [ativo]);                       // mas nunca reexecuta o foco
```

Também troquei `ativo: aberto` por `ativo: aberto && montado` em `Modal`, `Painel` e
`PaletaComandos`: o portal só existe depois do `montado`, então antes disso o efeito
rodava com `container.current === null` e saía sem fazer nada — o foco inicial
dependia de um render extra por acaso.

**Alcance da correção:** o hook é o único focus trap do projeto. Corrigi-lo conserta
de uma vez o modal de certificado das duas telas, todos os demais modais, o
`DialogoConfirmacao`, o drawer `Painel` e a paleta de comandos (`Ctrl/⌘K`) —
qualquer campo dentro de qualquer camada, inclusive os de senha de usuário em
`/dashboard/usuarios`.

O campo de senha do **login** nunca teve o bug: não vive dentro de um modal, logo
nunca passou pelo focus trap.

### Prova

`frontend/testes/foco-senha-modal.test.tsx` renderiza o modal com
`aoFechar={() => setAberto(false)}` inline — o padrão exato das telas — e digita
`Cert@2024#A1x9` (14 caracteres: maiúsculas, minúsculas, números e símbolos) sem
reclicar no campo, afirmando após **cada tecla** que `document.activeElement` ainda é
o input.

```
✓ mantém o foco no input durante a digitação inteira da senha
✓ leva o foco para dentro do diálogo ao abrir
```

Confirmei que o teste realmente pega o bug: ao restaurar o array de dependências
antigo, ele falha; com a correção, passa. `tsc --noEmit` e `next build` (18 rotas)
passam limpos.
