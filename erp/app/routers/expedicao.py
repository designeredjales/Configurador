"""Expedição: caixa master, etiqueta de volume, carregamento e romaneio."""
import html

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import EXPEDICAO, empresa_atual
from ..models import CaixaMaster, Empresa, Usuario
from ..schemas import BipeCaixaIn, BipeCaixaOut, CaixaOut, CarregarIn, ExpedicaoProjeto
from ..services import code128, expedicao, pcp
from .producao import _limpo, pagina_etiquetas
from .projetos import carregar

router = APIRouter(prefix="/api", tags=["expedicao"])


def _erro(db: Session, e: Exception):
    db.rollback()
    if isinstance(e, expedicao.ErroExpedicao):
        raise HTTPException(e.status, e.detail)
    raise HTTPException(e.status, str(e))


def _caixa(db: Session, emp: Empresa, caixa_id: int) -> CaixaMaster:
    try:
        return expedicao.carregar_caixa(db, emp.id, caixa_id)
    except expedicao.ErroExpedicao as e:
        raise HTTPException(e.status, e.detail)


@router.post("/expedicao/bipar", response_model=BipeCaixaOut)
def bipar(dados: BipeCaixaIn, usuario: Usuario = Depends(EXPEDICAO), emp: Empresa = Depends(empresa_atual),
          db: Session = Depends(get_db)):
    try:
        r = expedicao.bipar(db, emp, usuario, dados.codigo_barras, dados.caixa_id, dados.nova_caixa)
    except (expedicao.ErroExpedicao, pcp.ErroPCP) as e:
        _erro(db, e)
    db.commit()
    return {**r, "caixa": expedicao.caixa_out(db, r["caixa"])}


