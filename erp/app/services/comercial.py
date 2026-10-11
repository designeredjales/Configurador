"""Comercial: funil (CRM leve), versões do XML do Promob, negociação dentro da política,
proposta ao cliente com aceite online, fechamento da venda e auditoria vendido × produção.

O orçamento nasce no Promob. Aqui o ERP aplica a política comercial do administrador,
mostra a margem real antes de vender e congela o que foi vendido para comparar com o
executivo que vai para a fábrica.
"""
import secrets
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..funcoes import efetivas
from ..models import (
    Categoria,
    ConfigComercial,
    Empresa,
    Lancamento,
    Oportunidade,
    Perfil,
    PrecoPromob,
    Projeto,
    TipoLancamento,
    Usuario,
    VersaoProposta,
)
from .promob_xml import ProjetoXML

ETAPAS_PADRAO = ["Contato", "Briefing", "Projeto", "Apresentação", "Negociação"]
CONDICOES_PADRAO = [
    {"nome": "À vista", "parcelas": 1, "ajuste_pct": -5.0},
    {"nome": "Entrada + 3x", "parcelas": 4, "ajuste_pct": 0.0},
    {"nome": "6x sem juros", "parcelas": 6, "ajuste_pct": 0.0},
    {"nome": "10x", "parcelas": 10, "ajuste_pct": 4.0},
]


class ErroComercial(ValueError):
    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.status = status


def config(db: Session, empresa_id: int) -> ConfigComercial:
    cfg = db.get(ConfigComercial, empresa_id)
    if cfg is None:
        cfg = ConfigComercial(empresa_id=empresa_id, etapas=list(ETAPAS_PADRAO),
                              condicoes=[dict(c) for c in CONDICOES_PADRAO])
        db.add(cfg)
        db.flush()
    return cfg


# --- Resumo do projeto (XML vendido ou árvore atual) -------------------------------

def _r(v, n=2):
    return round(v or 0.0, n)


def resumo_xml(lido: ProjetoXML) -> dict:
    ambientes, modulos, m2_total, pecas_total, mod_total = [], [], 0.0, 0, 0
    for nome, mods in lido.ambientes.items():
        m2_amb, pecas_amb, mods_amb = 0.0, 0, 0
        for m in mods:
            q = m.quantidade or 1
            mods_amb += q
            modulos.append({"ambiente": nome, "codigo": m.codigo, "descricao": m.descricao, "quantidade": q})
            for p in m.pecas:
                n = (p.quantidade or 1) * q
                pecas_amb += n
                m2_amb += p.comprimento_mm * p.largura_mm / 1e6 * n
        ambientes.append({"nome": nome, "modulos": mods_amb, "pecas": int(pecas_amb), "m2": _r(m2_amb, 3)})
        m2_total, pecas_total, mod_total = m2_total + m2_amb, pecas_total + pecas_amb, mod_total + mods_amb
    c = lido.comercial
    return {"cliente": lido.cliente, "ambientes": ambientes, "modulos": modulos, "total_modulos": mod_total,
            "total_pecas": int(pecas_total), "m2_chapa": _r(m2_total, 3), "valor_tabela": _r(c.valor_tabela),
            "valor_pedido": _r(c.valor_pedido), "valor_venda": _r(c.valor_venda), "frete": _r(c.frete),
            "montagem": _r(c.montagem), "condicao_promob": c.condicao}


def resumo_projeto(projeto: Projeto) -> dict:
    modulos, m2, pecas, total_mod = [], 0.0, 0, 0
    for a in projeto.ambientes:
        for m in a.modulos:
            q = m.quantidade or 1
            total_mod += q
            modulos.append({"ambiente": a.nome, "codigo": m.codigo, "descricao": m.descricao, "quantidade": q})
            for p in m.pecas:
                n = (p.quantidade or 1) * q
                pecas += n
                m2 += p.comprimento_mm * p.largura_mm / 1e6 * n
    return {"modulos": modulos, "total_modulos": total_mod, "total_pecas": int(pecas), "m2_chapa": _r(m2, 3),
            "valor_pedido": _r(projeto.valor_pedido), "valor_tabela": _r(projeto.valor_tabela)}


# --- Negociação -----------------------------------------------------------------------

