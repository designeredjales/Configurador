"""Controladoria: DRE gerencial por centro de custo, verbas, aprovação de despesas e consolidação.

Dois regimes, consolidados mês a mês pelo agendador (ou sob demanda):
- COMPETENCIA (operacional): receita das obras concluídas no mês, impostos pela alíquota, material
  consumido e refugado, custos vinculados à obra no mês da conclusão e despesas pelo vencimento;
- CAIXA (bancário): o que foi efetivamente recebido e pago (baixas), mais o que entrou no extrato
  bancário e ainda não foi conciliado, para a diferença aparecer em vez de sumir.
Meses sem dados do ERP usam o histórico importado (DRE de antes do sistema), marcado como tal.
"""
import csv
import io
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..funcoes import efetivas
from ..models import (
    Categoria,
    CenarioPlanejamento,
    CentroCusto,
    ConfigFinanceira,
    ConsolidacaoDRE,
    Empresa,
    ExecucaoConsolidacao,
    Lancamento,
    MovimentoBancario,
    MovimentoEstoque,
    OrigemMovimento,
    Perfil,
    Projeto,
    TipoLancamento,
    Usuario,
    VerbaCentro,
)
from . import markup

# código, rótulo, natureza (RECEITA soma; demais subtraem), grupo
CONTAS = [
    ("RECEITA", "Receita de vendas", "RECEITA"),
    ("IMPOSTOS", "Impostos sobre vendas", "VARIAVEL"),
    ("MATERIAL", "Material e insumos", "VARIAVEL"),
    ("COMISSOES", "Comissões e RT", "VARIAVEL"),
    ("FRETE_MONTAGEM", "Frete, montagem e assistência", "VARIAVEL"),
    ("PESSOAL", "Pessoal (folha, encargos, pró-labore)", "FIXO"),
    ("OCUPACAO", "Ocupação (aluguel, condomínio, IPTU, energia)", "FIXO"),
    ("ADMINISTRATIVAS", "Administrativas e gerais", "FIXO"),
    ("COMERCIAL", "Comercial e marketing", "FIXO"),
    ("MANUTENCAO", "Manutenção de máquinas e frota", "FIXO"),
    ("FINANCEIRO", "Resultado financeiro (juros, tarifas, rendimentos)", "FINANCEIRO"),
    ("INVESTIMENTOS", "Investimentos (máquinas, reformas, veículos)", "INVESTIMENTO"),
    ("NAO_CONCILIADO", "Extrato bancário não conciliado", "BANCO"),
]
NOMES = {c: n for c, n, _ in CONTAS}
GRUPO = {c: g for c, _, g in CONTAS}
DESPESAS = [c for c, _, g in CONTAS if g in ("FIXO", "VARIAVEL", "INVESTIMENTO")]
POR_CATEGORIA = {
    Categoria.VENDA: "RECEITA", Categoria.MATERIAL: "MATERIAL", Categoria.MAO_DE_OBRA: "PESSOAL",
    Categoria.FRETE: "FRETE_MONTAGEM", Categoria.MONTAGEM: "FRETE_MONTAGEM", Categoria.ASSISTENCIA: "FRETE_MONTAGEM",
    Categoria.COMISSAO: "COMISSOES", Categoria.IMPOSTO: "IMPOSTOS", Categoria.DESPESA_FIXA: "ADMINISTRATIVAS",
    Categoria.OUTROS: "ADMINISTRATIVAS",
}
REGIMES = ("COMPETENCIA", "CAIXA")


class ErroControladoria(ValueError):
    def __init__(self, mensagem: str, status: int = 422):
        super().__init__(mensagem)
        self.status = status


def config(db: Session, empresa_id: int) -> ConfigFinanceira:
    cfg = db.get(ConfigFinanceira, empresa_id)
    if cfg is None:
        cfg = ConfigFinanceira(empresa_id=empresa_id, centros_padrao={}, consolidacao_ativa=True, consolidacao_hora=6,
                               consolidacao_meses=2, exige_centro=False, bloqueia_sem_verba=False)
        db.add(cfg)
        db.flush()
    return cfg


