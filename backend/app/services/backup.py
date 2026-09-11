"""
Backup de verdade: o pacote que reconstrói o sistema num servidor novo.

"Exportar banco" não é backup. Um backup aqui é:

1. **dump lógico do banco** (JSONL compactado, uma linha por registro, na
   ordem de dependência das tabelas) — restaurável em qualquer banco que o
   SQLAlchemy crie, sem depender de binários do PostgreSQL no container;
2. **pg_dump** adicional quando o binário existe (bônus canônico em produção);
3. **manifesto.json** com data, versão e contagens de tudo que entrou;
4. **espelho vivo dos XMLs e certificados** (cópia incremental — só o que
   mudou desde o último backup), porque o dump do banco não carrega os
   arquivos fiscais em si;
5. **retenção**: além de N pacotes, os mais antigos são apagados.

E o que separa este módulo de um "export": o **teste de restauração**. Ele
extrai o pacote, recria o schema num banco temporário, recarrega todos os
registros e confere as contagens contra o manifesto. Backup que nunca foi
restaurado é esperança, não plano — então o teste é um clique na tela, e a
data da última passagem fica visível na saúde do sistema.
"""

from __future__ import annotations

import gzip
import json
import logging
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.models import BackupRegistro, StatusBackup

log = logging.getLogger("notasflow.backup")

# Tabelas cujo conteúdo NÃO entra no dump: o backup não deve crescer com
# estado transitório de processo (batimento é telemetria do momento).
_TABELAS_IGNORADAS = {"batimentos_sistema"}


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _pasta_backups() -> Path:
    return Path(settings.dados_dir) / "backups"


