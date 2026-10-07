"""Contrato (parcelas a receber), contas a pagar, DRE por obra e fluxo de caixa."""
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Categoria,
    Empresa,
    Lancamento,
    Material,
    MovimentoEstoque,
    OrigemMovimento,
    PedidoCompra,
    Projeto,
    StatusProjeto,
    TipoLancamento,
)
from . import estoque


class ErroFinanceiro(ValueError):
    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.status = status


def _soma_meses(d: date, meses: int) -> date:
    mes = d.month - 1 + meses
    ano, mes = d.year + mes // 12, mes % 12 + 1
    dias = [31, 29 if ano % 4 == 0 and (ano % 100 or ano % 400 == 0) else 28, 31, 30, 31, 30,
            31, 31, 30, 31, 30, 31][mes - 1]
    return date(ano, mes, min(d.day, dias))


def registrar_contrato(db: Session, projeto: Projeto, valor: float, parcelas: int,
                       primeiro_vencimento: date, usuario_id: int | None) -> list[Lancamento]:
    if projeto.contrato_em:
        raise ErroFinanceiro(f"Contrato do projeto {projeto.codigo} já registrado em {projeto.contrato_em:%d/%m/%Y}")
    if valor <= 0 or parcelas < 1:
        raise ErroFinanceiro("Informe valor e quantidade de parcelas válidos.", 422)
    base = round(valor / parcelas, 2)
    lancamentos = []
    for i in range(parcelas):
        # Última parcela absorve o arredondamento
        v = round(valor - base * (parcelas - 1), 2) if i == parcelas - 1 else base
        lanc = Lancamento(
            empresa_id=projeto.empresa_id, tipo=TipoLancamento.RECEBER, categoria=Categoria.VENDA,
            descricao=f"{projeto.codigo} · parcela {i + 1}/{parcelas}", valor=v,
            vencimento=_soma_meses(primeiro_vencimento, i), projeto_id=projeto.id,
            cliente_id=projeto.cliente_id, usuario_id=usuario_id,
        )
        db.add(lanc)
        lancamentos.append(lanc)
    projeto.valor_venda = round(valor, 2)
    projeto.contrato_em = date.today()
    if projeto.status == StatusProjeto.ORCAMENTO:
        projeto.status = StatusProjeto.APROVADO
    db.flush()
    return lancamentos


def conta_do_recebimento(db: Session, pedido: PedidoCompra, valor: float, usuario_id: int | None) -> None:
    if valor <= 0:
        return
    db.add(Lancamento(
        empresa_id=pedido.empresa_id, tipo=TipoLancamento.PAGAR, categoria=Categoria.MATERIAL,
        descricao=f"Pedido de compra {pedido.numero} · {pedido.fornecedor.nome}", valor=round(valor, 2),
        vencimento=date.today() + timedelta(days=pedido.fornecedor.prazo_pagamento_dias),
        pedido_id=pedido.id, fornecedor_id=pedido.fornecedor_id, usuario_id=usuario_id,
    ))
    db.flush()


def baixar(lanc: Lancamento, data: date, valor: float | None) -> None:
    if lanc.pago_em:
        raise ErroFinanceiro(f"Lançamento já baixado em {lanc.pago_em:%d/%m/%Y}")
    lanc.pago_em = data
    lanc.valor_pago = round(valor if valor is not None else lanc.valor, 2)


