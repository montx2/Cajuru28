"""Backup recuperável: banco, XMLs, certificados, integridade e cópia externa.

Cada execução gera uma única unidade de recuperação: dump lógico, pg_dump
quando disponível, todos os objetos fiscais, manifesto com hashes e pacote
cifrado. Em produção o pacote só é marcado como concluído depois da confirmação
no bucket S3 compatível configurado no secret manager.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, MultiFernet
from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.models import BackupRegistro, StatusBackup

log = logging.getLogger("notasflow.backup")
_TABELAS_IGNORADAS = {"batimentos_sistema"}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _pasta_backups() -> Path:
    return settings.pasta_backup


def _serializar_valor(valor: Any):
    """Transforma valores SQLAlchemy em JSON sem perder datas/decimais/enums."""
    if valor is None:
        return None
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, (str, int, float, bool)):
        return valor
    # Enum, Decimal e UUID têm representação textual estável para o dump.
    return str(getattr(valor, "value", valor))


def _dump_logico(db: Session, caminho: Path) -> dict[str, int]:
    contagens: dict[str, int] = {}
    bind = db.get_bind()
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        for tabela in Base.metadata.sorted_tables:
            if tabela.name in _TABELAS_IGNORADAS:
                continue
            total = 0
            with bind.connect() as conexao:
                resultado = conexao.execution_options(
                    stream_results=True, yield_per=500
                ).execute(select(tabela))
                for linha in resultado.mappings():
                    arquivo.write(
                        json.dumps(
                            {"t": tabela.name, "d": {c: _serializar_valor(v) for c, v in linha.items()}},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    total += 1
            contagens[tabela.name] = total
    return contagens


def _pg_dump_disponivel() -> bool:
    return shutil.which("pg_dump") is not None and not settings.usando_sqlite


def _dump_postgres(caminho: Path) -> bool:
    if not _pg_dump_disponivel():
        return False
    try:
        # A URL nunca entra em log. Em produção o processo roda isolado e o
        # segredo vem do ambiente protegido do container.
        with gzip.open(caminho, "wb") as arquivo:
            processo = subprocess.run(
                ["pg_dump", "--no-owner", "--no-privileges", settings.database_url],
                stdout=arquivo,
                stderr=subprocess.PIPE,
                timeout=1800,
                check=False,
            )
        if processo.returncode != 0:
            log.warning("pg_dump falhou; dump lógico será preservado.")
            return False
        return True
    except Exception:  # noqa: BLE001 - há fallback lógico verificável
        log.warning("pg_dump indisponível; dump lógico será preservado.")
        return False


def _sha256(caminho: Path) -> str:
    digest = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _descricao_arquivo(caminho: Path, *, relativo_a: Path) -> dict[str, Any]:
    """Entrada do manifesto para qualquer payload guardado no pacote."""
    return {
        "path": str(caminho.relative_to(relativo_a)).replace(os.sep, "/"),
        "bytes": caminho.stat().st_size,
        "sha256": _sha256(caminho),
    }


def _copiar_arvore(origem: Path, destino: Path) -> list[dict[str, Any]]:
    """Copia objetos para a unidade de backup e devolve hashes relativos."""
    arquivos: list[dict[str, Any]] = []
    if not origem.exists():
        return arquivos
    for caminho in sorted(origem.rglob("*")):
        if not caminho.is_file():
            continue
        relativo = caminho.relative_to(origem)
        alvo = destino / relativo
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(caminho, alvo)
        arquivos.append(_descricao_arquivo(alvo, relativo_a=destino))
    return arquivos


def _fernet_backup(*, incluir_anteriores: bool = False) -> Fernet | MultiFernet:
    chave = (settings.backup_encryption_key or "").strip()
    if not chave:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY é necessária para gerar backup cifrado.")
    chaves = [Fernet(chave.encode())]
    if incluir_anteriores:
        for anterior in settings.backup_previous_encryption_keys.split(","):
            if anterior.strip():
                chaves.append(Fernet(anterior.strip().encode()))
    return MultiFernet(chaves) if len(chaves) > 1 else chaves[0]


def _cifrar_pacote(pacote: Path) -> Path:
    fernet = _fernet_backup()
    cifrado = pacote.with_suffix(pacote.suffix + ".enc")
    with pacote.open("rb") as origem, cifrado.open("wb") as destino:
        destino.write(fernet.encrypt(origem.read()))
        destino.flush()
        os.fsync(destino.fileno())
    os.chmod(cifrado, 0o600)
    pacote.unlink()
    return cifrado


def _decifrar_pacote(pacote: Path, destino: Path) -> Path:
    if pacote.suffix != ".enc":
        return pacote
    try:
        conteudo = _fernet_backup(incluir_anteriores=True).decrypt(pacote.read_bytes())
    except Exception as exc:  # noqa: BLE001 - token inválido/chave ausente não é restaurável
        raise ValueError("Não foi possível decifrar o pacote com as chaves de backup configuradas.") from exc
    destino.write_bytes(conteudo)
    return destino


def _chave_remota(nome_arquivo: str) -> str:
    prefixo = (settings.backup_s3_prefix or "notasflow").strip().strip("/")
    return f"{prefixo}/{nome_arquivo}" if prefixo else nome_arquivo


def _enviar_para_s3(pacote: Path, checksum: str) -> str | None:
    """Envia e confirma tamanho/hash no storage S3; não registra credenciais."""
    bucket = (settings.backup_s3_bucket or "").strip()
    if not bucket:
        return None
    try:
        import boto3

        kwargs: dict[str, Any] = {"region_name": settings.backup_s3_region or None}
        if settings.backup_s3_endpoint_url:
            kwargs["endpoint_url"] = settings.backup_s3_endpoint_url
        if settings.backup_s3_access_key_id:
            kwargs["aws_access_key_id"] = settings.backup_s3_access_key_id
        if settings.backup_s3_secret_access_key:
            kwargs["aws_secret_access_key"] = settings.backup_s3_secret_access_key
        cliente = boto3.client("s3", **kwargs)
        chave = _chave_remota(pacote.name)
        extra: dict[str, Any] = {
            "Metadata": {"sha256": checksum, "app": "notasflow"},
            "ServerSideEncryption": "aws:kms" if settings.backup_s3_kms_key_id else "AES256",
        }
        if settings.backup_s3_kms_key_id:
            extra["SSEKMSKeyId"] = settings.backup_s3_kms_key_id
        cliente.upload_file(str(pacote), bucket, chave, ExtraArgs=extra)
        cabeca = cliente.head_object(Bucket=bucket, Key=chave)
        if int(cabeca.get("ContentLength", -1)) != pacote.stat().st_size:
            raise RuntimeError("o tamanho remoto não confere")
        if (cabeca.get("Metadata", {}).get("sha256") or "").lower() != checksum.lower():
            raise RuntimeError("o hash remoto não confere")
        return f"s3://{bucket}/{chave}"
    except Exception as exc:  # noqa: BLE001 - não ecoar endpoint/credenciais
        raise RuntimeError("Não foi possível confirmar o backup no storage externo.") from exc


def _aplicar_retencao(pasta: Path) -> int:
    pacotes = sorted(
        [*pasta.glob("backup-*.tar.gz"), *pasta.glob("backup-*.tar.gz.enc")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removidos = 0
    for pacote in pacotes[max(0, settings.backup_retencao) :]:
        try:
            pacote.unlink()
            removidos += 1
        except OSError:
            log.warning("Não foi possível aplicar retenção local de backup.")
    return removidos


def executar_backup(db: Session, *, tipo: str = "agendado", registro_id: int | None = None) -> BackupRegistro:
    if registro_id is not None:
        registro = db.get(BackupRegistro, registro_id)
        if registro is None:
            registro = BackupRegistro(tipo=tipo, status=StatusBackup.EM_ANDAMENTO)
            db.add(registro)
            db.commit()
    else:
        registro = BackupRegistro(tipo=tipo, status=StatusBackup.EM_ANDAMENTO)
        db.add(registro)
        db.commit()

    pasta = _pasta_backups()
    pasta.mkdir(parents=True, exist_ok=True)
    os.chmod(pasta, 0o700)
    inicio = _agora()
    rotulo = inicio.strftime("%Y%m%d-%H%M%S") + f"-{inicio.microsecond // 1000:03d}"
    pacote_base = pasta / f"backup-{rotulo}.tar.gz"

    try:
        with tempfile.TemporaryDirectory(dir=pasta, prefix="tmp-") as temporaria:
            trabalho = Path(temporaria)
            contagens = _dump_logico(db, trabalho / "banco.jsonl.gz")
            tem_pg_dump = _dump_postgres(trabalho / "banco.sql.gz")

            arquivos_xml = _copiar_arvore(Path(settings.dados_dir) / "xml", trabalho / "objetos" / "xml")
            arquivos_cert = _copiar_arvore(
                Path(settings.dados_dir) / "certificados", trabalho / "objetos" / "certificados"
            )
            payloads = [_descricao_arquivo(trabalho / "banco.jsonl.gz", relativo_a=trabalho)]
            if tem_pg_dump:
                payloads.append(_descricao_arquivo(trabalho / "banco.sql.gz", relativo_a=trabalho))
            manifesto = {
                "versao": 2,
                "criado_em": _agora().isoformat(),
                "tipo": tipo,
                "formato_logico": "jsonl",
                "pg_dump": tem_pg_dump,
                "contagens": contagens,
                "total_registros": sum(contagens.values()),
                # Todo payload recuperável tem tamanho e SHA-256; o checksum
                # externo do pacote protege inclusive este manifesto.
                "payloads": payloads,
                "objetos": {"xml": arquivos_xml, "certificados": arquivos_cert},
                "app": "notasflow",
            }
            (trabalho / "manifesto.json").write_text(
                json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with tarfile.open(pacote_base, "w:gz") as tar:
                for item in sorted(trabalho.iterdir()):
                    tar.add(item, arcname=item.name)

        pacote = _cifrar_pacote(pacote_base)
        checksum = _sha256(pacote)
        remoto = _enviar_para_s3(pacote, checksum)
        if settings.em_producao and not remoto:
            raise RuntimeError("Backup externo não foi confirmado.")

        registro.status = StatusBackup.OK
        registro.finalizado_em = _agora()
        registro.tamanho_bytes = pacote.stat().st_size
        registro.caminho = str(pacote)
        registro.checksum_sha256 = checksum
        registro.objeto_remoto = remoto
        registro.arquivos_incluidos = len(arquivos_xml) + len(arquivos_cert)
        registro.empresas = contagens.get("empresas", 0)
        registro.documentos = contagens.get("documentos_fiscais", 0)
        registro.execucoes = contagens.get("execucoes_importacao", 0)
        registro.detalhe = (
            f"{sum(contagens.values())} registros · {registro.arquivos_incluidos} objetos com hash"
            + (" · pg_dump incluído" if tem_pg_dump else "")
            + (" · cópia externa confirmada" if remoto else " · cópia local (desenvolvimento)")
        )
        registro.erro = None
        db.commit()
        _aplicar_retencao(pasta)
    except Exception as exc:  # noqa: BLE001
        # Nunca abandona um pacote em claro caso a cifra/configuração falhe.
        # Se a falha ocorreu depois da cifra (ex.: confirmação S3), o `.enc`
        # fica preservado para investigação/recuperação manual, nunca o bruto.
        try:
            pacote_base.unlink(missing_ok=True)
        except OSError:
            pass
        db.rollback()
        registro = db.get(BackupRegistro, registro.id)
        registro.status = StatusBackup.ERRO
        registro.finalizado_em = _agora()
        registro.erro = str(exc)[:500]
        db.commit()
        log.exception("Backup %s falhou", rotulo)
    return registro


def _desserializar(tabela, dados: dict):
    valores = {}
    for coluna in tabela.columns:
        if coluna.name not in dados:
            continue
        bruto = dados[coluna.name]
        if bruto is not None and coluna.type.python_type is datetime:
            valores[coluna.name] = datetime.fromisoformat(bruto)
        else:
            valores[coluna.name] = bruto
    return valores


def _verificar_arquivos(pasta: Path, arquivos: list[dict[str, Any]], *, rotulo: str = "") -> list[str]:
    """Confere presença, tamanho e hash antes que algo seja restaurado."""
    erros: list[str] = []
    raiz = pasta.resolve()
    for item in arquivos:
        relativo = Path(str(item.get("path") or ""))
        caminho = (pasta / relativo).resolve()
        if not relativo.parts or caminho == raiz or raiz not in caminho.parents:
            erros.append(f"{rotulo}{relativo}: caminho inválido")
        elif not caminho.is_file():
            erros.append(f"{rotulo}{relativo}: ausente")
        elif caminho.stat().st_size != item.get("bytes"):
            erros.append(f"{rotulo}{relativo}: tamanho diverge")
        elif _sha256(caminho) != item.get("sha256"):
            erros.append(f"{rotulo}{relativo}: hash diverge")
    return erros


def _verificar_objetos(pasta: Path, manifesto: dict) -> list[str]:
    erros: list[str] = []
    for categoria in ("xml", "certificados"):
        erros.extend(
            _verificar_arquivos(
                pasta / "objetos" / categoria,
                manifesto.get("objetos", {}).get(categoria, []),
                rotulo=f"{categoria}/",
            )
        )
    return erros


def _extrair_tar_seguro(pacote: Path, destino: Path) -> None:
    """Extrai somente arquivos/diretórios regulares sem seguir links ou '..'."""
    destino.mkdir(parents=True, exist_ok=True)
    raiz = destino.resolve()
    with tarfile.open(pacote, "r:gz") as tar:
        for membro in tar.getmembers():
            relativo = Path(membro.name)
            alvo = (destino / relativo).resolve()
            if (
                not membro.name
                or relativo.is_absolute()
                or ".." in relativo.parts
                or (alvo != raiz and raiz not in alvo.parents)
                or membro.issym()
                or membro.islnk()
                or not (membro.isdir() or membro.isfile())
            ):
                raise ValueError("Pacote contém caminho ou tipo de arquivo não seguro.")
            if membro.isdir():
                alvo.mkdir(parents=True, exist_ok=True)
                continue
            origem = tar.extractfile(membro)
            if origem is None:
                raise ValueError("Pacote contém arquivo ilegível.")
            alvo.parent.mkdir(parents=True, exist_ok=True)
            with origem, alvo.open("xb") as arquivo:
                shutil.copyfileobj(origem, arquivo, length=1024 * 1024)


def extrair_backup_verificado(
    pacote: Path,
    destino: Path,
    *,
    checksum_esperado: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Decifra, extrai com segurança e confere cada conteúdo recuperável.

    É a fronteira obrigatória tanto do teste pela UI como do utilitário de
    recuperação. Nada deve ler o dump ou copiar XML/PFX antes desta função.
    """
    if not pacote.is_file():
        raise ValueError("O pacote local do backup não está disponível.")
    if pacote.suffix != ".enc":
        raise ValueError("Backup não cifrado é recusado; gere um novo pacote protegido.")
    if checksum_esperado and _sha256(pacote) != checksum_esperado:
        raise ValueError("Checksum do pacote diverge; não é seguro restaurá-lo.")
    pacote_aberto = _decifrar_pacote(pacote, destino / "pacote.tar.gz")
    conteudo = destino / "conteudo"
    _extrair_tar_seguro(pacote_aberto, conteudo)
    manifesto_path = conteudo / "manifesto.json"
    if not manifesto_path.exists():
        raise ValueError("Pacote sem manifesto.")
    manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
    if manifesto.get("versao") != 2 or not manifesto.get("payloads"):
        raise ValueError("Backup legado sem manifesto de integridade; gere um novo backup cifrado.")
    erros_payloads = _verificar_arquivos(conteudo, manifesto["payloads"])
    if erros_payloads:
        raise ValueError("Payloads inválidos: " + "; ".join(erros_payloads[:5]))
    erros_objetos = _verificar_objetos(conteudo, manifesto)
    if erros_objetos:
        raise ValueError("Objetos inválidos: " + "; ".join(erros_objetos[:5]))
    return conteudo, manifesto


