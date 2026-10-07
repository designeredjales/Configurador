from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import POS_OBRA, empresa_atual
from ..models import Chamado, Empresa, Montagem, Projeto, StatusChamado, StatusProjeto, Usuario
from ..schemas import (
    ChamadoAtualizar,
    ChamadoIn,
    ChamadoOut,
    ConclusaoMontagemIn,
    ConferenciaIn,
    MontagemIn,
    MontagemOut,
    ResolucaoIn,
)
from ..services import pos_obra
from ..services.pos_obra import CAUSAS_INTERNAS, ErroPosObra

router = APIRouter(prefix="/api", tags=["montagem e pós-obra"])


def _projeto(db: Session, empresa_id: int, projeto_id: int) -> Projeto:
    p = db.get(Projeto, projeto_id)
    if p is None or p.empresa_id != empresa_id:
        raise HTTPException(404, "Projeto não encontrado")
    return p


def _montagem(db: Session, empresa_id: int, montagem_id: int) -> Montagem:
    m = db.get(Montagem, montagem_id)
    if m is None or m.empresa_id != empresa_id:
        raise HTTPException(404, "Montagem não encontrada")
    return m


def _chamado(db: Session, empresa_id: int, chamado_id: int) -> Chamado:
    c = db.get(Chamado, chamado_id)
    if c is None or c.empresa_id != empresa_id:
        raise HTTPException(404, "Chamado não encontrado")
    return c


def _m_out(m: Montagem) -> dict:
    return {
        "id": m.id, "projeto_id": m.projeto_id, "projeto_codigo": m.projeto.codigo, "projeto_nome": m.projeto.nome,
        "data_inicio": m.data_inicio, "data_fim": m.data_fim, "equipe": m.equipe, "endereco": m.endereco,
        "observacao": m.observacao, "status": m.status,
        "producao_concluida": m.projeto.status in (StatusProjeto.CONCLUIDO, StatusProjeto.ENTREGUE),
        "iniciada_em": m.iniciada_em, "concluida_em": m.concluida_em, "recebido_por": m.recebido_por,
        "itens": m.itens,
    }


def _c_out(c: Chamado) -> dict:
    return {
        "id": c.id, "numero": c.numero, "projeto_id": c.projeto_id, "projeto_codigo": c.projeto.codigo,
        "projeto_nome": c.projeto.nome, "tipo": c.tipo, "descricao": c.descricao, "status": c.status,
        "aberto_em": c.aberto_em, "agendado_para": c.agendado_para, "causa": c.causa, "solucao": c.solucao,
        "custo": c.custo, "resolvido_em": c.resolvido_em, "em_garantia": c.em_garantia,
        "retrabalho": c.causa in CAUSAS_INTERNAS,
    }


def _executar(db: Session, acao):
    try:
        resultado = acao()
    except ErroPosObra as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return resultado


# --- Montagem --------------------------------------------------------------------

@router.get("/montagens", response_model=list[MontagemOut])
def agenda(de: date | None = None, ate: date | None = None, emp: Empresa = Depends(empresa_atual),
           db: Session = Depends(get_db)):
    consulta = select(Montagem).where(Montagem.empresa_id == emp.id)
    if de:
        consulta = consulta.where(Montagem.data_fim >= de)
    if ate:
        consulta = consulta.where(Montagem.data_inicio <= ate)
    return [_m_out(m) for m in db.scalars(consulta.order_by(Montagem.data_inicio, Montagem.id))]


@router.post("/montagens", response_model=MontagemOut, status_code=201)
def agendar(dados: MontagemIn, usuario: Usuario = Depends(POS_OBRA), db: Session = Depends(get_db)):
    p = _projeto(db, usuario.empresa_id, dados.projeto_id)
    m = _executar(db, lambda: pos_obra.agendar(db, p, dados.data_inicio, dados.data_fim, dados.equipe,
                                               dados.endereco, dados.observacao))
    return _m_out(m)


@router.get("/montagens/{montagem_id}", response_model=MontagemOut)
def detalhe(montagem_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return _m_out(_montagem(db, emp.id, montagem_id))


@router.post("/montagens/{montagem_id}/iniciar", response_model=MontagemOut)
def iniciar(montagem_id: int, usuario: Usuario = Depends(POS_OBRA), db: Session = Depends(get_db)):
    m = _montagem(db, usuario.empresa_id, montagem_id)
    _executar(db, lambda: pos_obra.iniciar(m))
    return _m_out(m)


@router.post("/montagens/{montagem_id}/checklist/{item_id}", response_model=MontagemOut)
def conferir(montagem_id: int, item_id: int, dados: ConferenciaIn, usuario: Usuario = Depends(POS_OBRA),
             db: Session = Depends(get_db)):
    m = _montagem(db, usuario.empresa_id, montagem_id)
    _executar(db, lambda: pos_obra.conferir(m, item_id, dados.ok, dados.observacao, usuario))
    return _m_out(m)


@router.post("/montagens/{montagem_id}/concluir", response_model=MontagemOut)
def concluir(montagem_id: int, dados: ConclusaoMontagemIn, usuario: Usuario = Depends(POS_OBRA),
             db: Session = Depends(get_db)):
    m = _montagem(db, usuario.empresa_id, montagem_id)
    _executar(db, lambda: pos_obra.concluir(m, dados.recebido_por))
    return _m_out(m)


@router.post("/montagens/{montagem_id}/cancelar", response_model=MontagemOut)
def cancelar(montagem_id: int, usuario: Usuario = Depends(POS_OBRA), db: Session = Depends(get_db)):
    m = _montagem(db, usuario.empresa_id, montagem_id)
    _executar(db, lambda: pos_obra.cancelar(m))
    return _m_out(m)


# --- Assistência técnica -----------------------------------------------------------

@router.get("/chamados", response_model=list[ChamadoOut])
def chamados(abertos: bool = False, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    consulta = select(Chamado).where(Chamado.empresa_id == emp.id)
    if abertos:
        consulta = consulta.where(Chamado.status != StatusChamado.RESOLVIDO)
    return [_c_out(c) for c in db.scalars(consulta.order_by(Chamado.numero.desc()))]


@router.post("/chamados", response_model=ChamadoOut, status_code=201)
def abrir(dados: ChamadoIn, usuario: Usuario = Depends(POS_OBRA), db: Session = Depends(get_db)):
    p = _projeto(db, usuario.empresa_id, dados.projeto_id)
    c = _executar(db, lambda: pos_obra.abrir_chamado(db, p, dados.tipo, dados.descricao, usuario))
    return _c_out(c)


@router.patch("/chamados/{chamado_id}", response_model=ChamadoOut)
def agendar_visita(chamado_id: int, dados: ChamadoAtualizar, usuario: Usuario = Depends(POS_OBRA),
                   db: Session = Depends(get_db)):
    c = _chamado(db, usuario.empresa_id, chamado_id)
    if c.status == StatusChamado.RESOLVIDO:
        raise HTTPException(409, f"Chamado {c.numero} já resolvido")
    c.agendado_para = dados.agendado_para
    c.status = StatusChamado.AGENDADO if dados.agendado_para else StatusChamado.ABERTO
    db.commit()
    return _c_out(c)


@router.post("/chamados/{chamado_id}/resolver", response_model=ChamadoOut)
def resolver(chamado_id: int, dados: ResolucaoIn, usuario: Usuario = Depends(POS_OBRA),
             db: Session = Depends(get_db)):
    c = _chamado(db, usuario.empresa_id, chamado_id)
    _executar(db, lambda: pos_obra.resolver(db, c, dados.causa, dados.solucao, dados.custo, usuario))
    return _c_out(c)
