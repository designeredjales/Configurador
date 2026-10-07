"""Controle de produção: estorno de apontamento, refugo com reposição e consulta de peças."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    EtapaUnidade,
    MovimentoEstoque,
    Ocorrencia,
    OrdemProducao,
    OrigemMovimento,
    StatusOP,
    UnidadePeca,
    Usuario,
)
from .pcp import ErroPCP


def _unidade(db: Session, empresa_id: int, codigo: str) -> UnidadePeca:
    u = db.scalar(select(UnidadePeca).join(OrdemProducao).where(
        UnidadePeca.codigo_barras == codigo.strip(), OrdemProducao.empresa_id == empresa_id))
    if u is None:
        raise ErroPCP(f"Etiqueta {codigo} não encontrada", 404)
    return u


def _op_aberta(op: OrdemProducao) -> None:
    if op.status == StatusOP.CONCLUIDA:
        raise ErroPCP(f"OP {op.numero} concluída: o material já saiu do estoque. Peça com defeito depois da entrega vai para a Assistência")
    if op.status == StatusOP.CANCELADA:
        raise ErroPCP(f"OP {op.numero} cancelada")


def _motivo(motivo: str) -> str:
    motivo = (motivo or "").strip()
    if len(motivo) < 3:
        raise ErroPCP("Informe o motivo (ex.: bipe no setor errado, peça lascada no corte).", 422)
    return motivo[:300]


def estornar(db: Session, empresa_id: int, codigo: str, centro_codigo: str, motivo: str, usuario: Usuario) -> UnidadePeca:
    """Desfaz a última baixa da peça (só a última, para o roteiro continuar em sequência)."""
    u = _unidade(db, empresa_id, codigo)
    _op_aberta(u.op)
    motivo = _motivo(motivo)
    if not u.ativa:
        raise ErroPCP("Peça refugada não tem baixa para estornar")
    centro_codigo = centro_codigo.strip().upper()
    feitas = [e for e in u.etapas if e.concluida_em]
    if not feitas:
        raise ErroPCP("A peça ainda não teve nenhuma baixa")
    ultima = max(feitas, key=lambda e: e.sequencia)
    if ultima.centro.codigo != centro_codigo:
        raise ErroPCP(f"Só a última baixa pode ser estornada: estorne antes {ultima.centro.codigo}")
    ultima.concluida_em = ultima.operador = ultima.usuario_id = None
    if not any(e.concluida_em for un in u.op.unidades for e in un.etapas):
        u.op.status = StatusOP.ABERTA
    db.add(Ocorrencia(empresa_id=empresa_id, op_id=u.op_id, unidade_id=u.id, tipo="ESTORNO", centro_codigo=centro_codigo,
                      motivo=motivo, usuario_id=usuario.id, usuario_nome=usuario.nome))
    db.flush()
    return u


def _material_perdido(u: UnidadePeca) -> list[tuple[object, float]]:
    """(material, quantidade na unidade de estoque) que a peça consumiu."""
    p, perdas = u.peca, []
    m = p.material
    if m is not None:
        area = p.comprimento_mm * p.largura_mm / 1e6
        if m.unidade.upper() != "M2" and m.comprimento_mm and m.largura_mm:
            perdas.append((m, area / (m.comprimento_mm * m.largura_mm / 1e6)))
        else:
            perdas.append((m, area))
    return perdas


def refugar(db: Session, empresa_id: int, codigo: str, centro_codigo: str, motivo: str,
            usuario: Usuario) -> tuple[UnidadePeca, UnidadePeca, float]:
    """Marca a peça como refugada, baixa o material perdido e cria a reposição com etiqueta nova."""
    u = _unidade(db, empresa_id, codigo)
    op = u.op
    _op_aberta(op)
    motivo = _motivo(motivo)
    if not u.ativa:
        raise ErroPCP(f"Etiqueta {codigo} já foi refugada")
    u.status = "REFUGADA"

    seq = (db.scalar(select(func.max(UnidadePeca.sequencial)).where(UnidadePeca.op_id == op.id)) or 0) + 1
    nova = UnidadePeca(op=op, peca=u.peca, sequencial=seq, reposicao_de_id=u.id,
                       codigo_barras=f"{op.empresa_id:03d}{op.numero:06d}{seq:05d}")
    nova.etapas = [EtapaUnidade(centro=e.centro, sequencia=e.sequencia) for e in u.etapas]
    db.add(nova)

    custo = 0.0
    for material, qtd in _material_perdido(u):
        custo += qtd * material.custo_unitario
        db.add(MovimentoEstoque(
            empresa_id=empresa_id, material_id=material.id, quantidade=-round(qtd, 4),
            custo_unitario=material.custo_unitario, origem=OrigemMovimento.REFUGO,
            referencia=f"Refugo {u.codigo_barras} · OP {op.numero}", projeto_id=op.projeto_id, usuario_id=usuario.id,
        ))
    if op.status == StatusOP.ABERTA:
        op.status = StatusOP.EM_PRODUCAO
    db.flush()
    db.add(Ocorrencia(empresa_id=empresa_id, op_id=op.id, unidade_id=u.id, tipo="REFUGO",
                      centro_codigo=centro_codigo.strip().upper(), motivo=motivo, custo_material=round(custo, 2),
                      nova_unidade_id=nova.id, usuario_id=usuario.id, usuario_nome=usuario.nome))
    db.flush()
    return u, nova, round(custo, 2)


def situacao(u: UnidadePeca) -> str:
    if not u.ativa:
        return "REFUGADA"
    feitas = sum(1 for e in u.etapas if e.concluida_em)
    if feitas == 0:
        return "AGUARDANDO"
    return "CONCLUIDA" if feitas == len(u.etapas) else "EM_PROCESSO"


def consultar_pecas(db: Session, empresa_id: int, projeto_id: int | None = None, op_id: int | None = None,
                    situacao_filtro: str | None = None, centro: str | None = None, material: str | None = None,
                    busca: str | None = None, limite: int = 500) -> dict:
    consulta = (select(UnidadePeca).join(OrdemProducao)
                .where(OrdemProducao.empresa_id == empresa_id, OrdemProducao.status != StatusOP.CANCELADA))
    if projeto_id:
        consulta = consulta.where(OrdemProducao.projeto_id == projeto_id)
    if op_id:
        consulta = consulta.where(OrdemProducao.id == op_id)
    linhas, contagem = [], {"AGUARDANDO": 0, "EM_PROCESSO": 0, "CONCLUIDA": 0, "REFUGADA": 0}
    termo = (busca or "").strip().lower()
    for u in db.scalars(consulta.order_by(OrdemProducao.numero, UnidadePeca.sequencial)):
        p, sit = u.peca, situacao(u)
        proxima = next((e for e in u.etapas if not e.concluida_em), None) if sit != "REFUGADA" else None
        ultima = max((e for e in u.etapas if e.concluida_em), key=lambda e: e.sequencia, default=None)
        if material and p.material_codigo != material:
            continue
        if termo and termo not in f"{u.codigo_barras} {p.descricao} {p.codigo} {p.modulo.codigo} {p.modulo.descricao}".lower():
            continue
        if centro and (proxima is None or proxima.centro.codigo != centro.upper()):
            continue
        contagem[sit] += 1
        if situacao_filtro and sit != situacao_filtro:
            continue
        if len(linhas) < limite:
            linhas.append({
                "codigo_barras": u.codigo_barras, "op_id": u.op_id, "op_numero": u.op.numero, "op_status": u.op.status,
                "projeto_codigo": u.op.projeto.codigo, "ambiente": p.modulo.ambiente.nome, "modulo": p.modulo.codigo,
                "modulo_descricao": p.modulo.descricao or "",
                "peca": p.descricao, "material_codigo": p.material_codigo,
                "medidas": f"{p.comprimento_mm:g} × {p.largura_mm:g} × {(p.espessura_mm or 0):g}",
                "situacao": sit, "proxima_etapa": proxima.centro.codigo if proxima else None,
                "ultima_etapa": ultima.centro.codigo if ultima else None,
                "ultima_baixa_em": ultima.concluida_em if ultima else None,
                "ultimo_operador": ultima.operador if ultima else None,
                "reposicao": u.reposicao_de_id is not None,
            })
    return {"total": sum(contagem.values()), "por_situacao": contagem, "pecas": linhas}


def historico_baixas(db: Session, empresa_id: int, de: datetime, ate: datetime, centro: str | None = None,
                     operador: str | None = None) -> dict:
    consulta = (select(EtapaUnidade).join(UnidadePeca).join(OrdemProducao)
                .where(OrdemProducao.empresa_id == empresa_id, EtapaUnidade.concluida_em.between(de, ate)))
    baixas, por_operador, por_centro = [], {}, {}
    for e in db.scalars(consulta.order_by(EtapaUnidade.concluida_em.desc())):
        if centro and e.centro.codigo != centro.upper():
            continue
        if operador and (e.operador or "") != operador:
            continue
        nome = e.operador or "—"
        por_operador[nome] = por_operador.get(nome, 0) + 1
        por_centro[e.centro.codigo] = por_centro.get(e.centro.codigo, 0) + 1
        if len(baixas) < 300:
            baixas.append({"quando": e.concluida_em, "centro_codigo": e.centro.codigo, "operador": e.operador,
                           "codigo_barras": e.unidade.codigo_barras, "peca": e.unidade.peca.descricao,
                           "op_numero": e.unidade.op.numero})
    return {"total": sum(por_centro.values()), "por_operador": por_operador, "por_centro": por_centro, "baixas": baixas}