def _condicao(cfg: ConfigComercial, nome: str | None) -> dict:
    condicoes = cfg.condicoes or CONDICOES_PADRAO
    if nome is None:
        return condicoes[0]
    c = next((c for c in condicoes if c["nome"] == nome), None)
    if c is None:
        raise ErroComercial(f"Condição de pagamento '{nome}' não existe na política comercial", 422)
    return c


def conferencia_prices(db: Session, empresa_id: int, resumo: dict) -> dict | None:
    """Reprecifica os módulos do XML pela tabela vigente do Promob Prices (quando sincronizada).

    Os produtos do configurador têm preço próprio (custo × markup ou tabela do produto) e ficam fora da conferência.
    """
    resumo = {**resumo, "modulos": [m for m in resumo["modulos"] if m.get("origem") != "CONFIGURADOR"]}
    if not resumo["modulos"]:
        return None
    skus = {m["codigo"] for m in resumo["modulos"]}
    precos = dict(db.execute(select(PrecoPromob.sku, PrecoPromob.preco).where(
        PrecoPromob.empresa_id == empresa_id, PrecoPromob.sku.in_(skus))).all()) if skus else {}
    if not db.scalar(select(func.count()).select_from(PrecoPromob).where(PrecoPromob.empresa_id == empresa_id)):
        return None
    cobertos = [m for m in resumo["modulos"] if m["codigo"] in precos]
    valor = sum(precos[m["codigo"]] * m["quantidade"] for m in cobertos)
    base = resumo.get("valor_tabela") or 0
    return {"modulos_encontrados": len(cobertos), "modulos_total": len(resumo["modulos"]),
            "valor_tabela_prices": _r(valor), "faltando": sorted({m["codigo"] for m in resumo["modulos"]} - set(precos))[:30],
            "diferenca_pct": _r((valor - base) / base * 100, 1) if base and len(cobertos) == len(resumo["modulos"]) else None}


def limite_desconto(usuario: Usuario, cfg: ConfigComercial) -> float:
    if usuario.perfil == Perfil.ADMIN:
        return 100.0
    return cfg.desconto_max_gerente if "aprovar_venda" in efetivas(usuario) else cfg.desconto_max_vendedor


def calcular(db: Session, emp: Empresa, cfg: ConfigComercial, op: Oportunidade, versao: VersaoProposta,
             desconto: float, condicao: str | None) -> dict:
    if desconto < 0 or desconto > 100:
        raise ErroComercial("Desconto deve ficar entre 0% e 100%", 422)
    r, cond = versao.resumo, _condicao(cfg, condicao)
    base = r["valor_venda"] or r["valor_tabela"]
    if not base:
        raise ErroComercial("O XML não traz valor de venda (TOTALPRICES/BUDGET). Exporte o orçamento com preços no Promob", 422)
    preco = _r(base * (1 - desconto / 100) * (1 + cond["ajuste_pct"] / 100))
    impostos = _r(preco * emp.imposto_venda_pct / 100)
    rt_pct = op.parceiro.rt_pct if op.parceiro else 0.0
    rt = _r(preco * rt_pct / 100)
    comissao = _r(preco * cfg.comissao_vendedor_pct / 100) if op.vendedor_id else 0.0
    mao_de_obra = _r(r.get("mao_de_obra") or 0)  # tempo padrão dos setores × custo-hora (setup da base)
    custo = _r(r["valor_pedido"] + r["frete"] + r["montagem"] + mao_de_obra)
    margem = _r(preco - impostos - rt - comissao - custo)
    margem_pct = _r(margem / preco * 100, 1) if preco else 0.0
    nivel = None
    motivos = []
    if desconto > cfg.desconto_max_gerente:
        nivel = "ADMIN"
        motivos.append(f"desconto de {_g(desconto)}% acima do limite do gerente ({_g(cfg.desconto_max_gerente)}%)")
    elif desconto > cfg.desconto_max_vendedor:
        nivel = "GERENTE"
        motivos.append(f"desconto de {_g(desconto)}% acima do limite do vendedor ({_g(cfg.desconto_max_vendedor)}%)")
    if margem_pct < cfg.margem_minima:
        nivel = nivel or "GERENTE"
        motivos.append(f"margem de {_g(margem_pct)}% abaixo do mínimo de {_g(cfg.margem_minima)}%")
    m2 = r["m2_chapa"] or 0
    origem = ("MISTO" if r.get("promob") else "CONFIGURADOR") if r.get("configurados") else "PROMOB"
    return {"origem": origem, "preco_base": _r(base), "desconto_pct": desconto, "condicao": cond["nome"], "parcelas": cond["parcelas"],
            "ajuste_pct": cond["ajuste_pct"], "preco_final": preco, "parcela_valor": _r(preco / cond["parcelas"]),
            "impostos": impostos, "rt_pct": rt_pct, "rt": rt, "comissao_vendedor": comissao, "custo_producao": custo, "mao_de_obra": mao_de_obra,
            "margem": margem, "margem_pct": margem_pct, "preco_m2": _r(preco / m2) if m2 else None,
            "custo_m2": _r(custo / m2) if m2 else None, "nivel_exigido": nivel, "motivos": motivos,
            "prices": conferencia_prices(db, emp.id, r)}


