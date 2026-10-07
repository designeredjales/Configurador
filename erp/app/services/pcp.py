"""PCP: geração de OP, roteiro por peça, apontamento por código de barras e painel."""
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CentroTrabalho,
    EtapaUnidade,
    OrdemProducao,
    Projeto,
    RegraCentro,
    StatusOP,
    StatusProjeto,
    UnidadePeca,
)

CENTROS_PADRAO = [
    ("CORTE", "Corte / Seccionadora", 10, RegraCentro.TODAS),
    ("BORDA", "Coladeira de Borda", 20, RegraCentro.COM_FITA),
    ("USINAGEM", "Furação / CNC", 30, RegraCentro.COM_USINAGEM),
    ("EMBALAGEM", "Conferência e Embalagem", 40, RegraCentro.TODAS),
]


class ErroPCP(ValueError):
    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.status = status


def criar_centros_padrao(db: Session, empresa_id: int) -> None:
    for codigo, nome, seq, regra in CENTROS_PADRAO:
        db.add(CentroTrabalho(empresa_id=empresa_id, codigo=codigo, nome=nome,
                              sequencia=seq, regra=regra))


def _aplica(centro: CentroTrabalho, peca) -> bool:
    if centro.regra == RegraCentro.COM_FITA:
        return peca.tem_fita
    if centro.regra == RegraCentro.COM_USINAGEM:
        return peca.tem_usinagem
    return True


def gerar_op(db: Session, projeto: Projeto, prioridade: int = 3,
             data_entrega: date | None = None) -> OrdemProducao:
    if projeto.status != StatusProjeto.LIBERADO:
        raise ErroPCP(f"Projeto precisa estar LIBERADO pela engenharia (status atual: {projeto.status})")

    centros = list(db.scalars(
        select(CentroTrabalho)
        .where(CentroTrabalho.empresa_id == projeto.empresa_id, CentroTrabalho.ativo.is_(True))
        .order_by(CentroTrabalho.sequencia)
    ))
    if not centros:
        raise ErroPCP("Nenhum centro de trabalho ativo cadastrado", 422)

    ultimo = db.scalar(
        select(func.max(OrdemProducao.numero)).where(OrdemProducao.empresa_id == projeto.empresa_id)
    ) or 0
    op = OrdemProducao(
        empresa_id=projeto.empresa_id,
        numero=ultimo + 1,
        projeto=projeto,
        prioridade=prioridade,
        data_entrega=data_entrega or projeto.data_entrega,
    )
    db.add(op)

    seq = 0
    for amb in projeto.ambientes:
        for mod in amb.modulos:
            for peca in mod.pecas:
                roteiro = [c for c in centros if _aplica(c, peca)]
                for _ in range(peca.quantidade * mod.quantidade):
                    seq += 1
                    unidade = UnidadePeca(
                        peca=peca,
                        sequencial=seq,
                        codigo_barras=f"{projeto.empresa_id:03d}{op.numero:06d}{seq:05d}",
                    )
                    unidade.etapas = [
                        EtapaUnidade(centro=c, sequencia=i) for i, c in enumerate(roteiro, start=1)
                    ]
                    op.unidades.append(unidade)

    projeto.status = StatusProjeto.PRODUCAO
    db.flush()
    return op


def progresso(op: OrdemProducao) -> tuple[int, int]:
    etapas = [e for u in op.unidades for e in u.etapas]
    return len(etapas), sum(1 for e in etapas if e.concluida_em)


def apontar(db: Session, empresa_id: int, codigo_barras: str, centro_codigo: str,
            usuario=None) -> tuple[UnidadePeca, EtapaUnidade | None]:
    """Dá baixa da peça no centro. Retorna a unidade e a próxima etapa pendente."""
    unidade = db.scalar(
        select(UnidadePeca).join(OrdemProducao)
        .where(UnidadePeca.codigo_barras == codigo_barras.strip(),
               OrdemProducao.empresa_id == empresa_id)
    )
    if unidade is None:
        raise ErroPCP(f"Etiqueta {codigo_barras} não encontrada", 404)
    op = unidade.op
    if op.status in (StatusOP.CANCELADA, StatusOP.CONCLUIDA):
        raise ErroPCP(f"OP {op.numero} está {op.status}")

    centro_codigo = centro_codigo.strip().upper()
    etapa = next((e for e in unidade.etapas if e.centro.codigo == centro_codigo), None)
    if etapa is None:
        roteiro = " > ".join(e.centro.codigo for e in unidade.etapas)
        raise ErroPCP(f"Peça não passa por {centro_codigo}. Roteiro: {roteiro}", 422)
    if etapa.concluida_em:
        raise ErroPCP(f"Peça já apontada em {centro_codigo} em {etapa.concluida_em:%d/%m %H:%M}")
    anteriores = [e for e in unidade.etapas if e.sequencia < etapa.sequencia and not e.concluida_em]
    if anteriores:
        raise ErroPCP(f"Etapa anterior pendente: {anteriores[0].centro.codigo}")

    etapa.concluida_em = datetime.now()
    if usuario is not None:
        etapa.operador = usuario.nome
        etapa.usuario_id = usuario.id

    if op.status == StatusOP.ABERTA:
        op.status = StatusOP.EM_PRODUCAO
    total, feitas = progresso(op)
    if feitas == total:
        op.status = StatusOP.CONCLUIDA
        op.concluida_em = datetime.now()
        db.flush()
        abertas = db.scalar(
            select(func.count()).select_from(OrdemProducao)
            .where(OrdemProducao.projeto_id == op.projeto_id,
                   OrdemProducao.status.in_([StatusOP.ABERTA, StatusOP.EM_PRODUCAO]))
        )
        if not abertas:
            op.projeto.status = StatusProjeto.CONCLUIDO
            op.projeto.producao_concluida_em = datetime.now()
            from .estoque import consumir_projeto  # evita import circular
            consumir_projeto(db, op.projeto, usuario.id if usuario is not None else None)
    db.flush()

    proxima = next((e for e in unidade.etapas if not e.concluida_em), None)
    return unidade, proxima


def fila_por_centro(db: Session, empresa_id: int) -> list[dict]:
    """Peças na fila de cada centro (etapa liberada: todas as anteriores feitas)."""
    centros = list(db.scalars(
        select(CentroTrabalho).where(CentroTrabalho.empresa_id == empresa_id)
        .order_by(CentroTrabalho.sequencia)
    ))
    fila = {c.id: 0 for c in centros}
    hoje = {c.id: 0 for c in centros}
    inicio_dia = datetime.combine(date.today(), datetime.min.time())

    ops = db.scalars(
        select(OrdemProducao).where(
            OrdemProducao.empresa_id == empresa_id,
            OrdemProducao.status.in_([StatusOP.ABERTA, StatusOP.EM_PRODUCAO, StatusOP.CONCLUIDA]),
        )
    )
    for op in ops:
        for unidade in op.unidades:
            for etapa in unidade.etapas:
                if etapa.concluida_em:
                    if etapa.concluida_em >= inicio_dia:
                        hoje[etapa.centro_id] += 1
                elif op.status != StatusOP.CONCLUIDA:
                    fila[etapa.centro_id] += 1
                    break  # só a primeira etapa pendente está na fila
    return [
        {"centro_codigo": c.codigo, "centro_nome": c.nome,
         "na_fila": fila[c.id], "concluidas_hoje": hoje[c.id]}
        for c in centros
    ]
