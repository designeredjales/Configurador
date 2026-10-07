import html
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import APONTAR, PCP, empresa_atual
from ..models import Empresa, OrdemProducao, StatusOP, Usuario
from ..schemas import ApontamentoIn, ApontamentoOut, GerarOPIn, OPDetalhe, OPResumo, Painel, PlanoCorte
from ..services import code128, corte, pcp
from .projetos import carregar

router = APIRouter(prefix="/api", tags=["pcp"])


def resumo(op: OrdemProducao) -> dict:
    total, feitas = pcp.progresso(op)
    return {
        "id": op.id,
        "numero": op.numero,
        "projeto_id": op.projeto_id,
        "projeto_nome": op.projeto.nome,
        "status": op.status,
        "prioridade": op.prioridade,
        "data_entrega": op.data_entrega,
        "criada_em": op.criada_em,
        "total_unidades": len(op.unidades),
        "etapas_total": total,
        "etapas_concluidas": feitas,
        "progresso_pct": round(100 * feitas / total, 1) if total else 0.0,
    }


def carregar_op(db: Session, emp: Empresa, op_id: int) -> OrdemProducao:
    op = db.get(OrdemProducao, op_id)
    if op is None or op.empresa_id != emp.id:
        raise HTTPException(404, "OP não encontrada")
    return op


@router.post("/projetos/{projeto_id}/ops", response_model=OPResumo, status_code=201, dependencies=[Depends(PCP)])
def gerar_op(projeto_id: int, dados: GerarOPIn, emp: Empresa = Depends(empresa_atual),
             db: Session = Depends(get_db)):
    projeto = carregar(db, emp, projeto_id)
    try:
        op = pcp.gerar_op(db, projeto, dados.prioridade, dados.data_entrega)
    except pcp.ErroPCP as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return resumo(op)