def testar_restauracao(db: Session, backup_id: int) -> tuple[bool, str]:
    """Valida pacote cifrado, banco de prova e cada arquivo fiscal incluído."""
    registro = db.get(BackupRegistro, backup_id)
    if registro is None or not registro.caminho:
        return False, "Backup não encontrado."
    pacote = Path(registro.caminho)

    try:
        with tempfile.TemporaryDirectory(prefix="restore-test-") as temporaria:
            pasta = Path(temporaria)
            conteudo, manifesto = extrair_backup_verificado(
                pacote, pasta, checksum_esperado=registro.checksum_sha256
            )

            from sqlalchemy import create_engine

            engine_teste: Engine = create_engine(f"sqlite:///{pasta / 'restore.db'}")
            Base.metadata.create_all(engine_teste)
            carregadas: dict[str, int] = {}
            with gzip.open(conteudo / "banco.jsonl.gz", "rt", encoding="utf-8") as arquivo:
                with engine_teste.begin() as conexao:
                    for linha_bruta in arquivo:
                        linha = json.loads(linha_bruta)
                        tabela = Base.metadata.tables[linha["t"]]
                        conexao.execute(insert(tabela).values(_desserializar(tabela, linha["d"])))
                        carregadas[linha["t"]] = carregadas.get(linha["t"], 0) + 1
            engine_teste.dispose()
            divergencias = [
                nome for nome, esperado in manifesto.get("contagens", {}).items()
                if carregadas.get(nome, 0) != esperado
            ]
            if divergencias:
                return False, "Contagens do banco divergem: " + ", ".join(divergencias[:5])

            registro.restauracao_testada_em = _agora()
            registro.restauracao_ok = True
            db.commit()
            return True, (
                f"Restaurado em banco de prova: {sum(carregadas.values())} registros e "
                f"{registro.arquivos_incluidos} objeto(s) fiscal(is) com hashes conferidos."
            )
    except Exception as exc:  # noqa: BLE001
        try:
            registro.restauracao_testada_em = _agora()
            registro.restauracao_ok = False
            db.commit()
        except Exception:
            db.rollback()
        return False, "Falha no teste de restauração: " + str(exc)[:300]


