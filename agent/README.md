# Cajuru Agent

Estação de trabalho do módulo **Procurações RFB**. Roda no Windows do
escritório, ao lado dos certificados A1 e do Assinador Digital SERPRO.

## O que ele faz

1. **Inventaria** os certificados visíveis na máquina — apenas metadados
   (titular, CNPJ do OID ICP-Brasil, número de série, validade, thumbprint).
2. **Diagnostica** o Assinador Digital SERPRO: instalado, em execução, host
   mapeado, porta local respondendo, versão, certificado visível.
3. **Gera políticas de seleção automática de certificado**
   (`AutoSelectCertificateForUrls`) para Chrome/Edge, ancoradas no Subject e no
   Issuer do A1 correto — nunca "o primeiro certificado".
4. **Pede trabalho** ao Cajuru28 e recebe uma *ordem de trabalho* — sem senha,
   sem PFX, sem chave privada.
5. **Abre o navegador real do operador** na URL oficial da Receita e mostra o
   roteiro passo a passo em uma janela lateral.
6. **Registra** o que o operador confirmou: protocolo, texto do portal,
   capturas de tela. Nada é dado como concluído sem confirmação real.

## O que ele **não** faz, por decisão de projeto

- Não lê, não copia e não envia a chave privada ou a senha de nenhum A1.
- Não clica sozinho em "Nova Autorização", "Assinar" ou "Validar". A
  IN RFB nº 2.320/2026, art. 13, veda camada de intermediação que automatize
  outorga, alteração ou revogação de autorizações de acesso.
- Não contorna CAPTCHA, MFA ou qualquer verificação de segurança. Ao encontrar
  um desafio, ele para e devolve o volante ao operador.
- Não substitui o Assinador SERPRO por criptografia própria.

## Instalação

```powershell
# No PowerShell como Administrador, na máquina que tem os certificados:
.\instalar_agent.ps1 -ServidorUrl "https://cajuru.suaempresa.com.br" `
                     -Identificador "<identificador gerado no Cajuru28>" `
                     -Segredo "<segredo exibido uma única vez>"
```

O instalador:

- verifica Python 3.11+, instala as dependências em um venv isolado;
- grava a credencial no **Windows Credential Manager** (não em arquivo);
- registra uma tarefa agendada que sobe o Agent no logon do operador;
- roda o diagnóstico do Assinador e mostra o que falta.

Passo a passo completo e solução de problemas: `docs/AGENT_CAJURU.md`.

## Primeiro carregamento dos certificados (pasta + suas planilhas)

Se você já possui a pasta com todos os `.pfx/.p12` e uma ou duas planilhas com
**cliente/CNPJ, senha e validade**, faça isso **na máquina Windows que usará o
Assinador SERPRO**. Primeiro rode a prévia — ela não instala nem envia nada:

```powershell
cajuru-agent importar-certificados `
  --pasta "D:\Certificados" `
  --planilha "D:\Planilhas\senhas.xlsx" `
  --planilha "D:\Planilhas\validade.xlsx"
```

A prévia associa por CNPJ no nome do arquivo e, se ele não estiver presente,
por nome do cliente. Arquivo ambíguo ou sem senha fica como pendência: o Agent
**não tenta senhas genéricas e não usa uma senha de outro cliente**. Corrija o
nome do PFX para incluir o CNPJ quando precisar desambiguar.

Depois de revisar a prévia, instale os itens aprovados e já publique apenas o
inventário público (CNPJ, validade e thumbprint) no Cajuru28:

```powershell
cajuru-agent importar-certificados `
  --pasta "D:\Certificados" `
  --planilha "D:\Planilhas\senhas.xlsx" `
  --planilha "D:\Planilhas\validade.xlsx" `
  --executar --sincronizar
```

A senha percorre somente a memória local e o `stdin` do PowerShell; não entra
na linha de comando, log, Credential Manager, banco ou API. O PFX e a chave
privada permanecem no repositório de certificados do Windows (`CurrentUser\My`).
A data interna do certificado é a fonte de verdade: uma divergência com a
planilha vira aviso, não bloqueio silencioso.

## Execução manual

```powershell
cajuru-agent diagnose        # pré-flight completo: Windows, rede, Playwright, certificados, navegador e Assinador
cajuru-agent diagnostico     # só o diagnóstico do Assinador, sem falar com o servidor
cajuru-agent certificados    # lista o que a máquina enxerga
cajuru-agent executar        # laço principal
```

## Seleção automática do certificado no Chrome/Edge

Depois que os A1 estiverem instalados no Windows, gere a política do cliente:

```powershell
cajuru-agent politica-certificado `
  --documento 12.345.678/0001-95 `
  --navegador edge `
  --navegador chrome
```

O comando inventaria a máquina, exige **um único** certificado vigente com
chave privada para o documento e imprime um script PowerShell idempotente para
`HKCU\Software\Policies\...\AutoSelectCertificateForUrls`. Para aplicar na
conta Windows atual após revisar:

```powershell
cajuru-agent politica-certificado --documento 12.345.678/0001-95 --executar
```

Reinicie o navegador e confira `edge://policy` ou `chrome://policy`. Se houver
mais de um A1 do mesmo documento, fixe `--thumbprint`; o Agent não escolhe no
palpite.

## Onde fica a credencial

| Sistema | Local |
|---|---|
| Windows | Credential Manager (`CredRead`/`CredWrite`, escopo do usuário) |
| Linux/macOS (desenvolvimento) | arquivo `~/.cajuru-agent/credencial.json` com permissão `600` |

O segredo nunca é gravado em log. O que aparece no log é o identificador
público da estação.