def conta_de(l: Lancamento) -> str:
    if l.conta in NOMES:
        return l.conta
    if l.tipo == TipoLancamento.RECEBER and l.categoria != Categoria.VENDA:
        return "FINANCEIRO"
    return POR_CATEGORIA.get(Categoria(l.categoria), "ADMINISTRATIVAS")


def _brl(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _mes(d) -> tuple[int, int]:
    return d.year, d.month


def _soma_mes(ano: int, mes: int, n: int) -> tuple[int, int]:
    t = ano * 12 + (mes - 1) + n
    return t // 12, t % 12 + 1


# --- Aprovação de despesas ---------------------------------------------------------------------------

def verba_do_mes(db: Session, empresa_id: int, centro_id: int, ano: int, mes: int) -> float:
    return db.scalar(select(func.coalesce(func.sum(VerbaCentro.valor), 0.0)).where(
        VerbaCentro.empresa_id == empresa_id, VerbaCentro.centro_custo_id == centro_id,
        VerbaCentro.ano == ano, VerbaCentro.mes == mes)) or 0.0


def comprometido(db: Session, empresa_id: int, centro_id: int, ano: int, mes: int, exceto: int | None = None) -> float:
    inicio, (a2, m2) = date(ano, mes, 1), _soma_mes(ano, mes, 1)
    q = select(func.coalesce(func.sum(Lancamento.valor), 0.0)).where(
        Lancamento.empresa_id == empresa_id, Lancamento.centro_custo_id == centro_id, Lancamento.tipo == TipoLancamento.PAGAR,
        Lancamento.aprovacao != "RECUSADA", Lancamento.vencimento >= inicio, Lancamento.vencimento < date(a2, m2, 1))
    if exceto:
        q = q.where(Lancamento.id != exceto)
    return db.scalar(q) or 0.0


def _gestao(usuario: Usuario) -> bool:
    return usuario.perfil == Perfil.ADMIN or "aprovar_despesa" in efetivas(usuario)


def pode_aprovar(usuario: Usuario, l: Lancamento, nivel: str) -> bool:
    if _gestao(usuario):
        return True
    # O responsável pelo centro libera o que só passou da alçada (nunca a própria despesa);
    # estouro de verba sobe para a gestão
    return (nivel == "RESPONSAVEL" and l.centro_custo is not None and l.centro_custo.responsavel_id == usuario.id
            and l.usuario_id != usuario.id)


def avaliar(db: Session, usuario: Usuario, l: Lancamento) -> None:
    """Define a aprovação de uma despesa nova (manual) pelas regras da base."""
    if l.tipo != TipoLancamento.PAGAR:
        return
    cfg = config(db, l.empresa_id)
    if cfg.exige_centro and not l.centro_custo_id:
        raise ErroControladoria("Informe o centro de custo da despesa (regra da controladoria desta base)")
    motivos, nivel = [], None
    if l.centro_custo_id:
        ano, mes = _mes(l.vencimento)
        verba = verba_do_mes(db, l.empresa_id, l.centro_custo_id, ano, mes)
        usado = comprometido(db, l.empresa_id, l.centro_custo_id, ano, mes, exceto=l.id)
        centro = db.get(CentroCusto, l.centro_custo_id)
        if verba > 0 and usado + l.valor > verba + 0.005:
            motivos.append(f"estoura a verba de {centro.codigo} em {mes:02d}/{ano} (verba {_brl(verba)}, já comprometido {_brl(usado)})")
            nivel = "GESTAO"
        elif verba <= 0 and cfg.bloqueia_sem_verba:
            motivos.append(f"{centro.codigo} sem verba em {mes:02d}/{ano}")
            nivel = "GESTAO"
    if cfg.alcada_valor and l.valor > cfg.alcada_valor:
        motivos.append(f"acima da alçada de {_brl(cfg.alcada_valor)}")
        nivel = nivel or "RESPONSAVEL"
    if not motivos:
        l.aprovacao, l.aprovacao_motivo = "LIVRE", None
        return
    l.aprovacao_motivo = f"[{nivel}] " + "; ".join(motivos)
    if _gestao(usuario):  # quem aprova despesas não espera a própria aprovação
        l.aprovacao, l.aprovado_por = "APROVADA", usuario.nome
    else:
        l.aprovacao = "PENDENTE"


def nivel_de(l: Lancamento) -> str:
    return "GESTAO" if (l.aprovacao_motivo or "").startswith("[GESTAO]") else "RESPONSAVEL"


def decidir(usuario: Usuario, l: Lancamento, aprovar: bool, observacao: str | None) -> None:
    if l.aprovacao != "PENDENTE":
        raise ErroControladoria(f"Esta despesa não está aguardando aprovação ({l.aprovacao})", 409)
    if not pode_aprovar(usuario, l, nivel_de(l)):
        raise ErroControladoria("Esta despesa precisa de quem aprova despesas (estouro de verba) ou do responsável pelo centro", 403)
    l.aprovacao, l.aprovado_por = ("APROVADA" if aprovar else "RECUSADA"), usuario.nome
    if observacao:
        l.aprovacao_motivo = f"{l.aprovacao_motivo or ''} · {usuario.nome}: {observacao.strip()[:150]}"[:300]


def pendentes(db: Session, usuario: Usuario) -> list[Lancamento]:
    q = select(Lancamento).where(Lancamento.empresa_id == usuario.empresa_id, Lancamento.aprovacao == "PENDENTE")
    lista = list(db.scalars(q.order_by(Lancamento.vencimento)))
    return [l for l in lista if pode_aprovar(usuario, l, nivel_de(l))]


# --- Consolidação ----------------------------------------------------------------------------------

def _centro_padrao(cfg: ConfigFinanceira, conta: str) -> int | None:
    v = (cfg.centros_padrao or {}).get(conta)
    return int(v) if v else None


def _apurar(db: Session, emp: Empresa, cfg: ConfigFinanceira, ano: int, mes: int) -> dict[str, dict[tuple, float]]:
    inicio = date(ano, mes, 1)
    a2, m2 = _soma_mes(ano, mes, 1)
    fim = date(a2, m2, 1)
    ini_dt, fim_dt = datetime.combine(inicio, datetime.min.time()), datetime.combine(fim, datetime.min.time())
    comp: dict[tuple, float] = defaultdict(float)
    caixa: dict[tuple, float] = defaultdict(float)

    def centro(l: Lancamento | None, conta: str) -> int | None:
        return (l.centro_custo_id if l is not None and l.centro_custo_id else None) or _centro_padrao(cfg, conta)

    # Competência: obras concluídas no mês (faturamento) e seus custos
    concluidas = list(db.scalars(select(Projeto).where(Projeto.empresa_id == emp.id, Projeto.producao_concluida_em >= ini_dt,
                                                       Projeto.producao_concluida_em < fim_dt)))
    ids_mes = {p.id for p in concluidas}
    for p in concluidas:
        comp[("RECEITA", _centro_padrao(cfg, "RECEITA"))] += p.valor_venda or 0
        comp[("IMPOSTOS", _centro_padrao(cfg, "IMPOSTOS"))] += (p.valor_venda or 0) * emp.imposto_venda_pct / 100
    for m in db.scalars(select(MovimentoEstoque).where(
            MovimentoEstoque.empresa_id == emp.id, MovimentoEstoque.criado_em >= ini_dt, MovimentoEstoque.criado_em < fim_dt,
            MovimentoEstoque.origem.in_([OrigemMovimento.CONSUMO, OrigemMovimento.REFUGO]))):
        comp[("MATERIAL", _centro_padrao(cfg, "MATERIAL"))] += -m.quantidade * m.custo_unitario
    concluido_em = dict(db.execute(select(Projeto.id, Projeto.producao_concluida_em).where(Projeto.empresa_id == emp.id)).all())
    for l in db.scalars(select(Lancamento).where(Lancamento.empresa_id == emp.id, Lancamento.aprovacao != "RECUSADA")):
        conta = conta_de(l)
        if l.tipo == TipoLancamento.RECEBER and conta == "RECEITA":
            pass  # receita por competência vem da obra concluída
        elif l.tipo == TipoLancamento.PAGAR and conta == "MATERIAL":
            pass  # compra vira estoque; o custo entra no consumo
        elif l.tipo == TipoLancamento.PAGAR and conta == "IMPOSTOS" and l.projeto_id:
            pass  # imposto da obra já estimado pela alíquota
        else:
            if l.projeto_id and l.tipo == TipoLancamento.PAGAR:
                quando = concluido_em.get(l.projeto_id)
                no_mes = l.projeto_id in ids_mes if quando else False  # custo da obra em andamento espera a conclusão
            else:
                no_mes = inicio <= l.vencimento < fim
            if no_mes:
                sinal = 1 if l.tipo == TipoLancamento.PAGAR else -1  # receita financeira reduz a conta FINANCEIRO
                comp[(conta, centro(l, conta))] += sinal * l.valor
        # Caixa: o que foi baixado no mês
        if l.pago_em and inicio <= l.pago_em < fim:
            valor = l.valor_pago if l.valor_pago is not None else l.valor
            if l.tipo == TipoLancamento.RECEBER:
                caixa[(conta, centro(l, conta))] += valor if conta == "RECEITA" else -valor
            else:
                caixa[(conta, centro(l, conta))] += valor
    # Bancário: extrato sem conciliação no mês (entradas positivas reduzem a conta)
    for mv in db.scalars(select(MovimentoBancario).where(
            MovimentoBancario.empresa_id == emp.id, MovimentoBancario.data >= inicio, MovimentoBancario.data < fim,
            MovimentoBancario.lancamento_id.is_(None), MovimentoBancario.ignorado.is_(False))):
        caixa[("NAO_CONCILIADO", None)] += -mv.valor
    return {"COMPETENCIA": comp, "CAIXA": caixa}


def consolidar(db: Session, empresa_id: int, meses: int | None = None, origem: str = "MANUAL",
               usuario: str | None = None, hoje: date | None = None) -> ExecucaoConsolidacao | None:
    """Recalcula os meses recentes e guarda o DRE gerencial consolidado. Agendada: uma por dia."""
    hoje = hoje or date.today()
    emp = db.get(Empresa, empresa_id)
    cfg = config(db, empresa_id)
    n = max(1, min(meses or cfg.consolidacao_meses or 2, 24))
    chave = f"AGENDADA-{hoje.isoformat()}" if origem == "AGENDADA" else f"MANUAL-{datetime.now():%Y%m%d%H%M%S%f}"
    ex = ExecucaoConsolidacao(empresa_id=empresa_id, chave=chave, origem=origem, usuario=usuario)
    db.add(ex)
    try:
        db.flush()
    except IntegrityError:  # outra instância já rodou a consolidação agendada de hoje
        db.rollback()
        return None
    resumo = {"meses": [], "nao_conciliados": 0}
    for i in range(n):
        ano, mes = _soma_mes(hoje.year, hoje.month, -i)
        apurado = _apurar(db, emp, cfg, ano, mes)
        db.execute(delete(ConsolidacaoDRE).where(ConsolidacaoDRE.empresa_id == empresa_id, ConsolidacaoDRE.ano == ano,
                                                 ConsolidacaoDRE.mes == mes, ConsolidacaoDRE.fonte == "ERP"))
        for regime, valores in apurado.items():
            for (conta, centro_id), v in valores.items():
                if abs(v) >= 0.005:
                    db.add(ConsolidacaoDRE(empresa_id=empresa_id, ano=ano, mes=mes, regime=regime, centro_custo_id=centro_id,
                                           conta=conta, valor=round(v, 2), fonte="ERP"))
        receita = sum(v for (c, _), v in apurado["COMPETENCIA"].items() if c == "RECEITA")
        resumo["meses"].append({"mes": f"{ano}-{mes:02d}", "receita": round(receita, 2),
                                "contas": len(apurado["COMPETENCIA"]) + len(apurado["CAIXA"])})
    resumo["nao_conciliados"] = db.scalar(select(func.count()).select_from(MovimentoBancario).where(
        MovimentoBancario.empresa_id == empresa_id, MovimentoBancario.lancamento_id.is_(None),
        MovimentoBancario.ignorado.is_(False))) or 0
    resumo["aprovacoes_pendentes"] = db.scalar(select(func.count()).select_from(Lancamento).where(
        Lancamento.empresa_id == empresa_id, Lancamento.aprovacao == "PENDENTE")) or 0
    ex.status, ex.concluido_em, ex.resumo = "OK", datetime.now(), resumo
    db.flush()
    return ex


def importar_historico(db: Session, empresa_id: int, conteudo: str) -> dict:
    """CSV: mes (AAAA-MM); conta; valor; regime (opcional); centro (código, opcional). Substitui o histórico desses meses."""
    texto = conteudo.lstrip("﻿")
    sep = ";" if texto.split("\n", 1)[0].count(";") >= texto.split("\n", 1)[0].count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=sep)
    leitor.fieldnames = [c.strip().lower() for c in (leitor.fieldnames or [])]
    if not {"mes", "conta", "valor"} <= set(leitor.fieldnames):
        raise ErroControladoria("Cabeçalho do histórico: mes;conta;valor (regime e centro opcionais)")
    centros = {c.codigo: c.id for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == empresa_id))}
    linhas, meses = [], set()
    for n, ln in enumerate(leitor, start=2):
        try:
            ano, mes = (int(x) for x in (ln["mes"] or "").strip()[:7].split("-"))
            assert 1 <= mes <= 12
        except (ValueError, AssertionError):
            raise ErroControladoria(f"Linha {n}: mês '{ln.get('mes')}' (use AAAA-MM)")
        conta = (ln["conta"] or "").strip().upper()
        if conta not in NOMES:
            raise ErroControladoria(f"Linha {n}: conta '{conta}' não existe. Contas: {', '.join(NOMES)}")
        bruto = (ln["valor"] or "").strip().replace("R$", "").replace(" ", "")
        if "," in bruto:
            bruto = bruto.replace(".", "").replace(",", ".")
        try:
            valor = abs(float(bruto))
        except ValueError:
            raise ErroControladoria(f"Linha {n}: valor '{ln['valor']}'")
        regime = (ln.get("regime") or "COMPETENCIA").strip().upper()
        if regime not in REGIMES:
            raise ErroControladoria(f"Linha {n}: regime '{regime}' (COMPETENCIA ou CAIXA)")
        cc = (ln.get("centro") or "").strip().upper()
        if cc and cc not in centros:
            raise ErroControladoria(f"Linha {n}: centro de custo '{cc}' não cadastrado")
        linhas.append((ano, mes, regime, centros.get(cc), conta, valor))
        meses.add((ano, mes, regime))
    for ano, mes, regime in meses:
        db.execute(delete(ConsolidacaoDRE).where(ConsolidacaoDRE.empresa_id == empresa_id, ConsolidacaoDRE.ano == ano,
                                                 ConsolidacaoDRE.mes == mes, ConsolidacaoDRE.regime == regime,
                                                 ConsolidacaoDRE.fonte == "HISTORICO"))
    for ano, mes, regime, cc, conta, valor in linhas:
        db.add(ConsolidacaoDRE(empresa_id=empresa_id, ano=ano, mes=mes, regime=regime, centro_custo_id=cc, conta=conta,
                               valor=valor, fonte="HISTORICO"))
    db.flush()
    return {"linhas": len(linhas), "meses": sorted({f"{a}-{m:02d}" for a, m, _ in meses})}


