"""Setup da base: toda a parametrização de uma fábrica num arquivo JSON.

O consultor monta o setup uma vez (ou parte de um modelo pronto), personaliza para cada base e aplica:
parâmetros da fábrica, setores e roteiro, separação de peças, política comercial, integração com o
Promob Prices, parceiros e metas da gestão à vista. Tokens e senhas nunca entram no arquivo.

Aplicar é idempotente: setores, separações e parceiros são casados pelo código (ou nome) e atualizados;
nada é apagado, porque peças e ordens já produzidas apontam para eles.
"""
import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CenarioPlanejamento,
    CentroCusto,
    CentroTrabalho,
    ClasseSeparacao,
    Empresa,
    Material,
    Parceiro,
    RegraCentro,
)
from . import comercial, controladoria, depara, gestao, markup, promob_prices, separacao

FORMATO = "erp-moveleiro-setup"
VERSAO = 1
PASTA_MODELOS = Path(__file__).resolve().parent.parent / "setups"
SECOES = {
    "fabrica": "Parâmetros da fábrica (perdas, chapa, serra, imposto, garantia, caixa master, materiais do Promob)",
    "fiscal": "Padrões fiscais (NCM, CFOP, CSOSN)",
    "setores": "Setores, roteiro, capacidade, tempos padrão e custo-hora",
    "separacoes": "Separação de peças (tupia, tamburato...)",
    "comercial": "Política comercial e integração Promob Prices (sem token)",
    "parceiros": "Parceiros e RT",
    "gestao": "Metas, WIP do kanban, calendário, tambor e pulmão",
    "depara": "De-para Promob → estoque (casado pelo código do material nesta base)",
    "controladoria": "Centros de custo, regras de aprovação, agenda de consolidação e cenário de planejamento",
}
CAMPOS_SETOR = ["pessoas", "horas_dia", "eficiencia_pct", "custo_mensal", "minutos_peca", "minutos_m2"]
CAMPOS_FABRICA = ["perda_chapa_pct", "perda_fita_pct", "chapa_comprimento_mm", "chapa_largura_mm", "serra_mm",
                  "refilo_mm", "imposto_venda_pct", "garantia_meses", "caixa_max_modulos", "promob_cria_materiais"]
CAMPOS_FISCAL = ["ncm_padrao", "cfop_interno", "cfop_interestadual", "csosn_padrao"]
CAMPOS_COMERCIAL = ["desconto_max_vendedor", "desconto_max_gerente", "margem_minima", "comissao_vendedor_pct",
                    "limite_divergencia_pct", "validade_proposta_dias", "etapas", "condicoes", "prices_url",
                    "prices_tabela_preferida", "prices_colunas"]


class ErroSetup(ValueError):
    status = 422


class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Fabrica(_M):
    perda_chapa_pct: float | None = Field(None, ge=0, le=100)
    perda_fita_pct: float | None = Field(None, ge=0, le=100)
    chapa_comprimento_mm: float | None = Field(None, gt=0)
    chapa_largura_mm: float | None = Field(None, gt=0)
    serra_mm: float | None = Field(None, ge=0, le=20)
    refilo_mm: float | None = Field(None, ge=0, le=100)
    imposto_venda_pct: float | None = Field(None, ge=0, le=60)
    garantia_meses: int | None = Field(None, ge=0, le=120)
    caixa_max_modulos: int | None = Field(None, ge=1, le=50)
    promob_cria_materiais: bool | None = None


class Fiscal(_M):
    ncm_padrao: str | None = Field(None, pattern=r"^\d{8}$")
    cfop_interno: str | None = Field(None, pattern=r"^\d{4}$")
    cfop_interestadual: str | None = Field(None, pattern=r"^\d{4}$")
    csosn_padrao: str | None = Field(None, pattern=r"^\d{3}$")