@router.get("/ops", response_model=list[OPResumo])
def listar_ops(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    ops = db.scalars(
        select(OrdemProducao).where(OrdemProducao.empresa_id == emp.id)
        .order_by(OrdemProducao.prioridade, OrdemProducao.numero)
    )
    return [resumo(op) for op in ops]


@router.get("/ops/{op_id}", response_model=OPDetalhe)
def detalhe_op(op_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    op = carregar_op(db, emp, op_id)
    unidades = []
    for u in op.unidades:
        peca = u.peca
        unidades.append({
            "codigo_barras": u.codigo_barras,
            "sequencial": u.sequencial,
            "peca_codigo": peca.codigo,
            "peca_descricao": peca.descricao,
            "modulo": peca.modulo.codigo,
            "ambiente": peca.modulo.ambiente.nome,
            "material_codigo": peca.material_codigo,
            "comprimento_mm": peca.comprimento_mm,
            "largura_mm": peca.largura_mm,
            "etapas": [
                {"centro_codigo": e.centro.codigo, "sequencia": e.sequencia,
                 "concluida_em": e.concluida_em, "operador": e.operador}
                for e in u.etapas
            ],
        })
    return {**resumo(op), "unidades": unidades}


@router.post("/ops/{op_id}/cancelar", response_model=OPResumo, dependencies=[Depends(PCP)])
def cancelar_op(op_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    op = carregar_op(db, emp, op_id)
    if op.status == StatusOP.CONCLUIDA:
        raise HTTPException(409, "OP concluída não pode ser cancelada")
    op.status = StatusOP.CANCELADA
    db.commit()
    return resumo(op)


@router.post("/apontamentos", response_model=ApontamentoOut)
def apontar(dados: ApontamentoIn, usuario: Usuario = Depends(APONTAR),
            db: Session = Depends(get_db)):
    # Quem deu a baixa vem do login, não de um campo digitado
    try:
        unidade, proxima = pcp.apontar(db, usuario.empresa_id, dados.codigo_barras,
                                       dados.centro_codigo, usuario)
    except pcp.ErroPCP as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    op = unidade.op
    return {
        "codigo_barras": unidade.codigo_barras,
        "peca": f"{unidade.peca.modulo.codigo}/{unidade.peca.codigo} - {unidade.peca.descricao}",
        "centro_codigo": dados.centro_codigo.upper(),
        "proxima_etapa": proxima.centro.codigo if proxima else None,
        "op_numero": op.numero,
        "op_status": op.status,
        "op_progresso_pct": resumo(op)["progresso_pct"],
    }


@router.get("/painel", response_model=Painel)
def painel(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    ops = list(db.scalars(
        select(OrdemProducao).where(
            OrdemProducao.empresa_id == emp.id,
            OrdemProducao.status.in_([StatusOP.ABERTA, StatusOP.EM_PRODUCAO]),
        ).order_by(OrdemProducao.prioridade, OrdemProducao.data_entrega)
    ))
    hoje = date.today()
    return {
        "ops_abertas": sum(1 for o in ops if o.status == StatusOP.ABERTA),
        "ops_em_producao": sum(1 for o in ops if o.status == StatusOP.EM_PRODUCAO),
        "ops_atrasadas": sum(1 for o in ops if o.data_entrega and o.data_entrega < hoje),
        "centros": pcp.fila_por_centro(db, emp.id),
        "ops": [resumo(o) for o in ops],
    }


@router.get("/ops/{op_id}/plano-corte", response_model=PlanoCorte)
def plano_corte(op_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    op = carregar_op(db, emp, op_id)
    grupos: dict[str, list] = {}
    for u in op.unidades:
        grupos.setdefault(u.peca.material_codigo, []).append(u)
    materiais = []
    for codigo, unidades in sorted(grupos.items()):
        mat = unidades[0].peca.material
        medida_padrao = not (mat and mat.comprimento_mm and mat.largura_mm)
        comp = emp.chapa_comprimento_mm if medida_padrao else mat.comprimento_mm
        larg = emp.chapa_largura_mm if medida_padrao else mat.largura_mm
        descricoes = {u.codigo_barras: f"{u.peca.modulo.codigo}/{u.peca.descricao}" for u in unidades}
        chapas, nao_cabem = corte.otimizar(
            [corte.PecaCorte(u.codigo_barras, u.peca.comprimento_mm, u.peca.largura_mm, u.peca.veio)
             for u in unidades],
            comp, larg, emp.serra_mm, emp.refilo_mm,
        )
        area_total = sum(c.comprimento * c.largura for c in chapas)
        materiais.append({
            "material_codigo": codigo,
            "descricao": mat.descricao if mat else codigo,
            "espessura_mm": unidades[0].peca.espessura_mm,
            "chapa_comprimento_mm": comp, "chapa_largura_mm": larg, "medida_padrao": medida_padrao,
            "total_pecas": len(unidades), "total_chapas": len(chapas),
            "aproveitamento_pct": round(100 * sum(c.area_usada for c in chapas) / area_total, 1) if area_total else 0,
            "chapas": [{
                "numero": i, "aproveitamento_pct": round(100 * c.aproveitamento, 1),
                "pecas": [{**vars(pos), "descricao": descricoes[pos.ref]} for pos in c.pecas],
            } for i, c in enumerate(chapas, start=1)],
            "nao_cabem": [f"{r} {descricoes[r]}" for r in nao_cabem],
        })
    return {"op_numero": op.numero, "serra_mm": emp.serra_mm, "refilo_mm": emp.refilo_mm,
            "total_chapas": sum(m["total_chapas"] for m in materiais), "materiais": materiais}


@router.get("/ops/{op_id}/etiquetas.zpl", response_class=PlainTextResponse)
def etiquetas_zpl(op_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Etiquetas 100 x 50 mm (203 dpi) para impressora Zebra, uma por peça."""
    op = carregar_op(db, emp, op_id)

    def limpo(texto: str, n: int) -> str:
        # ^ e ~ são comandos ZPL; acentos saem com ^CI28 (UTF-8)
        return (texto or "").replace("^", " ").replace("~", " ")[:n]

    blocos = []
    for u in op.unidades:
        p = u.peca
        roteiro = " > ".join(e.centro.codigo for e in u.etapas)
        blocos.append("\n".join([
            "^XA^CI28^PW800^LL400",
            f"^FO20,15^A0N,28,28^FD{limpo(op.projeto.nome, 48)}^FS",
            f"^FO20,50^A0N,34,34^FD{limpo(p.descricao, 40)}^FS",
            f"^FO20,92^A0N,26,26^FD{limpo(p.modulo.codigo + ' - ' + p.modulo.descricao, 52)}^FS",
            f"^FO20,126^A0N,30,30^FD{p.comprimento_mm:g} x {p.largura_mm:g} x {(p.espessura_mm or 0):g} mm^FS",
            f"^FO20,162^A0N,24,24^FD{limpo(p.material_codigo, 40)}  OP {op.numero}  {u.sequencial}/{len(op.unidades)}^FS",
            f"^FO20,192^A0N,22,22^FD{limpo(roteiro, 60)}^FS",
            f"^FO20,225^BY3^BCN,120,Y,N,N^FD{u.codigo_barras}^FS",
            "^XZ",
        ]))
    return PlainTextResponse("\n".join(blocos) + "\n", headers={
        "Content-Disposition": f'attachment; filename="op{op.numero}_etiquetas.zpl"'})


@router.get("/ops/{op_id}/etiquetas.html", response_class=HTMLResponse)
def etiquetas_html(op_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Etiquetas 100 x 50 mm para imprimir pelo navegador (térmica ou A4 de etiquetas)."""
    op = carregar_op(db, emp, op_id)
    e = html.escape
    etiquetas = []
    for u in op.unidades:
        p = u.peca
        roteiro = " › ".join(et.centro.codigo for et in u.etapas)
        etiquetas.append(f"""<section class="etq">
  <div class="topo"><span>{e(op.projeto.nome)}</span><span>OP {op.numero} · {u.sequencial}/{len(op.unidades)}</span></div>
  <div class="peca">{e(p.descricao)}</div>
  <div class="mod">{e(p.modulo.codigo)} · {e(p.modulo.descricao)}</div>
  <div class="med">{p.comprimento_mm:g} × {p.largura_mm:g} × {(p.espessura_mm or 0):g} mm <small>{e(p.material_codigo)}</small></div>
  <div class="rot">{e(roteiro)}</div>
  <div class="cb">{code128.svg(u.codigo_barras)}<span>{u.codigo_barras}</span></div>
</section>""")
    pagina = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Etiquetas OP {op.numero}</title>
<style>
@page {{ size: 100mm 50mm; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; font: 9pt/1.2 system-ui, Arial, sans-serif; color: #000; background: #fff; }}
.barra {{ padding: 10px; background: #eee; font-size: 12pt; display: flex; gap: 12px; align-items: center; }}
.etq {{ width: 100mm; height: 50mm; padding: 2.5mm 3mm; page-break-after: always; overflow: hidden;
        display: grid; grid-template-rows: auto auto auto auto auto 1fr; gap: .6mm; border-bottom: 1px dashed #bbb; }}
.topo {{ display: flex; justify-content: space-between; font-size: 7pt; }}
.peca {{ font-size: 12pt; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.mod, .rot {{ font-size: 7.5pt; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.med {{ font-size: 11pt; font-weight: 700; }} .med small {{ font-size: 7.5pt; font-weight: 400; }}
.cb {{ display: flex; align-items: center; gap: 2mm; }} .cb svg {{ height: 12mm; width: auto; }}
.cb span {{ font: 8pt monospace; }}
@media print {{ .barra {{ display: none; }} .etq {{ border: 0; }} }}
</style></head><body>
<div class="barra"><b>OP {op.numero}</b> · {len(etiquetas)} etiquetas de 100 × 50 mm
<button onclick="print()">Imprimir</button></div>
{''.join(etiquetas)}
</body></html>"""
    return HTMLResponse(pagina)
