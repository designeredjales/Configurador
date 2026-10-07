"""Gestão à vista (metas, kanban, restrição, pulmões) e setup da base (exportar, modelos, aplicar)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ADMIN, INDICADORES, empresa_atual
from ..models import Empresa
from ..services import gestao, setup

router = APIRouter(prefix="/api", tags=["gestao"])


# --- Gestão à vista ------------------------------------------------------------------------------

@router.get("/gestao/painel", dependencies=[Depends(INDICADORES)])
def painel(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    r = gestao.painel(db, emp.id)
    db.commit()  # cria a configuração padrão na primeira visita
    return r


@router.get("/gestao/config", dependencies=[Depends(INDICADORES)])
def ver_config(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    cfg = gestao.config(db, emp.id)
    db.commit()
    return gestao.config_out(cfg)


@router.put("/gestao/config", dependencies=[Depends(ADMIN)])
def salvar_config(dados: setup.Gestao, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    s = setup.Setup(gestao=dados)
    try:
        setup.aplicar(db, emp, s, ["gestao"])
    except setup.ErroSetup as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    cfg = gestao.config(db, emp.id)
    # Metas e limites vêm completos da tela: o que ficou em branco deixa de ser cobrado
    if dados.metas is not None:
        cfg.metas = {k: v for k, v in dados.metas.items() if v is not None and k in {c for c, *_ in gestao.METAS}}
    if dados.limites_wip is not None:
        cfg.limites_wip = {k: v for k, v in dados.limites_wip.items() if v and k in {c for c, _ in gestao.COLUNAS}}
    db.commit()
    return gestao.config_out(cfg)


# --- Setup da base ------------------------------------------------------------------------------

@router.get("/setup/exportar", dependencies=[Depends(ADMIN)])
def exportar(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    dados = setup.exportar(db, emp)
    db.commit()
    return dados


@router.get("/setup/modelos", dependencies=[Depends(ADMIN)])
def listar_modelos():
    return {"secoes": setup.SECOES, "modelos": setup.modelos()}


@router.get("/setup/modelos/{codigo}", dependencies=[Depends(ADMIN)])
def ver_modelo(codigo: str):
    try:
        return setup.modelo(codigo)
    except setup.ErroSetup as e:
        raise HTTPException(404, str(e))


class AplicarIn(BaseModel):
    setup: dict | None = None
    modelo: str | None = Field(None, max_length=80)
    secoes: list[str] | None = None
    simular: bool = True


@router.post("/setup/aplicar", dependencies=[Depends(ADMIN)])
def aplicar(dados: AplicarIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Simula (padrão) ou aplica um setup. A simulação devolve as mudanças sem gravar nada."""
    try:
        bruto = setup.modelo(dados.modelo) if dados.modelo else dados.setup
        if bruto is None:
            raise setup.ErroSetup("Envie o arquivo de setup ou escolha um modelo")
        s = setup.validar(bruto)
        mudancas = setup.aplicar(db, emp, s, dados.secoes)
    except setup.ErroSetup as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    if dados.simular:
        db.rollback()
    else:
        db.commit()
    return {"nome": s.nome, "simulado": dados.simular, "mudancas": mudancas,
            "secoes": [x for x in setup.SECOES if getattr(s, x) is not None and (not dados.secoes or x in dados.secoes)]}
