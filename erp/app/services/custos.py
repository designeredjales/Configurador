"""Custo-hora por setor e mão de obra padrão da obra.

Custo-hora do setor = custo mensal (folha + encargos + rateio de despesas fixas) ÷ horas produtivas
do mês (pessoas × horas do turno × eficiência × dias úteis). Tempo padrão de cada peça no setor =
minutos fixos por peça + minutos por m². A mão de obra padrão de uma obra soma, peça a peça, o
roteiro que ela vai percorrer (as mesmas regras da OP) × o custo-hora de cada setor.
"""
from collections import defaultdict
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OPERACOES_USINAGEM, CentroTrabalho, Projeto
from . import gestao, separacao
from .pcp import _aplica


def dias_uteis(db: Session, empresa_id: int) -> int:
    return gestao.config(db, empresa_id).dias_uteis_mes or 22


def centros(db: Session, empresa_id: int, so_ativos: bool = True) -> list[CentroTrabalho]:
    q = select(CentroTrabalho).where(CentroTrabalho.empresa_id == empresa_id)
    if so_ativos:
        q = q.where(CentroTrabalho.ativo)
    lista = list(db.scalars(q.order_by(CentroTrabalho.sequencia)))
    return anotar(db, empresa_id, lista)


def anotar(db: Session, empresa_id: int, lista):
    """Informa os dias úteis da base para o custo-hora calculado de cada setor."""
    dias = dias_uteis(db, empresa_id)
    for c in lista:
        c.dias_uteis = dias
    return lista


def _somar(pecas, cts: list[CentroTrabalho], classes: dict, dias: int) -> dict:
    horas: dict[str, float] = defaultdict(float)
    custo: dict[str, float] = defaultdict(float)
    for peca, n in pecas:
        area = peca.comprimento_mm * peca.largura_mm / 1e6
        for c in cts:
            if _aplica(c, peca, classes):
                h = c.minutos(area) * n / 60
                horas[c.codigo] += h
                custo[c.codigo] += h * c.custo_hora_para(dias)
    por_setor = [{"centro_codigo": c.codigo, "centro_nome": c.nome, "horas": round(horas[c.codigo], 2),
                  "custo_hora": c.custo_hora_para(dias), "custo": round(custo[c.codigo], 2)}
                 for c in cts if horas[c.codigo] or custo[c.codigo]]
    return {"horas": round(sum(horas.values()), 2), "total": round(sum(custo.values()), 2), "por_setor": por_setor}


def mao_de_obra_projeto(db: Session, projeto: Projeto) -> dict:
    cts = centros(db, projeto.empresa_id)
    classes = separacao.mapa(db, projeto.empresa_id)
    pecas = [(pc, (pc.quantidade or 1) * (m.quantidade or 1)) for a in projeto.ambientes for m in a.modulos for pc in m.pecas]
    return _somar(pecas, cts, classes, dias_uteis(db, projeto.empresa_id))


def mao_de_obra_xml(db: Session, empresa_id: int, lido) -> dict:
    """Mesma conta para um XML ainda não importado (versão da proposta no comercial)."""
    cts = centros(db, empresa_id)
    if not any(c.custo_mensal and (c.minutos_peca or c.minutos_m2) for c in cts):
        return {"horas": 0.0, "total": 0.0, "por_setor": []}
    classes = separacao.mapa(db, empresa_id)
    lista_classes = [c for c in classes.values()]
    pecas = []
    for mods in lido.ambientes.values():
        for m in mods:
            modulo = SimpleNamespace(codigo=m.codigo, descricao=m.descricao)
            for px in m.pecas:
                ops = set(px.operacoes)
                p = SimpleNamespace(codigo=px.codigo, descricao=px.descricao, comprimento_mm=px.comprimento_mm,
                                    largura_mm=px.largura_mm, operacoes=",".join(px.operacoes), modulo=modulo,
                                    tem_fita=bool(px.fita_codigo) or "BORDA" in ops, tem_usinagem=bool(OPERACOES_USINAGEM & ops))
                p.separacao = separacao.classificar(p, lista_classes)
                pecas.append((p, max(1, round(px.quantidade)) * max(1, round(m.quantidade))))
    return _somar(pecas, cts, classes, dias_uteis(db, empresa_id))