# --- Relatórios --------------------------------------------------------------------------------------

def _realizado(db: Session, empresa_id: int, regime: str, meses: list[tuple[int, int]], centro_id: int | None = None):
    """{(ano, mes): {conta: valor}} com a fonte de cada mês (ERP ou histórico quando o ERP não tem o mês)."""
    q = select(ConsolidacaoDRE).where(ConsolidacaoDRE.empresa_id == empresa_id, ConsolidacaoDRE.regime == regime,
                                      ConsolidacaoDRE.ano >= min(a for a, _ in meses), ConsolidacaoDRE.ano <= max(a for a, _ in meses))
    if centro_id is not None:
        q = q.where(ConsolidacaoDRE.centro_custo_id == centro_id)
    por: dict[tuple, dict] = {(a, m): {"ERP": defaultdict(float), "HISTORICO": defaultdict(float)} for a, m in meses}
    for r in db.scalars(q):
        if (r.ano, r.mes) in por:
            por[(r.ano, r.mes)][r.fonte][r.conta] += r.valor
    saida = {}
    for k, fontes in por.items():
        fonte = "ERP" if fontes["ERP"] or not fontes["HISTORICO"] else "HISTORICO"
        saida[k] = (fonte, dict(fontes[fonte]))
    return saida


def _totais(v: dict) -> dict:
    receita = v.get("RECEITA", 0.0)
    variaveis = sum(v.get(c, 0.0) for c, _, g in CONTAS if g == "VARIAVEL")
    fixos = sum(v.get(c, 0.0) for c, _, g in CONTAS if g == "FIXO")
    mc = receita - variaveis
    ebitda = mc - fixos
    resultado = ebitda - v.get("FINANCEIRO", 0.0)
    return {"margem_contribuicao": round(mc, 2), "margem_pct": round(100 * mc / receita, 1) if receita else None,
            "ebitda": round(ebitda, 2), "resultado": round(resultado, 2),
            "resultado_pct": round(100 * resultado / receita, 1) if receita else None,
            "geracao_caixa": round(resultado - v.get("INVESTIMENTOS", 0.0) - v.get("NAO_CONCILIADO", 0.0), 2),
            "variaveis_pct": round(100 * variaveis / receita, 1) if receita else None}


