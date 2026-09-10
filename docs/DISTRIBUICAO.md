# Distribuir o NotasFlow — publicar uma versão que chega em todo mundo

Este documento é para **quem mantém o projeto** (você). O guia de quem usa está
em [`PASSO_A_PASSO.md`](PASSO_A_PASSO.md).

---

## A ideia em uma frase

> Todo computador com o NotasFlow instalado pergunta, sozinho, se existe versão
> nova. Você publica uma vez; ele baixa, confere a digital do arquivo (SHA-256) e
> se atualiza — sem ninguém clicar em nada.

Isso é o que substitui o "deploy": no modo programa instalado não existe "publiquei
e todo mundo já está na versão nova". O que existe é um mecanismo no programa.

---

## O ciclo completo, do bug à correção em todas as máquinas

```text
  você corrige o código
        │
        ▼
  sobe a versão em `versao.txt`        (1.0.0 → 1.0.1)
        │
        ▼
  Actions → "Publicar versão do NotasFlow" → Run workflow
        │
        ├── roda a suíte de testes (129 testes) — se falhar, não publica
        ├── compila o painel (Next.js → export estático)
        ├── monta o NotasFlow.exe (PyInstaller)
        ├── monta o instalador (Inno Setup) e o ZIP portátil
        └── cria a Release no GitHub com
              • NotasFlow-Setup-1.0.1.exe
              • NotasFlow-1.0.1-portatil.zip
              • latest.json          ← o manifesto que o programa consulta
        │
        ▼
  cada programa instalado:
      lê  https://github.com/montx2/Cajuru28/releases/latest/download/latest.json
      compara a versão (1.0.1 > 1.0.0)
      mostra a faixa "Versão 1.0.1 disponível" com as notas
        │
        ▼  (o usuário clica em "Atualizar agora", ou aceita sozinho se for obrigatória)
      baixa o instalador, confere o SHA-256, roda em silêncio
      (/VERYSILENT) e reabre o programa na versão nova
```

O caminho `releases/latest/download/` é de propósito: ele **não consome a cota
da API do GitHub** (60 consultas/hora por IP). Um escritório inteiro sai pelo
mesmo IP — usar `api.github.com` funcionaria hoje e falharia no dia em que os
computadores abrissem juntos.

---

## Publicando (o jeito fácil: GitHub Actions)

1. Edite `versao.txt` na raiz:
   ```
   1.0.1
   ```
2. Faça commit e push na `main`.
3. No GitHub: **Actions → Publicar versão do NotasFlow → Run workflow**.
   - **versão**: deixe vazio para usar `versao.txt` (ou digite `1.0.1`)
   - **notas**: o que mudou, em uma linha — é isso que o contador lê na faixa de
     atualização (`"Corrige o cancelamento de NFS-e e acelera a primeira varredura"`)
   - **obrigatória**: marque só para correção de segurança ou de perda de dados —
     obrigatória não oferece "depois"
4. Espere ~10 minutos e confira a Release publicada.

Também funciona por tag:

```bash
git tag v1.0.1 && git push origin v1.0.1
```

O workflow roda os testes **antes** de empacotar. Isso não é preciosismo: uma
atualização automática que entrega um erro chega em **todas** as máquinas ao mesmo
tempo, e não existe "voltar atrás" fácil do lado do cliente.

### Publicar sem internet (pasta de rede)

O escritório pode não ter internet liberada. Nesse caso:

1. Rode em uma máquina Windows com Python + Node:

   ```bat
   python scripts\empacotar.py --notas "Corrige o cancelamento de NFS-e"
   ```

   Isso produz em `dist\`: o instalador, o ZIP portátil e o `latest.json`.

2. Copie os três arquivos para a pasta compartilhada (ex.: `\\SERVIDOR\NotasFlow`).
3. Nos computadores, aponte o manifesto uma única vez, em
   `%APPDATA%\NotasFlow\.env`:

   ```env
   NOTASFLOW_UPDATE_MANIFEST=\\SERVIDOR\NotasFlow
   ```

O programa lê o `latest.json` da pasta, compara o SHA-256 e instala. Funciona
igual ao GitHub — só troca a origem. Também aceita uma URL própria
(`https://intranet/notasflow/latest.json`), mas **nunca** `http://` simples: um
instalador não pode vir por canal sem TLS.

---

## O que exatamente o `empacotar.py` faz

```bat
python scripts\empacotar.py                 :: tudo (painel + .exe + instalador + manifesto)
python scripts\empacotar.py --sem-frontend  :: reaproveita frontend\out (build do painel já feito)
python scripts\empacotar.py --portatil      :: só o ZIP portátil, sem Inno Setup
python scripts\empacotar.py --versao 1.2.0  :: publica com outra versão
python scripts\empacotar.py --limpar        :: apaga build\, dist\ e backend\web\ antes
```