def saude_do_backup(db: Session) -> dict:
    registros = db.query(BackupRegistro).order_by(BackupRegistro.id.desc()).limit(
        max(1, settings.backup_retencao)
    ).all()
    ultimo_ok = next((r for r in registros if r.status == StatusBackup.OK), None)
    ultimo_testado = next((r for r in registros if r.restauracao_testada_em), None)
    agora = _agora()
    horas = None
    if ultimo_ok and ultimo_ok.finalizado_em:
        fim = ultimo_ok.finalizado_em
        fim = fim if fim.tzinfo else fim.replace(tzinfo=timezone.utc)
        horas = (agora - fim).total_seconds() / 3600
    previsto = agora.astimezone().replace(hour=settings.backup_hora, minute=0, second=0, microsecond=0)
    if previsto <= agora:
        previsto += timedelta(days=1)
    atrasado = bool(settings.backup_ativo and ((horas is None and _tem_conteudo(db)) or (horas is not None and horas > settings.backup_alerta_horas)))
    return {
        "ativo": settings.backup_ativo,
        "ultimo_ok_em": ultimo_ok.finalizado_em if ultimo_ok else None,
        "ultimo_ok_tamanho_bytes": ultimo_ok.tamanho_bytes if ultimo_ok else None,
        "horas_desde_ultimo_ok": horas,
        "ultimo_teste_em": ultimo_testado.restauracao_testada_em if ultimo_testado else None,
        "ultimo_teste_ok": ultimo_testado.restauracao_ok if ultimo_testado else None,
        "proximo_previsto_em": previsto.astimezone(timezone.utc),
        "retencao": settings.backup_retencao,
        "atrasado": atrasado,
        "total_registros": len(registros),
        "erros_recentes": sum(1 for r in registros if r.status == StatusBackup.ERRO),
        "tamanho_total_bytes": sum((r.tamanho_bytes or 0) for r in registros if r.status == StatusBackup.OK),
    }


def _tem_conteudo(db: Session) -> bool:
    from app.models import DocumentoFiscal, Empresa

    return bool(db.query(func.count(Empresa.id)).scalar() or db.query(func.count(DocumentoFiscal.id)).scalar())
