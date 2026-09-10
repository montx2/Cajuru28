"""API FastAPI do NotasFlow, executada no ambiente Docker."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, certificados, documentos, empresas, importacoes, sistema
from app.bootstrap import garantir_usuario_inicial
from app.core.config import settings
from app.db.base import criar_tabelas


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    """Prepara o banco e o usuário; workers e agenda rodam em contêineres próprios."""
    criar_tabelas()
    garantir_usuario_inicial()
    yield


app = FastAPI(
    title="NotasFlow",
    description="Importação automática de NFS-e, NFe e CT-e via ADN/SEFAZ.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)

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
    return {"status": "ok", "app": "NotasFlow", "modo": "docker"}
