"""
Rotas do **programa**, não do negócio: versão, atualização, diagnóstico e
encerrar.

Elas existem porque o modo desktop precisa de um lugar onde a tela consiga
perguntar coisas que não são sobre nota fiscal: "tem versão nova?", "onde estão
meus dados?", "como eu fecho isso?". Deixar isso fora das rotas de negócio (e
fora do caminho de importação) mantém claro o que é operação fiscal e o que é
manutenção do programa.

No modo servidor elas continuam respondendo — com `modo_desktop: false` e sem
encerrar nada — para o painel não precisar de dois códigos.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.config import settings
from app.db.session import get_db
from app.api.deps import usuario_atual
from app.desktop import atualizador, caminhos, controle

log = logging.getLogger("notasflow.sistema")

router = APIRouter(prefix="/sistema", tags=["sistema"])

# Estado do processo de atualização. Vive na memória porque uma atualização
# nunca sobrevive ao processo que a iniciou: se o programa reiniciou, o estado
# certo é "nada acontecendo".
_estado_atualizacao = atualizador.Progresso(etapa="ocioso", mensagem="")
_trava = threading.Lock()
_verificado_em: datetime | None = None


class EncerrarResposta(BaseModel):
    encerrando: bool
    mensagem: str


class IniciarComWindows(BaseModel):
    ativar: bool


@router.get("/info")
def informacao_do_programa(_usuario=Depends(usuario_atual)):
    """
    Diagnóstico completo: versão, pastas, modo de execução, fila e agenda.

    É o que a tela "Configurações" mostra e o que o suporte pede por print
    quando algo não bate — as duas informações que mais resolvem chamado são
    *qual versão* e *onde estão os dados*.
    """
    fila = {}
    try:
        from app.worker.celery_app import celery_app

        if hasattr(celery_app, "estatisticas"):
            fila = celery_app.estatisticas()
        else:  # Celery de verdade não expõe a agenda por aqui
            fila = {"modo": "celery", "agenda": {k: {"tarefa": v.get("task")} for k, v in celery_app.conf.beat_schedule.items()}}
    except Exception as exc:  # noqa: BLE001 — diagnóstico nunca derruba a tela
        fila = {"erro": str(exc)[:200]}

    return {
        **caminhos.descricao_ambiente(),
        "modo_desktop": settings.modo_desktop,
        "modo_servidor": not settings.modo_desktop,
        "banco": "sqlite" if settings.usando_sqlite else "postgresql",
        "arquivo_env": str(caminhos.arquivo_env()),
        "fila": fila,
        "atualizacao": atualizador.info(),
        "verificado_em": _verificado_em.isoformat() if _verificado_em else None,
        "hora_do_servidor": datetime.now(timezone.utc).isoformat(),
        "diretorio_temporario": tempfile.gettempdir(),
        "iniciar_com_windows": _iniciar_com_windows_ativo(),
        "pode_iniciar_com_windows": platform.system() == "Windows" and settings.modo_desktop,
    }


def _iniciar_com_windows_ativo() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        from app.desktop.servidor import iniciar_com_windows_ativo

        return iniciar_com_windows_ativo()
    except Exception:  # noqa: BLE001 — diagnóstico não pode derrubar a tela
        return False


@router.post("/iniciar-com-windows")
def configurar_inicio_automatico(dados: IniciarComWindows, _usuario=Depends(usuario_atual)):
    """
    Liga/desliga "abrir junto com o Windows".

    É o que faz o sincronismo continuar existindo depois que o usuário reinicia
    o computador — sem isso, o programa só sincroniza quando alguém lembra de
    abri-lo, e a promessa de "não preciso clicar em nada" fica pela metade.
    """
    if platform.system() != "Windows":
        raise HTTPException(
            status_code=400, detail="Inicialização automática está disponível apenas no Windows."
        )
    from app.desktop.servidor import definir_iniciar_com_windows

    try:
        resultado = definir_iniciar_com_windows(dados.ativar)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Não foi possível alterar a inicialização automática: {exc}",
        ) from exc
    return {
        "ativo": resultado,
        "mensagem": (
            "O NotasFlow vai abrir junto com o Windows."
            if resultado
            else "O NotasFlow não vai mais abrir sozinho."
        ),
    }


@router.get("/atualizacao")
def estado_da_atualizacao(_usuario=Depends(usuario_atual)):
    """Última verificação conhecida — a tela usa para o aviso do topo."""
    with _trava:
        return {
            "etapa": _estado_atualizacao.etapa,
            "mensagem": _estado_atualizacao.mensagem,
            "erro": _estado_atualizacao.erro,
            "baixado": _estado_atualizacao.baixado,
            "total": _estado_atualizacao.total,
            "verificado_em": _verificado_em.isoformat() if _verificado_em else None,
            "versao_atual": atualizador.versao_atual(),
            "disponivel": (
                {
                    "versao": _estado_atualizacao.atualizacao.versao,
                    "notas": _estado_atualizacao.atualizacao.notas,
                    "obrigatoria": _estado_atualizacao.atualizacao.obrigatoria,
                    "tamanho": _estado_atualizacao.atualizacao.arquivo.tamanho
                    if _estado_atualizacao.atualizacao.arquivo
                    else 0,
                }
                if _estado_atualizacao.atualizacao
                else None
            ),
        }


def verificar_em_segundo_plano() -> tuple[bool, str]:
    """
    Dispara a verificação de versão nova e devolve `(iniciado, mensagem)`.

    É a função — e não a rota — porque existem três lugares que precisam
    perguntar a mesma coisa: o botão da tela, a abertura do programa e a
    checagem periódica de quem fica aberto por dias. Todos passam por aqui, o
    que garante que o resultado apareça na mesma faixa de aviso do painel.

    Roda numa thread para ninguém ficar esperando rede: quem chamou recebe a
    resposta na hora e o estado é acompanhado por `/sistema/atualizacao`.
    """
    global _verificado_em

    with _trava:
        if _estado_atualizacao.etapa in ("baixando", "verificando_hash", "instalando"):
            return False, "Já existe uma atualização em andamento."
        if _estado_atualizacao.etapa == "verificando":
            return False, "Já existe uma verificação em andamento."
        _estado_atualizacao.etapa = "verificando"
        _estado_atualizacao.mensagem = "Verificando se existe versão nova…"
        _estado_atualizacao.erro = None
        _estado_atualizacao.baixado = 0
        _estado_atualizacao.total = 0

    def tarefa() -> None:
        global _verificado_em
        resultado = atualizador.verificar(_estado_atualizacao)
        _verificado_em = datetime.now(timezone.utc)
        with _trava:
            _estado_atualizacao.atualizacao = resultado
            _estado_atualizacao.etapa = "disponivel" if resultado else "atualizado"
            if resultado is None and not _estado_atualizacao.mensagem.startswith("Não foi possível"):
                _estado_atualizacao.mensagem = (
                    f"Você está na versão mais nova ({atualizador.versao_atual()})."
                )
            elif resultado is not None:
                _estado_atualizacao.mensagem = (
                    f"Versão {resultado.versao} disponível "
                    f"(você tem {atualizador.versao_atual()})."
                )

    threading.Thread(target=tarefa, name="notasflow-verificar-update", daemon=True).start()
    return True, "Verificando…"


@router.post("/atualizacao/verificar")
def verificar_atualizacao(forcar: bool = Query(default=True), _usuario=Depends(usuario_atual)):
    """O botão "Verificar agora" da tela de Configurações."""
    iniciado, mensagem = verificar_em_segundo_plano()
    return {"iniciado": iniciado, "mensagem": mensagem}


@router.post("/atualizacao/aplicar", status_code=202)
def aplicar_atualizacao(_usuario=Depends(usuario_atual)):
    """
    Baixa, confere o SHA-256, instala e reabre — nesta ordem, sem clique.

    A resposta sai em 202 e a tela mostra o progresso. O processo **vai
    encerrar** quando o download terminar: é obrigatório no Windows, onde um
    programa em execução não consegue substituir os próprios arquivos.
    """
    with _trava:
        atualizacao = _estado_atualizacao.atualizacao
        if _estado_atualizacao.etapa in ("baixando", "verificando_hash", "instalando"):
            raise HTTPException(status_code=409, detail="Já existe uma atualização em andamento.")

    if atualizacao is None or not atualizacao.disponivel:
        raise HTTPException(
            status_code=404,
            detail="Nenhuma atualização verificada. Use 'Verificar atualizações' antes.",
        )

    if not settings.modo_desktop:
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta instalação roda em modo servidor (Docker). Atualize com "
                "`git pull` e `docker compose up --build -d` na máquina do servidor."
            ),
        )

    with _trava:
        _estado_atualizacao.etapa = "baixando"
        _estado_atualizacao.erro = None
        _estado_atualizacao.atualizacao = atualizacao

    def tarefa() -> None:
        try:
            atualizador.aplicar(atualizacao, _estado_atualizacao)
        except Exception as exc:  # noqa: BLE001 — falha de atualização vira aviso, não crash
            log.exception("Falha ao aplicar atualização: %s", exc)
            with _trava:
                _estado_atualizacao.etapa = "erro"
                _estado_atualizacao.erro = str(exc)[:600]
                _estado_atualizacao.mensagem = "Não foi possível atualizar agora."
            return

        with _trava:
            _estado_atualizacao.etapa = "instalando"
            _estado_atualizacao.mensagem = "Instalando e reabrindo…"
        # Só agora: o `.cmd` já está esperando este processo sair.
        controle.encerrar("atualização aplicada")

    threading.Thread(target=tarefa, name="notasflow-aplicar-update", daemon=True).start()
    return {"iniciado": True, "versao": atualizacao.versao}


@router.post("/encerrar", response_model=EncerrarResposta)
def encerrar_programa(_usuario=Depends(usuario_atual)):
    """
    Fecha o NotasFlow por completo (a API e a janela), não só a aba.

    Existe porque no programa instalado não há "servidor": se o usuário só
    fechar a aba do navegador, sobra um processo rodando escondido — e um
    programa que não fecha é percebido como programa defeituoso.
    """
    if not settings.modo_desktop:
        return EncerrarResposta(
            encerrando=False,
            mensagem="Esta instalação roda como servidor; encerre pelo Docker (docker compose down).",
        )
    if not controle.tem_encerrador():
        raise HTTPException(status_code=503, detail="O programa ainda está iniciando. Tente de novo em segundos.")
    controle.encerrar("pedido da tela")
    return EncerrarResposta(encerrando=True, mensagem="Fechando o NotasFlow…")


@router.get("/logs")
def ler_logs(linhas: int = Query(default=200, ge=1, le=2000), _usuario=Depends(usuario_atual)):
    """
    Últimas linhas do log do programa.

    Num programa sem console, o log é a única forma de o usuário (ou você, por
    telefone) descobrir o que aconteceu. Fica na pasta de dados.
    """
    arquivo = caminhos.pasta_logs() / "notasflow.log"
    if not arquivo.is_file():
        return {"arquivo": str(arquivo), "linhas": [], "mensagem": "Ainda não há log gravado."}
    try:
        with open(arquivo, "r", encoding="utf-8", errors="replace") as manipulador:
            conteudo = manipulador.readlines()[-linhas:]
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Não foi possível ler o log: {exc}") from exc
    return {"arquivo": str(arquivo), "linhas": [linha.rstrip("\n") for linha in conteudo]}


@router.post("/backup")
def gerar_backup(_usuario=Depends(usuario_atual)):
    """
    ZIP com banco, certificados e configuração — o que precisa de backup.

    Este é o único backup que realmente importa neste sistema: os XMLs podem
    ser baixados de novo da SEFAZ (dentro dos ~3 meses), mas o banco guarda o
    histórico e o `.env` guarda a chave que abre as senhas dos certificados.
    Sem esse par, todo certificado precisa ser reenviado.

    Fica na pasta `backups` da pasta de dados — o usuário copia para o
    OneDrive/pen drive dele.
    """
    pasta = caminhos.pasta_backups()
    carimbo = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino = pasta / f"notasflow-backup-{carimbo}.zip"

    dados_dir = Path(settings.dados_dir)
    origem_banco = caminhos.caminho_banco() if settings.usando_sqlite else None

    try:
        with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as pacote:
            # O banco vai pelo mecanismo de backup do próprio SQLite: copiar o
            # arquivo enquanto o worker grava daria um banco possivelmente
            # corrompido — e um backup que não abre é pior que nenhum.
            if origem_banco is not None and origem_banco.is_file():
                pacote.writestr("notasflow.db", _copia_consistente_do_banco())
            arquivo_env = caminhos.arquivo_env()
            if arquivo_env.is_file():
                pacote.write(arquivo_env, ".env")
            for pasta_nome in ("certificados",):
                raiz = dados_dir / pasta_nome
                if not raiz.is_dir():
                    continue
                for caminho in raiz.rglob("*"):
                    if caminho.is_file():
                        pacote.write(caminho, str(Path("dados") / pasta_nome / caminho.relative_to(raiz)))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Falha ao gerar o backup: {exc}") from exc

    if not os.path.isfile(destino):
        raise HTTPException(status_code=500, detail="O backup não pôde ser escrito.")

    # Mantém os 10 mais recentes: backup que enche o disco vira problema.
    antigos = sorted(pasta.glob("notasflow-backup-*.zip"))[:-10]
    for velho in antigos:
        try:
            velho.unlink()
        except OSError:
            pass

    return {
        "arquivo": str(destino),
        "bytes": destino.stat().st_size,
        "mensagem": "Backup criado. Copie o arquivo para um pen drive ou para a nuvem.",
    }


def _copia_consistente_do_banco() -> bytes:
    """
    Snapshot do SQLite **sem** depender de o banco estar parado.

    A API `Connection.backup()` do sqlite3 faz isso dentro do próprio motor:
    pega um ponto consistente mesmo com várias threads gravando. É a diferença
    entre um backup que abre e um arquivo corrompido.
    """
    import sqlite3
    import tempfile as _tempfile

    origem = sqlite3.connect(str(caminhos.caminho_banco()))
    temporario = _tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temporario.close()
    try:
        destino = sqlite3.connect(temporario.name)
        try:
            origem.backup(destino)
        finally:
            destino.close()
        return Path(temporario.name).read_bytes()
    finally:
        origem.close()
        try:
            os.unlink(temporario.name)
        except OSError:
            pass


@router.post("/abrir-pasta")
def abrir_pasta(_usuario=Depends(usuario_atual)):
    """
    Abre a pasta de dados no Explorador de Arquivos / Finder.

    Detalhe de usabilidade que economiza muito telefone: "onde ficam meus
    arquivos?" respondido com a pasta abrindo na frente do usuário.
    """
    pasta = caminhos.pasta_dados()
    try:
        if platform.system() == "Windows":
            os.startfile(str(pasta))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            import subprocess

            subprocess.Popen(["open", str(pasta)])
        else:
            import subprocess

            subprocess.Popen(["xdg-open", str(pasta)])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Não foi possível abrir a pasta: {exc}") from exc
    return {"pasta": str(pasta)}


@router.get("/saude-detalhada")
def saude_detalhada(db=Depends(get_db), _usuario=Depends(usuario_atual)):
    """Checagem que a tela faz para dizer 'está tudo funcionando' em um lugar só."""
    from sqlalchemy import text

    problemas: list[str] = []
    disco_livre = None
    try:
        uso = shutil.disk_usage(str(caminhos.pasta_dados()))
        disco_livre = uso.free
        if uso.free < 500 * 1024 * 1024:
            problemas.append(
                "Menos de 500 MB livres em disco — libere espaço antes de importar mais XMLs."
            )
    except OSError:
        pass

    banco_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        banco_ok = False
        problemas.append(f"Banco de dados inacessível: {str(exc)[:200]}")

    if settings.vault_master_key:
        try:
            from app.core.vault import decifrar_segredo, cifrar_segredo

            if decifrar_segredo(cifrar_segredo("teste")) != "teste":
                problemas.append("O cofre de certificados não está conseguindo cifrar/decifrar.")
        except Exception as exc:  # noqa: BLE001
            problemas.append(f"Cofre de certificados com problema: {str(exc)[:200]}")
    else:
        problemas.append("VAULT_MASTER_KEY não configurada — certificados não podem ser gravados.")

    if settings.modo_desktop and not caminhos.tem_painel_web():
        problemas.append("O painel web não foi encontrado no pacote (instalação incompleta?).")

    return {
        "ok": not problemas,
        "problemas": problemas,
        "banco_ok": banco_ok,
        "disco_livre_bytes": disco_livre,
        "pasta_dados": str(caminhos.pasta_dados()),
    }
