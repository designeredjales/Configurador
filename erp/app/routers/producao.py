from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import empresa_atual
from ..models import Empresa, OrdemProducao, StatusOP
from ..schemas import ApontamentoIn, ApontamentoOut, GerarOPIn, OPDetalhe, OPResumo, Painel
from ..services import pcp
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


@router.post("/projetos/{projeto_id}/ops", response_model=OPResumo, status_code=201)
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


@router.post("/ops/{op_id}/cancelar", response_model=OPResumo)
def cancelar_op(op_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    op = carregar_op(db, emp, op_id)
    if op.status == StatusOP.CONCLUIDA:
        raise HTTPException(409, "OP concluída não pode ser cancelada")
    op.status = StatusOP.CANCELADA
    db.commit()
    return resumo(op)


@router.post("/apontamentos", response_model=ApontamentoOut)
def apontar(dados: ApontamentoIn, emp: Empresa = Depends(empresa_atual),
            db: Session = Depends(get_db)):
    try:
        unidade, proxima = pcp.apontar(db, emp.id, dados.codigo_barras, dados.centro_codigo,
                                       dados.operador)
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
