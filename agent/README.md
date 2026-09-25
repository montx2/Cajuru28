# Cajuru Agent

Estação de trabalho do módulo **Procurações RFB**. Roda no Windows do
escritório, ao lado dos certificados A1 e do Assinador Digital SERPRO.

## O que ele faz

1. **Inventaria** os certificados visíveis na máquina — apenas metadados
   (titular, CNPJ do OID ICP-Brasil, número de série, validade, thumbprint).
2. **Diagnostica** o Assinador Digital SERPRO: instalado, em execução, host
   mapeado, porta local respondendo, versão, certificado visível.
3. **Pede trabalho** ao Cajuru28 e recebe uma *ordem de trabalho* — sem senha,
   sem PFX, sem chave privada.
4. **Abre o navegador real do operador** na URL oficial da Receita e mostra o
   roteiro passo a passo em uma janela lateral.
5. **Registra** o que o operador confirmou: protocolo, texto do portal,
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

## Execução manual

```powershell
cajuru-agent diagnostico     # só o diagnóstico, sem falar com o servidor
cajuru-agent certificados    # lista o que a máquina enxerga
cajuru-agent executar        # laço principal
```

## Onde fica a credencial

| Sistema | Local |
|---|---|
| Windows | Credential Manager (`CredRead`/`CredWrite`, escopo do usuário) |
| Linux/macOS (desenvolvimento) | arquivo `~/.cajuru-agent/credencial.json` com permissão `600` |

O segredo nunca é gravado em log. O que aparece no log é o identificador
público da estação.