def _atende(usuario: Usuario, nivel: str | None) -> bool:
    if nivel is None or usuario.perfil == Perfil.ADMIN:
        return True
    return nivel == "GERENTE" and "aprovar_venda" in efetivas(usuario)


def negociar(db: Session, emp: Empresa, usuario: Usuario, versao: VersaoProposta, desconto: float,
             condicao: str | None) -> VersaoProposta:
    op = versao.oportunidade
    if op.status != "ABERTA":
        raise ErroComercial(f"Oportunidade {op.numero} está {op.status}")
    if versao.aceite_em:
        raise ErroComercial("Proposta já aceita pelo cliente: crie uma nova versão para renegociar")
    cfg = config(db, emp.id)
    calc = calcular(db, emp, cfg, op, versao, desconto, condicao)
    versao.desconto_pct, versao.condicao, versao.calculo = desconto, calc["condicao"], calc
    versao.token_publico = versao.proposta_validade = None  # mudou o preço: proposta anterior deixa de valer
    if calc["nivel_exigido"] is None:
        versao.aprovacao, versao.aprovado_por, versao.aprovacao_motivo = "LIVRE", None, None
    elif _atende(usuario, calc["nivel_exigido"]):
        versao.aprovacao, versao.aprovado_por = "APROVADA", usuario.nome
        versao.aprovacao_motivo = "; ".join(calc["motivos"])
    else:
        versao.aprovacao, versao.aprovado_por = "PENDENTE", None
        versao.aprovacao_motivo = "; ".join(calc["motivos"])
    db.flush()
    return versao


def decidir(db: Session, usuario: Usuario, versao: VersaoProposta, aprovar: bool, observacao: str | None) -> VersaoProposta:
    if versao.aprovacao != "PENDENTE":
        raise ErroComercial(f"Esta versão não está aguardando aprovação ({versao.aprovacao})")
    nivel = (versao.calculo or {}).get("nivel_exigido")
    if not _atende(usuario, nivel):
        alcada = "o administrador" if nivel == "ADMIN" else "quem aprova vendas"
        raise ErroComercial(f"Este desconto precisa de {alcada}", 403)
    versao.aprovacao = "APROVADA" if aprovar else "RECUSADA"
    versao.aprovado_por = usuario.nome
    if observacao:
        versao.aprovacao_motivo = f"{versao.aprovacao_motivo or ''} · {usuario.nome}: {observacao.strip()[:150]}".strip(" ·")
    db.flush()
    return versao


# --- Proposta ao cliente -------------------------------------------------------------

def gerar_proposta(db: Session, cfg: ConfigComercial, versao: VersaoProposta) -> VersaoProposta:
    if not versao.calculo:
        raise ErroComercial("Negocie a versão (desconto e condição) antes de gerar a proposta", 422)
    if versao.aprovacao not in ("LIVRE", "APROVADA"):
        raise ErroComercial("A negociação precisa de aprovação antes de virar proposta"
                            if versao.aprovacao == "PENDENTE" else "Negociação recusada: ajuste o desconto ou a condição")
    if not versao.token_publico:
        versao.token_publico = secrets.token_urlsafe(18)
    versao.proposta_validade = date.today() + timedelta(days=cfg.validade_proposta_dias)
    db.flush()
    return versao