def dre_obra(db: Session, projeto: Projeto) -> dict:
    empresa = db.get(Empresa, projeto.empresa_id)
    receita = projeto.valor_venda or 0.0
    impostos = round(receita * empresa.imposto_venda_pct / 100, 2)

    # Material: realizado (baixa do estoque) quando o projeto concluiu; senão, previsto
    movs = list(db.scalars(select(MovimentoEstoque).where(
        MovimentoEstoque.projeto_id == projeto.id, MovimentoEstoque.origem == OrigemMovimento.CONSUMO)))
    if movs:
        material, material_base = round(sum(-m.quantidade * m.custo_unitario for m in movs), 2), "REALIZADO"
    else:
        custos = {m.codigo: m.custo_unitario for m in db.scalars(
            select(Material).where(Material.empresa_id == projeto.empresa_id))}
        material = round(sum(q * custos.get(c, 0.0) for c, q in estoque.necessidade_projeto(db, projeto).items()), 2)
        material_base = "PREVISTO"

    lancs = list(db.scalars(select(Lancamento).where(Lancamento.projeto_id == projeto.id)))
    custos_diretos: dict[str, float] = defaultdict(float)
    for l in lancs:
        if l.tipo == TipoLancamento.PAGAR:
            custos_diretos[l.categoria] += l.valor_pago if l.pago_em else l.valor
    total_diretos = round(sum(custos_diretos.values()), 2)
    margem = round(receita - impostos - material - total_diretos, 2)
    receber = [l for l in lancs if l.tipo == TipoLancamento.RECEBER]
    recebido = round(sum(l.valor_pago or 0 for l in receber if l.pago_em), 2)
    return {
        "projeto_id": projeto.id, "codigo": projeto.codigo, "status": projeto.status,
        "receita": round(receita, 2), "impostos": impostos, "imposto_pct": empresa.imposto_venda_pct,
        "receita_liquida": round(receita - impostos, 2),
        "material": material, "material_base": material_base,
        "custos_diretos": {k: round(v, 2) for k, v in sorted(custos_diretos.items())},
        "total_custos_diretos": total_diretos,
        "margem_contribuicao": margem,
        "margem_pct": round(100 * margem / receita, 1) if receita else 0.0,
        "orcado_frete": projeto.frete_orcado, "orcado_montagem": projeto.montagem_orcada,
        "recebido": recebido,
        "a_receber": round(sum(l.valor for l in receber if not l.pago_em), 2),
        "contrato_em": projeto.contrato_em,
    }


def fluxo_caixa(db: Session, empresa_id: int, meses: int = 6) -> dict:
    hoje = date.today()
    inicio = hoje.replace(day=1)
    chaves = [_soma_meses(inicio, i).strftime("%Y-%m") for i in range(meses)]
    linhas = {k: {"mes": k, "receber_previsto": 0.0, "pagar_previsto": 0.0,
                  "recebido": 0.0, "pago": 0.0} for k in chaves}
    vencido_receber = vencido_pagar = 0.0
    for l in db.scalars(select(Lancamento).where(Lancamento.empresa_id == empresa_id)):
        if l.pago_em:
            k = l.pago_em.strftime("%Y-%m")
            if k in linhas:
                linhas[k]["recebido" if l.tipo == TipoLancamento.RECEBER else "pago"] += l.valor_pago or 0
            continue
        if l.vencimento < hoje:
            if l.tipo == TipoLancamento.RECEBER:
                vencido_receber += l.valor
            else:
                vencido_pagar += l.valor
        # Atrasado entra no mês corrente: é caixa que ainda precisa acontecer
        k = max(l.vencimento, inicio).strftime("%Y-%m")
        if k in linhas:
            linhas[k]["receber_previsto" if l.tipo == TipoLancamento.RECEBER else "pagar_previsto"] += l.valor
    acumulado = 0.0
    saida = []
    for k in chaves:
        lin = {c: round(v, 2) if isinstance(v, float) else v for c, v in linhas[k].items()}
        acumulado += lin["recebido"] - lin["pago"] + lin["receber_previsto"] - lin["pagar_previsto"]
        lin["saldo_mes"] = round(lin["recebido"] - lin["pago"] + lin["receber_previsto"] - lin["pagar_previsto"], 2)
        lin["saldo_acumulado"] = round(acumulado, 2)
        saida.append(lin)
    return {"meses": saida, "vencido_receber": round(vencido_receber, 2), "vencido_pagar": round(vencido_pagar, 2)}