def cenario_principal(db: Session, empresa_id: int) -> CenarioPlanejamento | None:
    return db.scalar(select(CenarioPlanejamento).where(CenarioPlanejamento.empresa_id == empresa_id,
                                                       CenarioPlanejamento.principal.is_(True)))


def previsto(db: Session, empresa_id: int, meses: list[tuple[int, int]], centro_id: int | None = None) -> dict:
    """Previsto do mês: verbas dos centros; receita, variáveis e fixos sem verba pelo cenário principal."""
    prev = {k: defaultdict(float) for k in meses}
    q = select(VerbaCentro).where(VerbaCentro.empresa_id == empresa_id)
    if centro_id is not None:
        q = q.where(VerbaCentro.centro_custo_id == centro_id)
    for v in db.scalars(q):
        if (v.ano, v.mes) in prev:
            prev[(v.ano, v.mes)][v.conta] += v.valor
    cen = cenario_principal(db, empresa_id) if centro_id is None else None
    if cen:
        r = markup.calcular(cen.premissas)
        va = r["premissas"]["variaveis"]
        for (a, m) in meses:
            fat = r["meses"][m - 1]["faturamento"]
            p = prev[(a, m)]
            p["RECEITA"] = p.get("RECEITA") or fat
            p["IMPOSTOS"] = p.get("IMPOSTOS") or fat * va["imposto_pct"] / 100
            p["MATERIAL"] = p.get("MATERIAL") or fat * va["dv_pct"] / 100
            p["COMISSOES"] = p.get("COMISSOES") or fat * (va["rt_pct"] + va["comissoes_pct"]) / 100
            # Fixos do cenário onde o mês não tem verba cadastrada
            p["PESSOAL"] = p.get("PESSOAL") or r["pessoal"]["folha_total"]
            if r["premissas"]["imovel"]["situacao"] != "PROPRIO":
                p["OCUPACAO"] = p.get("OCUPACAO") or r["imovel"]["valor_locacao"]
            p["ADMINISTRATIVAS"] = p.get("ADMINISTRATIVAS") or r["fixos"]["fixos"]
            p["COMERCIAL"] = p.get("COMERCIAL") or r["fixos"]["marketing"]
    return {k: dict(v) for k, v in prev.items()}


