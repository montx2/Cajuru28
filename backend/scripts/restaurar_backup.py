#!/usr/bin/env python3
"""Restaura um pacote Fluxa v2 somente em destino vazio e explícito.

Não é endpoint HTTP e não sobrescreve uma operação viva: use numa cópia nova
em recuperação, depois faça a validação funcional antes de apontar o proxy.

Exemplos (executados no container/imagem backend com BACKUP_ENCRYPTION_KEY):
  python scripts/restaurar_backup.py --arquivo /backups/backup-....tar.gz.enc --validar
  python scripts/restaurar_backup.py --arquivo /backup.tar.gz.enc \
    --destino-dados /restore-data --database-url "$DATABASE_URL" \
    --checksum SHA256_DO_REGISTRO_OU_S3 --confirmar RESTAURAR
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import tempfile
from pathlib import Path

# Funciona tanto como `python scripts/...` dentro da imagem quanto como
# `python backend/scripts/...` a partir da raiz do repositório.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import create_engine, func, insert, select, text

from app.db.base import Base
from app.services.backup import _desserializar, extrair_backup_verificado


def _banco_vazio(engine) -> bool:
    """Recusa restaurar se qualquer tabela conhecida já tiver dado."""
    Base.metadata.create_all(engine)
    with engine.connect() as conexao:
        for tabela in Base.metadata.sorted_tables:
            if conexao.execute(select(tabela.c[0]).limit(1)).first() is not None:
                return False
    return True


def _redefinir_sequencias_postgres(conexao) -> None:
    """Após insert explícito de IDs, faz o próximo INSERT continuar no ID certo."""
    if conexao.dialect.name != "postgresql":
        return
    for tabela in Base.metadata.sorted_tables:
        pk = list(tabela.primary_key.columns)
        if len(pk) != 1:
            continue
        coluna = pk[0]
        sequencia = conexao.execute(
            text("SELECT pg_get_serial_sequence(:tabela, :coluna)"),
            {"tabela": tabela.name, "coluna": coluna.name},
        ).scalar()
        if not sequencia:
            continue
        maior = conexao.execute(select(func.max(coluna))).scalar()
        conexao.execute(
            text("SELECT setval(CAST(:sequencia AS regclass), :valor, :chamada)"),
            {"sequencia": sequencia, "valor": maior or 1, "chamada": maior is not None},
        )


def _restaurar_banco(engine, conteudo: Path, manifesto: dict) -> int:
    if not _banco_vazio(engine):
        raise RuntimeError("O banco de destino não está vazio; restauração foi abortada.")
    carregadas: dict[str, int] = {}
    with gzip.open(conteudo / "banco.jsonl.gz", "rt", encoding="utf-8") as arquivo:
        with engine.begin() as conexao:
            for linha_bruta in arquivo:
                import json

                linha = json.loads(linha_bruta)
                tabela = Base.metadata.tables[linha["t"]]
                conexao.execute(insert(tabela).values(_desserializar(tabela, linha["d"])))
                carregadas[linha["t"]] = carregadas.get(linha["t"], 0) + 1
            _redefinir_sequencias_postgres(conexao)
    esperadas = manifesto.get("contagens", {})
    if any(carregadas.get(nome, 0) != total for nome, total in esperadas.items()):
        raise RuntimeError("As contagens carregadas divergem do manifesto; destino deve ser descartado.")
    return sum(carregadas.values())


def _restaurar_objetos(conteudo: Path, destino_dados: Path) -> int:
    """Copia XML e certificados somente para árvore nova/vazia."""
    if destino_dados.exists() and any(destino_dados.iterdir()):
        raise RuntimeError("O diretório de dados de destino não está vazio; restauração foi abortada.")
    destino_dados.mkdir(parents=True, exist_ok=True)
    temporario = destino_dados / ".notasflow-restore-em-andamento"
    if temporario.exists():
        raise RuntimeError("Há uma restauração anterior inacabada no diretório de destino.")
    temporario.mkdir()
    try:
        total = 0
        for categoria in ("xml", "certificados"):
            origem = conteudo / "objetos" / categoria
            alvo = temporario / categoria
            if origem.exists():
                shutil.copytree(origem, alvo)
                total += sum(1 for arquivo in alvo.rglob("*") if arquivo.is_file())
            else:
                alvo.mkdir()
        # Os destinos finais ainda não existem porque a pasta inicial era vazia.
        (temporario / "xml").replace(destino_dados / "xml")
        (temporario / "certificados").replace(destino_dados / "certificados")
        temporario.rmdir()
        return total
    except Exception:
        shutil.rmtree(temporario, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida ou restaura backup cifrado Fluxa v2")
    parser.add_argument("--arquivo", required=True, type=Path, help="pacote .tar.gz.enc")
    parser.add_argument("--checksum", help="SHA-256 do banco ou metadata S3; recomendado")
    parser.add_argument("--validar", action="store_true", help="só valida cifra, manifesto e hashes")
    parser.add_argument("--destino-dados", type=Path, help="nova pasta vazia que receberá xml/certificados")
    parser.add_argument("--database-url", help="URL de banco novo e vazio; não é impressa")
    parser.add_argument("--confirmar", help="digite RESTAURAR para executar gravações")
    args = parser.parse_args()

    if args.validar and (args.destino_dados or args.database_url or args.confirmar):
        parser.error("--validar não pode ser combinado com opções de restauração")
    if not args.validar:
        if args.confirmar != "RESTAURAR":
            parser.error("a restauração exige --confirmar RESTAURAR")
        if not args.destino_dados or not args.database_url:
            parser.error("informe --destino-dados e --database-url para restaurar")

    try:
        with tempfile.TemporaryDirectory(prefix="notasflow-restore-") as diretorio:
            conteudo, manifesto = extrair_backup_verificado(
                args.arquivo, Path(diretorio), checksum_esperado=args.checksum
            )
            total_objetos = sum(
                len(manifesto.get("objetos", {}).get(categoria, []))
                for categoria in ("xml", "certificados")
            )
            if args.validar:
                print(
                    f"Backup válido: {manifesto.get('total_registros', 0)} registros e "
                    f"{total_objetos} objeto(s) fiscal(is) com hashes conferidos."
                )
                return 0

            engine = create_engine(args.database_url)
            try:
                total_registros = _restaurar_banco(engine, conteudo, manifesto)
            finally:
                engine.dispose()
            objetos = _restaurar_objetos(conteudo, args.destino_dados)
            print(
                f"Restauração concluída no destino novo: {total_registros} registros e "
                f"{objetos} objeto(s). Valide o ambiente isolado antes do corte."
            )
            return 0
    except Exception as exc:  # noqa: BLE001 - ferramenta CLI precisa sair com diagnóstico seguro
        print(f"Restauração não executada: {str(exc)[:500]}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