@router.post("/expedicao/carregar", response_model=CaixaOut, dependencies=[Depends(EXPEDICAO)])
def carregar_caminhao(dados: CarregarIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        caixa = expedicao.carregar(db, emp, dados.codigo_barras)
    except expedicao.ErroExpedicao as e:
        _erro(db, e)
    db.commit()
    return expedicao.caixa_out(db, caixa)


@router.get("/caixas", response_model=list[CaixaOut])
def listar(projeto_id: int | None = None, status: str | None = None, emp: Empresa = Depends(empresa_atual),
           db: Session = Depends(get_db)):
    consulta = select(CaixaMaster).where(CaixaMaster.empresa_id == emp.id)
    if projeto_id:
        consulta = consulta.where(CaixaMaster.projeto_id == projeto_id)
    if status:
        consulta = consulta.where(CaixaMaster.status == status.upper())
    return [expedicao.caixa_out(db, c) for c in db.scalars(consulta.order_by(CaixaMaster.numero.desc()).limit(200))]


@router.get("/caixas/{caixa_id}", response_model=CaixaOut)
def detalhe(caixa_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return expedicao.caixa_out(db, _caixa(db, emp, caixa_id))


def _acao(db: Session, emp: Empresa, caixa_id: int, funcao, *args):
    caixa = _caixa(db, emp, caixa_id)
    try:
        funcao(db, caixa, *args)
    except expedicao.ErroExpedicao as e:
        _erro(db, e)
    db.commit()
    db.refresh(caixa)
    return expedicao.caixa_out(db, caixa)


@router.post("/caixas/{caixa_id}/fechar", response_model=CaixaOut, dependencies=[Depends(EXPEDICAO)])
def fechar(caixa_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return _acao(db, emp, caixa_id, expedicao.fechar)


@router.post("/caixas/{caixa_id}/reabrir", response_model=CaixaOut, dependencies=[Depends(EXPEDICAO)])
def reabrir(caixa_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return _acao(db, emp, caixa_id, expedicao.reabrir)


@router.post("/caixas/{caixa_id}/remover", response_model=CaixaOut, dependencies=[Depends(EXPEDICAO)])
def remover(caixa_id: int, dados: CarregarIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return _acao(db, emp, caixa_id, expedicao.remover, dados.codigo_barras)


@router.get("/caixas/{caixa_id}/etiqueta.zpl", response_class=PlainTextResponse)
def etiqueta_zpl(caixa_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = expedicao.caixa_out(db, _caixa(db, emp, caixa_id))
    zpl = "\n".join([
        "^XA^CI28^PW800^LL400",
        f"^FO20,15^A0N,30,30^FDCAIXA {c['numero']}  VOLUME {c['volume']}/{c['volumes_projeto']}^FS",
        f"^FO20,55^A0N,36,36^FD{_limpo(c['cliente'] or c['projeto_nome'], 38)}^FS",
        f"^FO20,98^A0N,28,28^FD{_limpo(c['projeto_codigo'] + ' - ' + c['ambiente'], 48)}^FS",
        f"^FO20,135^A0N,24,24^FD{c['total_itens']} peca(s) - modulos: {_limpo(', '.join(c['modulos']), 40)}^FS",
        f"^FO20,180^BY3^BCN,140,Y,N,N^FD{c['codigo_barras']}^FS",
        "^XZ",
    ]) + "\n"
    return PlainTextResponse(zpl, headers={"Content-Disposition": f'attachment; filename="caixa{c["numero"]}.zpl"'})


@router.get("/caixas/{caixa_id}/etiqueta.html", response_class=HTMLResponse)
def etiqueta_html(caixa_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c, e = expedicao.caixa_out(db, _caixa(db, emp, caixa_id)), html.escape
    bloco = f"""<section class="etq">
  <div class="topo"><span>CAIXA MASTER {c['numero']}</span><span>VOLUME {c['volume']}/{c['volumes_projeto']}</span></div>
  <div class="peca">{e(c['cliente'] or c['projeto_nome'])}</div>
  <div class="mod">{e(c['projeto_codigo'])} · {e(c['ambiente'])}</div>
  <div class="med">{c['total_itens']} peça(s) <small>módulos {e(', '.join(c['modulos']))}</small></div>
  <div class="rot">{e(c['status'])}</div>
  <div class="cb">{code128.svg(c['codigo_barras'])}<span>{c['codigo_barras']}</span></div>
</section>"""
    return HTMLResponse(pagina_etiquetas(f"Caixa {c['numero']}", [bloco], "etiqueta"))


@router.get("/projetos/{projeto_id}/expedicao", response_model=ExpedicaoProjeto)
def resumo_projeto(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return expedicao.resumo_projeto(db, carregar(db, emp, projeto_id))


@router.get("/projetos/{projeto_id}/romaneio.html", response_class=HTMLResponse)
def romaneio(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Romaneio de carga: cada volume com o que tem dentro, para o motorista e o montador conferirem na obra."""
    r, e = expedicao.resumo_projeto(db, carregar(db, emp, projeto_id)), html.escape
    volumes = "".join(f"""<section><h2>Volume {c['volume']}/{c['volumes_projeto']} · caixa {c['numero']} · {e(c['ambiente'])}
  <small>{e(c['status'])}</small></h2><table><tr><th>Etiqueta</th><th>Módulo</th><th>Peça</th><th>Medida</th></tr>
  {''.join(f"<tr><td>{i['codigo_barras']}</td><td>{e(i['modulo'])}</td><td>{e(i['peca'])}</td><td>{e(i['medidas'])}</td></tr>" for i in c['itens'])}
  </table></section>""" for c in r["caixas"])
    falta = (f"<p class='alerta'>Atenção: {len(r['pendentes'])} peça(s) ainda fora de caixa.</p>" if r["pendentes"] else "")
    return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Romaneio {e(r['codigo'])}</title>
<style>body{{font:10pt system-ui,Arial,sans-serif;margin:16mm;color:#000}} h1{{font-size:15pt;margin:0 0 4px}}
h2{{font-size:11pt;margin:14px 0 4px}} h2 small{{font-weight:400;color:#555}} table{{width:100%;border-collapse:collapse}}
td,th{{border-bottom:1px solid #ccc;padding:3px 4px;text-align:left}} .alerta{{color:#b00;font-weight:700}}
.assina{{margin-top:28px;display:flex;gap:40px}} .assina div{{flex:1;border-top:1px solid #000;padding-top:4px}}
@media print{{button{{display:none}}}}</style></head><body>
<button onclick="print()">Imprimir</button>
<h1>Romaneio de carga · {e(r['codigo'])} · {e(r['nome'])}</h1>
<p>{len(r['caixas'])} volume(s) · {r['embaladas']} de {r['total_pecas']} peça(s) embaladas · {r['expedidas']} carregada(s)</p>
{falta}{volumes}
<div class="assina"><div>Conferido na expedição</div><div>Recebido na obra</div></div>
</body></html>""")