def dre_gerencial(db: Session, empresa_id: int, ano: int, regime: str = "COMPETENCIA", centro_id: int | None = None,
                  mes_de: int = 1, mes_ate: int = 12) -> dict:
    if regime not in REGIMES:
        raise ErroControladoria("Regime: COMPETENCIA ou CAIXA")
    meses = [(ano, m) for m in range(max(1, mes_de), min(12, mes_ate) + 1)]
    real = _realizado(db, empresa_id, regime, meses, centro_id)
    prev = previsto(db, empresa_id, meses, centro_id)
    colunas = []
    acum_r, acum_p = defaultdict(float), defaultdict(float)
    for k in meses:
        fonte, r = real[k]
        p = prev[k]
        for c, v in r.items():
            acum_r[c] += v
        if r:  # o acumulado compara o mesmo período: previsto só dos meses que já têm realizado
            for c, v in p.items():
                acum_p[c] += v
        colunas.append({"mes": f"{k[0]}-{k[1]:02d}", "fonte": fonte, "realizado": {c: round(v, 2) for c, v in r.items()},
                        "previsto": {c: round(v, 2) for c, v in p.items()}, "totais": _totais(r), "totais_previsto": _totais(p)})
    linhas = []
    for c, nome, grupo in CONTAS:
        if regime == "COMPETENCIA" and c == "NAO_CONCILIADO":
            continue
        rr, pp = acum_r.get(c, 0.0), acum_p.get(c, 0.0)
        linhas.append({"conta": c, "nome": nome, "grupo": grupo, "realizado": round(rr, 2), "previsto": round(pp, 2),
                       "variacao": round(rr - pp, 2), "variacao_pct": round(100 * (rr - pp) / pp, 1) if pp else None})
    return {"ano": ano, "regime": regime, "centro_custo_id": centro_id, "meses": colunas, "linhas": linhas,
            "totais": _totais(acum_r), "totais_previsto": _totais(acum_p)}