Requisitos na máquina do build: **Python 3.11**, **Node.js 20+**,
`pip install -r backend\requirements-desktop.txt` e o
[Inno Setup 6](https://jrsoftware.org/isdl.php) (opcional — sem ele sai só o ZIP).

O PyInstaller **não faz compilação cruzada**: o `.exe` tem de ser montado no
Windows. É exatamente por isso que existe o workflow no GitHub Actions, em um
runner `windows-latest` — a alternativa é um Windows na sua mesa.

---

## Decisões de empacotamento (e o porquê de cada uma)

| Decisão | Motivo |
| --- | --- |
| `--onedir` e não `--onefile` | O `--onefile` extrai todo o Python para uma pasta temporária **a cada abertura** (o contador abre o programa todo dia) e ainda facilita a vida de antivírus. O instalador entrega a mesma coisa: um arquivo para baixar |
| Sem UPX | Compactar economiza alguns MB e rende falso positivo de antivírus em máquina de escritório. Programa fiscal em quarentena é programa que não existe |
| Sem Celery/Redis/PostgreSQL no pacote | No modo desktop a fila é em processo e o banco é SQLite; as três bibliotecas seriam dezenas de MB nunca importados (ver `excludes` em `backend/notasflow.spec`) |
| Instalação **por usuário** (`PrivilegesRequired=lowest`) | Sem UAC — nem na instalação, nem, principalmente, na atualização automática, que roda sem ninguém olhando |
| Dados em `%APPDATA%\NotasFlow` | Atualizar e reinstalar troca a pasta do **programa**. Banco, certificados e XMLs ficam fora dela, e sobrevivem a tudo |
| Mesmo `AppId` no Inno Setup para sempre | É o que faz a versão nova ser **atualização** e não uma segunda instalação lado a lado |
| Desinstalar **não** apaga os dados por padrão | Um clique a mais é barato; perder o histórico fiscal não |
| Manifesto com `sha256` obrigatório | Proxy corporativo, download interrompido, arquivo trocado: o hash é o que garante que o que vai ser executado é o que foi publicado |
| Assinatura de código (Authenticode) **não** usada | Custa algumas centenas de dólares por ano. Enquanto não houver, o aviso do SmartScreen na primeira instalação é esperado (e está documentado no passo a passo). É o próximo investimento natural quando o programa for distribuído fora do escritório |

---

## Verificando uma publicação

Depois de publicar, confira o manifesto — é o contrato entre o seu build e os
programas instalados:

```bash
curl -sL https://github.com/montx2/Cajuru28/releases/latest/download/latest.json
```

```json
{
  "versao": "1.0.1",
  "data": "2026-09-10T12:00:00+00:00",
  "obrigatoria": false,
  "notas": "Corrige o cancelamento de NFS-e.",
  "arquivos": {
    "windows-instalador": {
      "url": "NotasFlow-Setup-1.0.1.exe",
      "sha256": "9f2c…",
      "tamanho": 41234567,
      "tipo": "instalador"
    }
  }
}
```

Para conferir o SHA-256 do arquivo baixado:

```powershell
Get-FileHash .\NotasFlow-Setup-1.0.1.exe -Algorithm SHA256
```

Teste real de atualização (10 minutos, uma vez por versão): instale a versão
anterior numa máquina limpa, publique a nova e veja o aviso aparecer. O caminho
"baixar → conferir hash → instalar silencioso → reabrir" é o que mais depende de
detalhe de sistema operacional — vale exercitá-lo, não supô-lo.

---

## Perguntas que sempre aparecem

**O que acontece se a atualização falhar no meio?** O instalador roda com
`/NOCANCEL` e troca a pasta do programa; se ele falhar, o `.cmd` reabre o
programa que está instalado (a versão antiga funciona, porque os dados não são
tocados). O log fica em `%TEMP%\notasflow-updates\atualizacao.log` — é o arquivo
a pedir para quem reportar problema.

**O usuário pode recusar a atualização?** Sim, clicando em "depois" — e a faixa
volta na próxima abertura. Para versões marcadas como obrigatórias, o botão de
adiar não aparece.

**Duas versões diferentes no mesmo escritório?** É normal e não quebra nada:
cada computador tem o seu banco. O que **não** se pode fazer é instalar o
programa em duas máquinas sincronizando os mesmos CNPJs — as duas consultariam a
SEFAZ e o CNPJ seria bloqueado por consumo indevido. Se o escritório precisa de
um banco só, use o modo servidor (Docker).

**Quero voltar para a versão anterior.** Reescreva `versao.txt` com a versão
antiga, rode `empacotar.py` e publique a Release — o atualizador compara números
e vai aceitar como "versão nova" (é o rollback). Os dados continuam compatíveis:
as migrações de coluna são aditivas.

**Posso publicar uma versão só para corrigir texto?** Pode, mas vale a pena:
cada atualização baixa ~40 MB em cada máquina. Agrupar correções pequenas em uma
versão por semana é mais amigável.