class Setor(_M):
    codigo: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    nome: str = Field(min_length=2, max_length=100)
    sequencia: int
    regra: RegraCentro = RegraCentro.TODAS
    ativo: bool = True
    exige_apontamento: bool = True
    pessoas: float | None = Field(None, ge=0, le=500)
    horas_dia: float | None = Field(None, ge=0, le=24)
    eficiencia_pct: float | None = Field(None, gt=0, le=150)
    custo_mensal: float | None = Field(None, ge=0)
    minutos_peca: float | None = Field(None, ge=0, le=600)
    minutos_m2: float | None = Field(None, ge=0, le=600)


class Separacao(_M):
    codigo: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_]+$")
    nome: str = Field(min_length=2, max_length=60)
    palavras_chave: str = Field("", max_length=400)
    centro_codigo: str | None = Field(None, max_length=20)
    vai_para_caixa: bool = True
    ativo: bool = True


class Condicao(_M):
    nome: str = Field(min_length=1, max_length=60)
    parcelas: int = Field(ge=1, le=60)
    ajuste_pct: float = Field(ge=-50, le=50)


class Comercial(_M):
    desconto_max_vendedor: float | None = Field(None, ge=0, le=100)
    desconto_max_gerente: float | None = Field(None, ge=0, le=100)
    margem_minima: float | None = Field(None, ge=-100, le=100)
    comissao_vendedor_pct: float | None = Field(None, ge=0, le=50)
    limite_divergencia_pct: float | None = Field(None, ge=0, le=100)
    validade_proposta_dias: int | None = Field(None, ge=1, le=180)
    etapas: list[str] | None = None
    condicoes: list[Condicao] | None = None
    prices_url: str | None = Field(None, max_length=300)
    prices_tabela_preferida: str | None = Field(None, max_length=200)
    prices_colunas: dict[str, str] | None = None


class ParceiroSetup(_M):
    nome: str = Field(min_length=2, max_length=160)
    tipo: str = Field("ARQUITETO", max_length=20)
    documento: str | None = Field(None, max_length=20)
    telefone: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=160)
    rt_pct: float = Field(0.0, ge=0, le=30)
    ativo: bool = True


class Gestao(_M):
    metas: dict[str, float | None] | None = None
    limites_wip: dict[str, int | None] | None = None
    dias_uteis_mes: int | None = Field(None, ge=1, le=31)
    horas_turno: float | None = Field(None, gt=0, le=24)
    pulmao_dias: float | None = Field(None, ge=0, le=60)
    tambor_codigo: str | None = Field(None, max_length=20)


class DeParaSetup(_M):
    codigo_promob: str = Field(min_length=1, max_length=60)
    material_codigo: str = Field(min_length=1, max_length=60)
    fator: float = Field(1.0, gt=0, le=100000)
    observacao: str | None = Field(None, max_length=200)


class CentroCustoSetup(_M):
    codigo: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_.-]+$")
    nome: str = Field(min_length=2, max_length=100)
    tipo: str = Field("ADMINISTRATIVO", pattern=r"^(PRODUTIVO|ADMINISTRATIVO|COMERCIAL|ESTRUTURA)$")
    setor_codigo: str | None = Field(None, max_length=20)
    ativo: bool = True


class Controladoria(_M):
    centros_custo: list[CentroCustoSetup] | None = None
    alcada_valor: float | None = Field(None, ge=0)
    exige_centro: bool | None = None
    bloqueia_sem_verba: bool | None = None
    centros_padrao: dict[str, str] | None = None  # {conta: código do centro}
    consolidacao_ativa: bool | None = None
    consolidacao_hora: int | None = Field(None, ge=0, le=23)
    consolidacao_meses: int | None = Field(None, ge=1, le=24)
    cenario: dict | None = None  # {"nome", "premissas"} vira o cenário principal


class Setup(_M):
    formato: str = FORMATO
    versao: int = VERSAO
    nome: str | None = None
    descricao: str | None = None
    fabrica: Fabrica | None = None
    fiscal: Fiscal | None = None
    setores: list[Setor] | None = None
    separacoes: list[Separacao] | None = None
    comercial: Comercial | None = None
    parceiros: list[ParceiroSetup] | None = None
    gestao: Gestao | None = None
    depara: list[DeParaSetup] | None = None
    controladoria: Controladoria | None = None


