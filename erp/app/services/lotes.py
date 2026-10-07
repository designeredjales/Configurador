"""Lote de produção: vários projetos liberados entram juntos na fábrica.

Cada projeto continua com a sua OP (rastreio por cliente), mas o corte e as
etiquetas saem do lote inteiro, o que aproveita melhor as chapas.
"""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import LoteProducao, OrdemProducao, Projeto, StatusOP, StatusProjeto, Usuario
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
    for op in lote.ops:
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
