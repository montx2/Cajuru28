"""
Importação em massa de empresas e certificados.

Recebe vários .pfx de uma vez (e/ou um CSV/XLSX) e já cria as empresas com CNPJ,
razão social e UF: CNPJ vem do certificado (campo ICP-Brasil) e a razão
social do subject do X.509. A senha é identificada automaticamente através
de padrões heurísticos (ex: EMPRESA2026, EMPRESA26, EMPRESA25), planilhas de
senhas anexadas, senhas comuns ou senha informada pelo usuário.

CSV ou Excel opcional (razao_social;cnpj_cpf;uf[;senha]) permite cadastrar empresas
sem certificado e/ou informar senha individual por CNPJ.
"""

from __future__ import annotations

import csv
import io
import os
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual, requer_escrita
from app.core.config import settings
from app.core.documentos import eh_cnpj_numerico, normalizar_documento
from app.core.vault import cifrar_segredo
from app.db.session import get_db
from app.models import (
    Certificado,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    EventoFiscalPendente,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusExecucao,
    Usuario,
)
from app.services import auditoria
from app.schemas import (
    ConsultaCNPJResposta,
    EmpresaAtualizar,
    EmpresaCriar,
    EmpresaResposta,
    EstadoSincronizacaoResposta,
    ItemLoteEmpresas,
    LoteEmpresasResposta,
    LoteTextoEntrada,
)
from app.api.routers.importacoes import estados_do_escritorio
from app.services.cnpj import consultar_cnpj
from app.services.certificados import (
    abrir_pfx_tentando_senhas,
    cnpj_de_nome_arquivo,
    guardar_pfx_protegido,
    validar_documento,
)
from app.services.senhas import (
    buscar_senhas_por_nome,
    construir_candidatas_pfx,
    fundir_planilhas_dados,
)

router = APIRouter(prefix="/empresas", tags=["empresas"])

_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

_LIMITE_ARQUIVOS = 600
_LIMITE_BYTES_PFX = 30 * 1024 * 1024  # 30 MB por .pfx (mesmo limite do CAJURUFINAL)
_LIMITE_BYTES_CSV = 10 * 1024 * 1024


def _empresa_do_escritorio(db: Session, empresa_id: int, escritorio_id: int) -> Empresa:
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")
    return empresa


def _validar_uf_ou_vazio(valor: str | None) -> str:
    uf = (valor or "").strip().upper()
    if uf and uf not in _UFS_VALIDAS:
        raise HTTPException(status_code=422, detail=f"UF inválida: {uf!r}")
    return uf


def _consulta_publica(cnpj_cpf: str):
    """Consulta BrasilAPI somente para CNPJ numérico; alfa segue manualmente."""
    if not eh_cnpj_numerico(cnpj_cpf):
        return None
    return consultar_cnpj(cnpj_cpf)


