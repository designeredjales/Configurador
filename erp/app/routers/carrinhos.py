"""Carrinhos: apontamento agrupado, conferência do carrinho inteiro e marcadores por obra."""
import html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import APONTAR, PCP, empresa_atual
from ..models import Carrinho, Empresa, Usuario
from ..schemas import (
    BipeCarrinhoIn,
    BipeCarrinhoOut,
    CarrinhoOut,
    ConferenciaOut,
    ConferirCarrinhoIn,
    CriarCarrinhosIn,
)
from ..services import carrinhos, code128
from ..services.pcp import ErroPCP
from .producao import _limpo, pagina_etiquetas

router = APIRouter(prefix="/api/carrinhos", tags=["carrinhos"])


def _carrinho(db: Session, emp: Empresa, carrinho_id: int) -> Carrinho:
    try:
        return carrinhos.carregar(db, emp.id, carrinho_id)
    except ErroPCP as e:
        raise HTTPException(e.status, str(e))


def _falha(db: Session, e: ErroPCP):
    db.rollback()
    raise HTTPException(e.status, str(e))


@router.get("", response_model=list[CarrinhoOut])
def listar(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    lista = db.scalars(select(Carrinho).where(Carrinho.empresa_id == emp.id).order_by(Carrinho.numero))
    return [carrinhos.carrinho_out(db, c) for c in lista]


@router.post("", response_model=list[CarrinhoOut], status_code=201, dependencies=[Depends(PCP)])
def criar(dados: CriarCarrinhosIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    novos = carrinhos.criar(db, emp.id, dados.quantidade)
    db.commit()
    return [carrinhos.carrinho_out(db, c) for c in novos]


@router.post("/conferir", response_model=ConferenciaOut)
def conferir(dados: ConferirCarrinhoIn, usuario: Usuario = Depends(APONTAR), emp: Empresa = Depends(empresa_atual),
             db: Session = Depends(get_db)):
    try:
        r = carrinhos.conferir(db, emp, usuario, dados.codigo_barras, dados.centro_codigo)
    except ErroPCP as e:
        _falha(db, e)
    db.commit()
    return {**r, "carrinho": carrinhos.carrinho_out(db, r["carrinho"])}


@router.get("/{carrinho_id}", response_model=CarrinhoOut)
def detalhe(carrinho_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return carrinhos.carrinho_out(db, _carrinho(db, emp, carrinho_id))


@router.post("/{carrinho_id}/bipar", response_model=BipeCarrinhoOut)
def bipar(carrinho_id: int, dados: BipeCarrinhoIn, usuario: Usuario = Depends(APONTAR),
          emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    carrinho = _carrinho(db, emp, carrinho_id)
    try:
        r = carrinhos.bipar(db, emp, usuario, carrinho, dados.codigo_barras, dados.centro_codigo)
    except ErroPCP as e:
        _falha(db, e)
    db.commit()
    return {**r, "carrinho": carrinhos.carrinho_out(db, r["carrinho"])}


@router.post("/{carrinho_id}/remover", response_model=CarrinhoOut, dependencies=[Depends(APONTAR)])
def remover(carrinho_id: int, dados: ConferirCarrinhoIn, emp: Empresa = Depends(empresa_atual),
            db: Session = Depends(get_db)):
    carrinho = _carrinho(db, emp, carrinho_id)
    try:
        carrinhos.remover(db, carrinho, dados.codigo_barras)
    except ErroPCP as e:
        _falha(db, e)
    db.commit()
    return carrinhos.carrinho_out(db, carrinho)


@router.post("/{carrinho_id}/esvaziar", response_model=CarrinhoOut, dependencies=[Depends(APONTAR)])
def esvaziar(carrinho_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    carrinho = carrinhos.esvaziar(db, _carrinho(db, emp, carrinho_id))
    db.commit()
    return carrinhos.carrinho_out(db, carrinho)


@router.get("/{carrinho_id}/etiqueta.html", response_class=HTMLResponse)
def etiqueta(carrinho_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = _carrinho(db, emp, carrinho_id)
    bloco = f"""<section class="etq">
  <div class="topo"><span>{html.escape(emp.nome)}</span><span>CARRINHO</span></div>
  <div class="peca" style="font-size:28pt">CARRINHO {c.numero}</div>
  <div class="mod">Bipe esta etiqueta no setor para conferir o carrinho inteiro</div><div></div><div></div>
  <div class="cb">{code128.svg(c.codigo_barras)}<span>{c.codigo_barras}</span></div>
</section>"""
    return HTMLResponse(pagina_etiquetas(f"Carrinho {c.numero}", [bloco], "etiqueta"))


@router.get("/{carrinho_id}/marcadores.html", response_class=HTMLResponse)
def marcadores_html(carrinho_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Um marcador por grupo (lote, obra/cliente e separação) para ir entre as peças no carrinho."""
    c, e = carrinhos.carrinho_out(db, _carrinho(db, emp, carrinho_id)), html.escape
    blocos = []
    for i, g in enumerate(c["grupos"], start=1):
        modulos = sorted({p["modulo"] for p in g["pecas"]})
        blocos.append(f"""<section class="etq">
  <div class="topo"><span>CARRINHO {c['numero']} · MARCADOR {i}/{len(c['grupos'])}</span><span>{'LOTE ' + str(g['lote_numero']) if g['lote_numero'] else ''}</span></div>
  <div class="peca">{e(g['cliente'] or g['projeto_nome'])}</div>
  <div class="mod">{e(g['projeto_codigo'])} · {e(g['projeto_nome'])}</div>
  <div class="med">{g['quantidade']} peça(s){f" <small>SEPARAR: {e(g['separacao_nome'].upper())}</small>" if g['separacao_nome'] else ''}</div>
  <div class="rot">módulos {e(', '.join(modulos))}</div>
  <div class="peca" style="font-size:20pt">{e(g['separacao_nome'].upper()) if g['separacao_nome'] else e(g['projeto_codigo'])}</div>
</section>""")
    return HTMLResponse(pagina_etiquetas(f"Marcadores do carrinho {c['numero']}", blocos, "marcadores"))


@router.get("/{carrinho_id}/marcadores.zpl", response_class=PlainTextResponse)
def marcadores_zpl(carrinho_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = carrinhos.carrinho_out(db, _carrinho(db, emp, carrinho_id))
    blocos = []
    for i, g in enumerate(c["grupos"], start=1):
        blocos.append("\n".join([
            "^XA^CI28^PW800^LL400",
            f"^FO20,15^A0N,26,26^FDCARRINHO {c['numero']} - MARCADOR {i}/{len(c['grupos'])}"
            f"{'  LOTE ' + str(g['lote_numero']) if g['lote_numero'] else ''}^FS",
            f"^FO20,55^A0N,44,44^FD{_limpo(g['cliente'] or g['projeto_nome'], 32)}^FS",
            f"^FO20,110^A0N,30,30^FD{_limpo(g['projeto_codigo'] + ' - ' + g['projeto_nome'], 46)}^FS",
            f"^FO20,155^A0N,30,30^FD{g['quantidade']} peca(s)^FS",
            f"^FO20,220^A0N,70,70^FD{_limpo(('SEPARAR ' + g['separacao_nome']).upper() if g['separacao_nome'] else g['projeto_codigo'], 22)}^FS",
            "^XZ",
        ]))
    return PlainTextResponse("\n".join(blocos) + "\n", headers={
        "Content-Disposition": f'attachment; filename="carrinho{c["numero"]}_marcadores.zpl"'})
