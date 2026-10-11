"""Sequenciamento pela restrição (tambor-pulmão-corda, da Teoria das Restrições).

- Tambor: o setor com mais dias de carga (horas pendentes ÷ horas produtivas por dia). Ele dita
  o ritmo; programar além da capacidade dele só aumenta estoque em processo.
- Sequência: obras em aberto pela data de entrega (e prioridade), encaixadas na capacidade do tambor.
- Pulmão: dias de proteção. Saída prevista = passagem pelo tambor + pulmão.
- Corda: data até a qual a obra precisa ser liberada (lote/OP e material) para chegar no tambor a tempo.

A carga usa os tempos padrão dos setores (minutos por peça + por m²). Sem tempos cadastrados,
usa m² de chapa e a vazão observada nos últimos 7 dias.
"""
import math
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OrdemProducao, Projeto, StatusOP, StatusProjeto
from . import custos, gestao, separacao
from .pcp import _aplica


def _soma_uteis(d: date, n: int) -> date:
    """Data a n dias úteis de d (n pode ser negativo)."""
    passo = 1 if n >= 0 else -1
    while d.weekday() >= 5:
        d += timedelta(days=passo)
    falta = abs(n)
    while falta:
        d += timedelta(days=passo)
        if d.weekday() < 5:
            falta -= 1
    return d