def _serializar_valor(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.isoformat()
    if isinstance(valor, (str, int, float, bool)):
        return valor
    return str(valor)  # enum, date e afins


def _dump_logico(db: Session, caminho: Path) -> dict[str, int]:
    """Dump JSONL de todas as tabelas, na ordem de dependência do metadata."""
    contagens: dict[str, int] = {}
    # O bind da sessão do chamador — nunca um engine global: o backup deve
    # enxergar exatamente o banco que a requisição está usando.
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
    """Tenta o dump canônico do PostgreSQL (requer pg_dump no container)."""
    if not _pg_dump_disponivel():
        return False
    url = settings.database_url
    # postgresql:// → postgresql:// já serve ao pg_dump; esconder eco de senha
    # em log não é necessário: nada aqui é impresso.
    try:
        with gzip.open(caminho, "wb") as arquivo:
            processo = subprocess.run(  # noqa: S603 — binário conhecido, sem shell
                ["pg_dump", "--no-owner", "--no-privileges", url],
                stdout=arquivo,
                stderr=subprocess.PIPE,
                timeout=1800,
                check=False,
            )
        if processo.returncode != 0:
            log.warning("pg_dump falhou (%s); ficamos com o dump lógico.", processo.stderr[:200])
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — dump lógico já cobre o caso
        log.warning("pg_dump indisponível: %s", exc)
        return False


def _espelhar(origem: Path, destino: Path, desde: datetime | None) -> int:
    """Copia para `destino` os arquivos de `origem` novos/alterados desde `desde`."""
    if not origem.exists():
        return 0
    copiados = 0
    for caminho in origem.rglob("*"):
        if not caminho.is_file():
            continue
        if desde is not None:
            try:
                mtime = datetime.fromtimestamp(caminho.stat().st_mtime, tz=timezone.utc)
                if mtime <= desde:
                    continue
            except OSError:
                continue
        alvo = destino / caminho.relative_to(origem)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(caminho, alvo)
        copiados += 1
    return copiados


def _ultimo_backup_ok_em(db: Session) -> datetime | None:
    registro = (
        db.query(BackupRegistro)
        .filter(BackupRegistro.status == StatusBackup.OK)
        .order_by(BackupRegistro.id.desc())
        .first()
    )
    if registro is None or registro.finalizado_em is None:
        return None
    visto = registro.finalizado_em
    return visto if visto.tzinfo else visto.replace(tzinfo=timezone.utc)


def _aplicar_retencao(pasta: Path) -> int:
    """Mantém apenas os N pacotes mais recentes; devolve quantos removeu."""
    pacotes = sorted(
        pasta.glob("backup-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    removidos = 0
    for pacote in pacotes[max(0, settings.backup_retencao) :]:
        try:
            pacote.unlink()
            removidos += 1
        except OSError:
            pass
    return removidos


def executar_backup(
    db: Session, tipo: str = "agendado", registro_id: int | None = None
) -> BackupRegistro:
    """
    Roda o backup completo e devolve o registro correspondente.

    `registro_id` permite reaproveitar a linha já criada pelo endpoint manual
    (a UI mostra "em andamento" no instante do clique, não depois).

    Levanta exceção só em falha catastrófica (sem disco, sem permissão);
    o registro com status=erro é o caminho normal de "tentou e falhou" —
    o painel precisa mostrar isso, não engolir.
    """
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
    # Milissegundos no nome: dois backups no mesmo segundo (teste, disparo
    # manual em cima do agendado) nunca se sobrescrevem.
    agora_inicio = _agora()
    rotulo = agora_inicio.strftime("%Y%m%d-%H%M%S") + f"-{agora_inicio.microsecond // 1000:03d}"
    nome_pacote = pasta / f"backup-{rotulo}.tar.gz"

    try:
        with tempfile.TemporaryDirectory(dir=pasta, prefix="tmp-") as temporaria:
            trabalho = Path(temporaria)

            # 1. Dump lógico (sempre — é o formato que o teste de restauração lê).
            contagens = _dump_logico(db, trabalho / "banco.jsonl.gz")

            # 2. pg_dump quando disponível (cópia canônica adicional).
            tem_pg_dump = _dump_postgres(trabalho / "banco.sql.gz")

            # 3. Manifesto: o que entrou, quando, e com que versão.
            total_registros = sum(contagens.values())
            manifesto = {
                "criado_em": _agora().isoformat(),
                "tipo": tipo,
                "formato_logico": "jsonl",
                "pg_dump": tem_pg_dump,
                "contagens": contagens,
                "total_registros": total_registros,
                "app": "notasflow",
            }
            (trabalho / "manifesto.json").write_text(
                json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 4. Pacote final.
            with tarfile.open(nome_pacote, "w:gz") as tar:
                for item in sorted(trabalho.iterdir()):
                    tar.add(item, arcname=item.name)

        # 5. Espelho vivo dos arquivos (fora do pacote — sempre atual).
        desde = _ultimo_backup_ok_em(db)
        dados = Path(settings.dados_dir)
        xmls = _espelhar(dados / "xml", pasta / "espelho-xml", desde)
        certificados = _espelhar(
            dados / "certificados", pasta / "espelho-certificados", desde
        )

        registro.status = StatusBackup.OK
        registro.finalizado_em = _agora()
        registro.tamanho_bytes = nome_pacote.stat().st_size
        registro.caminho = str(nome_pacote)
        registro.empresas = contagens.get("empresas", 0)
        registro.documentos = contagens.get("documentos_fiscais", 0)
        registro.execucoes = contagens.get("execucoes_importacao", 0)
        registro.detalhe = (
            f"{total_registros} registros · {len(contagens)} tabelas"
            + (f" · pg_dump incluído" if tem_pg_dump else "")
            + f" · espelho: {xmls} XML(s), {certificados} certificado(s) novos"
        )
        registro.erro = None
        db.commit()

        removidos = _aplicar_retencao(pasta)
        if removidos:
            log.info("Retenção apagou %d backup(s) antigo(s).", removidos)

    except Exception as exc:  # noqa: BLE001 — falha vira registro visível, não stacktrace
        db.rollback()
        registro = db.get(BackupRegistro, registro.id)
        registro.status = StatusBackup.ERRO
        registro.finalizado_em = _agora()
        registro.erro = str(exc)[:2000]
        db.commit()
        log.exception("Backup %s falhou", rotulo)

    return registro


# ---------------------------------------------------------------------------
# Teste de restauração — a parte que transforma backup em plano
# ---------------------------------------------------------------------------


def _desserializar(tabela, dados: dict):
    """Converte uma linha do JSONL de volta em valores aceitos pelo insert."""
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


def testar_restauracao(db: Session, backup_id: int) -> tuple[bool, str]:
    """
    Extrai o pacote, recria o schema num banco temporário, recarrega os
    registros e confere as contagens contra o manifesto.

    Roda num SQLite em arquivo temporário: independe do banco de produção e
    não toca em nada vivo. É o "restore de verdade" que a tela de saúde
    precisa para dizer "sim, isto aqui volta".
    """
    registro = db.get(BackupRegistro, backup_id)
    if registro is None or not registro.caminho:
        return False, "Backup não encontrado."
    pacote = Path(registro.caminho)
    if not pacote.exists():
        return False, "O arquivo do backup não está mais no disco."

    try:
        with tempfile.TemporaryDirectory(prefix="restore-test-") as temporaria:
            pasta = Path(temporaria)
            with tarfile.open(pacote, "r:gz") as tar:
                # `filter` existe a partir do 3.11.4/3.12; em versões mais
                # antigas extraímos sem filtro — o pacote é gerado por nós.
                try:
                    tar.extractall(pasta, filter="data")  # noqa: S202
                except TypeError:  # pragma: no cover — Python antigo
                    tar.extractall(pasta)  # noqa: S202

            manifesto_path = pasta / "manifesto.json"
            if not manifesto_path.exists():
                return False, "Pacote sem manifesto — não é um backup deste sistema."
            manifesto = json.loads(manifesto_path.read_text(encoding="utf-8"))
            esperado = manifesto.get("contagens", {})

            from sqlalchemy import create_engine

            engine_teste: Engine = create_engine(f"sqlite:///{pasta / 'restore.db'}")
            Base.metadata.create_all(engine_teste)

            carregadas: dict[str, int] = {}
            with gzip.open(pasta / "banco.jsonl.gz", "rt", encoding="utf-8") as arquivo:
                with engine_teste.begin() as conexao:
                    for linha_bruta in arquivo:
                        registro_json = json.loads(linha_bruta)
                        tabela = Base.metadata.tables[registro_json["t"]]
                        conexao.execute(
                            insert(tabela).values(
                                _desserializar(tabela, registro_json["d"])
                            )
                        )
                        carregadas[registro_json["t"]] = (
                            carregadas.get(registro_json["t"], 0) + 1
                        )

            divergencias = [
                f"{tabela}: manifesto={esperado} restaurado={carregadas.get(tabela, 0)}"
                for tabela, esperado in esperado.items()
                if carregadas.get(tabela, 0) != esperado
            ]
            engine_teste.dispose()

            if divergencias:
                return False, "Contagens divergem: " + "; ".join(divergencias[:5])

            total = sum(carregadas.values())
            registro.restauracao_testada_em = _agora()
            registro.restauracao_ok = True
            db.commit()
            return True, (
                f"Restaurado em banco de prova: {total} registros em "
                f"{len(carregadas)} tabelas, contagens conferem com o manifesto."
            )
    except Exception as exc:  # noqa: BLE001
        try:
            registro.restauracao_testada_em = _agora()
            registro.restauracao_ok = False
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return False, f"Falha no teste de restauração: {exc}"


def saude_do_backup(db: Session) -> dict:
    """O retrato que a tela de saúde mostra: último, próximo, testado, tamanho."""
    registros = (
        db.query(BackupRegistro)
        .order_by(BackupRegistro.id.desc())
        .limit(max(1, settings.backup_retencao))
        .all()
    )
    ultimo_ok = next((r for r in registros if r.status == StatusBackup.OK), None)
    ultimo_testado = next((r for r in registros if r.restauracao_testada_em), None)

    agora = _agora()
    horas_desde_ok = None
    if ultimo_ok is not None and ultimo_ok.finalizado_em is not None:
        fim = ultimo_ok.finalizado_em
        fim = fim if fim.tzinfo else fim.replace(tzinfo=timezone.utc)
        horas_desde_ok = (agora - fim).total_seconds() / 3600

    # Próximo previsto: hoje às `backup_hora` (hora local) se ainda não passou,
    # senão amanhã. É o que o operador espera ver ao lado de "último backup".
    previsto = agora.astimezone().replace(
        hour=settings.backup_hora, minute=0, second=0, microsecond=0
    )
    if previsto <= agora:
        previsto = previsto + timedelta(days=1)

    atrasado = bool(
        settings.backup_ativo
        and (
            horas_desde_ok is None
            and (
                # Sem nenhum backup ainda: só é atraso se o sistema já tem
                # conteúdo para perder.
                _tem_conteudo(db)
            )
            or (horas_desde_ok is not None and horas_desde_ok > settings.backup_alerta_horas)
        )
    )

    return {
        "ativo": settings.backup_ativo,
        "ultimo_ok_em": ultimo_ok.finalizado_em if ultimo_ok else None,
        "ultimo_ok_tamanho_bytes": ultimo_ok.tamanho_bytes if ultimo_ok else None,
        "horas_desde_ultimo_ok": horas_desde_ok,
        "ultimo_teste_em": ultimo_testado.restauracao_testada_em if ultimo_testado else None,
        "ultimo_teste_ok": ultimo_testado.restauracao_ok if ultimo_testado else None,
        "proximo_previsto_em": previsto.astimezone(timezone.utc),
        "retencao": settings.backup_retencao,
        "atrasado": atrasado,
        "total_registros": len(registros),
        "erros_recentes": sum(1 for r in registros if r.status == StatusBackup.ERRO),
        "tamanho_total_bytes": _tamanho_espelho(),
    }


def _tem_conteudo(db: Session) -> bool:
    from app.models import DocumentoFiscal, Empresa

    return bool(
        db.query(func.count(Empresa.id)).scalar()
        or db.query(func.count(DocumentoFiscal.id)).scalar()
    )


def _tamanho_espelho() -> int:
    total = 0
    for nome in ("espelho-xml", "espelho-certificados"):
        pasta = _pasta_backups() / nome
        if not pasta.exists():
            continue
        for caminho in pasta.rglob("*"):
            if caminho.is_file():
                total += caminho.stat().st_size
    return total
