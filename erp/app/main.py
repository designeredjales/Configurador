from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (registra as tabelas)
from .db import Base, engine
from .routers import auth, cadastros, compras, producao, projetos

STATIC = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Até entrar o Alembic, o schema nasce do modelo
    Base.metadata.create_all(engine)
    yield


app = FastAPI(
    title="ERP Moveleiro",
    description="Núcleo Engenharia + PCP para fábricas de móveis sob medida",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(auth.router)
app.include_router(cadastros.router)
app.include_router(projetos.router)
app.include_router(producao.router)
app.include_router(compras.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
