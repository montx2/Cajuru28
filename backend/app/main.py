from fastapi import FastAPI

from app.api.routers import auth, certificados, documentos, empresas, importacoes
from app.db.base import criar_tabelas

app = FastAPI(
    title="NotasFlow",
    description="Importação automática de NFS-e, NFe e CT-e via ADN/SEFAZ, com certificado A1.",
    version="0.1.0",
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
    return {"status": "ok"}
