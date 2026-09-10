"""
Importação em massa de empresas e certificados — estilo JetTax360.

Recebe vários .pfx de uma vez (e/ou um CSV) e já cria as empresas com CNPJ,
razão social e UF: CNPJ vem do certificado (campo ICP-Brasil) e a razão
social do subject do X.509. A senha é informada pelo usuário — o sistema
NÃO tenta descobrir/adivinhar senha; se não bater, o arquivo é reportado
como erro e os demais seguem.

CSV opcional (razao_social;cnpj_cpf;uf[;senha]) permite cadastrar empresas
sem certificado e/ou informar senha individual por CNPJ.
"""

from __future__ import annotations

import csv
import io
import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.core.config import settings
from app.core.vault import cifrar_segredo
from app.db.session import get_db
from app.models import Certificado, Empresa
from app.schemas import (
    EmpresaAtualizar,
    EmpresaCriar,
    EmpresaResposta,
    EstadoSincronizacaoResposta,
    ItemLoteEmpresas,
    LoteEmpresasResposta,
)
from app.api.routers.importacoes import listar_estado_sincronizacao
from app.services.certificados import (
    apenas_digitos,
    cnpj_de_nome_arquivo,
    extrair_identidade,
    validar_documento,
)

router = APIRouter(prefix="/empresas", tags=["empresas"])

_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

_LIMITE_ARQUIVOS = 200
_LIMITE_BYTES_PFX = 30 * 1024 * 1024  # 30 MB por .pfx (mesmo limite do CAJURUFINAL)
_LIMITE_BYTES_CSV = 5 * 1024 * 1024


def _empresa_do_escritorio(db: Session, empresa_id: int, escritorio_id: int) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


@router.get("", response_model=list[EmpresaResposta])
def listar_empresas(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    return db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id).all()


@router.post("", response_model=EmpresaResposta, status_code=status.HTTP_201_CREATED)
def criar_empresa(
    dados: EmpresaCriar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    ja_existe = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == dados.cnpj_cpf)
        .first()
    )
    if ja_existe:
        raise HTTPException(status_code=409, detail="Já existe uma empresa com esse CNPJ/CPF")

    empresa = Empresa(escritorio_id=escritorio_id, **dados.model_dump())
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/{empresa_id}", response_model=EmpresaResposta)
def obter_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