def aceitar(db: Session, versao: VersaoProposta, nome: str, ip: str | None) -> VersaoProposta:
    if versao.aceite_em:
        raise ErroComercial("Esta proposta já foi aceita")
    if versao.oportunidade.status != "ABERTA":
        raise ErroComercial("Esta proposta não está mais disponível")
    if versao.proposta_validade and versao.proposta_validade < date.today():
        raise ErroComercial("Proposta vencida: peça uma proposta atualizada ao seu consultor")
    if len((nome or "").strip()) < 3:
        raise ErroComercial("Informe seu nome completo para registrar o aceite", 422)
    versao.aceite_em, versao.aceite_nome, versao.aceite_ip = datetime.now(), nome.strip()[:160], ip
    db.flush()
    return versao


# --- Fechamento da venda --------------------------------------------------------------

def fechar(db: Session, emp: Empresa, usuario: Usuario, op: Oportunidade, versao: VersaoProposta,
           primeiro_vencimento: date, data_entrega: date | None) -> Projeto:
    from ..routers.projetos import _proximo_codigo  # numeração única dos projetos
    from .financeiro import registrar_contrato
    from .importacao import importar_promob_xml

    if op.status != "ABERTA":
        raise ErroComercial(f"Oportunidade {op.numero} já está {op.status}")
    if versao.oportunidade_id != op.id:
        raise ErroComercial("Versão de outra oportunidade", 422)
    if not versao.calculo:
        raise ErroComercial("Negocie a versão antes de fechar", 422)
    if versao.aprovacao not in ("LIVRE", "APROVADA"):
        raise ErroComercial("A negociação desta versão não está aprovada")
    calc = versao.calculo
    projeto = Projeto(empresa_id=emp.id, codigo=_proximo_codigo(db, emp.id), nome=f"{op.cliente_nome} · {op.titulo}",
                      data_entrega=data_entrega, oportunidade_id=op.id)
    db.add(projeto)
    db.flush()
    if versao.xml:
        importar_promob_xml(db, projeto, versao.xml.encode("utf-8"))
    else:
        projeto.origem = "CONFIGURADOR"
        projeto.valor_tabela = projeto.valor_pedido = projeto.valor_venda = 0.0
    if versao.itens_config:  # produtos do configurador: módulos congelados na venda
        from . import configurador
        configurador.gerar_modulos(db, projeto, versao.itens_config)
        conf = (versao.resumo or {}).get("configurados") or {}
        projeto.valor_tabela = round((projeto.valor_tabela or 0) + conf.get("valor", 0), 2)
        projeto.valor_pedido = round((projeto.valor_pedido or 0) + conf.get("custo_material", 0), 2)
        projeto.valor_venda = round((projeto.valor_venda or 0) + conf.get("valor", 0), 2)
    projeto.nome = f"{op.cliente_nome} · {op.titulo}"
    parcelas = registrar_contrato(db, projeto, calc["preco_final"], calc["parcelas"], primeiro_vencimento, usuario.id)
    projeto.venda_resumo = {**versao.resumo, "versao": versao.numero, "preco_final": calc["preco_final"],
                            "desconto_pct": calc["desconto_pct"], "condicao": calc["condicao"],
                            "margem_pct": calc["margem_pct"], "fechado_em": date.today().isoformat(),
                            "aceite": versao.aceite_nome}
    # Comissões pagas conforme o cliente paga: uma conta a pagar por parcela recebida
    cfg = config(db, emp.id)
    regras = []
    if op.parceiro and op.parceiro.rt_pct:
        regras.append((f"RT {op.parceiro.nome}", op.parceiro.rt_pct))
    if op.vendedor and cfg.comissao_vendedor_pct:
        regras.append((f"Comissão {op.vendedor.nome}", cfg.comissao_vendedor_pct))
    for rotulo, pct in regras:
        for i, p in enumerate(parcelas, start=1):
            db.add(Lancamento(empresa_id=emp.id, tipo=TipoLancamento.PAGAR, categoria=Categoria.COMISSAO,
                              descricao=f"{rotulo} · {projeto.codigo} parcela {i}/{len(parcelas)}",
                              valor=_r(p.valor * pct / 100), vencimento=p.vencimento, projeto_id=projeto.id,
                              usuario_id=usuario.id))
    op.status, op.projeto_id, op.fechado_em, op.etapa = "GANHA", projeto.id, datetime.now(), "Fechado"
    db.flush()
    return projeto


