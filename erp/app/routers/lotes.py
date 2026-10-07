"""Formação e controle de lotes de produção."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import PCP, empresa_atual
from ..models import Empresa, LoteProducao, Usuario
from ..schemas import LoteAdicionar, LoteIn, LoteOut, PlanoCorte
from ..services import lotes, pcp
from .producao import montar_html, montar_plano, montar_zpl

router = APIRouter(prefix="/api/lotes", tags=["lotes"])


def carregar_lote(db: Session, emp: Empresa, lote_id: int) -> LoteProducao:
    lote = db.get(LoteProducao, lote_id)
    if lote is None or lote.empresa_id != emp.id:
        raise HTTPException(404, "Lote não encontrado")
    return lote


@router.get("", response_model=list[LoteOut])
def listar(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    todos = db.scalars(select(LoteProducao).where(LoteProducao.empresa_id == emp.id).order_by(LoteProducao.numero.desc()))
    return [lotes.resumo(lo) for lo in todos]


@router.post("", response_model=LoteOut, status_code=201)
def formar(dados: LoteIn, usuario: Usuario = Depends(PCP), db: Session = Depends(get_db)):
    try:
        lote = lotes.formar(db, usuario.empresa_id, dados.descricao, dados.projeto_ids, dados.prioridade,
                            dados.data_entrega, usuario)
    except pcp.ErroPCP as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return lotes.resumo(lote)


@router.get("/{lote_id}", response_model=LoteOut)
def detalhe(lote_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return lotes.resumo(carregar_lote(db, emp, lote_id))


@router.post("/{lote_id}/projetos", response_model=LoteOut, dependencies=[Depends(PCP)])
def adicionar(lote_id: int, dados: LoteAdicionar, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    lote = carregar_lote(db, emp, lote_id)
    try:
        lotes.adicionar(db, lote, dados.projeto_ids)
    except pcp.ErroPCP as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return lotes.resumo(lote)


@router.post("/{lote_id}/voltar-programacao", response_model=LoteOut)
def voltar_programacao(lote_id: int, usuario: Usuario = Depends(PCP), emp: Empresa = Depends(empresa_atual),
                       db: Session = Depends(get_db)):
    """Desfaz o lote inteiro: todas as OPs voltam e os projetos ficam livres para outro lote."""
    lote = carregar_lote(db, emp, lote_id)
    try:
        lotes.voltar_lote(db, lote, usuario)
    except pcp.ErroPCP as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    db.refresh(lote)
    return lotes.resumo(lote)


@router.get("/{lote_id}/plano-corte", response_model=PlanoCorte)
def plano_corte(lote_id: int, apenas_reposicoes: bool = False, emp: Empresa = Depends(empresa_atual),
                db: Session = Depends(get_db)):
    lote = carregar_lote(db, emp, lote_id)
    return {"titulo": f"Lote {lote.numero}", **montar_plano(emp, lotes.unidades(lote, apenas_reposicoes))}


@router.get("/{lote_id}/etiquetas.zpl", response_class=PlainTextResponse)
def etiquetas_zpl(lote_id: int, apenas_reposicoes: bool = False, emp: Empresa = Depends(empresa_atual),
                  db: Session = Depends(get_db)):
    lote = carregar_lote(db, emp, lote_id)
    return PlainTextResponse(montar_zpl(lotes.unidades(lote, apenas_reposicoes)), headers={
        "Content-Disposition": f'attachment; filename="lote{lote.numero}_etiquetas.zpl"'})


@router.get("/{lote_id}/etiquetas.html", response_class=HTMLResponse)
def etiquetas_html(lote_id: int, apenas_reposicoes: bool = False, emp: Empresa = Depends(empresa_atual),
                   db: Session = Depends(get_db)):
    lote = carregar_lote(db, emp, lote_id)
    return HTMLResponse(montar_html(f"Lote {lote.numero} · {lote.descricao}", lotes.unidades(lote, apenas_reposicoes)))