def _completar_dados_empresa(dados: EmpresaCriar) -> dict:
    """
    Aplica o preenchimento automático de UF/razão social pelo CNPJ.

    A UF continua obrigatória para salvar porque NFe/CT-e precisam dela; a
    diferença é que agora o sistema tenta descobri-la antes de pedir que o
    operador escolha manualmente.
    """
    documento = normalizar_documento(dados.cnpj_cpf)
    uf = _validar_uf_ou_vazio(dados.uf)
    razao = (dados.razao_social or "").strip()
    codigo_ibge = dados.codigo_ibge

    # A consulta também entrega o IBGE municipal de sete dígitos. Buscar mesmo
    # quando razão/UF já vieram preenchidas elimina um bloqueio do cadastro
    # consulta externa sem substituir dado manual informado pelo operador.
    consulta = _consulta_publica(documento) if (eh_cnpj_numerico(documento) and (not uf or not razao or not codigo_ibge)) else None
    if consulta is not None:
        uf = uf or _validar_uf_ou_vazio(consulta.uf)
        razao = razao or consulta.razao_social or consulta.nome_fantasia
        codigo_ibge = codigo_ibge or consulta.codigo_ibge or None

    if not razao:
        raise HTTPException(
            status_code=422,
            detail="Razão social não identificada automaticamente. Informe o nome da empresa.",
        )
    if not uf:
        raise HTTPException(
            status_code=422,
            detail="Não foi possível identificar a UF automaticamente. Informe a UF manualmente.",
        )

    return {
        "razao_social": razao[:255],
        "cnpj_cpf": documento,
        "uf": uf,
        "codigo_ibge": codigo_ibge,
        "inscricao_municipal": dados.inscricao_municipal,
    }


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
    usuario: Usuario = Depends(requer_escrita),
):
    dados_empresa = _completar_dados_empresa(dados)
    ja_existe = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == dados_empresa["cnpj_cpf"])
        .first()
    )
    if ja_existe:
        raise HTTPException(status_code=409, detail="Já existe uma empresa com esse CNPJ/CPF")

    empresa = Empresa(escritorio_id=escritorio_id, **dados_empresa)
    db.add(empresa)
    db.flush()
    auditoria.registrar(
        db, usuario, "empresa_criada",
        entidade="empresa", entidade_id=empresa.id,
        detalhe=f"{empresa.razao_social} ({empresa.cnpj_cpf}/{empresa.uf})",
    )
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/consulta-cnpj/{cnpj}", response_model=ConsultaCNPJResposta)
def consultar_cadastro_publico_cnpj(
    cnpj: str,
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Pré-preenche razão social e UF pelo CNPJ para deixar o cadastro simples."""
    del escritorio_id  # mantém o endpoint protegido pelo tenant/autenticação
    try:
        documento = normalizar_documento(cnpj)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not eh_cnpj_numerico(documento):
        return ConsultaCNPJResposta(
            documento=documento,
            encontrado=False,
            mensagem="CNPJ alfanumérico: informe razão social e UF manualmente até a fonte pública confirmar suporte.",
        )
    dados = consultar_cnpj(documento)
    if dados is None:
        return ConsultaCNPJResposta(
            documento=documento,
            encontrado=False,
            mensagem="Não foi possível consultar esse CNPJ agora. Preencha a UF manualmente.",
        )
    return ConsultaCNPJResposta(
        documento=documento,
        encontrado=True,
        razao_social=dados.razao_social,
        nome_fantasia=dados.nome_fantasia,
        uf=dados.uf,
        municipio=dados.municipio,
        codigo_ibge=dados.codigo_ibge,
        fonte=dados.fonte,
        mensagem="Dados encontrados automaticamente.",
    )


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
    usuario: Usuario = Depends(requer_escrita),
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
    auditoria.registrar(
        db, usuario, "empresa_atualizada",
        entidade="empresa", entidade_id=empresa.id,
        detalhe=f"{empresa.razao_social}: {', '.join(sorted(mudanca)) or 'sem mudanças'}",
    )
    db.commit()
    db.refresh(empresa)
    return empresa


@router.delete("/{empresa_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """Exclui a empresa e todos os seus certificados, documentos e históricos."""
    empresa = _empresa_do_escritorio(db, empresa_id, escritorio_id)
    em_andamento = (
        db.query(ExecucaoImportacao.id)
        .filter(
            ExecucaoImportacao.empresa_id == empresa.id,
            ExecucaoImportacao.status == StatusExecucao.EM_ANDAMENTO,
        )
        .first()
    )
    if em_andamento:
        raise HTTPException(
            status_code=409,
            detail="Aguarde a importação em andamento terminar antes de excluir a empresa.",
        )

    caminhos = [c.arquivo_path for c in db.query(Certificado).filter_by(empresa_id=empresa.id)]
    caminhos += [d.xml_path for d in db.query(DocumentoFiscal).filter_by(empresa_id=empresa.id) if d.xml_path]
    caminhos += [f.xml_path for f in db.query(DocumentoFiscalFonte).join(DocumentoFiscal, DocumentoFiscal.id == DocumentoFiscalFonte.documento_id).filter(DocumentoFiscal.empresa_id == empresa.id) if f.xml_path]

    db.query(EventoFiscalPendente).filter(EventoFiscalPendente.empresa_id == empresa.id).delete()
    db.query(SincronizacaoDFe).filter(SincronizacaoDFe.empresa_id == empresa.id).delete()
    db.query(ExecucaoImportacao).filter(ExecucaoImportacao.empresa_id == empresa.id).delete()
    db.query(DocumentoFiscalFonte).filter(
        DocumentoFiscalFonte.documento_id.in_(
            db.query(DocumentoFiscal.id).filter(DocumentoFiscal.empresa_id == empresa.id)
        )
    ).delete(synchronize_session=False)
    db.query(DocumentoFiscal).filter(DocumentoFiscal.empresa_id == empresa.id).delete()
    db.query(Certificado).filter(Certificado.empresa_id == empresa.id).delete()
    db.delete(empresa)
    db.flush()

    for caminho in caminhos:
        try:
            if caminho and os.path.exists(caminho):
                os.remove(caminho)
        except OSError:
            pass

    auditoria.registrar(
        db, usuario, "empresa_excluida",
        entidade="empresa", entidade_id=empresa.id,
        detalhe=f"{empresa.razao_social} ({empresa.cnpj_cpf})",
    )
    db.commit()


@router.get("/{empresa_id}/sincronizacao", response_model=list[EstadoSincronizacaoResposta])
@router.get("/{empresa_id}/sincronismo", response_model=list[EstadoSincronizacaoResposta])
def obter_sincronismo_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Cursor, maxNSU, janelas e bloqueios desta empresa — por tipo de documento."""
    _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return estados_do_escritorio(db, escritorio_id=escritorio_id, empresa_id=empresa_id)


@router.post("/lote", response_model=LoteEmpresasResposta)
async def importar_empresas_em_massa(
    uf_padrao: str = Form(""),
    senha: str = Form(""),
    arquivos: list[UploadFile] = File(default=[]),
    csv_arquivos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Cadastra várias empresas de uma vez.

    - `arquivos`: um ou mais .pfx/.p12 (A1). Para cada um, abre com senha inteligente
      (padrões comuns como EMPRESA2026, EMPRESA26, EMPRESA25, senhas das planilhas ou
      a senha global informada), extrai CNPJ/razão social do certificado, cria a empresa
      e grava o certificado cifrado.
    - `csv_arquivos`: opcional, uma ou mais planilhas (.xlsx, .xlsm, .csv, .txt)
      de senhas com colunas `razao_social;cnpj_cpf;uf` e opcionalmente `senha`.
    - `uf_padrao`: compatibilidade com clientes antigos; o front-end consulta a
      UF pelo CNPJ e não escolhe uma UF arbitrária para o lote.
    """
    uf_padrao = (uf_padrao or "").strip().upper()
    if uf_padrao and uf_padrao not in _UFS_VALIDAS:
        raise HTTPException(status_code=400, detail=f"UF padrão inválida: {uf_padrao!r}")

    if not arquivos and not csv_arquivos:
        raise HTTPException(
            status_code=400, detail="Envie ao menos um arquivo .pfx ou um CSV."
        )
    if len(arquivos) > _LIMITE_ARQUIVOS:
        raise HTTPException(
            status_code=400,
            detail=f"Limite de {_LIMITE_ARQUIVOS} arquivos por lote.",
        )

    # Linhas do CSV/Excel por CNPJ (senha/UF/razão por empresa, se informadas)
    linhas_csv, todas_senhas, lista_planilhas = await _fundir_planilhas(csv_arquivos)
    resultados: list[ItemLoteEmpresas] = []
    vistos: set[str] = set()

    # 1) Arquivos .pfx — empresas + certificados. A pasta pode trazer o
    # certificado antigo e o atualizado do mesmo CNPJ: sobrevive a versão de
    # maior validade real (X.509), não a primeira da lista.
    planos_pfx = await _escolher_versoes(
        arquivos,
        senha=senha,
        linhas_csv=linhas_csv,
        todas_senhas=todas_senhas,
        lista_planilhas=lista_planilhas,
        db=db,
        escritorio_id=escritorio_id,
    )

    for passo in planos_pfx:
        if isinstance(passo, ItemLoteEmpresas):
            resultados.append(passo)
            continue
        resultados.append(
            await _processar_pfx(
                passo,
                senha=senha,
                uf_padrao=uf_padrao,
                linhas_csv=linhas_csv,
                todas_senhas=todas_senhas,
                lista_planilhas=lista_planilhas,
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
        resultados.append(_criar_empresa_de_linha(cnpj, linha, db, escritorio_id, vistos, uf_padrao))

    criadas = sum(1 for r in resultados if r.status == "criada")
    certificados = sum(1 for r in resultados if r.status == "certificado_atualizado")
    ja_existiam = sum(1 for r in resultados if r.status == "ja_existia")
    erros = sum(1 for r in resultados if r.status == "erro")
    substituidos = sum(1 for r in resultados if r.status == "substituido")
    auditoria.registrar(
        db, usuario, "empresas_lote",
        detalhe=(
            f"{len(resultados)} itens: {criadas} criadas, {certificados} certificados, "
            f"{erros} erros"
            + (f", {substituidos} versões antigas descartadas" if substituidos else "")
        ),
    )
    db.commit()

    return LoteEmpresasResposta(
        total=len(resultados),
        criadas=criadas,
        certificados=certificados,
        ja_existiam=ja_existiam,
        erros=erros,
        itens=resultados,
    )


@router.post("/lote-texto", response_model=LoteEmpresasResposta)
def cadastrar_empresas_de_pendencias(
    dados: LoteTextoEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    O botão "Cadastrar estas empresas" do resultado de uma importação de lista.
    """
    resultados: list[ItemLoteEmpresas] = []
    vistos: set[str] = set()
    for pendencia in dados.empresas:
        try:
            documento = normalizar_documento(pendencia.documento)
        except ValueError:
            resultados.append(
                ItemLoteEmpresas(
                    origem="Pendência da importação",
                    cnpj_cpf=pendencia.documento.strip()[:30],
                    razao_social=pendencia.razao_social.strip()[:255],
                    status="erro",
                    mensagem="Documento inválido: confira o valor na origem.",
                )
            )
            continue
        resultados.append(
            _criar_empresa_de_linha(
                documento,
                {"razao_social": pendencia.razao_social.strip()},
                db,
                escritorio_id,
                vistos,
                uf_padrao="",
                origem="Pendência da importação",
            )
        )

    criadas = sum(1 for r in resultados if r.status == "criada")
    ja_existiam = sum(1 for r in resultados if r.status == "ja_existia")
    erros = sum(1 for r in resultados if r.status == "erro")
    auditoria.registrar(
        db,
        usuario,
        "empresas_lote_pendencias",
        detalhe=(
            f"{len(resultados)} pendências: {criadas} criadas, "
            f"{ja_existiam} já existiam, {erros} sem UF/documento"
        ),
    )
    db.commit()

    return LoteEmpresasResposta(
        total=len(resultados),
        criadas=criadas,
        certificados=0,
        ja_existiam=ja_existiam,
        erros=erros,
        itens=resultados,
    )


async def _escolher_versoes(
    arquivos: list[UploadFile],
    *,
    senha: str,
    linhas_csv: dict[str, dict],
    todas_senhas: list[str] | None = None,
    lista_planilhas: list[dict] | None = None,
    db: Session | None = None,
    escritorio_id: int = 0,
) -> list[UploadFile | ItemLoteEmpresas]:
    """
    A pasta do escritório costuma ter o certificado antigo e o atualizado do
    mesmo CNPJ. Quem decide qual fica é o próprio X.509, não a ordem em que o
    navegador listou os arquivos: para cada CNPJ com mais de uma versão,
    sobrevive a de maior validade e as demais entram no resultado como
    "substituido".
    """
    plano: list[UploadFile | ItemLoteEmpresas] = list(arquivos)
    grupos: dict[str, list[int]] = {}
    for indice, arquivo in enumerate(arquivos):
        nome = (arquivo.filename or "").lower()
        if not nome.endswith((".pfx", ".p12")):
            continue
        cnpj = cnpj_de_nome_arquivo(arquivo.filename or "")
        if cnpj:
            grupos.setdefault(cnpj, []).append(indice)

    for cnpj, indices in grupos.items():
        if len(indices) < 2:
            continue

        linha_csv = linhas_csv.get(cnpj, {})
        razao = linha_csv.get("razao_social") or ""
        if not razao and db is not None:
            emp = db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj).first()
            if emp:
                razao = emp.razao_social

        senhas_decl = list(linha_csv.get("senhas", []))
        if not senhas_decl and razao and lista_planilhas:
            senhas_decl.extend(buscar_senhas_por_nome(razao, lista_planilhas))

        abertos: dict[int, datetime] = {}
        for indice in indices:
            conteudo = await arquivos[indice].read()
            await arquivos[indice].seek(0)
            candidatas = construir_candidatas_pfx(
                nome_arquivo=arquivos[indice].filename or "",
                cnpj=cnpj,
                razao_social=razao,
                senhas_declaradas=senhas_decl,
                senha_global=senha,
                todas_senhas_planilha=todas_senhas,
            )
            try:
                identidade, _ = abrir_pfx_tentando_senhas(conteudo, candidatas)
                abertos[indice] = identidade.validade_utc
            except ValueError:
                continue

        vencedor = max(abertos, key=abertos.get) if abertos else indices[0]
        nome_vencedor = arquivos[vencedor].filename or "arquivo.pfx"
        validade_vencedor = abertos.get(vencedor)
        for indice in indices:
            if indice == vencedor:
                continue
            if validade_vencedor is not None:
                mensagem = (
                    f"Versão antiga deixada de fora: {nome_vencedor} vale até "
                    f"{validade_vencedor.strftime('%d/%m/%Y')}."
                )
            else:
                mensagem = (
                    f"Outra versão do mesmo CNPJ ({nome_vencedor}) foi processada no lugar."
                )
            plano[indice] = ItemLoteEmpresas(
                origem=arquivos[indice].filename or "arquivo.pfx",
                cnpj_cpf=cnpj,
                status="substituido",
                mensagem=mensagem,
                validade=abertos.get(indice),
            )
    return plano


async def _processar_pfx(
    arquivo: UploadFile,
    *,
    senha: str,
    uf_padrao: str,
    linhas_csv: dict[str, dict],
    todas_senhas: list[str] | None = None,
    lista_planilhas: list[dict] | None = None,
    db: Session,
    escritorio_id: int,
    vistos: set[str],
) -> ItemLoteEmpresas:
    nome = arquivo.filename or "arquivo.pfx"
    if not nome.lower().endswith((".pfx", ".p12")):
        return ItemLoteEmpresas(
            origem=nome, status="erro", mensagem="Extensão não suportada (use .pfx ou .p12)."
        )

    conteudo = await arquivo.read(_LIMITE_BYTES_PFX + 1)
    if len(conteudo) > _LIMITE_BYTES_PFX:
        return ItemLoteEmpresas(
            origem=nome,
            status="erro",
            mensagem=f"Arquivo maior que {_LIMITE_BYTES_PFX // (1024 * 1024)} MB.",
        )
    if not conteudo:
        return ItemLoteEmpresas(origem=nome, status="erro", mensagem="Arquivo vazio.")

    cnpj_nome = cnpj_de_nome_arquivo(nome)
    linha_csv = linhas_csv.get(cnpj_nome, {})
    razao_conhecida = linha_csv.get("razao_social") or ""
    uf_da_empresa = ""
    if cnpj_nome:
        empresa_existente = (
            db.query(Empresa)
            .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj_nome)
            .first()
        )
        if empresa_existente:
            razao_conhecida = razao_conhecida or empresa_existente.razao_social
            uf_da_empresa = empresa_existente.uf or ""

    senhas_declaradas = [s.strip() for s in linha_csv.get("senhas", []) if s.strip()]
    if senha.strip() and senha.strip() not in senhas_declaradas:
        senhas_declaradas.append(senha.strip())
    if not senhas_declaradas and razao_conhecida and lista_planilhas:
        senhas_declaradas.extend(buscar_senhas_por_nome(razao_conhecida, lista_planilhas))

    candidatas = construir_candidatas_pfx(
        nome_arquivo=nome,
        cnpj=cnpj_nome,
        razao_social=razao_conhecida,
        senhas_declaradas=senhas_declaradas,
        senha_global=senha,
        todas_senhas_planilha=todas_senhas,
    )

    try:
        identidade, senha_efetiva = abrir_pfx_tentando_senhas(conteudo, candidatas)
        cnpj = identidade.documento
    except ValueError as exc_inicial:
        sucesso = False
        if cnpj_nome and eh_cnpj_numerico(cnpj_nome) and not razao_conhecida:
            try:
                publico = _consulta_publica(cnpj_nome)
                if publico and publico.razao_social:
                    novas_candidatas = construir_candidatas_pfx(
                        nome_arquivo=nome,
                        cnpj=cnpj_nome,
                        razao_social=publico.razao_social,
                        senhas_declaradas=buscar_senhas_por_nome(publico.razao_social, lista_planilhas or []),
                        senha_global=senha,
                        todas_senhas_planilha=todas_senhas,
                    )
                    identidade, senha_efetiva = abrir_pfx_tentando_senhas(conteudo, novas_candidatas)
                    cnpj = identidade.documento
                    sucesso = True
            except Exception:
                pass

        if not sucesso:
            if len(senhas_declaradas) > 1:
                msg_erro = (
                    "Não foi possível abrir o certificado com a senha informada "
                    f"(senha incorreta ou arquivo corrompido). Foram testadas {len(senhas_declaradas)} senha(s) declaradas para este CNPJ "
                    "(as das planilhas anexadas e a senha global)."
                )
            else:
                msg_erro = str(exc_inicial)
            return ItemLoteEmpresas(
                origem=nome,
                cnpj_cpf=cnpj_nome,
                status="erro",
                mensagem=msg_erro,
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
    if not uf_da_empresa:
        empresa_existente = (
            db.query(Empresa)
            .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj)
            .first()
        )
        uf_da_empresa = empresa_existente.uf if empresa_existente else ""

    publico = None
    if not (linha.get("uf") or uf_padrao or uf_da_empresa):
        publico = _consulta_publica(cnpj)
    uf = (linha.get("uf") or uf_padrao or uf_da_empresa or (publico.uf if publico else "")).upper()

    # A UF define o cUFAutor da consulta de NF-e/CT-e. Assumir SP aqui fazia
    # uma empresa de outro estado parecer cadastrada e só falhar na SEFAZ muito
    # depois. Quando a consulta pública não resolver, o resultado explica como
    # completar o dado sem exibir um campo arbitrário para todo lote.
    if uf not in _UFS_VALIDAS:
        return ItemLoteEmpresas(
            origem=nome,
            cnpj_cpf=cnpj,
            razao_social=identidade.razao_social,
            status="erro",
            mensagem="UF não identificada automaticamente. Anexe uma planilha de apoio com as colunas CNPJ e UF e importe este certificado novamente.",
        )

    razao = (
        linha.get("razao_social")
        or (publico.razao_social if publico else "")
        or identidade.razao_social
    ).strip()
    empresa, criada_agora = _obter_ou_criar_empresa(
        db, escritorio_id, cnpj, razao, uf, vistos
    )

    pasta = os.path.join(settings.dados_dir, "certificados", str(empresa.id))
    caminho = os.path.join(pasta, f"{cnpj}.pfx.enc")
    guardar_pfx_protegido(caminho, conteudo)

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

    venceu = identidade.validade_utc.strftime("%d/%m/%Y")
    if identidade.validade_utc <= datetime.now(timezone.utc):
        mensagem = (
            f"Certificado EXPIRADO (venceu em {venceu}) — vinculado, mas não serve para "
            f"capturar: envie a versão atualizada e ele assume no lugar."
        )
    else:
        mensagem = f"Certificado vinculado (válido até {venceu})."

    return ItemLoteEmpresas(
        origem=nome,
        cnpj_cpf=cnpj,
        razao_social=empresa.razao_social,
        uf=empresa.uf,
        status="criada" if criada_agora else "certificado_atualizado",
        mensagem=mensagem,
        empresa_id=empresa.id,
        certificado_id=certificado.id,
        validade=identidade.validade_utc,
    )


