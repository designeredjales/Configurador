"""Ponto de equilíbrio, meta de faturamento e markup (modelo de planejamento "Ponto de equilíbrio 2.0").

Reproduz a planilha da consultoria, aba por aba:
- Análise: imóvel (locado ou próprio), investimentos (máquinas, frota, showroom, diversos), retorno
  esperado sobre o capital, pessoal, custos fixos, custos de crescimento, despesas variáveis,
  venda necessária, faturamento de equilíbrio, meta e markup (divisor) + markup Promob;
- R$ Hr Máq: custo-hora de máquina e simulação de ociosidade;
- projeção mensal (faturamento × lucro sobre o equilíbrio).
Percentuais nas premissas vêm em % (ex.: 11 = 11%).
"""
from copy import deepcopy

DP_DURAVEL = 1 / 120     # depreciação mensal de bens duráveis (10 anos)
DP_MENOS_DURAVEL = 1 / 60  # bens menos duráveis (5 anos)

PREMISSAS_PADRAO: dict = {
    "imovel": {"situacao": "LOCADO", "frente_m": 52, "fundo_m": 40, "locacao_m2": 37.2, "valor_m2": 6189},
    "investimentos": [
        {"nome": "Seccionadora", "tipo": "MAQUINA", "valor": 0},
        {"nome": "Coladeira de fita", "tipo": "MAQUINA", "valor": 0},
        {"nome": "Centro de usinagem (CNC)", "tipo": "MAQUINA", "valor": 320000},
        {"nome": "Coladeira de borda", "tipo": "MAQUINA", "valor": 150000},
        {"nome": "Frota", "tipo": "FROTA", "valor": 250000},
        {"nome": "Diversos", "tipo": "OUTRO", "valor": 30000},
        {"nome": "Showroom", "tipo": "OUTRO", "valor": 0},
    ],
    "retorno_mercado_pct": 1.0,     # custo de oportunidade do capital ao mês
    "retorno_pretendido_pct": 10.0,  # acima do retorno de mercado
    "pessoal": {"funcionarios": 24, "folha": 56000, "encargos_pct": 80.0, "pro_labore": 20000, "encargos_pro_labore_pct": 27.5},
    "fixos": {"modo": "RESUMO", "resumo": 15000, "itens": {
        "Condomínio e IPTU": 0, "Água, luz e telefone": 0, "Manutenção e conservação": 0, "Seguros": 0,
        "Internet": 0, "Material de escritório": 0, "Treinamentos e viagens": 0, "Combustível": 0}},
    "crescimento": {"marketing": 3000, "reserva_caixa": True, "reserva_meses": 6, "investimento": True,
                    "investimento_pct_ano": 20.0, "depreciacao": True, "vida_util_anos": 10},
    "variaveis": {"dv_pct": 70.0, "rt_pct": 0.0, "comissoes_pct": 10.0, "imposto_pct": 11.0},
    "lucro_pct": 15.0,
    "maquinas": {"quantidade": 3, "dias": 20, "horas": 6, "taxa_retorno_pct": 1.0, "produtividade_pct": 70.0,
                 "operador": 3500, "horas_ociosas": 30},
    "sazonalidade": [1.0] * 12,
}


class ErroPremissas(ValueError):
    status = 422


def _num(v, nome: str, minimo: float | None = 0.0, maximo: float | None = None) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        raise ErroPremissas(f"Premissa '{nome}' precisa ser um número")
    if (minimo is not None and x < minimo) or (maximo is not None and x > maximo):
        raise ErroPremissas(f"Premissa '{nome}' fora da faixa ({minimo} a {maximo})")
    return x


