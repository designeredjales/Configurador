from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import COMPRAS, ESTOQUE, empresa_atual
from ..models import (
    Empresa,
    Fornecedor,
    ItemPedido,
    Material,
    MovimentoEstoque,
    PedidoCompra,
    StatusPedido,
    Usuario,
)
from ..schemas import (
    FornecedorIn,
    FornecedorOut,
    InventarioIn,
    MovimentoOut,
    PedidoIn,
    PedidoOut,
    PosicaoEstoque,
    RecebimentoIn,
)
from ..services import estoque, financeiro

router = APIRouter(prefix="/api", tags=["compras e estoque"])


# --- Fornecedores ---------------------------------------------------------------

@router.get("/fornecedores", response_model=list[FornecedorOut])
def listar_fornecedores(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return db.scalars(select(Fornecedor).where(Fornecedor.empresa_id == emp.id).order_by(Fornecedor.nome))


@router.post("/fornecedores", response_model=FornecedorOut, status_code=201)
def criar_fornecedor(dados: FornecedorIn, usuario: Usuario = Depends(COMPRAS), db: Session = Depends(get_db)):
    fornecedor = Fornecedor(empresa_id=usuario.empresa_id, **dados.model_dump())
    db.add(fornecedor)
    db.commit()
    return fornecedor


# --- Estoque -------------------------------------------------------------------

@router.get("/estoque", response_model=list[PosicaoEstoque])
def posicao(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return estoque.posicao(db, emp.id)


@router.get("/estoque/movimentos", response_model=list[MovimentoOut])
def movimentos(material_id: int | None = None, limite: int = 100,
               emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    consulta = select(MovimentoEstoque).where(MovimentoEstoque.empresa_id == emp.id)
    if material_id is not None:
        consulta = consulta.where(MovimentoEstoque.material_id == material_id)
    movs = db.scalars(consulta.order_by(MovimentoEstoque.id.desc()).limit(min(limite, 500)))
    return [{
        "id": m.id, "material_codigo": m.material.codigo, "quantidade": m.quantidade,
        "custo_unitario": m.custo_unitario, "origem": m.origem, "referencia": m.referencia,
        "observacao": m.observacao, "usuario": m.usuario.nome if m.usuario else None,
        "criado_em": m.criado_em,
    } for m in movs]


@router.post("/estoque/inventario", response_model=PosicaoEstoque)
def inventario(dados: InventarioIn, usuario: Usuario = Depends(ESTOQUE), db: Session = Depends(get_db)):
    material = db.get(Material, dados.material_id)
    if material is None or material.empresa_id != usuario.empresa_id:
        raise HTTPException(404, "Material não encontrado")
    estoque.inventario(db, material, dados.quantidade_contada, usuario.id, dados.observacao)
    db.commit()
    return next(p for p in estoque.posicao(db, usuario.empresa_id) if p["material_id"] == material.id)


# --- Pedidos de compra -----------------------------------------------------------

def _pedido_out(p: PedidoCompra) -> dict:
    itens = [{
        "id": i.id, "material_id": i.material_id, "material_codigo": i.material.codigo,
        "descricao": i.material.descricao, "unidade": i.material.unidade, "quantidade": i.quantidade,
        "recebido": i.recebido, "pendente": i.pendente, "custo_unitario": i.custo_unitario,
    } for i in p.itens]
    return {
        "id": p.id, "numero": p.numero, "fornecedor_id": p.fornecedor_id,
        "fornecedor_nome": p.fornecedor.nome, "status": p.status, "previsao": p.previsao,
        "observacao": p.observacao, "criado_em": p.criado_em, "itens": itens,
        "total": round(sum(i.quantidade * i.custo_unitario for i in p.itens), 2),
    }


def _carregar(db: Session, empresa_id: int, pedido_id: int) -> PedidoCompra:
    pedido = db.get(PedidoCompra, pedido_id)
    if pedido is None or pedido.empresa_id != empresa_id:
        raise HTTPException(404, "Pedido não encontrado")
    return pedido


@router.get("/pedidos", response_model=list[PedidoOut])
def listar_pedidos(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    pedidos = db.scalars(select(PedidoCompra).where(PedidoCompra.empresa_id == emp.id)
                         .order_by(PedidoCompra.numero.desc()))
    return [_pedido_out(p) for p in pedidos]


@router.get("/pedidos/{pedido_id}", response_model=PedidoOut)
def detalhe_pedido(pedido_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return _pedido_out(_carregar(db, emp.id, pedido_id))


@router.post("/pedidos", response_model=PedidoOut, status_code=201)
def criar_pedido(dados: PedidoIn, usuario: Usuario = Depends(COMPRAS), db: Session = Depends(get_db)):
    fornecedor = db.get(Fornecedor, dados.fornecedor_id)
    if fornecedor is None or fornecedor.empresa_id != usuario.empresa_id:
        raise HTTPException(404, "Fornecedor não encontrado")
    ultimo = db.scalar(select(func.max(PedidoCompra.numero))
                       .where(PedidoCompra.empresa_id == usuario.empresa_id)) or 0
    pedido = PedidoCompra(empresa_id=usuario.empresa_id, numero=ultimo + 1, fornecedor=fornecedor,
                          previsao=dados.previsao, observacao=dados.observacao, usuario_id=usuario.id)
    vistos = set()
    for item in dados.itens:
        material = db.get(Material, item.material_id)
        if material is None or material.empresa_id != usuario.empresa_id:
            raise HTTPException(404, f"Material {item.material_id} não encontrado")
        if material.id in vistos:
            raise HTTPException(422, f"Material {material.codigo} repetido no pedido")
        vistos.add(material.id)
        custo = item.custo_unitario if item.custo_unitario is not None else material.custo_unitario
        pedido.itens.append(ItemPedido(material=material, quantidade=item.quantidade, custo_unitario=custo))
    db.add(pedido)
    db.commit()
    return _pedido_out(pedido)


@router.post("/pedidos/{pedido_id}/enviar", response_model=PedidoOut)
def enviar_pedido(pedido_id: int, usuario: Usuario = Depends(COMPRAS), db: Session = Depends(get_db)):
    pedido = _carregar(db, usuario.empresa_id, pedido_id)
    if pedido.status != StatusPedido.RASCUNHO:
        raise HTTPException(409, f"Pedido {pedido.numero} já está {pedido.status}")
    pedido.status = StatusPedido.ENVIADO
    db.commit()
    return _pedido_out(pedido)


@router.post("/pedidos/{pedido_id}/cancelar", response_model=PedidoOut)
def cancelar_pedido(pedido_id: int, usuario: Usuario = Depends(COMPRAS), db: Session = Depends(get_db)):
    pedido = _carregar(db, usuario.empresa_id, pedido_id)
    if pedido.status not in (StatusPedido.RASCUNHO, StatusPedido.ENVIADO):
        raise HTTPException(409, f"Pedido {pedido.status} não pode ser cancelado")
    pedido.status = StatusPedido.CANCELADO
    db.commit()
    return _pedido_out(pedido)


@router.post("/pedidos/{pedido_id}/receber", response_model=PedidoOut)
def receber_pedido(pedido_id: int, dados: RecebimentoIn, usuario: Usuario = Depends(COMPRAS),
                   db: Session = Depends(get_db)):
    pedido = _carregar(db, usuario.empresa_id, pedido_id)
    quantidades: dict[int, float] = {}
    for item in dados.itens:
        quantidades[item.item_id] = quantidades.get(item.item_id, 0) + item.quantidade
    custos = {i.id: i.custo_unitario for i in pedido.itens}
    try:
        estoque.receber(db, pedido, quantidades, usuario.id)
        # Cada recebimento gera a conta a pagar do que entrou, no prazo do fornecedor
        financeiro.conta_do_recebimento(
            db, pedido, sum(q * custos[i] for i, q in quantidades.items()), usuario.id)
    except estoque.ErroEstoque as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return _pedido_out(pedido)
