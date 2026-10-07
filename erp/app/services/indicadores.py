"""Indicadores do dono: venda, margem, prazo, fábrica, qualidade e caixa num só lugar."""
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CentroTrabalho,
    Chamado,
    Ocorrencia,
    OrdemProducao,
    Projeto,
    StatusChamado,
    StatusOP,
    StatusProjeto,
)
from . import estoque, financeiro, pcp
from .pos_obra import CAUSAS_INTERNAS


def _media(valores: list[float]) -> float | None:
    return round(mean(valores), 1) if valores else None


def calcular(db: Session, empresa_id: int, dias: int = 90) -> dict:
    hoje = date.today()
    inicio = hoje - timedelta(days=dias)
    inicio_dt = datetime.combine(inicio, datetime.min.time())
    projetos = list(db.scalars(select(Projeto).where(Projeto.empresa_id == empresa_id)))

    # Comercial: contratos fechados no período
    contratos = [p for p in projetos if p.contrato_em and p.contrato_em >= inicio]
    faturamento = round(sum(p.valor_venda or 0 for p in contratos), 2)
    por_mes: dict[str, float] = defaultdict(float)
    seis_meses = financeiro._soma_meses(hoje.replace(day=1), -5)
    for p in projetos:
        if p.contrato_em and p.contrato_em >= seis_meses:
            por_mes[p.contrato_em.strftime("%Y-%m")] += p.valor_venda or 0
    meses = [financeiro._soma_meses(seis_meses, i).strftime("%Y-%m") for i in range(6)]

    # Margem: obras com produção concluída ou entregues no período
    fechados = [p for p in projetos if p.status in (StatusProjeto.CONCLUIDO, StatusProjeto.ENTREGUE)
                and (p.producao_concluida_em or datetime.min) >= inicio_dt and p.valor_venda]
    dres = [financeiro.dre_obra(db, p) for p in fechados]
    receita_f = sum(d["receita"] for d in dres)
    margem_ponderada = round(100 * sum(d["margem_contribuicao"] for d in dres) / receita_f, 1) if receita_f else None

    # Prazos
    entregues = [p for p in projetos if p.entregue_em and p.entregue_em >= inicio_dt]
    lead_venda = [(p.entregue_em.date() - p.contrato_em).days for p in entregues if p.contrato_em]
    lead_fabrica = [(p.producao_concluida_em - p.liberado_em).total_seconds() / 86400
                    for p in projetos if p.producao_concluida_em and p.liberado_em and p.producao_concluida_em >= inicio_dt]
    com_prazo = [p for p in entregues if p.data_entrega]
    no_prazo = [p for p in com_prazo if p.entregue_em.date() <= p.data_entrega]
    atrasados_hoje = [p for p in projetos if p.data_entrega and p.data_entrega < hoje
                      and p.status not in (StatusProjeto.ENTREGUE, StatusProjeto.CANCELADO)]

    # Fábrica: tempo de passagem por setor (da etapa anterior, ou da criação da OP, até a baixa)
    centros = list(db.scalars(select(CentroTrabalho).where(CentroTrabalho.empresa_id == empresa_id)
                              .order_by(CentroTrabalho.sequencia)))
    passagem: dict[int, list[float]] = defaultdict(list)
    baixas: dict[int, int] = defaultdict(int)
    for op in db.scalars(select(OrdemProducao).where(OrdemProducao.empresa_id == empresa_id,
                                                     OrdemProducao.status != StatusOP.CANCELADA)):
        for u in op.unidades:
            anterior = op.criada_em
            for e in u.etapas:
                if not e.concluida_em:
                    break
                if e.concluida_em >= inicio_dt:
                    passagem[e.centro_id].append((e.concluida_em - anterior).total_seconds() / 3600)
                    baixas[e.centro_id] += 1
                anterior = e.concluida_em
    fila = {f["centro_codigo"]: f["na_fila"] for f in pcp.fila_por_centro(db, empresa_id)}
    setores = [{
        "centro_codigo": c.codigo, "centro_nome": c.nome, "pecas_no_periodo": baixas[c.id],
        "passagem_media_h": _media(passagem[c.id]), "na_fila": fila.get(c.codigo, 0),
    } for c in centros]
    # Gargalo: maior tempo de passagem quando há tempo medido; senão, a maior fila; senão, nenhum
    medidos = [s for s in setores if (s["passagem_media_h"] or 0) >= 0.1]
    if medidos:
        gargalo = max(medidos, key=lambda s: (s["passagem_media_h"], s["na_fila"]))["centro_codigo"]
    else:
        com_fila = [s for s in setores if s["na_fila"] > 0]
        gargalo = max(com_fila, key=lambda s: s["na_fila"])["centro_codigo"] if com_fila else None

    # Qualidade: assistência e retrabalho
    chamados = list(db.scalars(select(Chamado).where(Chamado.empresa_id == empresa_id)))
    resolvidos = [c for c in chamados if c.status == StatusChamado.RESOLVIDO and c.resolvido_em >= inicio_dt]
    retrabalhos = [c for c in resolvidos if c.causa in CAUSAS_INTERNAS]
    custo_assist = round(sum(c.custo for c in resolvidos), 2)
    por_causa: dict[str, int] = defaultdict(int)
    for c in resolvidos:
        por_causa[c.causa] += 1

    refugos = list(db.scalars(select(Ocorrencia).where(Ocorrencia.empresa_id == empresa_id, Ocorrencia.tipo == "REFUGO",
                                                     Ocorrencia.criado_em >= inicio_dt)))

    # Caixa e estoque
    fluxo = financeiro.fluxo_caixa(db, empresa_id, 1)
    pos = estoque.posicao(db, empresa_id)

    return {
        "periodo_dias": dias, "de": inicio, "ate": hoje,
        "comercial": {
            "faturamento": faturamento, "contratos": len(contratos),
            "ticket_medio": round(faturamento / len(contratos), 2) if contratos else None,
            "por_mes": [{"mes": m, "valor": round(por_mes.get(m, 0), 2)} for m in meses],
        },
        "margem": {
            "margem_media_pct": margem_ponderada, "obras": len(dres),
            "projetos": sorted(({"codigo": d["codigo"], "receita": d["receita"], "margem": d["margem_contribuicao"],
                                 "margem_pct": d["margem_pct"], "material_base": d["material_base"]} for d in dres),
                               key=lambda x: x["margem_pct"]),
        },
        "prazo": {
            "entregas": len(entregues), "lead_time_venda_dias": _media(lead_venda),
            "lead_time_fabrica_dias": _media(lead_fabrica),
            "pontualidade_pct": round(100 * len(no_prazo) / len(com_prazo), 1) if com_prazo else None,
            "atrasados_hoje": [{"codigo": p.codigo, "nome": p.nome, "data_entrega": p.data_entrega,
                                "status": p.status, "dias_atraso": (hoje - p.data_entrega).days} for p in atrasados_hoje],
        },
        "fabrica": {"setores": setores, "gargalo": gargalo},
        "qualidade": {
            "chamados_abertos": sum(1 for c in chamados if c.status != StatusChamado.RESOLVIDO),
            "chamados_resolvidos": len(resolvidos), "retrabalhos": len(retrabalhos),
            "taxa_retrabalho_pct": round(100 * len(retrabalhos) / len(entregues), 1) if entregues else None,
            "custo_assistencia": custo_assist,
            "custo_assistencia_pct": round(100 * custo_assist / faturamento, 2) if faturamento else None,
            "por_causa": dict(sorted(por_causa.items())),
            "refugos": len(refugos), "custo_refugo": round(sum(o.custo_material for o in refugos), 2),
        },
        "caixa": {
            "vencido_receber": fluxo["vencido_receber"], "vencido_pagar": fluxo["vencido_pagar"],
            "saldo_mes": fluxo["meses"][0]["saldo_mes"],
            "valor_estoque": round(sum(max(0, p["saldo"]) * p["custo_unitario"] for p in pos), 2),
            "materiais_em_falta": sum(1 for p in pos if p["disponivel"] < 0),
        },
    }