@router.patch("/{empresa_id}", response_model=EmpresaResposta)
def atualizar_empresa(
    empresa_id: int,
    dados: EmpresaAtualizar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Ajusta cadastro e automação de uma empresa.

    O que mais importa aqui é `sincronizar_automaticamente`: ligado, o agendador
    entra no ADN/SEFAZ sozinho, dentro das janelas de consumo, sem ninguém
    apertar botão. Desligado (ex.: empresa em homologação ou com outro sistema
    consultando o mesmo CNPJ), ela fica fora da varredura automática.
    """
    empresa = _empresa_do_escritorio(db, empresa_id, escritorio_id)

    mudanca = dados.model_dump(exclude_unset=True)
    if "quais_tipos_sincronizar" in mudanca:
        tipos = mudanca.pop("quais_tipos_sincronizar")
        empresa.quais_tipos_sincronizar = (
            ",".join(t.value for t in tipos) if tipos else ""
        )
    for campo, valor in mudanca.items():
        if valor is None:
            continue
        setattr(empresa, campo, valor)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/{empresa_id}/sincronizacao", response_model=list[EstadoSincronizacaoResposta])
def sincronizacao_da_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Cursor, maxNSU, janelas e bloqueios desta empresa — por tipo de documento."""
    _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return listar_estado_sincronizacao(db=db, escritorio_id=escritorio_id, empresa_id=empresa_id)


@router.post("/lote", response_model=LoteEmpresasResposta)
async def importar_empresas_em_massa(
    uf_padrao: str = Form("SP"),
    senha: str = Form(""),
    arquivos: list[UploadFile] = File(default=[]),
    csv_arquivo: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Cadastra várias empresas de uma vez.

    - `arquivos`: um ou mais .pfx/.p12 (A1). Para cada um, abre com a
      `senha`, extrai CNPJ/razão social do certificado, cria a empresa e
      grava o certificado cifrado.
    - `csv_arquivo`: opcional, texto com colunas
      `razao_social;cnpj_cpf;uf` (ou nome;cnpj;uf) e, opcionalmente, `senha`
      individual. Linhas sem certificado ainda cadastram a empresa.
    - `uf_padrao`: UF usada quando a linha/arquivo não trouxer uma.
    """
    uf_padrao = (uf_padrao or "SP").strip().upper()
    if uf_padrao not in _UFS_VALIDAS:
        raise HTTPException(status_code=400, detail=f"UF padrão inválida: {uf_padrao!r}")

    if not arquivos and csv_arquivo is None:
        raise HTTPException(
            status_code=400, detail="Envie ao menos um arquivo .pfx ou um CSV."
        )
    if len(arquivos) > _LIMITE_ARQUIVOS:
        raise HTTPException(
            status_code=400,
            detail=f"Limite de {_LIMITE_ARQUIVOS} arquivos por lote.",
        )

    # Linhas do CSV por CNPJ (senha/UF/razão por empresa, se informadas)
    linhas_csv = await _ler_csv(csv_arquivo) if csv_arquivo else {}
    resultados: list[ItemLoteEmpresas] = []
    vistos: set[str] = set()

    # 1) Arquivos .pfx — empresas + certificados
    for arquivo in arquivos:
        resultados.append(
            await _processar_pfx(
                arquivo,
                senha=senha,
                uf_padrao=uf_padrao,
                linhas_csv=linhas_csv,
                db=db,
                escritorio_id=escritorio_id,
                vistos=vistos,
            )
        )
    db.flush()

    # 2) Linhas do CSV sem certificado correspondente
    usados = {r.cnpj_cpf for r in resultados if r.cnpj_cpf and r.status != "erro"}
    for cnpj, linha in linhas_csv.items():
        if cnpj in usados:
            continue
        resultados.append(_criar_empresa_de_linha(cnpj, linha, db, escritorio_id, vistos))

    criadas = sum(1 for r in resultados if r.status == "criada")
    certificados = sum(1 for r in resultados if r.status == "certificado_atualizado")
    ja_existiam = sum(1 for r in resultados if r.status == "ja_existia")
    erros = sum(1 for r in resultados if r.status == "erro")
    db.commit()

    return LoteEmpresasResposta(
        total=len(resultados),
        criadas=criadas,
        certificados=certificados,
        ja_existiam=ja_existiam,
        erros=erros,
        itens=resultados,
    )


async def _processar_pfx(
    arquivo: UploadFile,
    *,
    senha: str,
    uf_padrao: str,
    linhas_csv: dict[str, dict],
    db: Session,
    escritorio_id: int,
    vistos: set[str],
) -> ItemLoteEmpresas:
    nome = arquivo.filename or "arquivo.pfx"
    if not nome.lower().endswith((".pfx", ".p12")):
        return ItemLoteEmpresas(
            origem=nome, status="erro", mensagem="Extensão não suportada (use .pfx ou .p12)."
        )

    conteudo = await arquivo.read()
    if len(conteudo) > _LIMITE_BYTES_PFX:
        return ItemLoteEmpresas(
            origem=nome,
            status="erro",
            mensagem=f"Arquivo maior que {_LIMITE_BYTES_PFX // (1024 * 1024)} MB.",
        )
    if not conteudo:
        return ItemLoteEmpresas(origem=nome, status="erro", mensagem="Arquivo vazio.")

    # Senha que o usuário informou (compartilhada). Se o CSV tiver senha
    # individual para o CNPJ do arquivo, ela tem prioridade — mas é sempre
    # uma senha EXPLÍCITA, nunca uma lista tentada em loop.
    cnpj_nome = cnpj_de_nome_arquivo(nome)
    linha_csv = linhas_csv.get(cnpj_nome, {})
    senha_efetiva = (linha_csv.get("senha") or senha).strip()

    try:
        identidade = extrair_identidade(conteudo, senha_efetiva)
        # Revalida contra o CNPJ do nome do arquivo: se o X.509 diz outra
        # coisa, o certificado manda, mas avisamos no resultado.
        cnpj = identidade.documento
    except ValueError as exc:
        return ItemLoteEmpresas(
            origem=nome,
            cnpj_cpf=cnpj_nome,
            status="erro",
            mensagem=str(exc),
        )

    if cnpj in vistos:
        return ItemLoteEmpresas(
            origem=nome,
            cnpj_cpf=cnpj,
            razao_social=identidade.razao_social,
            status="erro",
            mensagem="CNPJ duplicado dentro do mesmo lote.",
        )

    linha = linhas_csv.get(cnpj, linha_csv)
    uf = (linha.get("uf") or uf_padrao).upper()
    if uf not in _UFS_VALIDAS:
        return ItemLoteEmpresas(
            origem=nome,
            cnpj_cpf=cnpj,
            razao_social=identidade.razao_social,
            status="erro",
            mensagem=f"UF inválida: {uf!r}.",
        )

    razao = (linha.get("razao_social") or identidade.razao_social).strip()
    empresa, criada_agora = _obter_ou_criar_empresa(
        db, escritorio_id, cnpj, razao, uf, vistos
    )

    # Grava/atualiza o certificado (senha cifrada, arquivo com 0600)
    pasta = os.path.join(settings.dados_dir, "certificados", str(empresa.id))
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"{cnpj}.pfx")
    with open(caminho, "wb") as f:
        f.write(conteudo)
    os.chmod(caminho, 0o600)

    db.query(Certificado).filter(
        Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True)
    ).update({"ativo": False})

    certificado = Certificado(
        empresa_id=empresa.id,
        arquivo_path=caminho,
        senha_cifrada=cifrar_segredo(senha_efetiva),
        validade=identidade.validade_utc,
        ativo=True,
    )
    db.add(certificado)
    db.flush()

    return ItemLoteEmpresas(
        origem=nome,
        cnpj_cpf=cnpj,
        razao_social=empresa.razao_social,
        uf=empresa.uf,
        status="criada" if criada_agora else "certificado_atualizado",
        mensagem=(
            f"Certificado vinculado (válido até "
            f"{identidade.validade_utc.strftime('%d/%m/%Y')})."
        ),
        empresa_id=empresa.id,
        certificado_id=certificado.id,
        validade=identidade.validade_utc,
    )


async def _ler_csv(arquivo: UploadFile | None) -> dict[str, dict]:
    if arquivo is None:
        return {}
    conteudo = await arquivo.read()
    if len(conteudo) > _LIMITE_BYTES_CSV:
        raise HTTPException(status_code=400, detail="CSV maior que 5 MB.")
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1", errors="replace")

    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    linhas = [linha for linha in leitor if any(celula.strip() for celula in linha)]
    if not linhas:
        return {}

    cabecalho = [c.strip().lower().replace(" ", "_") for c in linhas[0]]
    indice = {
        "razao": _indice_ou(cabecalho, ("razao_social", "razaosocial", "nome", "empresa", "razao")),
        "cnpj": _indice_ou(cabecalho, ("cnpj_cpf", "cnpj", "cpf", "documento", "doc")),
        "uf": _indice_ou(cabecalho, ("uf", "estado")),
        "senha": _indice_ou(cabecalho, ("senha", "password")),
    }
    if indice["cnpj"] is None:
        return {}  # sem coluna de documento, nada a fazer

    resultado: dict[str, dict] = {}
    for numero, linha in enumerate(linhas[1:], start=2):
        def valor(chave: str) -> str:
            i = indice[chave]
            return linha[i].strip() if i is not None and i < len(linha) else ""

        cnpj = apenas_digitos(valor("cnpj"))
        if not cnpj or not validar_documento(cnpj) or cnpj in resultado:
            continue
        resultado[cnpj] = {
            "cnpj": cnpj,
            "razao_social": valor("razao"),
            "uf": valor("uf").upper(),
            "senha": valor("senha"),
            "linha_csv": numero,
        }
    return resultado


def _indice_ou(colunas: list[str], nomes: tuple[str, ...]) -> int | None:
    for nome in nomes:
        if nome in colunas:
            return colunas.index(nome)
    return None


def _obter_ou_criar_empresa(
    db: Session,
    escritorio_id: int,
    cnpj: str,
    razao_social: str,
    uf: str,
    vistos: set[str],
) -> tuple[Empresa, bool]:
    """Retorna (empresa, criada_agora). Marca o CNPJ como visto no lote."""
    vistos.add(cnpj)
    empresa = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj)
        .first()
    )
    if empresa is not None:
        # Já existe: completa o que faltar (razão social vazia, UF), sem
        # sobrescrever dados já cadastrados pelo usuário.
        if not empresa.razao_social and razao_social:
            empresa.razao_social = razao_social[:255]
        if not empresa.uf and uf:
            empresa.uf = uf
        return empresa, False

    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social=(razao_social or f"Empresa {cnpj}")[:255],
        cnpj_cpf=cnpj,
        uf=uf,
    )
    db.add(empresa)
    db.flush()
    return empresa, True


def _criar_empresa_de_linha(
    cnpj: str,
    linha: dict,
    db: Session,
    escritorio_id: int,
    vistos: set[str],
) -> ItemLoteEmpresas:
    razao = (linha.get("razao_social") or "").strip()
    uf = (linha.get("uf") or "").upper()
    origem = f"CSV linha {linha.get('linha_csv', '?')}"

    if not razao:
        return ItemLoteEmpresas(origem=origem, cnpj_cpf=cnpj, status="erro", mensagem="Razão social vazia.")
    if uf not in _UFS_VALIDAS:
        return ItemLoteEmpresas(
            origem=origem, cnpj_cpf=cnpj, razao_social=razao, status="erro", mensagem=f"UF inválida: {uf!r}."
        )

    empresa, _criada_agora = _obter_ou_criar_empresa(
        db, escritorio_id, cnpj, razao, uf, vistos
    )
    return ItemLoteEmpresas(
        origem=origem,
        cnpj_cpf=cnpj,
        razao_social=empresa.razao_social,
        uf=empresa.uf,
        status="criada" if _criada_agora else "ja_existia",
        empresa_id=empresa.id,
    )