def numero_oportunidade(db: Session, empresa_id: int) -> int:
    return (db.scalar(select(func.max(Oportunidade.numero)).where(Oportunidade.empresa_id == empresa_id)) or 0) + 1


# --- Auditoria: projeto vendido × executivo de produção -------------------------------

def _g(v: float) -> str:
    """Número no formato brasileiro para mensagens (5,9 em vez de 5.9)."""
    return f"{v:g}".replace(".", ",")


def _pct(atual: float, vendido: float) -> float | None:
    return _r((atual - vendido) / vendido * 100, 1) if vendido else None


def auditoria(db: Session, projeto: Projeto) -> dict | None:
    v = projeto.venda_resumo
    if not v:
        return None
    a = resumo_projeto(projeto)
    cfg = config(db, projeto.empresa_id)
    def contar(mods: list[dict]) -> Counter:  # módulos repetidos (3 frentes iguais) somam
        c = Counter()
        for m in mods:
            c[(m["ambiente"], m["codigo"], m["descricao"])] += m["quantidade"]
        return c
    cv, ca = contar(v["modulos"]), contar(a["modulos"])
    acrescentados = [{"ambiente": k[0], "codigo": k[1], "descricao": k[2], "quantidade": q} for k, q in (ca - cv).items()]
    retirados = [{"ambiente": k[0], "codigo": k[1], "descricao": k[2], "quantidade": q} for k, q in (cv - ca).items()]
    d_m2, d_pedido = _pct(a["m2_chapa"], v["m2_chapa"]), _pct(a["valor_pedido"], v["valor_pedido"])
    divergencia = max(abs(d_m2 or 0), abs(d_pedido or 0))
    preco = v["preco_final"]
    return {
        "vendido": {"versao": v.get("versao"), "fechado_em": v.get("fechado_em"), "preco_final": preco,
                    "desconto_pct": v.get("desconto_pct"), "condicao": v.get("condicao"), "margem_pct": v.get("margem_pct"),
                    "modulos": v["total_modulos"], "pecas": v["total_pecas"], "m2": v["m2_chapa"], "valor_pedido": v["valor_pedido"],
                    "preco_m2": _r(preco / v["m2_chapa"]) if v["m2_chapa"] else None},
        "producao": {"modulos": a["total_modulos"], "pecas": a["total_pecas"], "m2": a["m2_chapa"], "valor_pedido": a["valor_pedido"],
                     "custo_m2": _r(a["valor_pedido"] / a["m2_chapa"]) if a["m2_chapa"] else None,
                     "venda_por_m2_produzido": _r(preco / a["m2_chapa"]) if a["m2_chapa"] else None},
        "diferencas": {"modulos": a["total_modulos"] - v["total_modulos"], "pecas": a["total_pecas"] - v["total_pecas"],
                       "m2": _r(a["m2_chapa"] - v["m2_chapa"], 3), "m2_pct": d_m2, "valor_pedido": _r(a["valor_pedido"] - v["valor_pedido"]),
                       "valor_pedido_pct": d_pedido},
        "modulos_acrescentados": acrescentados, "modulos_retirados": retirados,
        "divergencia_pct": divergencia, "limite_pct": cfg.limite_divergencia_pct,
        "exige_ciencia": divergencia > cfg.limite_divergencia_pct and not projeto.auditoria_ciente_em,
        "ciente_por": projeto.auditoria_ciente_por, "ciente_em": projeto.auditoria_ciente_em,
    }


def pendencia_auditoria(db: Session, projeto: Projeto) -> str | None:
    r = auditoria(db, projeto)
    if r and r["exige_ciencia"]:
        return (f"Executivo diverge {_g(r['divergencia_pct'])}% do projeto vendido (limite {_g(r['limite_pct'])}%): "
                f"quem aprova vendas precisa registrar ciência na auditoria da venda")
    return None