def validar(dados: dict) -> Setup:
    if not isinstance(dados, dict) or dados.get("formato") != FORMATO:
        raise ErroSetup("Arquivo não é um setup do ERP Moveleiro (campo 'formato' ausente ou diferente)")
    if (dados.get("versao") or 0) > VERSAO:
        raise ErroSetup(f"Setup na versão {dados.get('versao')}: atualize o ERP para aplicá-lo")
    try:
        return Setup.model_validate(dados)
    except ValidationError as e:
        erros = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:8])
        raise ErroSetup(f"Setup com campos inválidos: {erros}")


# --- Exportar -----------------------------------------------------------------------------------

def exportar(db: Session, emp: Empresa, nome: str | None = None) -> dict:
    cc = comercial.config(db, emp.id)
    cg = gestao.config(db, emp.id)
    centros = db.scalars(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id).order_by(CentroTrabalho.sequencia))
    parceiros = db.scalars(select(Parceiro).where(Parceiro.empresa_id == emp.id).order_by(Parceiro.nome))
    return {
        "formato": FORMATO, "versao": VERSAO, "nome": nome or f"Setup {emp.nome}",
        "descricao": f"Exportado de {emp.nome} em {datetime.now():%d/%m/%Y %H:%M}",
        "fabrica": {k: getattr(emp, k) for k in CAMPOS_FABRICA},
        "fiscal": {k: getattr(emp, k) for k in CAMPOS_FISCAL},
        "setores": [{"codigo": c.codigo, "nome": c.nome, "sequencia": c.sequencia, "regra": RegraCentro(c.regra).value,
                     "ativo": c.ativo, "exige_apontamento": c.exige_apontamento} | {k: getattr(c, k) for k in CAMPOS_SETOR}
                    for c in centros],
        "separacoes": [{"codigo": c.codigo, "nome": c.nome, "palavras_chave": c.palavras_chave, "centro_codigo": c.centro_codigo,
                        "vai_para_caixa": c.vai_para_caixa, "ativo": c.ativo} for c in separacao.garantir_padroes(db, emp.id)],
        "comercial": {k: getattr(cc, k) for k in CAMPOS_COMERCIAL} | {
            "etapas": cc.etapas or comercial.ETAPAS_PADRAO, "condicoes": cc.condicoes or comercial.CONDICOES_PADRAO},
        "parceiros": [{k: getattr(p, k) for k in ("nome", "tipo", "documento", "telefone", "email", "rt_pct", "ativo")}
                      for p in parceiros],
        "gestao": {"metas": cg.metas or {}, "limites_wip": cg.limites_wip or {}, "dias_uteis_mes": cg.dias_uteis_mes,
                   "horas_turno": cg.horas_turno, "pulmao_dias": cg.pulmao_dias, "tambor_codigo": cg.tambor_codigo},
        "controladoria": _exportar_controladoria(db, emp.id),
        "depara": [{"codigo_promob": d.codigo_promob, "material_codigo": d.material.codigo, "fator": d.fator,
                    "observacao": d.observacao} for d in sorted(depara.mapa(db, emp.id).values(), key=lambda d: d.codigo_promob)],
    }


def _exportar_controladoria(db: Session, empresa_id: int) -> dict:
    cf = controladoria.config(db, empresa_id)
    centros = list(db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == empresa_id).order_by(CentroCusto.codigo)))
    por_id = {c.id: c.codigo for c in centros}
    cen = controladoria.cenario_principal(db, empresa_id)
    return {"centros_custo": [{"codigo": c.codigo, "nome": c.nome, "tipo": c.tipo, "setor_codigo": c.setor_codigo, "ativo": c.ativo}
                              for c in centros],
            "alcada_valor": cf.alcada_valor, "exige_centro": cf.exige_centro, "bloqueia_sem_verba": cf.bloqueia_sem_verba,
            "centros_padrao": {k: por_id[v] for k, v in (cf.centros_padrao or {}).items() if v in por_id},
            "consolidacao_ativa": cf.consolidacao_ativa, "consolidacao_hora": cf.consolidacao_hora,
            "consolidacao_meses": cf.consolidacao_meses,
            "cenario": {"nome": cen.nome, "premissas": cen.premissas} if cen else None}