def completar(premissas: dict | None) -> dict:
    """Premissas recebidas sobre o padrão (o que faltar vem do modelo)."""
    base = deepcopy(PREMISSAS_PADRAO)
    for k, v in (premissas or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
            if k == "fixos" and isinstance(v.get("itens"), dict):
                base[k]["itens"] = dict(v["itens"])
        elif v is not None:
            base[k] = v
    return base


def calcular(premissas: dict | None) -> dict:
    p = completar(premissas)
    im, pes, fx, cr, va, mq = p["imovel"], p["pessoal"], p["fixos"], p["crescimento"], p["variaveis"], p["maquinas"]
    for chave, maximo in (("dv_pct", 99), ("rt_pct", 50), ("comissoes_pct", 50), ("imposto_pct", 60)):
        _num(va[chave], chave, 0, maximo)
    lucro_pct = _num(p["lucro_pct"], "lucro_pct", 0, 90)
    dv = va["dv_pct"] / 100
    imposto = va["imposto_pct"] / 100

    # Imóvel e estrutura
    area = _num(im["frente_m"], "frente_m") * _num(im["fundo_m"], "fundo_m")
    valor_locacao = area * _num(im["locacao_m2"], "locacao_m2")
    valor_proprio = area * _num(im["valor_m2"], "valor_m2")
    invest = [{"nome": i.get("nome") or "Investimento", "tipo": (i.get("tipo") or "OUTRO").upper(),
               "valor": _num(i.get("valor"), i.get("nome") or "investimento")} for i in p["investimentos"]]
    maquinas = sum(i["valor"] for i in invest if i["tipo"] == "MAQUINA")
    frota = sum(i["valor"] for i in invest if i["tipo"] == "FROTA")
    outros = sum(i["valor"] for i in invest if i["tipo"] not in ("MAQUINA", "FROTA"))
    total_invest = maquinas + frota + outros
    # Mesma composição da planilha: máquinas com depreciação durável, demais bens e 1/24 da frota
    custo_estrutura = maquinas * (1 + DP_DURAVEL) + (frota + outros) + DP_MENOS_DURAVEL + frota / 24
    mercado = _num(p["retorno_mercado_pct"], "retorno_mercado_pct", 0, 20) / 100
    if im["situacao"] == "PROPRIO":
        retorno_mercado = (valor_proprio + custo_estrutura) * mercado
    else:
        retorno_mercado = valor_locacao + custo_estrutura * mercado
    roi = retorno_mercado * (1 + _num(p["retorno_pretendido_pct"], "retorno_pretendido_pct", 0, 500) / 100)

    # Pessoal
    funcionarios = max(1.0, _num(pes["funcionarios"], "funcionarios"))
    folha = _num(pes["folha"], "folha") * (1 + _num(pes["encargos_pct"], "encargos_pct", 0, 300) / 100) + \
        _num(pes["pro_labore"], "pro_labore") * (1 + _num(pes["encargos_pro_labore_pct"], "encargos_pro_labore_pct", 0, 300) / 100)

    # Custos fixos e de crescimento
    if fx["modo"] == "DETALHADO":
        fixos = sum(_num(v, k) for k, v in fx["itens"].items()) + _num(cr["marketing"], "marketing")
    else:
        fixos = _num(fx["resumo"], "resumo")
    marketing = _num(cr["marketing"], "marketing")
    reserva = fixos * _num(cr["reserva_meses"], "reserva_meses", 0, 36) / 12 if cr["reserva_caixa"] else 0.0
    reinvest = total_invest * _num(cr["investimento_pct_ano"], "investimento_pct_ano", 0, 100) / 100 / 12 if cr["investimento"] else 0.0
    vida = max(1.0, _num(cr["vida_util_anos"], "vida_util_anos"))
    depreciacao = total_invest / vida / 12 if cr["depreciacao"] else 0.0
    crescimento = marketing + reserva + reinvest + depreciacao
    fixos_crescimento = fixos + crescimento

    # Venda necessária, equilíbrio e meta
    venda = (folha + roi + fixos_crescimento) / (1 - dv)
    venda_imposto = venda / (1 - imposto)
    pe_funcionario = venda_imposto / funcionarios
    equilibrio = pe_funcionario * funcionarios
    meta = equilibrio * (1 + lucro_pct / 100)

    # Markup (divisor) e markup a cadastrar no Promob
    df_mk = (roi + folha + fixos_crescimento) / meta * 100
    dv_mk = (va["rt_pct"] + va["comissoes_pct"])
    divisor = 100 - (df_mk + dv_mk + lucro_pct)
    if divisor <= 0:
        raise ErroPremissas("Fixos + comissões + lucro passam de 100% da meta: reveja as premissas")
    markup = 100 / divisor
    markup_final = markup + imposto

    # Custo-hora de máquina (aba R$ Hr Máq)
    qtd = max(1.0, _num(mq["quantidade"], "quantidade"))
    dias, horas = max(1.0, _num(mq["dias"], "dias")), max(0.1, _num(mq["horas"], "horas"))
    valor_medio = maquinas / qtd
    deprec_ano = DP_DURAVEL * 12
    manutencao = valor_medio / 48
    retorno_inv = valor_medio * _num(mq["taxa_retorno_pct"], "taxa_retorno_pct", 0, 50) / 100 * deprec_ano
    ponto_equilibrio_maq = roi + folha
    contribuicao = ponto_equilibrio_maq * _num(mq["produtividade_pct"], "produtividade_pct", 0, 100) / 100 / qtd
    custo_mes_maquina = retorno_inv + manutencao + _num(mq["operador"], "operador") + contribuicao
    custo_hora_maquina = custo_mes_maquina / dias / horas
    ociosidade = _num(mq["horas_ociosas"], "horas_ociosas") * qtd * custo_hora_maquina

    saz = list(p.get("sazonalidade") or [1.0] * 12)[:12] + [1.0] * max(0, 12 - len(p.get("sazonalidade") or []))
    media_saz = sum(saz) / 12 or 1
    meses = [{"mes": i + 1, "faturamento": round(meta * f / media_saz, 2), "lucro": round(meta * f / media_saz - equilibrio, 2)}
             for i, f in enumerate(saz)]

    r = lambda v: round(v, 2)  # noqa: E731
    return {
        "premissas": p,
        "imovel": {"area_m2": r(area), "valor_locacao": r(valor_locacao), "valor_proprio": r(valor_proprio)},
        "investimentos": {"maquinas": r(maquinas), "frota": r(frota), "outros": r(outros), "total": r(total_invest),
                          "custo_estrutura": r(custo_estrutura)},
        "retorno": {"mercado": r(retorno_mercado), "com_lucro_pretendido": r(roi)},
        "pessoal": {"folha_total": r(folha), "media_salario": r(_num(pes["folha"], "folha") / funcionarios)},
        "fixos": {"fixos": r(fixos), "marketing": r(marketing), "reserva_caixa": r(reserva), "reinvestimento": r(reinvest),
                  "depreciacao": r(depreciacao), "crescimento": r(crescimento), "fixos_e_crescimento": r(fixos_crescimento)},
        "venda_necessaria": r(venda), "venda_com_imposto": r(venda_imposto), "ponto_equilibrio_funcionario": r(pe_funcionario),
        "faturamento_equilibrio": r(equilibrio), "meta_faturamento": r(meta),
        "composicao_meta": {"pessoal": r(folha), "retorno": r(roi), "fixos_e_crescimento": r(fixos_crescimento),
                            "variaveis": r(meta * dv), "lucro": r(meta * lucro_pct / 100), "imposto": r(meta * imposto),
                            "meta_com_imposto": r(meta + meta * imposto)},
        "markup": {"despesas_fixas_pct": r(df_mk), "variaveis_pct": r(dv_mk), "lucro_pct": r(lucro_pct),
                   "divisor_pct": r(divisor), "markup": round(markup, 4), "markup_final": round(markup_final, 4),
                   "markup_promob_pct": r((markup_final - 1) * 100)},
        "maquina": {"valor_medio": r(valor_medio), "depreciacao_ano": round(deprec_ano, 4), "manutencao": r(manutencao),
                    "retorno_investimento": r(retorno_inv), "contribuicao": r(contribuicao), "custo_mes": r(custo_mes_maquina),
                    "custo_hora": r(custo_hora_maquina), "ociosidade_valor": r(ociosidade)},
        "meses": meses,
    }