def calcular(db: Session, empresa_id: int, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    cfg = gestao.config(db, empresa_id)
    cts = custos.centros(db, empresa_id)
    classes = separacao.mapa(db, empresa_id)
    em_horas = any((c.minutos_peca or c.minutos_m2) for c in cts)

    def carga_peca(c, peca, area: float, n: float) -> float:
        return c.minutos(area) * n / 60 if em_horas else area * n

    itens: dict[tuple, dict] = {}
    carga_item: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    # OPs em aberto: só as etapas que faltam
    for op in db.scalars(select(OrdemProducao).where(OrdemProducao.empresa_id == empresa_id,
                                                     OrdemProducao.status.in_([StatusOP.ABERTA, StatusOP.EM_PRODUCAO]))):
        chave = ("OP", op.id)
        p = op.projeto
        itens[chave] = {"tipo": "OP", "op_id": op.id, "op_numero": op.numero, "projeto_id": p.id, "codigo": p.codigo,
                        "nome": p.nome, "lote": op.lote.numero if op.lote else None, "prioridade": op.prioridade,
                        "data_entrega": op.data_entrega or p.data_entrega, "em_producao": op.status == StatusOP.EM_PRODUCAO}
        por_codigo = {c.id: c for c in cts}
        for u in op.unidades:
            if not u.ativa:
                continue
            area = u.peca.comprimento_mm * u.peca.largura_mm / 1e6
            for e in u.etapas:
                c = por_codigo.get(e.centro_id)
                if c is not None and not e.concluida_em:
                    carga_item[chave][c.codigo] += carga_peca(c, u.peca, area, 1)
    # Projetos liberados ainda sem OP: o roteiro inteiro
    for p in db.scalars(select(Projeto).where(Projeto.empresa_id == empresa_id, Projeto.status == StatusProjeto.LIBERADO)):
        chave = ("PROJETO", p.id)
        itens[chave] = {"tipo": "PROJETO", "op_id": None, "op_numero": None, "projeto_id": p.id, "codigo": p.codigo,
                        "nome": p.nome, "lote": None, "prioridade": None, "data_entrega": p.data_entrega, "em_producao": False}
        for a in p.ambientes:
            for m in a.modulos:
                for pc in m.pecas:
                    area, n = pc.comprimento_mm * pc.largura_mm / 1e6, (pc.quantidade or 1) * (m.quantidade or 1)
                    for c in cts:
                        if _aplica(c, pc, classes):
                            carga_item[chave][c.codigo] += carga_peca(c, pc, area, n)

    # Capacidade por dia: horas produtivas (com tempos) ou vazão observada em m²
    if em_horas:
        capacidade = {c.codigo: c.capacidade_h_dia for c in cts}
    else:
        capacidade = {s["centro_codigo"]: s["vazao_m2_dia"] or 0 for s in gestao.painel(db, empresa_id, hoje)["setores"]}
    total = defaultdict(float)
    for cargas in carga_item.values():
        for k, v in cargas.items():
            total[k] += v
    setores = [{"centro_codigo": c.codigo, "centro_nome": c.nome, "carga": round(total[c.codigo], 2),
                "capacidade_dia": round(capacidade.get(c.codigo) or 0, 2),
                "dias_de_carga": round(total[c.codigo] / capacidade[c.codigo], 1) if capacidade.get(c.codigo) else None}
               for c in cts]
    fixo = next((s for s in setores if s["centro_codigo"] == (cfg.tambor_codigo or "")), None)
    medidos = [s for s in setores if s["dias_de_carga"] is not None and s["carga"] > 0]
    if fixo:
        tambor = fixo
    elif medidos:
        tambor = max(medidos, key=lambda s: s["dias_de_carga"])
    else:
        com_carga = [s for s in setores if s["carga"] > 0]
        tambor = max(com_carga, key=lambda s: s["carga"]) if com_carga else None

    pulmao = cfg.pulmao_dias or 0
    ordem = sorted(itens.items(), key=lambda kv: (kv[1]["data_entrega"] or date.max, not kv[1]["em_producao"],
                                                   kv[1]["prioridade"] or 9, kv[1]["projeto_id"]))
    cap = tambor["capacidade_dia"] if tambor else 0
    cursor = 0.0
    saida = []
    for pos, (chave, it) in enumerate(ordem, start=1):
        carga = carga_item[chave].get(tambor["centro_codigo"], 0.0) if tambor else 0.0
        inicio = cursor
        dur = carga / cap if cap else 0.0
        cursor += dur
        d_ini, d_fim = _soma_uteis(hoje, math.floor(inicio)), _soma_uteis(hoje, math.ceil(cursor))
        previsao = _soma_uteis(d_fim, math.ceil(pulmao))
        liberar = _soma_uteis(d_ini, -math.ceil(pulmao))
        if it["data_entrega"] is None:
            status, folga = "SEM_DATA", None
        else:
            folga = (it["data_entrega"] - previsao).days
            status = "ATRASA" if folga < 0 else "RISCO" if folga < pulmao else "OK"
        saida.append({**it, "posicao": pos, "carga_tambor": round(carga, 2), "carga_total": round(sum(carga_item[chave].values()), 2),
                      "dias_no_tambor": round(dur, 2), "inicio_tambor": d_ini, "fim_tambor": d_fim, "saida_prevista": previsao,
                      "liberar_ate": max(liberar, hoje) if it["tipo"] == "PROJETO" else None,
                      "liberar_ja": it["tipo"] == "PROJETO" and liberar <= hoje, "folga_dias": folga, "status": status,
                      "sem_capacidade": bool(tambor and not cap)})
    return {"unidade": "h" if em_horas else "m²", "pulmao_dias": pulmao, "tambor": tambor,
            "tambor_fixo": bool(fixo), "setores": setores, "itens": saida, "dias_de_fila_tambor": round(cursor, 1)}


def prioridade_sugerida(item: dict, pulmao: float) -> int:
    if item["status"] in ("ATRASA", "RISCO"):
        return 1
    if item["status"] == "SEM_DATA":
        return 4
    return 2 if (item["folga_dias"] or 0) < 2 * max(pulmao, 1) else 3


def aplicar_prioridades(db: Session, empresa_id: int) -> dict:
    r = calcular(db, empresa_id)
    mudou = 0
    for it in r["itens"]:
        if it["tipo"] != "OP":
            continue
        op = db.get(OrdemProducao, it["op_id"])
        nova = prioridade_sugerida(it, r["pulmao_dias"])
        if op.prioridade != nova:
            op.prioridade = nova
            mudou += 1
    db.flush()
    return {"ops_alteradas": mudou}


def projetos_para_lote(db: Session, empresa_id: int, dias: float) -> list[int]:
    """Projetos liberados, na ordem da sequência, que cabem em `dias` de capacidade do tambor."""
    r = calcular(db, empresa_id)
    escolhidos, usado = [], 0.0
    for it in r["itens"]:
        if it["tipo"] != "PROJETO":
            continue
        if escolhidos and usado + it["dias_no_tambor"] > dias:
            break
        escolhidos.append(it["projeto_id"])
        usado += it["dias_no_tambor"]
    return escolhidos