def relatorio_centros(db: Session, empresa_id: int, ano: int, mes_de: int, mes_ate: int, regime: str = "COMPETENCIA") -> list[dict]:
    meses = [(ano, m) for m in range(max(1, mes_de), min(12, mes_ate) + 1)]
    centros = list(db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == empresa_id).order_by(CentroCusto.codigo)))
    inicio, (a2, m2) = date(ano, meses[0][1], 1), _soma_mes(ano, meses[-1][1], 1)
    abertos = defaultdict(float)
    for l in db.scalars(select(Lancamento).where(Lancamento.empresa_id == empresa_id, Lancamento.tipo == TipoLancamento.PAGAR,
                                                 Lancamento.pago_em.is_(None), Lancamento.aprovacao != "RECUSADA",
                                                 Lancamento.vencimento >= inicio, Lancamento.vencimento < date(a2, m2, 1))):
        abertos[l.centro_custo_id] += l.valor
    saida = []
    for c in centros + [None]:
        cid = c.id if c else None
        real = _realizado(db, empresa_id, regime, meses, cid) if c else None
        if c is None:  # despesas sem centro de custo
            q = select(ConsolidacaoDRE).where(ConsolidacaoDRE.empresa_id == empresa_id, ConsolidacaoDRE.regime == regime,
                                              ConsolidacaoDRE.ano == ano, ConsolidacaoDRE.centro_custo_id.is_(None),
                                              ConsolidacaoDRE.fonte == "ERP")
            contas = defaultdict(float)
            for r in db.scalars(q):
                if (ano, r.mes) in meses:
                    contas[r.conta] += r.valor
        else:
            contas = defaultdict(float)
            for _, (_, r) in real.items():
                for k, v in r.items():
                    contas[k] += v
        despesa = sum(v for k, v in contas.items() if k in DESPESAS)
        verba = 0.0
        if c:
            verba = db.scalar(select(func.coalesce(func.sum(VerbaCentro.valor), 0.0)).where(
                VerbaCentro.empresa_id == empresa_id, VerbaCentro.centro_custo_id == cid, VerbaCentro.ano == ano,
                VerbaCentro.mes >= meses[0][1], VerbaCentro.mes <= meses[-1][1])) or 0.0
        # Competência já conta a despesa pelo vencimento (paga ou não); no caixa, soma o que está em aberto
        usado = despesa if regime == "COMPETENCIA" else despesa + abertos.get(cid, 0.0)
        if c is None and not despesa and not abertos.get(None):
            continue
        saida.append({"centro_custo_id": cid, "codigo": c.codigo if c else "—", "nome": c.nome if c else "Sem centro de custo",
                      "tipo": c.tipo if c else None, "responsavel": c.responsavel.nome if c and c.responsavel else None,
                      "verba": round(verba, 2), "realizado": round(despesa, 2), "em_aberto": round(abertos.get(cid, 0.0), 2),
                      "saldo": round(verba - usado, 2) if c else None,
                      "consumo_pct": round(100 * usado / verba, 1) if verba else None,
                      "por_conta": {k: round(v, 2) for k, v in sorted(contas.items()) if k in DESPESAS and abs(v) >= 0.005}})
    return saida


