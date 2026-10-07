"""Lote de produção: vários projetos liberados entram juntos na fábrica.

Cada projeto continua com a sua OP (rastreio por cliente), mas o corte e as
etiquetas saem do lote inteiro, o que aproveita melhor as chapas.
"""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ItemCaixa,
    LoteProducao,
    Ocorrencia,
    OrdemProducao,
    Projeto,
    StatusOP,
    StatusProjeto,
    UnidadePeca,
    Usuario,
)
from . import pcp
from .pcp import ErroPCP


def _projetos_liberados(db: Session, empresa_id: int, projeto_ids: list[int]) -> list[Projeto]:
    projetos = []
    for pid in dict.fromkeys(projeto_ids):  # sem repetir, na ordem enviada
        p = db.get(Projeto, pid)
        if p is None or p.empresa_id != empresa_id:
            raise ErroPCP(f"Projeto {pid} não encontrado", 404)
        if p.status != StatusProjeto.LIBERADO:
            raise ErroPCP(f"Projeto {p.codigo} precisa estar LIBERADO pela engenharia para entrar no lote (status atual: {p.status})")
        projetos.append(p)
    return projetos


def status(lote: LoteProducao) -> str:
    ativas = [o for o in lote.ops if o.status != StatusOP.CANCELADA]
    if not ativas:
        return "CANCELADO"
    if all(o.status == StatusOP.CONCLUIDA for o in ativas):
        return "CONCLUIDO"
    if any(o.status != StatusOP.ABERTA for o in ativas):
        return "EM_PRODUCAO"
    return "ABERTO"


def formar(db: Session, empresa_id: int, descricao: str, projeto_ids: list[int], prioridade: int,
           data_entrega: date | None, usuario: Usuario) -> LoteProducao:
    projetos = _projetos_liberados(db, empresa_id, projeto_ids)
    numero = (db.scalar(select(func.max(LoteProducao.numero)).where(LoteProducao.empresa_id == empresa_id)) or 0) + 1
    lote = LoteProducao(empresa_id=empresa_id, numero=numero, descricao=descricao.strip(),
                        data_entrega=data_entrega, criado_por=usuario.nome)
    db.add(lote)
    for p in projetos:
        pcp.gerar_op(db, p, prioridade, data_entrega or p.data_entrega, lote=lote)
    db.flush()
    return lote


def adicionar(db: Session, lote: LoteProducao, projeto_ids: list[int]) -> LoteProducao:
    if status(lote) != "ABERTO":
        raise ErroPCP(f"Lote {lote.numero} já começou a produzir: forme um lote novo para os outros projetos")
    projetos = _projetos_liberados(db, lote.empresa_id, projeto_ids)
    prioridade = min((o.prioridade for o in lote.ops), default=3)
    for p in projetos:
        pcp.gerar_op(db, p, prioridade, lote.data_entrega or p.data_entrega, lote=lote)
    db.flush()
    db.refresh(lote)
    return lote


def resumo(lote: LoteProducao) -> dict:
    projetos, total, feitas, pecas = [], 0, 0, 0
    ativas = [o for o in lote.ops if o.status != StatusOP.CANCELADA]
    for op in ativas or lote.ops:  # OPs que voltaram para programação saem da lista (a menos que todas tenham voltado)
        t, f = pcp.progresso(op)
        n = sum(1 for u in op.unidades if u.ativa)
        if op.status != StatusOP.CANCELADA:
            total, feitas, pecas = total + t, feitas + f, pecas + n
        p = op.projeto
        projetos.append({
            "projeto_id": p.id, "codigo": p.codigo, "nome": p.nome, "cliente": p.cliente.nome if p.cliente else None,
            "op_id": op.id, "op_numero": op.numero, "op_status": op.status, "pecas": n,
            "progresso_pct": round(100 * f / t, 1) if t else 0.0,
        })
    return {
        "id": lote.id, "numero": lote.numero, "descricao": lote.descricao, "status": status(lote),
        "data_entrega": lote.data_entrega, "criado_em": lote.criado_em, "criado_por": lote.criado_por,
        "total_pecas": pecas, "etapas_total": total, "etapas_concluidas": feitas,
        "progresso_pct": round(100 * feitas / total, 1) if total else 0.0, "projetos": projetos,
    }


def unidades(lote: LoteProducao, apenas_reposicoes: bool = False) -> list:
    return [u for op in lote.ops if op.status != StatusOP.CANCELADA for u in op.unidades
            if u.ativa and (not apenas_reposicoes or u.reposicao_de_id)]


# --- Voltar para programação ------------------------------------------------------
# Desfaz a programação de uma OP que a fábrica ainda não tocou: a OP fica cancelada
# (o número e as etiquetas nunca são reaproveitados) e o projeto volta a LIBERADO,
# pronto para entrar em outro lote ou ganhar uma OP nova.

def impedimento(db: Session, op: OrdemProducao) -> str | None:
    if op.status == StatusOP.CANCELADA:
        return f"OP {op.numero} já está cancelada"
    if op.status == StatusOP.CONCLUIDA:
        return f"OP {op.numero} já foi concluída"
    baixas = sum(1 for u in op.unidades for e in u.etapas if e.concluida_em)
    if baixas:
        return (f"OP {op.numero} ({op.projeto.codigo}) já tem {baixas} baixa(s) na fábrica: "
                f"estorne as baixas no Controle de Produção ou cancele a OP")
    ids = [u.id for u in op.unidades]
    if ids and db.scalar(select(func.count()).select_from(ItemCaixa).where(ItemCaixa.unidade_id.in_(ids))):
        return f"OP {op.numero} ({op.projeto.codigo}) tem peças em caixa master"
    if db.scalar(select(func.count()).select_from(Ocorrencia).where(Ocorrencia.op_id == op.id)):
        return f"OP {op.numero} ({op.projeto.codigo}) tem estorno ou refugo registrado: cancele a OP em vez de reprogramar"
    return None


def _devolver(db: Session, op: OrdemProducao, usuario: Usuario) -> None:
    op.status = StatusOP.CANCELADA
    op.motivo_cancelamento = f"Voltou para programação ({usuario.nome})"
    db.flush()
    ativas = db.scalar(select(func.count()).select_from(OrdemProducao).where(
        OrdemProducao.projeto_id == op.projeto_id,
        OrdemProducao.status.in_([StatusOP.ABERTA, StatusOP.EM_PRODUCAO])))
    if not ativas and op.projeto.status == StatusProjeto.PRODUCAO:
        op.projeto.status = StatusProjeto.LIBERADO


def voltar_op(db: Session, op: OrdemProducao, usuario: Usuario) -> None:
    motivo = impedimento(db, op)
    if motivo:
        raise ErroPCP(motivo)
    _devolver(db, op, usuario)
    db.flush()


def voltar_lote(db: Session, lote: LoteProducao, usuario: Usuario) -> list[OrdemProducao]:
    """Tudo ou nada: se alguma OP do lote já foi tocada pela fábrica, nenhuma volta."""
    ops = [o for o in lote.ops if o.status != StatusOP.CANCELADA]
    if not ops:
        raise ErroPCP(f"Lote {lote.numero} não tem OPs ativas")
    problemas = [m for m in (impedimento(db, o) for o in ops) if m]
    if problemas:
        raise ErroPCP(f"Lote {lote.numero} não pode voltar inteiro para programação: " + "; ".join(problemas))
    for o in ops:
        _devolver(db, o, usuario)
    db.flush()
    return ops