async def _fundir_planilhas(
    arquivos: list[UploadFile],
) -> tuple[dict[str, dict], list[str], list[dict]]:
    """
    Lê e funde uma ou mais planilhas (.xlsx, .xlsm, .csv, .txt) em:
    (dicionário_por_cnpj, todas_senhas_unicas, lista_completa_linhas).
    """
    planilhas_bytes: list[tuple[str, bytes]] = []
    for arquivo in arquivos:
        conteudo = await arquivo.read(_LIMITE_BYTES_CSV + 1)
        if len(conteudo) > _LIMITE_BYTES_CSV:
            raise HTTPException(
                status_code=413,
                detail=f"Planilha {arquivo.filename or ''} maior que 10 MB.",
            )
        planilhas_bytes.append((arquivo.filename or "", conteudo))
    try:
        return fundir_planilhas_dados(planilhas_bytes)
    except ValueError as erro:
        # Planilha malformada não pode virar 500: recusa clara para o operador
        # corrigir o arquivo e reenviar, em vez de "falha interna" genérica.
        raise HTTPException(status_code=400, detail=str(erro)) from erro


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
    uf_padrao: str = "",
    origem: str | None = None,
) -> ItemLoteEmpresas:
    origem = origem or f"Linha {linha.get('linha_csv', '?')}"
    razao = (linha.get("razao_social") or "").strip()

    existente = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj)
        .first()
    )
    if existente is not None:
        empresa, _ = _obter_ou_criar_empresa(db, escritorio_id, cnpj, razao, "", vistos)
        return ItemLoteEmpresas(
            origem=origem,
            cnpj_cpf=cnpj,
            razao_social=empresa.razao_social,
            uf=empresa.uf,
            status="ja_existia",
            empresa_id=empresa.id,
        )

    publico = None
    if not (linha.get("uf") or uf_padrao):
        publico = _consulta_publica(cnpj)
    razao = razao or (publico.razao_social if publico else "")
    uf = (linha.get("uf") or uf_padrao or (publico.uf if publico else "")).upper()

    if not razao:
        return ItemLoteEmpresas(
            origem=origem,
            cnpj_cpf=cnpj,
            status="erro",
            mensagem="Razão social não identificada. Informe no CSV.",
        )
    if uf not in _UFS_VALIDAS:
        return ItemLoteEmpresas(
            origem=origem,
            cnpj_cpf=cnpj,
            razao_social=razao,
            status="erro",
            mensagem="UF não identificada automaticamente. Informe no CSV ou em UF padrão.",
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
