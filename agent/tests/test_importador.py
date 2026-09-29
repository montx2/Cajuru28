"""Contrato da preparação local de certificados A1.

Os testes evitam dois riscos de produção: associar uma senha ao cliente errado
ou deixar uma senha aparecer no relatório. Nenhum deles chama PowerShell ou
instala certificado de verdade; a fronteira Windows é um callback injetável.
"""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl

from cajuru_agent import importador


CNPJ_UM = "12345678000195"
CNPJ_DOIS = "11444777000161"
SENHA_UM = "Senha-Privada-Um!"
SENHA_DOIS = "Senha-Privada-Dois!"


def _csv(caminho: Path, conteudo: str) -> Path:
    caminho.write_text(conteudo, encoding="utf-8")
    return caminho


def _pfx(pasta: Path, nome: str) -> Path:
    caminho = pasta / nome
    caminho.write_bytes(b"pfx-falso-apenas-para-planejamento")
    return caminho


def test_duas_planilhas_complementares_geram_plano_sem_expor_senhas(tmp_path):
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    _pfx(pasta, f"cliente-um-{CNPJ_UM}.pfx")
    _pfx(pasta, f"cliente-dois-{CNPJ_DOIS}.p12")

    senhas = _csv(
        tmp_path / "senhas.csv",
        "CNPJ;Cliente;Senha\n"
        f"{CNPJ_UM};Cliente Um Ltda;{SENHA_UM}\n"
        f"{CNPJ_DOIS};Cliente Dois Ltda;{SENHA_DOIS}\n",
    )
    validade = _csv(
        tmp_path / "validade.csv",
        "CNPJ;Validade\n"
        f"{CNPJ_UM};31/12/2030\n"
        f"{CNPJ_DOIS};2031-06-30\n",
    )

    plano = importador.montar_plano(pasta, [senhas, validade])

    assert [item.status for item in plano] == ["pronto", "pronto"]
    assert plano[0].documento == CNPJ_DOIS  # ordenação pelo nome do arquivo
    assert plano[1].documento == CNPJ_UM
    assert plano[1].validade_declarada is not None
    # A prévia é segura para log/terminal: nem dataclass repr nem JSON do
    # resultado expõem os segredos que vieram da planilha.
    assert SENHA_UM not in repr(plano)
    assert SENHA_DOIS not in repr(plano)


def test_associacao_por_nome_nao_aceita_empate(tmp_path):
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    _pfx(pasta, "Mercado-Alfa-2026.pfx")
    planilha = _csv(
        tmp_path / "senhas.csv",
        "Cliente;Senha\n"
        f"Mercado Alfa Ltda;{SENHA_UM}\n"
        f"Mercado Alfa Comercio Ltda;{SENHA_DOIS}\n",
    )

    plano = importador.montar_plano(pasta, [planilha])

    assert plano[0].status == "sem_associacao"
    assert "semelhante" in plano[0].mensagem.lower()
    assert SENHA_UM not in plano[0].mensagem
    assert SENHA_DOIS not in plano[0].mensagem


def test_planilha_excel_e_lida_localmente(tmp_path):
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    _pfx(pasta, f"{CNPJ_UM}-cliente-um.pfx")

    livro = openpyxl.Workbook()
    aba = livro.active
    aba.append(["Razão social", "CNPJ", "Senha do certificado", "Vencimento"])
    aba.append(["Cliente Um Ltda", CNPJ_UM, SENHA_UM, "31/12/2030"])
    planilha = tmp_path / "carteira.xlsx"
    livro.save(planilha)

    plano = importador.montar_plano(pasta, [planilha])

    assert len(plano) == 1
    assert plano[0].status == "pronto"
    assert plano[0].cliente == "Cliente Um Ltda"
    assert plano[0].validade_declarada is not None


def test_excel_com_abas_complementares_le_cada_cabecalho(tmp_path):
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    _pfx(pasta, f"{CNPJ_UM}-cliente-um.pfx")

    livro = openpyxl.Workbook()
    senhas = livro.active
    senhas.title = "Senhas"
    senhas.append(["CNPJ", "Senha"])
    senhas.append([CNPJ_UM, SENHA_UM])
    validade = livro.create_sheet("Validades")
    validade.append(["CNPJ", "Vencimento"])
    validade.append([CNPJ_UM, "31/12/2030"])
    planilha = tmp_path / "duas-abas.xlsx"
    livro.save(planilha)

    plano = importador.montar_plano(pasta, [planilha])

    assert plano[0].status == "pronto"
    assert plano[0].validade_declarada is not None


def test_execucao_tenta_somente_as_senhas_declaradas_e_saida_nao_vaza(tmp_path):
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    arquivo = _pfx(pasta, f"{CNPJ_UM}.pfx")
    planilha_a = _csv(
        tmp_path / "a.csv",
        "CNPJ;Senha\n"
        f"{CNPJ_UM};senha-antiga-declarada\n",
    )
    planilha_b = _csv(
        tmp_path / "b.csv",
        "CNPJ;Senha\n"
        f"{CNPJ_UM};{SENHA_UM}\n",
    )
    plano = importador.montar_plano(pasta, [planilha_a, planilha_b])
    tentadas: list[str] = []

    def importar_falso(caminho: Path, senha: str) -> dict[str, str]:
        assert caminho == arquivo
        tentadas.append(senha)
        if senha != SENHA_UM:
            raise importador.ImportacaoLocalError("senha incorreta")
        return {
            "resultado": "importado",
            "thumbprint": "a" * 40,
            "valido_ate": "2030-12-31T00:00:00+00:00",
        }

    resultado = importador.executar_plano(plano, importar=importar_falso)

    assert tentadas == ["senha-antiga-declarada", SENHA_UM]
    assert resultado[0].status == "importado"
    assert resultado[0].tentativas == 2
    saida = json.dumps(resultado[0].para_saida(), ensure_ascii=False)
    assert SENHA_UM not in saida
    assert "senha-antiga-declarada" not in saida


def test_arquivo_sem_senha_declarada_e_ignorado_sem_chute(tmp_path):
    pasta = tmp_path / "certificados"
    pasta.mkdir()
    _pfx(pasta, f"cliente-{CNPJ_UM}.pfx")
    planilha = _csv(
        tmp_path / "sem-senha.csv",
        "CNPJ;Cliente;Senha\n"
        f"{CNPJ_UM};Cliente Um Ltda;\n",
    )

    plano = importador.montar_plano(pasta, [planilha])
    resultado = importador.executar_plano(plano, importar=lambda *_: (_ for _ in ()).throw(AssertionError("não deve importar")))

    assert plano[0].status == "sem_senha"
    assert resultado[0].status == "ignorado"
    assert "senha preenchida" in resultado[0].mensagem.lower()
