"""
Importação em massa de empresas e certificados.

Recebe vários .pfx de uma vez (e/ou um CSV/XLSX) e já cria as empresas com CNPJ,
razão social e UF: CNPJ vem do certificado (campo ICP-Brasil) e a razão
social do subject do X.509. A senha é identificada automaticamente através
de padrões heurísticos (ex: EMPRESA2026, EMPRESA26, EMPRESA25), planilhas de
senhas anexadas, senhas comuns ou senha informada pelo usuário.

CSV ou Excel opcional (razao_social;cnpj_cpf;uf[;senha]) permite cadastrar empresas
sem certificado e/ou informar senha individual por CNPJ.

O subject de um A1 traz a marca da cadeia ("ICP-Brasil"), não o nome do titular,
e a planilha do escritório costuma ter só CNPJ e senha. Quando falta nome — ou
falta UF — o cadastro é resolvido pelo CNPJ em `app.services.cadastro`: primeiro
no Acessórias do escritório, depois nas fontes públicas da Receita
(ver docs/IMPORTACAO_CERTIFICADOS.md).
"""

from __future__ import annotations

import csv
import io
import os
import unicodedata
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import escritorio_id_atual, requer_escrita
from app.core.plural import contagem, plural
from app.core.config import settings
from app.core.documentos import eh_cnpj_numerico, normalizar_documento
from app.core.nomes import nome_provisorio, nome_usavel, precisa_completar_nome
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
    TipoDocumentoFiscal,
    Usuario,
)
from app.services import auditoria
from app.schemas import (
    CompletarCadastrosEntrada,
    CompletarCadastrosResposta,
    ConsultaCNPJResposta,
    EmpresaAtualizar,
    EmpresaCriar,
    EmpresaResposta,
    EstadoSincronizacaoResposta,
    ItemCadastroCorrigido,
    ItemLoteEmpresas,
    LoteEmpresasResposta,
)
from app.api.routers.importacoes import estados_do_escritorio
from app.services import cadastro as cadastro_servico
from app.services.cadastro import (
    CadastroEmpresa,
    acessorias_configurado,
    consultar_cadastro,
)
from app.services.cnpj import consultar_cnpj
from app.services.certificados import (
    abrir_pfx_tentando_senhas,
    cnpj_de_nome_arquivo,
    guardar_pfx_protegido,
    validar_documento,
)
from app.services.senhas import (
    buscar_senhas_por_nome,
    chave_de_arquivo,
    construir_candidatas_pfx,
    fundir_planilhas_dados,
    indexar_por_arquivo,
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


def _cnpj_do_arquivo(nome: str, por_arquivo: dict[str, dict]) -> str:
    """CNPJ do .pfx: o que está no nome do arquivo ou o que a planilha declara.

    A planilha do escritório costuma trazer a coluna `arquivo` com o nome exato
    do certificado. Quando o .pfx não tem CNPJ no nome (`certificado-novo.pfx`),
    é ela que diz a que empresa o arquivo pertence.
    """
    cnpj = cnpj_de_nome_arquivo(nome)
    if cnpj:
        return cnpj
    linha = por_arquivo.get(chave_de_arquivo(nome)) or {}
    return (linha.get("cnpj") or "").strip()


def _linha_do_certificado(
    nome: str,
    cnpj: str,
    linhas_csv: dict[str, dict],
    por_arquivo: dict[str, dict],
) -> dict:
    """Linha da planilha que fala deste certificado: pelo CNPJ ou pelo nome."""
    if cnpj:
        linha = linhas_csv.get(cnpj)
        if linha:
            return linha
    return por_arquivo.get(chave_de_arquivo(nome)) or {}


def _consulta_publica(cnpj_cpf: str):
    """Consulta BrasilAPI somente para CNPJ numérico; alfa segue manualmente."""
    if not eh_cnpj_numerico(cnpj_cpf):
        return None
    return consultar_cnpj(cnpj_cpf)


def _cadastro(
    db: Session | None,
    escritorio_id: int,
    cnpj_cpf: str,
    *,
    forcar: bool = False,
    buscar_ibge: bool = False,
) -> CadastroEmpresa | None:
    """Cadastro da empresa pelo CNPJ: Acessórias primeiro, fonte pública depois.

    É a mesma chamada que entrega a UF, então um lookup resolve nome e estado —
    e é por isso que ela acontece sempre que falta qualquer um dos dois.
    `consultar_publica` é injetada para que os testes (e nenhuma rota)
    dependam da internet.
    """
    return consultar_cadastro(
        db,
        escritorio_id,
        cnpj_cpf,
        consultar_publica=_consulta_publica,
        forcar=forcar,
        buscar_ibge=buscar_ibge,
    )


async def _cadastro_seguro(
    db: Session | None,
    escritorio_id: int,
    cnpj_cpf: str,
    *,
    forcar: bool = False,
    buscar_ibge: bool = False,
) -> CadastroEmpresa | None:
    """`_cadastro` fora da event loop: um lote com centenas de CNPJs espera HTTP, não o servidor todo."""
    return await run_in_threadpool(
        _cadastro, db, escritorio_id, cnpj_cpf, forcar=forcar, buscar_ibge=buscar_ibge
    )


def _completar_dados_empresa(
    dados: EmpresaCriar,
    existente: Empresa | None = None,
    *,
    db: Session | None = None,
    escritorio_id: int = 0,
) -> dict:
    """
    Aplica o preenchimento automático de UF/razão social pelo CNPJ.

    A UF continua obrigatória para salvar porque NFe/CT-e precisam dela; a
    diferença é que agora o sistema tenta descobri-la antes de pedir que o
    operador escolha manualmente.
    """
    documento = normalizar_documento(dados.cnpj_cpf)
    uf = _validar_uf_ou_vazio(dados.uf)
    razao_digitada = (dados.razao_social or "").strip()
    razao = nome_usavel(razao_digitada, documento=documento)
    codigo_ibge = dados.codigo_ibge

    # A consulta também entrega o IBGE municipal de sete dígitos. Buscar mesmo
    # quando razão/UF já vieram preenchidas elimina um bloqueio do cadastro
    # consulta externa sem substituir dado manual informado pelo operador. Um
    # nome que era só ruído ("ICP-Brasil") conta como ausente: é o caso em que
    # a consulta pública salva o cadastro.
    precisa_consultar = not uf or not razao or not codigo_ibge or razao != razao_digitada
    cadastro = (
        _cadastro(db, escritorio_id, documento, buscar_ibge=True) if precisa_consultar else None
    )
    if cadastro is not None:
        uf = uf or _validar_uf_ou_vazio(cadastro.uf)
        razao = razao or cadastro.razao_social or cadastro.nome_fantasia
        codigo_ibge = codigo_ibge or cadastro.codigo_ibge or None

    if existente is not None:
        uf = uf or _validar_uf_ou_vazio(existente.uf)
        razao = razao or nome_usavel(existente.razao_social, documento=documento)
        codigo_ibge = codigo_ibge or existente.codigo_ibge or None

    if not razao:
        # Nada encontrado: o que o operador escreveu é melhor que inventar.
        razao = razao_digitada

    if not razao:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "razao_social"],
                    "msg": "Razão social não identificada automaticamente. Informe o nome da empresa.",
                    "type": "value_error",
                }
            ],
        )
    if not uf:
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "loc": ["body", "uf"],
                    "msg": "Não foi possível identificar a UF automaticamente. Informe a UF manualmente.",
                    "type": "value_error",
                }
            ],
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
    documento = normalizar_documento(dados.cnpj_cpf)
    ja_existe = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == documento)
        .first()
    )
    dados_empresa = _completar_dados_empresa(
        dados, existente=ja_existe, db=db, escritorio_id=escritorio_id
    )
    if ja_existe is not None:
        ja_existe.razao_social = dados_empresa["razao_social"]
        ja_existe.uf = dados_empresa["uf"]
        if dados_empresa.get("codigo_ibge"):
            ja_existe.codigo_ibge = dados_empresa["codigo_ibge"]
        if dados_empresa.get("inscricao_municipal"):
            ja_existe.inscricao_municipal = dados_empresa["inscricao_municipal"]
        ja_existe.ativa = True
        db.flush()
        auditoria.registrar(
            db, usuario, "empresa_atualizada",
            entidade="empresa", entidade_id=ja_existe.id,
            detalhe=f"{ja_existe.razao_social} ({ja_existe.cnpj_cpf}/{ja_existe.uf})",
        )
        db.commit()
        db.refresh(ja_existe)
        return ja_existe

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
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Pré-preenche razão social e UF pelo CNPJ para deixar o cadastro simples.

    Começa pelo Acessórias — o cadastro do próprio escritório é a fonte mais
    atual e a única que conhece um CNPJ alfanumérico — e só então consulta a
    Receita. Assim a tela de empresa para de depender de o nome estar ou não
    no certificado.
    """
    try:
        documento = normalizar_documento(cnpj)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    cadastro = _cadastro(db, escritorio_id, documento, buscar_ibge=True)
    if cadastro is not None:
        return ConsultaCNPJResposta(
            documento=documento,
            encontrado=True,
            razao_social=cadastro.razao_social,
            nome_fantasia=cadastro.nome_fantasia,
            uf=cadastro.uf,
            municipio=cadastro.municipio,
            codigo_ibge=cadastro.codigo_ibge,
            fonte=cadastro.fonte,
            mensagem="Dados encontrados automaticamente.",
        )
    if not eh_cnpj_numerico(documento):
        return ConsultaCNPJResposta(
            documento=documento,
            encontrado=False,
            mensagem="CNPJ alfanumérico sem cadastro no Acessórias: informe razão social e UF manualmente.",
        )
    return ConsultaCNPJResposta(
        documento=documento,
        encontrado=False,
        mensagem="Não foi possível consultar esse CNPJ agora. Preencha a UF manualmente.",
    )


@router.post("/completar-cadastros", response_model=CompletarCadastrosResposta)
async def completar_cadastros_pendentes(
    dados: CompletarCadastrosEntrada,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
    usuario: Usuario = Depends(requer_escrita),
):
    """Corrige razão social (e UF) das empresas importadas sem nome de verdade.

    Um lote de certificados pode entrar com o nome da cadeia emissora no lugar
    da razão social — `ICP-Brasil` em cada uma das linhas — quando a planilha
    só traz CNPJ e senha. Esta rota repassa os CNPJs pendentes ao cadastro do
    escritório no Acessórias e, para o que não está lá, às fontes públicas da
    Receita. É a correção em lote sem exigir reenvio de nenhum `.pfx`.
    """
    consulta = db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id)
    empresas = consulta.order_by(Empresa.razao_social).all()
    if dados.somente_pendentes:
        empresas = [
            empresa
            for empresa in empresas
            if precisa_completar_nome(empresa.razao_social, empresa.cnpj_cpf) or not empresa.uf
        ]
    empresas = empresas[: dados.limite]

    # Uma credencial decifrada e um cliente por rodada — a rota pode percorrer
    # centenas de CNPJs, e montar o cliente por empresa custaria uma consulta
    # ao banco para cada um deles.
    cliente, _motivo = cadastro_servico.cliente_acessorias(db, escritorio_id)
    corrigidas = uf_completada = sem_fonte = 0
    itens: list[ItemCadastroCorrigido] = []
    for empresa in empresas:
        # Mesmo `consultar_cadastro` da importação: um reparo e um lote não
        # podem divergir sobre qual fonte manda no nome.
        cadastro = await run_in_threadpool(
            consultar_cadastro,
            db,
            escritorio_id,
            empresa.cnpj_cpf,
            consultar_publica=_consulta_publica,
            forcar=dados.reconsultar,
            buscar_ibge=True,
            cliente=cliente,
        )
        if cadastro is None:
            sem_fonte += 1
            itens.append(
                ItemCadastroCorrigido(
                    empresa_id=empresa.id,
                    cnpj_cpf=empresa.cnpj_cpf,
                    razao_social=empresa.razao_social,
                    uf=empresa.uf,
                    status="sem_fonte",
                )
            )
            continue
        mudou_nome = False
        novo_nome = nome_usavel(cadastro.razao_social or cadastro.nome_fantasia, documento=empresa.cnpj_cpf)
        if novo_nome and precisa_completar_nome(empresa.razao_social, empresa.cnpj_cpf):
            empresa.razao_social = novo_nome[:255]
            mudou_nome = True
        if cadastro.uf and empresa.uf not in _UFS_VALIDAS:
            empresa.uf = cadastro.uf
            uf_completada += 1
        if cadastro.codigo_ibge and not empresa.codigo_ibge:
            empresa.codigo_ibge = cadastro.codigo_ibge
        itens.append(
            ItemCadastroCorrigido(
                empresa_id=empresa.id,
                cnpj_cpf=empresa.cnpj_cpf,
                razao_social=empresa.razao_social,
                uf=empresa.uf,
                fonte=cadastro.fonte,
                status="corrigido" if mudou_nome else "uf",
            )
        )
        if mudou_nome:
            corrigidas += 1

    if corrigidas or uf_completada:
        auditoria.registrar(
            db,
            usuario,
            "empresas_cadastros_completados",
            detalhe=(
                f"{corrigidas} {plural(corrigidas, 'razão social corrigida', 'razões sociais corrigidas')}"
                + (f", {uf_completada} UF" if uf_completada else "")
                + f", {sem_fonte} sem fonte disponível"
            ),
        )
    db.commit()
    return CompletarCadastrosResposta(
        analisadas=len(empresas),
        corrigidas=corrigidas,
        uf_completada=uf_completada,
        sem_fonte=sem_fonte,
        acessorias_configurado=acessorias_configurado(db, escritorio_id),
        itens=itens,
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

    from app.services import lotes_recebidos
    caminhos_lotes = [str(arquivo) for tipo in TipoDocumentoFiscal for arquivo in lotes_recebidos.arquivos_pendentes(empresa.id, tipo)]
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

    for caminho in caminhos + caminhos_lotes:
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
      com a senha de cada certificado. As colunas são descobertas pelo conteúdo:
      valem `cnpj;senha`, `razao_social;cnpj_cpf;uf;senha` e o inventário de A1
      `arquivo;cnpj;emissor;senha;validade`, com ou sem linha de título. O `.pfx`
      é amarrado à linha pelo CNPJ do nome do arquivo ou pelo nome que a própria
      planilha cita.
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
    # A mesma planilha também é lida pelo nome do arquivo que ela cita: é assim
    # que `21260898000107.pfx` acha a senha mesmo quando a coluna CNPJ veio com
    # um dígito a menos.
    por_arquivo = indexar_por_arquivo(lista_planilhas)
    resultados: list[ItemLoteEmpresas] = []
    vistos: set[str] = set()

    # 1) Arquivos .pfx — empresas + certificados. A pasta pode trazer o
    # certificado antigo e o atualizado do mesmo CNPJ: sobrevive a versão de
    # maior validade real (X.509), não a primeira da lista.
    planos_pfx = await _escolher_versoes(
        arquivos,
        senha=senha,
        linhas_csv=linhas_csv,
        por_arquivo=por_arquivo,
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
                por_arquivo=por_arquivo,
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
        resultados.append(
            await _criar_empresa_de_linha(cnpj, linha, db, escritorio_id, vistos, uf_padrao)
        )

    criadas = sum(1 for r in resultados if r.status == "criada")
    certificados = sum(1 for r in resultados if r.status == "certificado_atualizado")
    ja_existiam = sum(1 for r in resultados if r.status == "ja_existia")
    erros = sum(1 for r in resultados if r.status == "erro")
    substituidos = sum(1 for r in resultados if r.status == "substituido")
    # Empresas que entraram sem nome de empresa (só o placeholder "Empresa
    # <CNPJ>"): o número é a deixa para o reparo em um clique na tela.
    sem_nome = sum(
        1
        for r in resultados
        if r.cnpj_cpf
        and r.status in {"criada", "certificado_atualizado", "ja_existia"}
        and precisa_completar_nome(r.razao_social, r.cnpj_cpf)
    )
    auditoria.registrar(
        db, usuario, "empresas_lote",
        detalhe=(
            f"{len(resultados)} itens: {criadas} criadas, {certificados} certificados, "
            f"{erros} erros"
            + (f", {substituidos} versões antigas descartadas" if substituidos else "")
            + (f", {sem_nome} sem razão social" if sem_nome else "")
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
        linhas_da_planilha=len(lista_planilhas),
        senhas_da_planilha=sum(
            1 for linha in lista_planilhas if (linha.get("senha") or "").strip()
        ),
        empresas_sem_nome=sem_nome,
    )


async def _escolher_versoes(
    arquivos: list[UploadFile],
    *,
    senha: str,
    linhas_csv: dict[str, dict],
    por_arquivo: dict[str, dict] | None = None,
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
    por_arquivo = por_arquivo or {}
    plano: list[UploadFile | ItemLoteEmpresas] = list(arquivos)
    grupos: dict[str, list[int]] = {}
    for indice, arquivo in enumerate(arquivos):
        nome = (arquivo.filename or "").lower()
        if not nome.endswith((".pfx", ".p12")):
            continue
        cnpj = _cnpj_do_arquivo(arquivo.filename or "", por_arquivo)
        if cnpj:
            grupos.setdefault(cnpj, []).append(indice)

    for cnpj, indices in grupos.items():
        if len(indices) < 2:
            continue

        linha_csv = _linha_do_certificado(
            arquivos[indices[0]].filename or "", cnpj, linhas_csv, por_arquivo
        )
        # Só um nome de empresa de verdade gera candidatos de senha: com
        # "ICP-Brasil" a busca por nome acertaria a senha de outra linha.
        razao = nome_usavel(linha_csv.get("razao_social"), documento=cnpj)
        if not razao and db is not None:
            emp = db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj).first()
            if emp:
                razao = nome_usavel(emp.razao_social, documento=cnpj)

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

        agora = datetime.now(timezone.utc)
        # Nunca substitua um certificado válido por uma versão vencida. Se
        # houver várias versões válidas, fica a de maior validade. Quando
        # todas estiverem vencidas, deixamos uma delas seguir para que o
        # processamento devolva um erro explícito ao operador.
        validos = [indice for indice, validade in abertos.items() if validade > agora]
        candidatos_vencedor = validos or list(abertos)
        vencedor = max(candidatos_vencedor, key=abertos.get) if candidatos_vencedor else indices[0]
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
    por_arquivo: dict[str, dict] | None = None,
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

    cnpj_nome = _cnpj_do_arquivo(nome, por_arquivo or {})
    linha_csv = _linha_do_certificado(nome, cnpj_nome, linhas_csv, por_arquivo or {})
    # A coluna de nome da planilha é a que pode trazer "ICP-Brasil" (a marca da
    # cadeia, repetida em cada uma das 203 linhas). `nome_usavel` descarta isso
    # e ainda limpa rótulos do tipo "Razão social: …".
    razao_da_planilha = nome_usavel(linha_csv.get("razao_social"), documento=cnpj_nome)
    razao_conhecida = razao_da_planilha
    uf_da_empresa = ""
    if cnpj_nome:
        empresa_existente = (
            db.query(Empresa)
            .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj_nome)
            .first()
        )
        if empresa_existente:
            # Um cadastro legado com o nome da cadeia não é "nome conhecido":
            # tratá-lo como ausente é o que permite corrigir ao reimportar.
            razao_conhecida = razao_conhecida or nome_usavel(
                empresa_existente.razao_social, documento=cnpj_nome
            )
            uf_da_empresa = empresa_existente.uf or ""

    # Quando a UF também não é conhecida, a consulta pelo CNPJ ia acontecer de
    # qualquer forma: ela passa a valer para o nome antes mesmo de as senhas
    # serem tentadas (o nome da empresa é um dos padrões de senha mais comuns).
    cadastro: CadastroEmpresa | None = None
    if cnpj_nome and not razao_conhecida and not (uf_da_empresa or linha_csv.get("uf") or uf_padrao):
        cadastro = await _cadastro_seguro(db, escritorio_id, cnpj_nome)
        razao_conhecida = cadastro.razao_social if cadastro else ""

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
        # Um A1 que não abre ainda pode ser aberto com a senha-padrão derivada
        # do nome — e o nome pode estar só no cadastro do escritório. Uma
        # consulta por CNPJ, reaproveitando a que já foi feita acima.
        if cnpj_nome and not razao_conhecida:
            cadastro = cadastro or await _cadastro_seguro(db, escritorio_id, cnpj_nome)
            nome_do_cadastro = cadastro.razao_social if cadastro else ""
            try:
                if nome_do_cadastro:
                    novas_candidatas = construir_candidatas_pfx(
                        nome_arquivo=nome,
                        cnpj=cnpj_nome,
                        razao_social=nome_do_cadastro,
                        senhas_declaradas=buscar_senhas_por_nome(nome_do_cadastro, lista_planilhas or []),
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
                    f"(senha incorreta ou arquivo corrompido). Foram testadas {contagem(len(senhas_declaradas), 'senha declarada', 'senhas declaradas')} para este CNPJ "
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

    if cadastro and cadastro.documento != cnpj:
        # O CNPJ do nome do arquivo não é o do certificado: o cadastro achado
        # vale para outra empresa e não pode ser usado aqui.
        cadastro = None

    agora = datetime.now(timezone.utc)
    if identidade.validade_utc <= agora:
        return ItemLoteEmpresas(
            origem=nome,
            cnpj_cpf=identidade.documento or cnpj_nome,
            razao_social=identidade.razao_social,
            status="erro",
            validade=identidade.validade_utc,
            mensagem=(
                "Certificado vencido e não importado "
                f"(validade: {identidade.validade_utc.strftime('%d/%m/%Y')}). "
                "Envie um certificado válido."
            ),
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

    uf_da_planilha = (linha.get("uf") or "").upper()
    razao_do_certificado = identidade.razao_social if identidade.nome_no_certificado else ""
    if not cadastro and (
        not (uf_da_planilha or uf_padrao or uf_da_empresa)
        or not (razao_da_planilha or razao_do_certificado or razao_conhecida)
    ):
        # Falta UF ou falta nome: a mesma consulta responde pelos dois. É o que
        # impede um lote cujo .pfx só traz a marca da cadeia de gravar
        # "ICP-Brasil" como razão social de trezentas empresas.
        cadastro = await _cadastro_seguro(db, escritorio_id, cnpj)
    uf = (
        uf_da_planilha
        or uf_padrao
        or uf_da_empresa
        or (cadastro.uf if cadastro else "")
    ).upper()

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

    # Ordem do nome: planilha (o dado que o escritório escolheu), cadastro
    # (Acessórias/Receita), subject do certificado e, em último lugar, o
    # placeholder "Empresa <CNPJ>" — que a rota /completar-cadastros corrige.
    razao = (
        nome_usavel(linha.get("razao_social"), documento=cnpj)
        or (cadastro.razao_social if cadastro else "")
        or nome_usavel(razao_do_certificado, documento=cnpj)
        or nome_provisorio(cnpj)
    ).strip()
    empresa, criada_agora = _obter_ou_criar_empresa(
        db, escritorio_id, cnpj, razao, uf, vistos,
        cadastro=cadastro if cadastro and cadastro.documento == cnpj else None,
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
    *,
    cadastro: CadastroEmpresa | None = None,
) -> tuple[Empresa, bool]:
    """Retorna (empresa, criada_agora). Marca o CNPJ como visto no lote."""
    vistos.add(cnpj)
    empresa = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj)
        .first()
    )
    if empresa is not None:
        if not empresa.ativa:
            empresa.ativa = True
        # Nome ruído ("ICP-Brasil"), vazio ou placeholder "Empresa <CNPJ>" é
        # corrigido no reimportar. Um nome verdadeiro nunca é substituído pelo
        # que o certificado achou — só por um nome também verdadeiro.
        if razao_social and precisa_completar_nome(empresa.razao_social, cnpj):
            empresa.razao_social = razao_social[:255]
        if not empresa.uf and uf:
            empresa.uf = uf
        if cadastro is not None:
            if not empresa.codigo_ibge and cadastro.codigo_ibge:
                empresa.codigo_ibge = cadastro.codigo_ibge
        return empresa, False

    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social=(razao_social or nome_provisorio(cnpj))[:255],
        cnpj_cpf=cnpj,
        uf=uf,
        codigo_ibge=(cadastro.codigo_ibge if cadastro else "") or None,
    )
    db.add(empresa)
    db.flush()
    return empresa, True


async def _criar_empresa_de_linha(
    cnpj: str,
    linha: dict,
    db: Session,
    escritorio_id: int,
    vistos: set[str],
    uf_padrao: str = "",
    origem: str | None = None,
) -> ItemLoteEmpresas:
    origem = origem or f"Linha {linha.get('linha_csv', '?')}"
    # "ICP-Brasil" na coluna de nome é a autoridade certificadora, não a
    # empresa: vazia, a linha passa a valer pelo que o cadastro disser.
    razao = nome_usavel(linha.get("razao_social"), documento=cnpj)

    existente = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == cnpj)
        .first()
    )
    if existente is not None:
        uf_existente = (existente.uf or linha.get("uf") or uf_padrao or "").upper()
        cadastro = None
        if uf_existente not in _UFS_VALIDAS or precisa_completar_nome(existente.razao_social, cnpj):
            cadastro = await _cadastro_seguro(db, escritorio_id, cnpj)
            if uf_existente not in _UFS_VALIDAS and cadastro:
                uf_existente = cadastro.uf.upper()
        empresa, _ = _obter_ou_criar_empresa(
            db,
            escritorio_id,
            cnpj,
            razao or (cadastro.razao_social if cadastro else ""),
            uf_existente if uf_existente in _UFS_VALIDAS else "",
            vistos,
            cadastro=cadastro,
        )
        return ItemLoteEmpresas(
            origem=origem,
            cnpj_cpf=cnpj,
            razao_social=empresa.razao_social,
            uf=empresa.uf,
            status="ja_existia",
            empresa_id=empresa.id,
        )

    cadastro = None
    if not (linha.get("uf") or uf_padrao) or not razao:
        cadastro = await _cadastro_seguro(db, escritorio_id, cnpj)
    razao = (
        razao
        or (cadastro.razao_social if cadastro else "")
        or (cadastro.nome_fantasia if cadastro else "")
    )
    uf = (linha.get("uf") or uf_padrao or (cadastro.uf if cadastro else "")).upper()

    if not razao:
        return ItemLoteEmpresas(
            origem=origem,
            cnpj_cpf=cnpj,
            status="erro",
            mensagem=(
                "Razão social não identificada no CSV, no Acessórias nem na "
                "Receita. Informe o nome na planilha."
            ),
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
        db, escritorio_id, cnpj, razao, uf, vistos, cadastro=cadastro
    )
    return ItemLoteEmpresas(
        origem=origem,
        cnpj_cpf=cnpj,
        razao_social=empresa.razao_social,
        uf=empresa.uf,
        status="criada" if _criada_agora else "ja_existia",
        empresa_id=empresa.id,
    )
