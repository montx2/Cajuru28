from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, certificados, documentos, empresas, importacoes
from app.core.config import settings
from app.db.base import criar_tabelas

app = FastAPI(
    title="NotasFlow",
    description="Importação automática de NFS-e, NFe e CT-e via ADN/SEFAZ, com certificado A1.",
    version="0.2.0",
)

# Frontend (Next.js) roda em outra origem — sem CORS o browser bloqueia o login.
_origens = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def ao_iniciar() -> None:
    criar_tabelas()


app.include_router(auth.router)
app.include_router(empresas.router)
app.include_router(certificados.router)
app.include_router(documentos.router)
app.include_router(importacoes.router)


@app.get("/saude", tags=["infra"])
def verificar_saude():
    return {"status": "ok", "versao": "0.2.0"}
