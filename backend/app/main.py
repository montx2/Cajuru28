from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, certificados, documentos, empresas, importacoes
from app.bootstrap import garantir_usuario_inicial
from app.core.config import settings
from app.db.base import criar_tabelas


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    criar_tabelas()
    garantir_usuario_inicial()
    yield
    # Shutdown (se precisar)


app = FastAPI(
    title="NotasFlow",
    description="Importação automática de NFS-e, NFe e CT-e via ADN/SEFAZ, com certificado A1.",
    version="1.0.0",
    lifespan=lifespan,
)

# Frontend (Next.js) roda em outra origem — sem CORS o browser bloqueia o login.
# No modo desktop (.exe), Electron carrega via file://, então precisamos liberar tudo.
_origens = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
if settings.is_desktop or "*" in _origens:
    # Desktop: libera qualquer origem (file://, localhost, etc)
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


@app.get("/saude", tags=["infra"])
def verificar_saude():
    return {"status": "ok", "versao": "1.0.0", "modo": "desktop" if settings.is_desktop else "server"}


@app.get("/", tags=["infra"])
def root():
    return {
        "nome": "NotasFlow",
        "versao": "1.0.0",
        "modo": "desktop" if settings.is_desktop else "server",
        "docs": "/docs",
        "saude": "/saude",
    }
