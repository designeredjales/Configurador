import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from . import models, observabilidade  # noqa: F401  (registra as tabelas)
from .db import Base, engine
from .routers import (
    auth, cadastros, carrinhos, comercial, compras, configuracoes, controladoria, expedicao, financeiro, gestao, lotes, planejamento,
    pos_obra, producao, projetos, sistema,
)

STATIC = Path(__file__).parent / "static"
# Em produção o schema vem das migrações (alembic upgrade head); create_all fica para desenvolvimento
CRIAR_TABELAS = os.getenv("ERP_CRIAR_TABELAS", "1") == "1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if CRIAR_TABELAS:
        Base.metadata.create_all(engine)
    from .services import agendador  # consolidação financeira diária (ERP_AGENDADOR=0 desliga)
    agendador.iniciar()
    yield
    agendador.parar()


app = FastAPI(
    title="ERP Moveleiro",
    description="ERP para fábricas de móveis sob medida: do XML do Promob ao DRE da obra",
    version="1.0.0",
    lifespan=lifespan,
)


# Auditoria e erros ficam por dentro dos cabeçalhos de segurança (a resposta de erro também os recebe)
app.middleware("http")(observabilidade.observar)
observabilidade.configurar_sentry()


@app.middleware("http")
async def cabecalhos_seguranca(request: Request, call_next):
    resposta = await call_next(request)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    if request.url.path.startswith("/api/"):
        resposta.headers.setdefault("Cache-Control", "no-store")  # dados de negócio não ficam em cache
    return resposta


app.include_router(auth.router)
app.include_router(cadastros.router)
app.include_router(projetos.router)
app.include_router(producao.router)
app.include_router(compras.router)
app.include_router(financeiro.router)
app.include_router(pos_obra.router)
app.include_router(lotes.router)
app.include_router(expedicao.router)
app.include_router(carrinhos.router)
app.include_router(configuracoes.router)
app.include_router(sistema.router)
app.include_router(comercial.router)
app.include_router(gestao.router)
app.include_router(planejamento.router)
app.include_router(controladoria.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/api/saude", include_in_schema=False)
def saude():
    """Verificação para o orquestrador/balanceador: aplicação no ar e banco respondendo."""
    with engine.connect() as conexao:
        conexao.execute(text("select 1"))
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
