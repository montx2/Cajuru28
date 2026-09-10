"""
Aplicação FastAPI — o mesmo backend nos dois modos.

A diferença entre "servidor" e "programa instalado" aparece em dois pontos, e
só neles:

1. no fim do arquivo, o **painel web** é montado a partir do build estático
   quando `MODO_DESKTOP=true` (no servidor quem serve o painel é o contêiner
   Node);
2. na inicialização, a **fila em processo** é ligada — no servidor quem cuida
   disso é o `celery worker` + `celery beat`.

Todo o resto (importadores, governador de consumo da SEFAZ, cofre, rotas) é
literalmente o mesmo código. É isso que permite corrigir um bug uma vez e as
duas implantações ficarem corrigidas.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, certificados, documentos, empresas, importacoes, sistema
from app.bootstrap import garantir_usuario_inicial
from app.core.config import settings
from app.db.base import criar_tabelas

log = logging.getLogger("notasflow")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    """
    Startup: cria/atualiza tabelas, garante o usuário inicial e, no modo
    desktop, liga a fila em processo.

    Usa `lifespan` (e não o `@app.on_event`, que está depreciado) porque o
    encerramento precisa ser determinístico: ao fechar o programa, a fila para
    e as conexões do banco fecham antes do processo morrer. Um SQLite fechado
    no meio de uma escrita é um arquivo a menos para explicar depois.
    """
    criar_tabelas()
    garantir_usuario_inicial()

    if settings.modo_desktop:
        # Importar aqui garante que as tarefas existem antes de a fila subir —
        # o agendador procura por nome, e um nome desconhecido é simplesmente
        # ignorado (o que faria o sincronismo automático nunca rodar).
        from app.worker import tasks  # noqa: F401
        from app.worker.celery_app import celery_app

        if hasattr(celery_app, "iniciar"):
            celery_app.iniciar()
        log.info(
            "Modo desktop: fila em processo ativa (concorrência %s).",
            settings.notasflow_concorrencia,
        )

    yield

    if settings.modo_desktop:
        from app.worker.celery_app import celery_app

        if hasattr(celery_app, "parar"):
            celery_app.parar()


app = FastAPI(
    title="NotasFlow",
    description=(
        "Importação automática de NFS-e, NFe e CT-e via ADN/SEFAZ, com certificado A1."
    ),
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

# O painel roda em outra origem no modo servidor (Next.js na porta 3000). No
# modo desktop o painel é servido pela própria API, então não há CORS nenhum
# acontecendo — mas a configuração continua valendo para quem usa o servidor.
_origens = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if "*" in _origens:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origens or ["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


app.include_router(auth.router)
app.include_router(empresas.router)
app.include_router(certificados.router)
app.include_router(documentos.router)
app.include_router(importacoes.router)
app.include_router(sistema.router)


@app.get("/saude", tags=["infra"])
def verificar_saude():
    """
    Identificação + estado. A tela inicial e o próprio programa usam isto para
    saber que a API subiu e qual versão está respondendo.
    """
    from app.desktop.caminhos import versao_do_pacote

    return {
        "status": "ok",
        "app": "NotasFlow",
        "versao": versao_do_pacote(),
        "modo": "desktop" if settings.modo_desktop else "servidor",
    }


# ---------------------------------------------------------------------------
# Painel web embutido (modo desktop)
# ---------------------------------------------------------------------------
# Fica por último de propósito: as rotas da API são registradas antes e por
# isso têm prioridade. Este "pega-tudo" só responde o que sobrou — que é
# exatamente o painel.
if settings.modo_desktop:
    from app.desktop import caminhos
    from app.desktop.painel import PainelEstatico

    _pasta_web = caminhos.pasta_web()
    if caminhos.tem_painel_web():
        app.mount("/", PainelEstatico(_pasta_web), name="painel")
        log.info("Painel web servido de %s", _pasta_web)
    else:
        log.warning(
            "MODO_DESKTOP ligado, mas o painel web não foi encontrado em %s. "
            "Rode o build do frontend (npm run build:desktop).",
            _pasta_web,
        )
