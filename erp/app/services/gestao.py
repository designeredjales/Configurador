"""Gestão à vista: o quadro da fábrica para a reunião diária e para a TV do chão de fábrica.

Tudo sai dos dados que já entram pelo Promob e pelo apontamento:
- KPIs do mês em m² (vendido, produzido, preço e custo por m²) contra as metas da base;
- ritmo × takt (Toyota): quanto a fábrica precisa produzir por dia útil e quanto está produzindo;
- restrição (Teoria das Restrições): o setor com mais dias de fila, que dita o ritmo da fábrica;
- pulmão de cada obra (gerenciamento de pulmões do TPC): tempo consumido × trabalho feito;
- kanban do fluxo da obra com limite de WIP por coluna;
- andon: o que precisa de ação hoje.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CentroTrabalho,
    Chamado,
    ConfigGestao,
    Ocorrencia,
    Oportunidade,
    OrdemProducao,
    Projeto,
    StatusChamado,
    StatusOP,
    StatusProjeto,
)

# código, rótulo, unidade, sentido (+1 quanto maior melhor, -1 quanto menor melhor), acumula no mês
METAS = [
    ("faturamento_mes", "Vendido no mês", "R$", 1, True),
    ("m2_vendido_mes", "m² vendidos no mês", "m²", 1, True),
    ("m2_produzido_mes", "m² produzidos no mês", "m²", 1, True),
    ("preco_m2", "Preço médio de venda por m²", "R$", 1, False),
    ("custo_m2", "Custo de produção por m²", "R$", -1, False),
    ("margem_pct", "Margem prevista das vendas", "%", 1, False),
    ("pontualidade_pct", "Entregas no prazo", "%", 1, False),
    ("refugo_pct", "Refugo sobre peças produzidas", "%", -1, False),
    ("conversao_pct", "Conversão comercial", "%", 1, False),
]
METAS_PADRAO = {"pontualidade_pct": 90.0, "refugo_pct": 2.0}
COLUNAS = [("NEGOCIACAO", "Negociação"), ("ENGENHARIA", "Engenharia"), ("LIBERADO", "Liberado (aguarda lote)"),
           ("PRODUCAO", "Em produção"), ("EXPEDICAO", "Produzido (expedição/montagem)"), ("ENTREGUE", "Entregue no mês")]
ZONAS = ["PRETO", "VERMELHO", "AMARELO", "VERDE"]


def config(db: Session, empresa_id: int) -> ConfigGestao:
    cfg = db.get(ConfigGestao, empresa_id)
    if cfg is None:
        cfg = ConfigGestao(empresa_id=empresa_id, metas=dict(METAS_PADRAO), limites_wip={}, dias_uteis_mes=22, horas_turno=8.8)
        db.add(cfg)
        db.flush()
    return cfg


def config_out(cfg: ConfigGestao) -> dict:
    return {"metas": cfg.metas or {}, "limites_wip": cfg.limites_wip or {}, "dias_uteis_mes": cfg.dias_uteis_mes,
            "horas_turno": cfg.horas_turno, "pulmao_dias": cfg.pulmao_dias, "tambor_codigo": cfg.tambor_codigo,
            "catalogo_metas": [{"codigo": c, "nome": n, "unidade": u, "maior_melhor": s > 0} for c, n, u, s, _ in METAS],
            "colunas": [{"codigo": c, "nome": n} for c, n in COLUNAS if c != "ENTREGUE"]}


def _br(v, n=1) -> str:
    """Número curto no formato brasileiro para os textos do andon (2,4 em vez de 2.4)."""
    return f"{round(v, n):g}".replace(".", ",")


def _r(v, n=2):
    return round(v, n) if v is not None else None


def _dias_uteis(de: date, ate: date) -> int:
    """Dias de segunda a sexta entre as datas, inclusive."""
    if ate < de:
        return 0
    return sum(1 for i in range((ate - de).days + 1) if (de + timedelta(days=i)).weekday() < 5)


def _m2(peca) -> float:
    return (peca.comprimento_mm or 0) * (peca.largura_mm or 0) / 1e6


def _m2_projeto(p: Projeto) -> float:
    if p.venda_resumo and p.venda_resumo.get("m2_chapa"):
        return p.venda_resumo["m2_chapa"]
    return sum(_m2(pc) * (pc.quantidade or 1) * (m.quantidade or 1) for a in p.ambientes for m in a.modulos for pc in m.pecas)


def _status_meta(valor, meta, sentido: int, acumula: bool, fracao_mes: float) -> str | None:
    if meta is None or valor is None:
        return None
    alvo = meta * fracao_mes if acumula else meta  # metas do mês são cobradas proporcionalmente aos dias úteis
    if sentido > 0:
        if valor >= alvo:
            return "OK"
        return "ATENCAO" if alvo and valor >= alvo * 0.85 else "CRITICO"
    if valor <= alvo:
        return "OK"
    return "ATENCAO" if valor <= alvo * 1.15 else "CRITICO"


def painel(db: Session, empresa_id: int, hoje: date | None = None) -> dict:
    hoje = hoje or date.today()
    agora = datetime.now()
    cfg = config(db, empresa_id)
    metas = cfg.metas or {}
    inicio_mes = hoje.replace(day=1)
    inicio_mes_dt = datetime.combine(inicio_mes, datetime.min.time())
    fim_mes = (inicio_mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    janela = hoje - timedelta(days=6)  # ritmo dos últimos 7 dias
    janela_dt = datetime.combine(janela, datetime.min.time())

    projetos = list(db.scalars(select(Projeto).where(Projeto.empresa_id == empresa_id)))
    centros = list(db.scalars(select(CentroTrabalho).where(CentroTrabalho.empresa_id == empresa_id, CentroTrabalho.ativo)
                              .order_by(CentroTrabalho.sequencia)))
    ops = list(db.scalars(select(OrdemProducao).where(OrdemProducao.empresa_id == empresa_id,
                                                      OrdemProducao.status != StatusOP.CANCELADA)))

    # --- Fábrica: produzido (última etapa), fila e vazão por setor, progresso por obra ---------------
    m2_mes = pecas_mes = 0.0
    por_dia: dict[date, float] = defaultdict(float)
    fila_pecas: dict[int, int] = defaultdict(int)
    fila_m2: dict[int, float] = defaultdict(float)
    vazao_m2: dict[int, float] = defaultdict(float)
    vazao_pecas: dict[int, int] = defaultdict(int)
    etapas_total: dict[int, int] = defaultdict(int)
    etapas_feitas: dict[int, int] = defaultdict(int)
    for op in ops:
        for u in op.unidades:
            if not u.ativa:
                continue
            area = _m2(u.peca)
            pendente_achada = False
            for e in u.etapas:
                etapas_total[op.projeto_id] += 1
                if e.concluida_em:
                    etapas_feitas[op.projeto_id] += 1
                    if e.concluida_em >= janela_dt:
                        vazao_m2[e.centro_id] += area
                        vazao_pecas[e.centro_id] += 1
                elif not pendente_achada and op.status != StatusOP.CONCLUIDA:
                    pendente_achada = True
                    if e.centro.exige_apontamento:
                        fila_pecas[e.centro_id] += 1
                        fila_m2[e.centro_id] += area
            ultima = u.etapas[-1] if u.etapas else None
            if ultima and ultima.concluida_em:
                dia = ultima.concluida_em.date()
                if dia >= hoje - timedelta(days=13):
                    por_dia[dia] += area
                if ultima.concluida_em >= inicio_mes_dt:
                    m2_mes += area
                    pecas_mes += 1

    uteis_janela = max(1, _dias_uteis(janela, hoje))
    setores = []
    for c in centros:
        vz = vazao_m2[c.id] / uteis_janela
        setores.append({"centro_codigo": c.codigo, "centro_nome": c.nome, "conferencia": c.exige_apontamento,
                        "fila_pecas": fila_pecas[c.id], "fila_m2": _r(fila_m2[c.id]),
                        "vazao_m2_dia": _r(vz), "vazao_pecas_dia": _r(vazao_pecas[c.id] / uteis_janela, 1),
                        "dias_de_fila": _r(fila_m2[c.id] / vz, 1) if vz else None})
    com_fila = [s for s in setores if s["fila_pecas"]]
    medidos = [s for s in com_fila if s["dias_de_fila"] is not None]
    if medidos:
        restricao = max(medidos, key=lambda s: s["dias_de_fila"])["centro_codigo"]
    elif com_fila:  # sem vazão medida: quem acumula mais m² parado
        restricao = max(com_fila, key=lambda s: s["fila_m2"])["centro_codigo"]
    else:
        restricao = None
    if cfg.tambor_codigo and any(s["centro_codigo"] == cfg.tambor_codigo for s in setores):
        restricao = cfg.tambor_codigo  # tambor fixado no setup da base

    # --- Ritmo × takt ------------------------------------------------------------------------------
    uteis_mes = cfg.dias_uteis_mes or max(1, _dias_uteis(inicio_mes, fim_mes))
    decorridos = _dias_uteis(inicio_mes, hoje)
    restantes = _dias_uteis(hoje + timedelta(days=1), fim_mes)
    fracao = min(1.0, decorridos / uteis_mes) if uteis_mes else 1.0
    ritmo = sum(v for d, v in por_dia.items() if d >= janela) / uteis_janela
    meta_m2 = metas.get("m2_produzido_mes")
    takt = {"meta_m2_mes": meta_m2, "takt_m2_dia": _r(meta_m2 / uteis_mes) if meta_m2 else None,
            "takt_min_por_m2": _r(cfg.horas_turno * 60 / (meta_m2 / uteis_mes), 1) if meta_m2 else None,
            "ritmo_m2_dia": _r(ritmo), "produzido_mes_m2": _r(m2_mes), "projecao_mes_m2": _r(m2_mes + ritmo * restantes),
            "dias_uteis_mes": uteis_mes, "dias_uteis_decorridos": decorridos, "dias_uteis_restantes": restantes,
            "serie": [{"dia": (hoje - timedelta(days=13 - i)).isoformat(),
                       "m2": _r(por_dia.get(hoje - timedelta(days=13 - i), 0.0))} for i in range(14)]}
    if meta_m2:
        falta = max(0.0, meta_m2 - m2_mes)
        takt["necessario_m2_dia"] = _r(falta / restantes) if restantes else _r(falta)

    # --- Comercial do mês ---------------------------------------------------------------------------
    vendidos = [p for p in projetos if p.contrato_em and inicio_mes <= p.contrato_em <= hoje]
    faturamento = sum(p.valor_venda or 0 for p in vendidos)
    m2_vendido = sum(_m2_projeto(p) for p in vendidos)
    custo = sum((p.venda_resumo or {}).get("valor_pedido") or p.valor_pedido or 0 for p in vendidos)
    com_margem = [p for p in vendidos if (p.venda_resumo or {}).get("margem_pct") is not None]
    base_margem = sum(p.venda_resumo["preco_final"] for p in com_margem)
    margem = (sum(p.venda_resumo["margem_pct"] * p.venda_resumo["preco_final"] for p in com_margem) / base_margem
              if base_margem else None)
    entregues_mes = [p for p in projetos if p.entregue_em and p.entregue_em >= inicio_mes_dt]
    com_prazo = [p for p in entregues_mes if p.data_entrega]
    pontualidade = (100 * sum(1 for p in com_prazo if p.entregue_em.date() <= p.data_entrega) / len(com_prazo)
                    if com_prazo else None)
    refugos_mes = db.scalars(select(Ocorrencia).where(Ocorrencia.empresa_id == empresa_id, Ocorrencia.tipo == "REFUGO",
                                                      Ocorrencia.criado_em >= inicio_mes_dt)).all()
    oportunidades = list(db.scalars(select(Oportunidade).where(Oportunidade.empresa_id == empresa_id)))
    fechadas = [o for o in oportunidades if o.fechado_em and o.fechado_em >= inicio_mes_dt and o.status in ("GANHA", "PERDIDA")]
    conversao = 100 * sum(1 for o in fechadas if o.status == "GANHA") / len(fechadas) if fechadas else None

    valores = {"faturamento_mes": faturamento, "m2_vendido_mes": m2_vendido, "m2_produzido_mes": m2_mes,
               "preco_m2": faturamento / m2_vendido if m2_vendido else None,
               "custo_m2": custo / m2_vendido if m2_vendido else None, "margem_pct": margem,
               "pontualidade_pct": pontualidade,
               "refugo_pct": 100 * len(refugos_mes) / pecas_mes if pecas_mes else (0.0 if not refugos_mes else None),
               "conversao_pct": conversao}
    kpis = []
    for codigo, nome, unidade, sentido, acumula in METAS:
        v, meta = valores[codigo], metas.get(codigo)
        kpis.append({"codigo": codigo, "nome": nome, "unidade": unidade, "valor": _r(v), "meta": meta,
                     "esperado_ate_hoje": _r(meta * fracao) if meta is not None and acumula else None,
                     "status": _status_meta(v, meta, sentido, acumula, fracao)})

    # --- Pulmão de cada obra (tempo consumido × trabalho feito) ------------------------------------
    pulmoes = []
    for p in projetos:
        if p.status not in (StatusProjeto.LIBERADO, StatusProjeto.PRODUCAO) or not p.data_entrega:
            continue
        inicio = (p.liberado_em.date() if p.liberado_em else p.contrato_em or p.criado_em.date())
        total = max(1, (p.data_entrega - inicio).days)
        tempo = min(100.0, 100 * max(0, (hoje - inicio).days) / total)
        trabalho = 100 * etapas_feitas[p.id] / etapas_total[p.id] if etapas_total[p.id] else 0.0
        if hoje > p.data_entrega:
            zona = "PRETO"
        else:
            gap = tempo - trabalho
            zona = "VERDE" if gap <= 0 else "AMARELO" if gap <= 25 else "VERMELHO"
        pulmoes.append({"projeto_id": p.id, "codigo": p.codigo, "nome": p.nome, "status": p.status,
                        "data_entrega": p.data_entrega, "dias_restantes": (p.data_entrega - hoje).days,
                        "tempo_pct": _r(tempo, 0), "trabalho_pct": _r(trabalho, 0), "zona": zona})
    pulmoes.sort(key=lambda x: (ZONAS.index(x["zona"]), x["data_entrega"]))

    # --- Kanban do fluxo da obra -------------------------------------------------------------------
    def cartao(p: Projeto, desde) -> dict:
        d = desde.date() if isinstance(desde, datetime) else desde
        return {"id": p.id, "codigo": p.codigo, "nome": p.nome, "valor": p.valor_venda, "data_entrega": p.data_entrega,
                "dias_na_etapa": (hoje - d).days if d else None,
                "atrasado": bool(p.data_entrega and p.data_entrega < hoje)}
    grupos: dict[str, list] = {c: [] for c, _ in COLUNAS}
    for o in oportunidades:
        if o.status == "ABERTA":
            ultima = o.versoes[-1].calculo if o.versoes and o.versoes[-1].calculo else {}
            grupos["NEGOCIACAO"].append({"id": o.id, "codigo": f"Nº {o.numero}", "nome": f"{o.cliente_nome} · {o.titulo}",
                                         "valor": ultima.get("preco_final") or o.valor_estimado, "data_entrega": None,
                                         "dias_na_etapa": (hoje - o.criado_em.date()).days, "atrasado": False,
                                         "etapa": o.etapa})
    for p in projetos:
        if p.status in (StatusProjeto.ORCAMENTO, StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA):
            grupos["ENGENHARIA"].append(cartao(p, p.contrato_em or p.criado_em))
        elif p.status == StatusProjeto.LIBERADO:
            grupos["LIBERADO"].append(cartao(p, p.liberado_em))
        elif p.status == StatusProjeto.PRODUCAO:
            grupos["PRODUCAO"].append(cartao(p, p.liberado_em))
        elif p.status == StatusProjeto.CONCLUIDO:
            grupos["EXPEDICAO"].append(cartao(p, p.producao_concluida_em))
        elif p.status == StatusProjeto.ENTREGUE and p.entregue_em and p.entregue_em >= inicio_mes_dt:
            grupos["ENTREGUE"].append(cartao(p, p.entregue_em))
    limites = cfg.limites_wip or {}
    kanban = []
    for codigo, nome in COLUNAS:
        itens = sorted(grupos[codigo], key=lambda x: (not x["atrasado"], x["data_entrega"] or date.max))
        limite = limites.get(codigo) if codigo != "ENTREGUE" else None
        kanban.append({"codigo": codigo, "nome": nome, "quantidade": len(itens), "limite": limite,
                       "excedido": bool(limite and len(itens) > limite),
                       "valor": _r(sum(i["valor"] or 0 for i in itens)), "itens": itens[:40]})

    # --- Andon: o que pede ação hoje ---------------------------------------------------------------
    andon = []
    for b in pulmoes:
        if b["zona"] == "PRETO":
            andon.append({"nivel": "CRITICO", "texto": f"{b['codigo']} {b['nome']}: entrega vencida há {-b['dias_restantes']} dia(s)"})
        elif b["zona"] == "VERMELHO":
            andon.append({"nivel": "ATENCAO", "texto": f"{b['codigo']} {b['nome']}: {_br(b['tempo_pct'], 0)}% do prazo usado e {_br(b['trabalho_pct'], 0)}% feito"})
    if restricao:
        s = next(s for s in setores if s["centro_codigo"] == restricao)
        if (s["dias_de_fila"] or 0) >= 2 or s["dias_de_fila"] is None:
            fila = f"{_br(s['dias_de_fila'])} dia(s) de fila" if s["dias_de_fila"] is not None else "fila sem vazão nos últimos 7 dias"
            andon.append({"nivel": "ATENCAO", "texto": f"Restrição em {s['centro_nome']}: {fila} ({s['fila_pecas']} peças, {_br(s['fila_m2'])} m²). Proteja este setor: sem parada, sem setup desnecessário, peças conferidas antes de chegar"})
    for k in kanban:
        if k["excedido"]:
            andon.append({"nivel": "ATENCAO", "texto": f"Kanban {k['nome']}: {k['quantidade']} obras para limite de {k['limite']}. Termine antes de puxar mais"})
    ocorr = db.scalars(select(Ocorrencia).where(Ocorrencia.empresa_id == empresa_id, Ocorrencia.criado_em >= janela_dt)).all()
    por_setor: dict[tuple, int] = defaultdict(int)
    for o in ocorr:
        por_setor[(o.tipo, o.centro_codigo)] += 1
    for (tipo, setor), n in sorted(por_setor.items(), key=lambda x: -x[1]):
        if n >= 3 or tipo == "REFUGO":
            andon.append({"nivel": "ATENCAO" if n < 5 else "CRITICO",
                          "texto": f"{n} {'refugo(s)' if tipo == 'REFUGO' else 'estorno(s)'} em {setor} nos últimos 7 dias"})
    abertos = db.scalars(select(Chamado).where(Chamado.empresa_id == empresa_id, Chamado.status != StatusChamado.RESOLVIDO)).all()
    if abertos:
        andon.append({"nivel": "ATENCAO", "texto": f"{len(abertos)} chamado(s) de assistência aberto(s)"})
    pend = sum(1 for o in oportunidades if o.status == "ABERTA" and o.versoes and o.versoes[-1].aprovacao == "PENDENTE")
    if pend:
        andon.append({"nivel": "ATENCAO", "texto": f"{pend} negociação(ões) aguardando aprovação de desconto"})
    from .comercial import pendencia_auditoria
    for p in projetos:
        if p.venda_resumo and p.status in (StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA) and pendencia_auditoria(db, p):
            andon.append({"nivel": "CRITICO", "texto": f"{p.codigo}: executivo diverge do vendido, liberação travada até a ciência"})
    andon.sort(key=lambda a: a["nivel"] != "CRITICO")

    return {"gerado_em": agora, "mes": inicio_mes.strftime("%Y-%m"), "kpis": kpis, "takt": takt,
            "setores": setores, "restricao": restricao, "pulmoes": pulmoes, "kanban": kanban, "andon": andon}
