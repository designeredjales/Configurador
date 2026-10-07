"""Carrinhos da fábrica: a peça é bipada para dentro do carrinho (com a baixa do setor)
e o setor seguinte confere o carrinho inteiro de uma vez, bipando a etiqueta dele.

O carrinho mistura obras (é assim que sai do corte de um lote); por isso cada grupo
(lote, obra/cliente e separação) ganha um marcador impresso que vai entre as peças.
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Carrinho, Empresa, ItemCarrinho, OrdemProducao, UnidadePeca, Usuario
from . import pcp, separacao
from .pcp import ErroPCP


def eh_codigo_carrinho(codigo: str) -> bool:
    return len(codigo) == 12 and codigo.startswith("98") and codigo.isdigit()


def criar(db: Session, empresa_id: int, quantidade: int = 1) -> list[Carrinho]:
    ultimo = db.scalar(select(func.max(Carrinho.numero)).where(Carrinho.empresa_id == empresa_id)) or 0
    novos = [Carrinho(empresa_id=empresa_id, numero=n, codigo_barras=f"98{empresa_id:03d}{n:07d}")
             for n in range(ultimo + 1, ultimo + 1 + quantidade)]
    db.add_all(novos)
    db.flush()
    return novos


def carregar(db: Session, empresa_id: int, carrinho_id: int | None = None, codigo: str | None = None) -> Carrinho:
    if codigo is not None:
        c = db.scalar(select(Carrinho).where(Carrinho.codigo_barras == codigo.strip(), Carrinho.empresa_id == empresa_id))
    else:
        c = db.get(Carrinho, carrinho_id)
        c = c if c is not None and c.empresa_id == empresa_id else None
    if c is None:
        raise ErroPCP("Carrinho não encontrado", 404)
    return c


def _unidade(db: Session, empresa_id: int, codigo: str) -> UnidadePeca:
    u = db.scalar(select(UnidadePeca).join(OrdemProducao).where(
        UnidadePeca.codigo_barras == codigo.strip(), OrdemProducao.empresa_id == empresa_id))
    if u is None:
        raise ErroPCP(f"Etiqueta {codigo} não encontrada", 404)
    return u


def tirar_de_carrinho(db: Session, unidade_id: int) -> None:
    item = db.scalar(select(ItemCarrinho).where(ItemCarrinho.unidade_id == unidade_id))
    if item is not None:
        db.delete(item)
        db.flush()


def bipar(db: Session, emp: Empresa, usuario: Usuario, carrinho: Carrinho, codigo: str, centro: str) -> dict:
    """Dá a baixa no setor (se ainda não deu) e coloca a peça no carrinho."""
    if not carrinho.ativo:
        raise ErroPCP(f"Carrinho {carrinho.numero} está desativado")
    unidade = _unidade(db, emp.id, codigo)
    centro = centro.strip().upper()
    etapa = next((e for e in unidade.etapas if e.centro.codigo == centro), None)
    apontou = False
    if etapa is not None and etapa.concluida_em:
        pass  # já tinha a baixa neste setor: só entra no carrinho
    else:
        pcp.apontar(db, emp.id, codigo, centro, usuario)  # valida roteiro, ordem, refugo, OP
        apontou = True
    anterior = db.scalar(select(ItemCarrinho).where(ItemCarrinho.unidade_id == unidade.id))
    veio_de = None
    if anterior is not None:
        if anterior.carrinho_id == carrinho.id:
            raise ErroPCP(f"{unidade.peca.descricao} já está neste carrinho")
        veio_de = anterior.carrinho.numero
        db.delete(anterior)
        db.flush()
    db.add(ItemCarrinho(carrinho=carrinho, unidade=unidade, centro_codigo=centro, usuario_nome=usuario.nome))
    db.flush()
    db.refresh(carrinho)
    classes = separacao.mapa(db, emp.id)
    classe = classes.get(unidade.peca.separacao)
    proxima = next((e for e in unidade.etapas if not e.concluida_em), None)
    return {"carrinho": carrinho, "apontou": apontou, "veio_de_carrinho": veio_de,
            "codigo_barras": unidade.codigo_barras, "peca": unidade.peca.descricao,
            "proxima_etapa": proxima.centro.codigo if proxima else None,
            "separacao": classe.codigo if classe else None, "separacao_nome": classe.nome if classe else None,
            "grupo": _rotulo(_chave(unidade, classes))}


def conferir(db: Session, emp: Empresa, usuario: Usuario, codigo_carrinho: str, centro: str) -> dict:
    """O setor bipa a etiqueta do carrinho: dá baixa em todas as peças que estão esperando por ele."""
    carrinho = carregar(db, emp.id, codigo=codigo_carrinho)
    centro = centro.strip().upper()
    baixadas, ja_feitas, nao_passam, bloqueadas = 0, 0, 0, []
    for item in list(carrinho.itens):
        u = item.unidade
        etapa = next((e for e in u.etapas if e.centro.codigo == centro), None)
        if etapa is None:
            nao_passam += 1
            continue
        if etapa.concluida_em:
            ja_feitas += 1
            continue
        try:
            pcp.apontar(db, emp.id, u.codigo_barras, centro, usuario)
            item.centro_codigo = centro
            baixadas += 1
        except ErroPCP as e:
            bloqueadas.append({"codigo_barras": u.codigo_barras, "peca": u.peca.descricao, "motivo": str(e)})
    db.flush()
    return {"carrinho": carrinho, "centro_codigo": centro, "baixadas": baixadas, "ja_feitas": ja_feitas,
            "nao_passam": nao_passam, "bloqueadas": bloqueadas}


def remover(db: Session, carrinho: Carrinho, codigo: str) -> Carrinho:
    item = next((i for i in carrinho.itens if i.unidade.codigo_barras == codigo.strip()), None)
    if item is None:
        raise ErroPCP(f"Etiqueta {codigo} não está no carrinho {carrinho.numero}", 404)
    carrinho.itens.remove(item)
    db.flush()
    return carrinho


def esvaziar(db: Session, carrinho: Carrinho) -> Carrinho:
    carrinho.itens.clear()
    db.flush()
    return carrinho


def _chave(u: UnidadePeca, classes: dict) -> tuple:
    op, p = u.op, u.op.projeto
    classe = classes.get(u.peca.separacao)
    return (op.lote.numero if op.lote else None, p.codigo, p.nome, p.cliente.nome if p.cliente else None,
            classe.codigo if classe else None, classe.nome if classe else None)


def _rotulo(chave: tuple) -> str:
    lote, codigo, _, cliente, _, sep_nome = chave
    partes = ([f"Lote {lote}"] if lote else []) + [codigo] + ([cliente] if cliente else [])
    return " · ".join(partes) + (f" · SEPARAR {sep_nome.upper()}" if sep_nome else "")


def carrinho_out(db: Session, carrinho: Carrinho) -> dict:
    classes = separacao.mapa(db, carrinho.empresa_id)
    grupos: dict[tuple, list] = {}
    for item in carrinho.itens:
        grupos.setdefault(_chave(item.unidade, classes), []).append(item)
    lista = []
    for chave in sorted(grupos, key=lambda k: (k[0] or 0, k[1], k[4] or "")):
        lote, codigo, nome, cliente, sep, sep_nome = chave
        itens = grupos[chave]
        lista.append({
            "lote_numero": lote, "projeto_codigo": codigo, "projeto_nome": nome, "cliente": cliente,
            "separacao": sep, "separacao_nome": sep_nome, "rotulo": _rotulo(chave), "quantidade": len(itens),
            "pecas": [{"codigo_barras": i.unidade.codigo_barras, "peca": i.unidade.peca.descricao,
                       "modulo": i.unidade.peca.modulo.codigo, "centro_codigo": i.centro_codigo,
                       "proxima_etapa": next((e.centro.codigo for e in i.unidade.etapas if not e.concluida_em), None)}
                      for i in itens],
        })
    return {"id": carrinho.id, "numero": carrinho.numero, "codigo_barras": carrinho.codigo_barras,
            "ativo": carrinho.ativo, "total_pecas": len(carrinho.itens), "grupos": lista}