# --- Aplicar ------------------------------------------------------------------------------------

def _fmt(v) -> str:
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False)[:80]
    return "—" if v is None else str(v)


def _campos(obj, novos: dict, rotulo: str, mudancas: list, secao: str) -> None:
    for k, v in novos.items():
        if v is None:
            continue
        atual = getattr(obj, k)
        if atual != v:
            mudancas.append({"secao": secao, "texto": f"{rotulo}{k}: {_fmt(atual)} → {_fmt(v)}"})
            setattr(obj, k, v)


def aplicar(db: Session, emp: Empresa, s: Setup, secoes: list[str] | None = None) -> list[dict]:
    """Aplica as seções pedidas na sessão e devolve o que mudou. Quem chama decide entre commit e rollback."""
    escolhidas = [x for x in (secoes or SECOES) if x in SECOES and getattr(s, x) is not None]
    mud: list[dict] = []
    if "fabrica" in escolhidas:
        _campos(emp, s.fabrica.model_dump(), "", mud, "fabrica")
    if "fiscal" in escolhidas:
        _campos(emp, s.fiscal.model_dump(), "", mud, "fiscal")
    if "setores" in escolhidas:
        codigos = [x.codigo.upper() for x in s.setores]
        if len(set(codigos)) != len(codigos):
            raise ErroSetup("Setup com setor repetido")
        existentes = {c.codigo: c for c in db.scalars(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id))}
        for st in s.setores:
            dados = st.model_dump(mode="json") | {"codigo": st.codigo.upper()}
            c = existentes.get(dados["codigo"])
            if c is None:
                db.add(CentroTrabalho(empresa_id=emp.id, **{k: v for k, v in dados.items() if v is not None}))
                mud.append({"secao": "setores", "texto": f"Novo setor {dados['codigo']} · {st.nome} (seq. {st.sequencia}, {st.regra.value})"})
            else:
                _campos(c, {k: v for k, v in dados.items() if k != "codigo"}, f"Setor {c.codigo} · ", mud, "setores")
        for cod in sorted(set(existentes) - set(codigos)):
            mud.append({"secao": "setores", "texto": f"Setor {cod} não está no setup: mantido como está"})
        db.flush()
    if "separacoes" in escolhidas:
        setores_ok = {c.codigo for c in db.scalars(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id))}
        existentes = {c.codigo: c for c in separacao.garantir_padroes(db, emp.id)}
        for sp in s.separacoes:
            dados = sp.model_dump() | {"codigo": sp.codigo.upper(),
                                       "centro_codigo": sp.centro_codigo.upper() if sp.centro_codigo else None}
            if dados["centro_codigo"] and dados["centro_codigo"] not in setores_ok:
                raise ErroSetup(f"Separação {dados['codigo']} aponta para o setor {dados['centro_codigo']}, que não existe nesta base")
            c = existentes.get(dados["codigo"])
            if c is None:
                db.add(ClasseSeparacao(empresa_id=emp.id, **dados))
                mud.append({"secao": "separacoes", "texto": f"Nova separação {dados['codigo']} · {sp.nome}"})
            else:
                _campos(c, {k: v for k, v in dados.items() if k != "codigo"} | {"centro_codigo": dados["centro_codigo"]},
                        f"Separação {c.codigo} · ", mud, "separacoes")
                if c.centro_codigo != dados["centro_codigo"]:
                    c.centro_codigo = dados["centro_codigo"]
        db.flush()
    if "comercial" in escolhidas:
        cfg = comercial.config(db, emp.id)
        dados = s.comercial.model_dump()
        if dados.get("etapas") is not None:
            dados["etapas"] = [e.strip()[:40] for e in dados["etapas"] if e and e.strip()]
            if len(dados["etapas"]) < 2:
                raise ErroSetup("O funil do setup precisa de pelo menos duas etapas")
        if dados.get("condicoes") is not None and not dados["condicoes"]:
            raise ErroSetup("O setup precisa de ao menos uma condição de pagamento")
        if dados.get("prices_url"):
            try:
                promob_prices.validar_url(dados["prices_url"])
            except promob_prices.ErroPrices as e:
                raise ErroSetup(str(e))
        for k in ("prices_url", "prices_tabela_preferida"):  # vazio no setup = padrão
            if k in s.comercial.model_fields_set and not dados.get(k) and getattr(cfg, k):
                mud.append({"secao": "comercial", "texto": f"{k}: {getattr(cfg, k)} → padrão"})
                setattr(cfg, k, None)
        if dados.get("prices_colunas") is not None:
            dados["prices_colunas"] = {k: v.strip() for k, v in dados["prices_colunas"].items()
                                       if k in ("sku", "descricao", "preco") and v and v.strip()} or None
            if dados["prices_colunas"] is None and cfg.prices_colunas:
                mud.append({"secao": "comercial", "texto": "prices_colunas → detecção automática"})
                cfg.prices_colunas = None
        _campos(cfg, dados, "", mud, "comercial")
        if cfg.desconto_max_vendedor > cfg.desconto_max_gerente:
            raise ErroSetup("No setup, o limite de desconto do vendedor passa o do gerente")
    if "parceiros" in escolhidas:
        existentes = {p.nome.strip().lower(): p for p in db.scalars(select(Parceiro).where(Parceiro.empresa_id == emp.id))}
        for ps in s.parceiros:
            p = existentes.get(ps.nome.strip().lower())
            if p is None:
                db.add(Parceiro(empresa_id=emp.id, **ps.model_dump()))
                mud.append({"secao": "parceiros", "texto": f"Novo parceiro {ps.nome} (RT {ps.rt_pct:g}%)"})
            else:
                _campos(p, ps.model_dump(), f"Parceiro {p.nome} · ", mud, "parceiros")
    if "gestao" in escolhidas:
        cfg = gestao.config(db, emp.id)
        dados = s.gestao.model_dump()
        validas = {c for c, *_ in gestao.METAS}
        if dados.get("metas") is not None:
            dados["metas"] = {k: v for k, v in dados["metas"].items() if k in validas and v is not None}
        colunas = {c for c, _ in gestao.COLUNAS}
        if dados.get("limites_wip") is not None:
            dados["limites_wip"] = {k: v for k, v in dados["limites_wip"].items() if k in colunas and v}
        if "tambor_codigo" in s.gestao.model_fields_set:
            tambor = (dados.pop("tambor_codigo") or "").strip().upper() or None
            if tambor and db.scalar(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id,
                                                                 CentroTrabalho.codigo == tambor)) is None:
                raise ErroSetup(f"O tambor do setup ({tambor}) não é um setor desta base")
            if cfg.tambor_codigo != tambor:
                mud.append({"secao": "gestao", "texto": f"tambor_codigo: {cfg.tambor_codigo or 'calculado'} → {tambor or 'calculado'}"})
                cfg.tambor_codigo = tambor
        else:
            dados.pop("tambor_codigo", None)
        _campos(cfg, dados, "", mud, "gestao")
    if "controladoria" in escolhidas:
        ct = s.controladoria
        setores_ok = {c.codigo for c in db.scalars(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id))}
        existentes = {c.codigo: c for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == emp.id))}
        for cs in ct.centros_custo or []:
            dados = cs.model_dump() | {"codigo": cs.codigo.upper(), "setor_codigo": (cs.setor_codigo or "").upper() or None}
            if dados["setor_codigo"] and dados["setor_codigo"] not in setores_ok:
                raise ErroSetup(f"Centro de custo {dados['codigo']} aponta para o setor {dados['setor_codigo']}, que não existe nesta base")
            c = existentes.get(dados["codigo"])
            if c is None:
                c = CentroCusto(empresa_id=emp.id, **dados)
                db.add(c)
                existentes[c.codigo] = c
                mud.append({"secao": "controladoria", "texto": f"Novo centro de custo {c.codigo} · {c.nome} ({c.tipo})"})
            else:
                if c.setor_codigo != dados["setor_codigo"]:
                    mud.append({"secao": "controladoria", "texto": f"Centro {c.codigo} · setor_codigo: {c.setor_codigo or '—'} → {dados['setor_codigo'] or '—'}"})
                    c.setor_codigo = dados["setor_codigo"]
                _campos(c, {k: v for k, v in dados.items() if k not in ("codigo", "setor_codigo")}, f"Centro {c.codigo} · ", mud, "controladoria")
        db.flush()
        cf = controladoria.config(db, emp.id)
        regras = ct.model_dump(include={"alcada_valor", "exige_centro", "bloqueia_sem_verba", "consolidacao_ativa",
                                        "consolidacao_hora", "consolidacao_meses"})
        _campos(cf, regras, "", mud, "controladoria")
        if ct.centros_padrao is not None:
            mapa = {}
            for conta, cod in ct.centros_padrao.items():
                c = existentes.get((cod or "").upper())
                if conta in controladoria.NOMES and c is not None:
                    mapa[conta] = c.id
            if (cf.centros_padrao or {}) != mapa:
                mud.append({"secao": "controladoria", "texto": f"centros_padrao: {len(cf.centros_padrao or {})} → {len(mapa)} conta(s)"})
                cf.centros_padrao = mapa
        if ct.cenario and ct.cenario.get("premissas"):
            try:
                markup.calcular(ct.cenario["premissas"])
            except markup.ErroPremissas as e:
                raise ErroSetup(f"Cenário do setup: {e}")
            nome = (ct.cenario.get("nome") or "Cenário do setup")[:120]
            cen = db.scalar(select(CenarioPlanejamento).where(CenarioPlanejamento.empresa_id == emp.id, CenarioPlanejamento.nome == nome))
            novas = markup.completar(ct.cenario["premissas"])
            if cen is None:
                cen = CenarioPlanejamento(empresa_id=emp.id, nome=nome, premissas=novas, criado_por="Setup da base")
                db.add(cen)
                mud.append({"secao": "controladoria", "texto": f"Novo cenário principal: {nome}"})
            elif cen.premissas != novas or not cen.principal:
                cen.premissas = novas
                mud.append({"secao": "controladoria", "texto": f"Cenário {nome} atualizado e marcado como principal"})
            db.flush()
            for outro in db.scalars(select(CenarioPlanejamento).where(CenarioPlanejamento.empresa_id == emp.id)):
                outro.principal = outro.id == cen.id
    if "depara" in escolhidas:
        materiais = {m.codigo: m for m in db.scalars(select(Material).where(Material.empresa_id == emp.id))}
        atuais = depara.mapa(db, emp.id)
        for dp in s.depara:
            m = materiais.get(dp.material_codigo)
            if m is None:
                mud.append({"secao": "depara", "texto": f"{dp.codigo_promob} → {dp.material_codigo}: material não existe nesta base (ignorado)"})
                continue
            d = atuais.get(dp.codigo_promob)
            if d is None or d.material_id != m.id or d.fator != dp.fator:
                antes = f"{d.material.codigo} ×{d.fator:g}" if d else "sem vínculo"
                try:
                    depara.salvar(db, emp.id, dp.codigo_promob, m.id, dp.fator, dp.observacao)
                except depara.ErroDePara as e:
                    raise ErroSetup(f"De-para {dp.codigo_promob}: {e}")
                mud.append({"secao": "depara", "texto": f"{dp.codigo_promob}: {antes} → {m.codigo} ×{dp.fator:g}"})
    db.flush()
    return mud


# --- Modelos prontos ----------------------------------------------------------------------------

def modelos() -> list[dict]:
    lista = []
    for arq in sorted(PASTA_MODELOS.glob("*.json")):
        try:
            d = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        lista.append({"codigo": arq.stem, "nome": d.get("nome") or arq.stem, "descricao": d.get("descricao"),
                      "secoes": [x for x in SECOES if d.get(x) is not None]})
    return lista


def modelo(codigo: str) -> dict:
    arq = PASTA_MODELOS / f"{codigo}.json"
    if not codigo.replace("-", "").replace("_", "").isalnum() or not arq.is_file():
        raise ErroSetup("Modelo de setup não encontrado")
    return json.loads(arq.read_text(encoding="utf-8"))
