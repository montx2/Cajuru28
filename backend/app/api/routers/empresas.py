"""
Importação em massa de empresas e certificados.

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
    cnpj_de_nome_arquivo,
    extrair_identidade,
    guardar_pfx_protegido,
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
    caminhos += [d.xml_path for d in db.query(DocumentoFiscal).filter_by(empresa_id=empresa.id)]
    nome, documento = empresa.razao_social, empresa.cnpj_cpf

    # Ordem explícita para funcionar igualmente em SQLite e PostgreSQL, sem
    # depender de cascatas configuradas no banco instalado.
    db.query(EventoFiscalPendente).filter_by(empresa_id=empresa.id).delete(synchronize_session=False)
    # Exclusão local apaga apenas o acervo deste sistema:
    # esse DELETE também apaga as notas remotas, então só o operador pode fazer
    # isso conscientemente fora deste fluxo.
    ids_documentos = db.query(DocumentoFiscal.id).filter_by(empresa_id=empresa.id).subquery()
    db.query(DocumentoFiscalFonte).filter(DocumentoFiscalFonte.documento_id.in_(ids_documentos)).delete(synchronize_session=False)
    db.query(DocumentoFiscal).filter_by(empresa_id=empresa.id).delete(synchronize_session=False)
    db.query(ExecucaoImportacao).filter_by(empresa_id=empresa.id).delete(synchronize_session=False)
    db.query(SincronizacaoDFe).filter_by(empresa_id=empresa.id).delete(synchronize_session=False)
    db.query(Certificado).filter_by(empresa_id=empresa.id).delete(synchronize_session=False)
    db.delete(empresa)
    auditoria.registrar(
        db, usuario, "empresa_excluida", entidade="empresa", entidade_id=empresa_id,
        detalhe=f"{nome} ({documento}); documentos e certificado removidos",
    )
    db.commit()

    for caminho in caminhos:
        try:
            if caminho and os.path.isfile(caminho):
                os.remove(caminho)
        except OSError:
            # A exclusão dos dados não deve falhar por um XML já ausente ou
            # volume temporariamente indisponível.
            pass
    return None


@router.get("/{empresa_id}/sincronizacao", response_model=list[EstadoSincronizacaoResposta])
def sincronizacao_da_empresa(
    empresa_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Cursor, maxNSU, janelas e bloqueios desta empresa — por tipo de documento."""
    _empresa_do_escritorio(db, empresa_id, escritorio_id)
    return estados_do_escritorio(db, escritorio_id=escritorio_id, empresa_id=empresa_id)


