"""Estoque, reservas, MRP (sugestão de compra) e recebimento de pedidos.

Unidade de estoque = unidade do cadastro do material. Chapa cadastrada por
chapa (CH, com medidas) é reservada em fração de chapa; em M2, em metros
quadrados. As reservas já incluem a perda configurada na empresa.
"""
import math
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    ItemPedido,
    Material,
    MovimentoEstoque,
    OrigemMovimento,
    PedidoCompra,
    Projeto,
    Reserva,
    StatusPedido,
)
from . import engenharia

ABERTOS = (StatusPedido.RASCUNHO, StatusPedido.ENVIADO, StatusPedido.PARCIAL)


class ErroEstoque(ValueError):
    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.status = status


def necessidade_projeto(db: Session, projeto: Projeto) -> dict[str, float]:
    """Quanto o projeto consome de cada material, na unidade de estoque (com perda)."""
    c = engenharia.consumo(db, projeto)
    materiais = {
        m.codigo: m for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))
    }
    total: dict[str, float] = {}
    for linha in c["chapas"]:
        mat = materiais.get(linha["material_codigo"])
        if linha["unidade"] == "CH" and mat and mat.comprimento_mm and mat.largura_mm:
            total[linha["material_codigo"]] = linha["quantidade_com_perda"] / (mat.comprimento_mm * mat.largura_mm / 1e6)
        else:
            total[linha["material_codigo"]] = linha["quantidade_com_perda"]
    for linha in c["fitas"]:
        total[linha["material_codigo"]] = linha["quantidade_com_perda"]
    for linha in c["itens"]:
        total[linha["material_codigo"]] = linha["quantidade_liquida"]
    return {k: round(v, 4) for k, v in total.items()}


def reservar_projeto(db: Session, projeto: Projeto) -> None:
    materiais = {
        m.codigo: m for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))
    }
    for codigo, qtd in necessidade_projeto(db, projeto).items():
        if qtd > 0 and codigo in materiais:
            db.add(Reserva(empresa_id=projeto.empresa_id, projeto_id=projeto.id,
                           material_id=materiais[codigo].id, quantidade=qtd))
    db.flush()


def consumir_projeto(db: Session, projeto: Projeto, usuario_id: int | None = None) -> None:
    """Projeto concluído: a reserva vira saída de estoque, ao custo médio atual."""
    reservas = db.scalars(select(Reserva).where(Reserva.projeto_id == projeto.id,
                                                Reserva.baixada_em.is_(None)))
    agora = datetime.now()
    for r in reservas:
        db.add(MovimentoEstoque(
            empresa_id=r.empresa_id, material_id=r.material_id, quantidade=-r.quantidade,
            custo_unitario=r.material.custo_unitario, origem=OrigemMovimento.CONSUMO,
            referencia=f"Projeto {projeto.codigo}", projeto_id=projeto.id, usuario_id=usuario_id,
        ))
        r.baixada_em = agora
    db.flush()


def saldos(db: Session, empresa_id: int) -> dict[int, float]:
    return dict(db.execute(
        select(MovimentoEstoque.material_id, func.sum(MovimentoEstoque.quantidade))
        .where(MovimentoEstoque.empresa_id == empresa_id).group_by(MovimentoEstoque.material_id)
    ).all())


def posicao(db: Session, empresa_id: int) -> list[dict]:
    """Saldo, reservado, em pedido, disponível e sugestão de compra por material."""
    saldo = saldos(db, empresa_id)
    reservado = dict(db.execute(
        select(Reserva.material_id, func.sum(Reserva.quantidade))
        .where(Reserva.empresa_id == empresa_id, Reserva.baixada_em.is_(None))
        .group_by(Reserva.material_id)
    ).all())
    em_pedido: dict[int, float] = defaultdict(float)
    for item in db.scalars(
        select(ItemPedido).join(PedidoCompra)
        .where(PedidoCompra.empresa_id == empresa_id, PedidoCompra.status.in_(ABERTOS))
    ):
        em_pedido[item.material_id] += item.pendente

    linhas = []
    for m in db.scalars(select(Material).where(Material.empresa_id == empresa_id).order_by(Material.codigo)):
        s, r, p = saldo.get(m.id, 0.0), reservado.get(m.id, 0.0), em_pedido.get(m.id, 0.0)
        falta = r + m.estoque_minimo - s - p
        # Chapa, ferragem e qualquer item contável se compram inteiros
        sugestao = math.ceil(falta - 1e-9) if falta > 0 and m.unidade.upper() not in ("M", "M2", "KG", "L") else max(0.0, falta)
        linhas.append({
            "material_id": m.id, "codigo": m.codigo, "descricao": m.descricao, "tipo": m.tipo,
            "unidade": m.unidade, "saldo": round(s, 3), "reservado": round(r, 3),
            "em_pedido": round(p, 3), "disponivel": round(s - r, 3), "estoque_minimo": m.estoque_minimo,
            "sugestao_compra": round(sugestao, 3), "custo_unitario": m.custo_unitario,
            "fornecedor_id": m.fornecedor_id,
        })
    return linhas


def receber(db: Session, pedido: PedidoCompra, quantidades: dict[int, float],
            usuario_id: int | None = None) -> None:
    """Entrada no estoque e custo médio ponderado do material."""
    if pedido.status not in ABERTOS:
        raise ErroEstoque(f"Pedido {pedido.numero} está {pedido.status}")
    itens = {i.id: i for i in pedido.itens}
    if not quantidades or any(q <= 0 for q in quantidades.values()):
        raise ErroEstoque("Informe quantidades recebidas maiores que zero.", 422)
    saldo = saldos(db, pedido.empresa_id)
    for item_id, qtd in quantidades.items():
        item = itens.get(item_id)
        if item is None:
            raise ErroEstoque(f"Item {item_id} não pertence ao pedido {pedido.numero}", 422)
        if qtd > item.pendente + 1e-9:
            raise ErroEstoque(f"{item.material.codigo}: recebendo {qtd}, mas só faltam {item.pendente}", 422)
        mat = item.material
        atual = max(0.0, saldo.get(mat.id, 0.0))
        if item.custo_unitario > 0:
            mat.custo_unitario = round(
                (atual * mat.custo_unitario + qtd * item.custo_unitario) / (atual + qtd), 4)
        item.recebido += qtd
        saldo[mat.id] = saldo.get(mat.id, 0.0) + qtd
        db.add(MovimentoEstoque(
            empresa_id=pedido.empresa_id, material_id=mat.id, quantidade=qtd,
            custo_unitario=item.custo_unitario, origem=OrigemMovimento.RECEBIMENTO,
            referencia=f"Pedido {pedido.numero}", usuario_id=usuario_id,
        ))
    pedido.status = (StatusPedido.RECEBIDO if all(i.pendente <= 1e-9 for i in pedido.itens)
                     else StatusPedido.PARCIAL)
    db.flush()


def inventario(db: Session, material: Material, contado: float, usuario_id: int | None,
               observacao: str | None = None) -> MovimentoEstoque | None:
    diferenca = contado - saldos(db, material.empresa_id).get(material.id, 0.0)
    if abs(diferenca) < 1e-9:
        return None
    mov = MovimentoEstoque(
        empresa_id=material.empresa_id, material_id=material.id, quantidade=round(diferenca, 4),
        custo_unitario=material.custo_unitario, origem=OrigemMovimento.INVENTARIO,
        referencia="Contagem física", observacao=observacao, usuario_id=usuario_id,
    )
    db.add(mov)
    db.flush()
    return mov
