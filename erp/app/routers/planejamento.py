"""De-para Promob → estoque e sequenciamento da produção pela restrição."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import CADASTROS, PCP, empresa_atual
from ..models import DeParaMaterial, Empresa, Usuario
from ..services import depara, lotes, sequencia
from ..services.pcp import ErroPCP

router = APIRouter(prefix="/api", tags=["planejamento"])


# --- De-para ---------------------------------------------------------------------------------------

class DeParaIn(BaseModel):
    codigo_promob: str = Field(min_length=1, max_length=60)
    material_id: int
    fator: float = Field(1.0, gt=0, le=100000)
    observacao: str | None = Field(None, max_length=200)


@router.get("/depara", dependencies=[Depends(CADASTROS)])
def listar_depara(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return sorted((depara.depara_out(d) for d in depara.mapa(db, emp.id).values()), key=lambda x: x["codigo_promob"])


@router.get("/depara/codigos", dependencies=[Depends(CADASTROS)])
def codigos(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Códigos do Promob em uso nos projetos abertos, com a situação e sugestões de vínculo."""
    return {"cria_materiais": emp.promob_cria_materiais, "codigos": depara.codigos_em_uso(db, emp.id)}


@router.post("/depara", status_code=201, dependencies=[Depends(CADASTROS)])
def salvar_depara(dados: DeParaIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        d = depara.salvar(db, emp.id, dados.codigo_promob, dados.material_id, dados.fator, dados.observacao)
    except depara.ErroDePara as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return depara.depara_out(d)


@router.delete("/depara/{depara_id}", dependencies=[Depends(CADASTROS)])
def apagar_depara(depara_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    d = db.get(DeParaMaterial, depara_id)
    if d is None or d.empresa_id != emp.id:
        raise HTTPException(404, "De-para não encontrado")
    db.delete(d)
    db.commit()
    return {"ok": True}


@router.post("/depara/reaplicar", dependencies=[Depends(CADASTROS)])
def reaplicar_depara(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    r = depara.reaplicar(db, emp.id)
    db.commit()
    return r


# --- Sequenciamento pela restrição ----------------------------------------------------------------

@router.get("/pcp/sequencia", dependencies=[Depends(PCP)])
def ver_sequencia(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    r = sequencia.calcular(db, emp.id)
    db.commit()
    for it in r["itens"]:
        it["prioridade_sugerida"] = sequencia.prioridade_sugerida(it, r["pulmao_dias"]) if it["tipo"] == "OP" else None
    return r


@router.post("/pcp/sequencia/prioridades", dependencies=[Depends(PCP)])
def aplicar_prioridades(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    r = sequencia.aplicar_prioridades(db, emp.id)
    db.commit()
    return r


class LoteSequenciaIn(BaseModel):
    dias: float = Field(gt=0, le=60)
    descricao: str | None = Field(None, max_length=120)


@router.post("/pcp/sequencia/lote", status_code=201)
def formar_lote(dados: LoteSequenciaIn, usuario: Usuario = Depends(PCP), db: Session = Depends(get_db)):
    """Forma um lote com os próximos projetos liberados da sequência que cabem em N dias do tambor."""
    ids = sequencia.projetos_para_lote(db, usuario.empresa_id, dados.dias)
    if not ids:
        raise HTTPException(422, "Nenhum projeto liberado aguardando lote")
    descricao = dados.descricao or f"Sequência pela restrição · {date.today():%d/%m} · {dados.dias:g} dia(s) de tambor"
    try:
        lote = lotes.formar(db, usuario.empresa_id, descricao, ids, 2, None, usuario)
    except ErroPCP as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return {"lote_id": lote.id, "numero": lote.numero, "projetos": len(ids)}