@router.post("/lote", response_model=LoteEmpresasResposta)
async def importar_empresas_em_massa(
    uf_padrao: str = Form("SP"),
    senha: str = Form(""),
    arquivos: list[UploadFile] = File(default=[]),
    csv_arquivos: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """
    Cadastra várias empresas de uma vez.

    - `arquivos`: um ou mais .pfx/.p12 (A1). Para cada um, abre com a
      `senha`, extrai CNPJ/razão social do certificado, cria a empresa e
      grava o certificado cifrado.
    - `csv_arquivos`: opcional, uma ou mais planilhas de senhas (a atual e a
      antiga, por exemplo) com colunas `razao_social;cnpj_cpf;uf` (ou
      nome;cnpj;uf) e, opcionalmente, `senha` individual. As senhas de todas
      as planilhas são candidatas; a que abre o certificado é a guardada.
      Linhas sem certificado ainda cadastram a empresa.
    - `uf_padrao`: fallback opcional. Se ficar vazio, a UF é tentada pelo CNPJ
      e só as empresas sem retorno público pedem correção manual.
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

    # Linhas do CSV por CNPJ (senha/UF/razão por empresa, se informadas)
    linhas_csv = await _fundir_planilhas(csv_arquivos)
    resultados: list[ItemLoteEmpresas] = []
    vistos: set[str] = set()

    # 1) Arquivos .pfx — empresas + certificados. A pasta pode trazer o
    # certificado antigo e o atualizado do mesmo CNPJ: sobrevive a versão de
    # maior validade real (X.509), não a primeira da lista.
    for passo in await _escolher_versoes(arquivos, senha=senha, linhas_csv=linhas_csv):
        if isinstance(passo, ItemLoteEmpresas):
            resultados.append(passo)
            continue
        resultados.append(
            await _processar_pfx(
                passo,
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

    A lista importada (procurações do painel, relatórios) já trouxe nome e
    CNPJ de quem está fora da carteira — este endpoint cadastra quem o
    operador marcou, sem redigitação. A UF vem da consulta pública pelo CNPJ;
    sem UF confirmada a empresa **não** é criada (cadastro fiscal incompleto
    contaminaria apuração e emissão) e a pendência continua dizendo o que
    falta. A razão social é a da lista: a fonte já a escreveu como o
    escritório a reconhece.
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
) -> list[UploadFile | ItemLoteEmpresas]:
    """
    A pasta do escritório costuma ter o certificado antigo e o atualizado do
    mesmo CNPJ. Quem decide qual fica é o próprio X.509, não a ordem em que o
    navegador listou os arquivos: para cada CNPJ com mais de uma versão,
    sobrevive a de maior validade e as demais entram no resultado como
    "substituido" — o operador vê o que ficou de fora e até quando o mantido
    vale. Arquivo que nem abre com a senha do CNPJ não é candidata; se
    nenhuma abrir, a primeira segue para o `_processar_pfx` produzir o erro
    de senha honesto.
    """
    plano: list[UploadFile | ItemLoteEmpresas] = list(arquivos)
    grupos: dict[str, list[int]] = {}
    for indice, arquivo in enumerate(arquivos):
        nome = (arquivo.filename or "").lower()
        if not nome.endswith((".pfx", ".p12")):
            continue  # extensão errada segue para o _processar_pfx dar o erro honesto
        cnpj = cnpj_de_nome_arquivo(arquivo.filename or "")
        if cnpj:
            grupos.setdefault(cnpj, []).append(indice)

    for cnpj, indices in grupos.items():
        if len(indices) < 2:
            continue
        candidatas = _senhas_candidatas(linhas_csv.get(cnpj) or {}, senha)
        abertos: dict[int, datetime] = {}
        for indice in indices:
            conteudo = await arquivos[indice].read()
            await arquivos[indice].seek(0)
            try:
                # A versão antiga costuma abrir com a senha da planilha
                # antiga, e a atualizada com a da planilha nova: quem decide
                # qual é qual é a validade do próprio X.509.
                identidade, _ = _abrir_com_alguma_senha(conteudo, candidatas)
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


def _senhas_candidatas(linha_csv: dict, senha_global: str) -> list[str]:
    """
    Senhas DECLARADAS para um CNPJ: as das planilhas anexadas (atual e
    antiga, se houverem) e, por último, a senha global do formulário. Não é
    adivinhação nem força bruta — cada candidata foi escrita pelo operador, e
    a que abre o certificado é a que vai para o cofre.
    """
    candidatas: list[str] = []
    for senha in [(s or "").strip() for s in linha_csv.get("senhas", [])]:
        if senha and senha not in candidatas:
            candidatas.append(senha)
    senha_global = (senha_global or "").strip()
    if senha_global and senha_global not in candidatas:
        candidatas.append(senha_global)
    return candidatas


def _abrir_com_alguma_senha(
    conteudo: bytes, candidatas: list[str]
) -> tuple[object, str]:
    """Abre o PFX com a primeira senha declarada que servir."""
    for tentativa in candidatas:
        try:
            return extrair_identidade(conteudo, tentativa), tentativa
        except ValueError:
            continue
    detalhe = (
        f" Foram testadas {len(candidatas)} senha(s) declaradas para este CNPJ "
        "(as das planilhas anexadas e a senha global)."
        if len(candidatas) > 1
        else ""
    )
    raise ValueError(
        "Não foi possível abrir o certificado com a senha informada "
        f"(senha incorreta ou arquivo corrompido).{detalhe}"
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

    conteudo = await arquivo.read(_LIMITE_BYTES_PFX + 1)
    if len(conteudo) > _LIMITE_BYTES_PFX:
        return ItemLoteEmpresas(
            origem=nome,
            status="erro",
            mensagem=f"Arquivo maior que {_LIMITE_BYTES_PFX // (1024 * 1024)} MB.",
        )
    if not conteudo:
        return ItemLoteEmpresas(origem=nome, status="erro", mensagem="Arquivo vazio.")

    # As senhas declaradas para este CNPJ (planilhas anexadas + senha
    # global): a primeira que abre o certificado é a efetiva — a certa pode
    # estar na planilha antiga quando a empresa trocou de senha ao renovar.
    cnpj_nome = cnpj_de_nome_arquivo(nome)
    linha_csv = linhas_csv.get(cnpj_nome, {})
    candidatas = _senhas_candidatas(linha_csv, senha)

    try:
        identidade, senha_efetiva = _abrir_com_alguma_senha(conteudo, candidatas)
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
    publico = None
    if not (linha.get("uf") or uf_padrao):
        publico = _consulta_publica(cnpj)
    uf = (linha.get("uf") or uf_padrao or (publico.uf if publico else "")).upper()
    if uf not in _UFS_VALIDAS:
        return ItemLoteEmpresas(
            origem=nome,
            cnpj_cpf=cnpj,
            razao_social=identidade.razao_social,
            status="erro",
            mensagem="UF não identificada automaticamente. Informe no CSV ou em UF padrão.",
        )

    razao = (
        linha.get("razao_social")
        or (publico.razao_social if publico else "")
        or identidade.razao_social
    ).strip()
    empresa, criada_agora = _obter_ou_criar_empresa(
        db, escritorio_id, cnpj, razao, uf, vistos
    )

    # Arquivo e senha ficam cifrados; o PFX em claro só existe nesta requisição.
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


async def _fundir_planilhas(arquivos: list[UploadFile]) -> dict[str, dict]:
    """
    Uma ou mais planilhas de senhas (a atual e a antiga, por exemplo) viram
    um dicionário único por CNPJ. Razão social e UF vêm da primeira planilha
    que as trouxe; as senhas de TODAS viram candidatas, na ordem em que
    foram anexadas — quem decide qual abre é o certificado.
    """
    fundido: dict[str, dict] = {}
    for arquivo in arquivos:
        for cnpj, linha in (await _ler_csv(arquivo)).items():
            if cnpj not in fundido:
                fundido[cnpj] = {
                    "cnpj": cnpj,
                    "razao_social": (linha.get("razao_social") or "").strip(),
                    "uf": (linha.get("uf") or "").strip().upper(),
                    "senhas": [],
                    "linha_csv": linha.get("linha_csv"),
                }
            atual = fundido[cnpj]
            for chave in ("razao_social", "uf"):
                if not atual.get(chave) and linha.get(chave):
                    atual[chave] = linha[chave]
            senha = (linha.get("senha") or "").strip()
            if senha and senha not in atual["senhas"]:
                atual["senhas"].append(senha)
    return fundido


async def _ler_csv(arquivo: UploadFile | None) -> dict[str, dict]:
    if arquivo is None:
        return {}
    # Limite na leitura, não depois: multipart grande não deve ocupar memória
    # da API só para descobrir que ultrapassou a regra do lote.
    conteudo = await arquivo.read(_LIMITE_BYTES_CSV + 1)
    if len(conteudo) > _LIMITE_BYTES_CSV:
        raise HTTPException(status_code=413, detail="CSV maior que 5 MB.")
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1", errors="replace")

    linhas = _linhas_do_csv(texto)
    if not linhas:
        return {}

    cabecalho = [_normalizar_cabecalho(celula) for celula in linhas[0]]
    indice = {
        "razao": _indice_ou(cabecalho, ("razao_social", "razaosocial", "nome", "empresa", "razao")),
        "cnpj": _indice_ou(cabecalho, ("cnpj_cpf", "cnpj", "cpf", "documento", "doc")),
        "uf": _indice_ou(cabecalho, ("uf", "estado")),
        "senha": _indice_ou(cabecalho, ("senha", "password")),
    }
    if indice["cnpj"] is None:
        # Sem cabeçalho reconhecível, resta o formato curto da "planilha de
        # senhas": `documento;senha` (ou `documento;senha;uf`). Qualquer coisa
        # mais ambígua não é interpretada — adivinhar coluna é inventar dado.
        return _ler_csv_sem_cabecalho(linhas)

    resultado: dict[str, dict] = {}
    for numero, linha in enumerate(linhas[1:], start=2):
        def valor(chave: str) -> str:
            i = indice[chave]
            return linha[i].strip() if i is not None and i < len(linha) else ""

        try:
            cnpj = normalizar_documento(valor("cnpj"))
        except ValueError:
            continue
        if not validar_documento(cnpj) or cnpj in resultado:
            continue
        resultado[cnpj] = {
            "cnpj": cnpj,
            "razao_social": valor("razao"),
            "uf": valor("uf").upper(),
            "senha": valor("senha"),
            "linha_csv": numero,
        }
    return resultado


def _separador_do_csv(texto: str) -> str:
    """`;` é o padrão de planilha brasileira — `,` aparece em export de fora.

    Quem tem mais ocorrências NA PRIMEIRA LINHA com conteúdo vence; empate
    fica com `;`. Tab é o terceiro candidato (copiar-e-colar do Excel).
    """
    primeira = next((linha for linha in texto.splitlines() if linha.strip()), "")
    contagens = {
        ";": primeira.count(";"),
        ",": primeira.count(","),
        "\t": primeira.count("\t"),
    }
    return max(contagens, key=lambda separador: contagens[separador])


def _linhas_do_csv(texto: str) -> list[list[str]]:
    leitor = csv.reader(io.StringIO(texto), delimiter=_separador_do_csv(texto))
    return [linha for linha in leitor if any(celula.strip() for celula in linha)]


def _normalizar_cabecalho(celula: str) -> str:
    """minúsculo, sem acento, espaços viram `_` — "Razão Social" → "razao_social"."""
    texto = unicodedata.normalize("NFD", celula.strip().lower())
    sem_acento = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return sem_acento.replace(" ", "_")


def _ler_csv_sem_cabecalho(linhas: list[list[str]]) -> dict[str, dict]:
    resultado: dict[str, dict] = {}
    for numero, linha in enumerate(linhas, start=1):
        if len(linha) < 2:
            continue
        try:
            cnpj = normalizar_documento(linha[0])
        except ValueError:
            continue
        if not validar_documento(cnpj) or cnpj in resultado:
            continue
        uf = linha[2].strip().upper() if len(linha) >= 3 else ""
        if len(linha) >= 3 and uf not in _UFS_VALIDAS:
            # Terceira coluna que não é UF = formato desconhecido: não inventa.
            continue
        resultado[cnpj] = {
            "cnpj": cnpj,
            "razao_social": "",
            "uf": uf,
            "senha": linha[1].strip(),
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
    uf_padrao: str = "",
    origem: str | None = None,
) -> ItemLoteEmpresas:
    origem = origem or f"CSV linha {linha.get('linha_csv', '?')}"
    razao = (linha.get("razao_social") or "").strip()

    # Já cadastrada: nada a descobrir fora daqui — a UF que vale é a que o
    # escritório mantém, e a consulta pública é dispensável.
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