def historico_premissas(db: Session, empresa_id: int, meses: int = 6, hoje: date | None = None) -> dict:
    """Médias dos últimos meses consolidados, no formato das premissas, para mesclar com o cenário."""
    hoje = hoje or date.today()
    lista = [_soma_mes(hoje.year, hoje.month, -i) for i in range(1, meses + 1)]
    real = _realizado(db, empresa_id, "COMPETENCIA", lista)
    com_dados = [(k, r) for k, (f, r) in real.items() if r.get("RECEITA")]
    n = len(com_dados)
    if not n:
        return {"meses_com_dados": 0, "periodo": [f"{a}-{m:02d}" for a, m in reversed(lista)]}
    media = lambda c: sum(r.get(c, 0.0) for _, r in com_dados) / n  # noqa: E731
    receita = media("RECEITA")
    variaveis = media("MATERIAL") + media("FRETE_MONTAGEM")
    return {"meses_com_dados": n, "periodo": [f"{a}-{m:02d}" for a, m in reversed(lista)],
            "receita_media": round(receita, 2), "pessoal_medio": round(media("PESSOAL"), 2),
            "fixos_medio": round(media("OCUPACAO") + media("ADMINISTRATIVAS") + media("MANUTENCAO"), 2),
            "marketing_medio": round(media("COMERCIAL"), 2),
            "dv_pct": round(100 * variaveis / receita, 1), "comissoes_pct": round(100 * media("COMISSOES") / receita, 1),
            "imposto_pct": round(100 * media("IMPOSTOS") / receita, 1)}
