"""API FastAPI do NotasFlow."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.routers import (
    acessorias,
    alertas,
    auditoria,
    auth,
    certificados,
    dashboard,
    documentos,
    empresas,
    importacoes,
    integracoes,
    metricas,
    painel,
    relatorios,
    sistema,
    usuarios,
)
from app.bootstrap import garantir_usuario_inicial
from app.core.config import settings
from app.core.rate_limit import limitar_mutacao
from app.db.base import criar_tabelas


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    # Valida de novo na inicialização para tornar a fronteira evidente nos logs
    # e impedir que uma instância de produção incompleta comece a servir dados.
    settings.validar_producao()
    criar_tabelas()
    garantir_usuario_inicial()
    yield


app = FastAPI(
    title="NotasFlow",
    description="Sistema operacional fiscal privado.",
    version="3.1.0",
    lifespan=ciclo_de_vida,
    # Swagger/OpenAPI não é superfície necessária no servidor público.
    docs_url=None if settings.em_producao else "/docs",
    redoc_url=None if settings.em_producao else "/redoc",
    openapi_url=None if settings.em_producao else "/openapi.json",
)

_origens = settings.cors_origens_lista
_hosts = [host.strip() for host in settings.trusted_hosts.split(",") if host.strip()]
# Certificado A1 permitido = 30 MiB; margem cobre multipart. Este limite vem
# antes do parser FastAPI para que uma requisição declaradamente gigante não
# consuma memória/disco. Caddy replica a barreira no perímetro público.
_MAX_TAMANHO_REQUISICAO = 35 * 1024 * 1024
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origens,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


@app.middleware("http")
async def protecoes_http(request: Request, call_next):
    """CSRF, limite de mutações e cabeçalhos mínimos para API pública."""
    try:
        tamanho_declarado = int(request.headers.get("content-length", "0"))
    except ValueError:
        tamanho_declarado = 0
    if tamanho_declarado > _MAX_TAMANHO_REQUISICAO:
        return JSONResponse(
            status_code=413,
            content={"detail": "Requisição excede o limite de 35 MiB."},
        )

    metodo_inseguro = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    usa_cookie = bool(request.cookies.get(settings.session_cookie_name))
    webhook_jettax = request.url.path.startswith("/integracoes/jettax/webhooks/")

    # Cookies HttpOnly eliminam a exposição ao JavaScript, mas exigem proteção
    # explícita contra submissão cross-site. O login também é protegido quando
    # chega de um browser (login-CSRF troca silenciosamente a sessão da vítima
    # pela conta do atacante). Clientes não-browser sem Origin seguem podendo
    # autenticar por contrato; uma sessão já existente sempre exige Origin.
    origem = request.headers.get("origin", "").rstrip("/")
    exige_origem = usa_cookie or (request.url.path == "/auth/login" and bool(origem))
    if metodo_inseguro and not webhook_jettax and exige_origem:
        if not origem or origem not in _origens:
            return JSONResponse(
                status_code=403,
                content={"detail": "Origem não autorizada para esta sessão."},
            )

    if (
        metodo_inseguro
        and request.url.path not in {"/auth/login", "/auth/logout"}
        and not webhook_jettax
    ):
        try:
            limitar_mutacao(request)
        except Exception as exc:  # HTTPException não deve virar stacktrace de middleware
            status_code = getattr(exc, "status_code", 503)
            detalhe = getattr(exc, "detail", "Proteção de acesso indisponível.")
            headers = getattr(exc, "headers", None)
            return JSONResponse(status_code=status_code, content={"detail": detalhe}, headers=headers)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    if settings.em_producao:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    return response


app.include_router(auth.router)
app.include_router(acessorias.router)
app.include_router(usuarios.router)
app.include_router(auditoria.router)
app.include_router(metricas.router)
app.include_router(empresas.router)
app.include_router(certificados.router)
app.include_router(documentos.router)
app.include_router(importacoes.router)
app.include_router(integracoes.router)
app.include_router(dashboard.router)
app.include_router(painel.router)
app.include_router(alertas.router)
app.include_router(relatorios.router)
app.include_router(sistema.router)


@app.get("/saude", tags=["infra"])
def verificar_saude():
    return {"status": "ok", "app": "NotasFlow", "ambiente": settings.app_env}
