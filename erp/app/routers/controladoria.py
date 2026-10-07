"""Planejamento e controladoria: DRE gerencial, centros de custo, verbas, aprovações, cenários e consolidação."""
import csv
import io
from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ADMIN, CONTROLADORIA, FINANCEIRO, empresa_atual, usuario_atual
from ..models import (
    CenarioPlanejamento,
    CentroCusto,
    CentroTrabalho,
    Empresa,
    ExecucaoConsolidacao,
    Lancamento,
    Usuario,
    VerbaCentro,
)
from ..services import controladoria as ctl
from ..services import gestao, markup

router = APIRouter(prefix="/api", tags=["controladoria"])
TIPOS_CENTRO = ("PRODUTIVO", "ADMINISTRATIVO", "COMERCIAL", "ESTRUTURA")


def _erro(db: Session, e: Exception):
    db.rollback()
    raise HTTPException(getattr(e, "status", 422), str(e))


# --- Configuração ----------------------------------------------------------------------------------

class ConfigIn(BaseModel):
    alcada_valor: float | None = Field(None, ge=0)
    exige_centro: bool | None = None
    bloqueia_sem_verba: bool | None = None
    centros_padrao: dict[str, int | None] | None = None
    consolidacao_ativa: bool | None = None
    consolidacao_hora: int | None = Field(None, ge=0, le=23)
    consolidacao_meses: int | None = Field(None, ge=1, le=24)


def config_out(cfg) -> dict:
    return {"alcada_valor": cfg.alcada_valor, "exige_centro": cfg.exige_centro, "bloqueia_sem_verba": cfg.bloqueia_sem_verba,
            "centros_padrao": cfg.centros_padrao or {}, "consolidacao_ativa": cfg.consolidacao_ativa,
            "consolidacao_hora": cfg.consolidacao_hora, "consolidacao_meses": cfg.consolidacao_meses,
            "contas": [{"codigo": c, "nome": n, "grupo": g} for c, n, g in ctl.CONTAS], "tipos_centro": TIPOS_CENTRO}


@router.get("/controladoria/config")
def ver_config(usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    cfg = ctl.config(db, usuario.empresa_id)
    db.commit()
    return config_out(cfg)


@router.put("/controladoria/config", dependencies=[Depends(ADMIN)])
def salvar_config(dados: ConfigIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    cfg = ctl.config(db, emp.id)
    campos = dados.model_dump(exclude_unset=True)
    if "centros_padrao" in campos:
        validos = {c.id for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == emp.id))}
        mapa = {k: v for k, v in (campos.pop("centros_padrao") or {}).items() if k in ctl.NOMES and v}
        if any(v not in validos for v in mapa.values()):
            raise HTTPException(422, "Centro de custo padrão inválido")
        cfg.centros_padrao = mapa
    if "alcada_valor" in campos:
        cfg.alcada_valor = campos.pop("alcada_valor") or None
    for k, v in campos.items():
        if v is not None:
            setattr(cfg, k, v)
    db.commit()
    return config_out(cfg)


# --- Centros de custo ------------------------------------------------------------------------------

class CentroCustoIn(BaseModel):
    codigo: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9_.-]+$")
    nome: str = Field(min_length=2, max_length=100)
    tipo: str = "ADMINISTRATIVO"
    responsavel_id: int | None = None
    setor_codigo: str | None = Field(None, max_length=20)
    ativo: bool = True


def centro_out(c: CentroCusto) -> dict:
    return {"id": c.id, "codigo": c.codigo, "nome": c.nome, "tipo": c.tipo, "responsavel_id": c.responsavel_id,
            "responsavel": c.responsavel.nome if c.responsavel else None, "setor_codigo": c.setor_codigo, "ativo": c.ativo}


def _validar_centro(db: Session, emp_id: int, dados: CentroCustoIn) -> dict:
    d = dados.model_dump() | {"codigo": dados.codigo.upper(), "tipo": dados.tipo.upper(),
                              "setor_codigo": (dados.setor_codigo or "").upper() or None}
    if d["tipo"] not in TIPOS_CENTRO:
        raise HTTPException(422, f"Tipo do centro: {', '.join(TIPOS_CENTRO)}")
    if d["responsavel_id"]:
        u = db.get(Usuario, d["responsavel_id"])
        if u is None or u.empresa_id != emp_id:
            raise HTTPException(422, "Responsável não encontrado")
    if d["setor_codigo"] and db.scalar(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp_id,
                                                                    CentroTrabalho.codigo == d["setor_codigo"])) is None:
        raise HTTPException(422, f"Setor da fábrica {d['setor_codigo']} não existe")
    return d


@router.get("/centros-custo")
def listar_centros(usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    return [centro_out(c) for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == usuario.empresa_id)
                                              .order_by(CentroCusto.codigo))]


@router.post("/centros-custo", status_code=201, dependencies=[Depends(CONTROLADORIA)])
def criar_centro(dados: CentroCustoIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    d = _validar_centro(db, emp.id, dados)
    if db.scalar(select(CentroCusto).where(CentroCusto.empresa_id == emp.id, CentroCusto.codigo == d["codigo"])):
        raise HTTPException(409, f"Centro de custo {d['codigo']} já existe")
    c = CentroCusto(empresa_id=emp.id, **d)
    db.add(c)
    db.commit()
    return centro_out(c)


@router.put("/centros-custo/{centro_id}", dependencies=[Depends(CONTROLADORIA)])
def alterar_centro(centro_id: int, dados: CentroCustoIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = db.get(CentroCusto, centro_id)
    if c is None or c.empresa_id != emp.id:
        raise HTTPException(404, "Centro de custo não encontrado")
    d = _validar_centro(db, emp.id, dados)
    if d["codigo"] != c.codigo and db.scalar(select(CentroCusto).where(CentroCusto.empresa_id == emp.id,
                                                                       CentroCusto.codigo == d["codigo"])):
        raise HTTPException(409, f"Centro de custo {d['codigo']} já existe")
    for k, v in d.items():
        setattr(c, k, v)
    db.commit()
    return centro_out(c)


# --- Verbas (orçamento por centro) -----------------------------------------------------------------

class VerbaIn(BaseModel):
    centro_custo_id: int
    ano: int = Field(ge=2000, le=2100)
    mes: int = Field(ge=1, le=12)
    conta: str
    valor: float = Field(ge=0)


@router.get("/verbas", dependencies=[Depends(CONTROLADORIA)])
def listar_verbas(ano: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return [{"id": v.id, "centro_custo_id": v.centro_custo_id, "ano": v.ano, "mes": v.mes, "conta": v.conta, "valor": v.valor}
            for v in db.scalars(select(VerbaCentro).where(VerbaCentro.empresa_id == emp.id, VerbaCentro.ano == ano)
                                .order_by(VerbaCentro.centro_custo_id, VerbaCentro.conta, VerbaCentro.mes))]


def _gravar_verba(db: Session, emp_id: int, centros: set, d: VerbaIn) -> None:
    if d.centro_custo_id not in centros:
        raise HTTPException(422, "Centro de custo inválido")
    if d.conta not in ctl.DESPESAS:
        raise HTTPException(422, f"Verba é para conta de despesa: {', '.join(ctl.DESPESAS)}")
    v = db.scalar(select(VerbaCentro).where(VerbaCentro.empresa_id == emp_id, VerbaCentro.centro_custo_id == d.centro_custo_id,
                                            VerbaCentro.ano == d.ano, VerbaCentro.mes == d.mes, VerbaCentro.conta == d.conta))
    if v is None:
        if d.valor:
            db.add(VerbaCentro(empresa_id=emp_id, **d.model_dump()))
    elif d.valor:
        v.valor = d.valor
    else:
        db.delete(v)


@router.put("/verbas", dependencies=[Depends(CONTROLADORIA)])
def salvar_verbas(dados: list[VerbaIn], emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    centros = {c.id for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == emp.id))}
    for d in dados[:2000]:
        _gravar_verba(db, emp.id, centros, d)
        db.flush()
    db.commit()
    return {"gravadas": len(dados)}


class GerarVerbasIn(BaseModel):
    ano: int = Field(ge=2000, le=2100)
    meses: list[int] = Field(min_length=1)
    origem: str = "HISTORICO"  # HISTORICO (média realizada) ou MES (copia um mês)
    mes_origem: int | None = Field(None, ge=1, le=12)
    meses_base: int = Field(3, ge=1, le=12)
    ajuste_pct: float = Field(0.0, ge=-90, le=300)


@router.post("/verbas/gerar", dependencies=[Depends(CONTROLADORIA)])
def gerar_verbas(dados: GerarVerbasIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Gera verbas dos meses pedidos a partir da média realizada por centro (ou copiando um mês), com ajuste %."""
    centros = {c.id for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == emp.id))}
    base: dict[tuple, float] = defaultdict(float)
    if dados.origem == "MES":
        if not dados.mes_origem:
            raise HTTPException(422, "Informe o mês de origem")
        for v in db.scalars(select(VerbaCentro).where(VerbaCentro.empresa_id == emp.id, VerbaCentro.ano == dados.ano,
                                                      VerbaCentro.mes == dados.mes_origem)):
            base[(v.centro_custo_id, v.conta)] = v.valor
    else:
        hoje = date.today()
        lista = [ctl._soma_mes(hoje.year, hoje.month, -i) for i in range(1, dados.meses_base + 1)]
        for cid in centros:
            real = ctl._realizado(db, emp.id, "COMPETENCIA", lista, cid)
            for _, (_, r) in real.items():
                for conta, v in r.items():
                    if conta in ctl.DESPESAS:
                        base[(cid, conta)] += v / dados.meses_base
    if not base:
        raise HTTPException(422, "Sem base para gerar verbas (nenhum realizado por centro nos meses anteriores ou mês de origem vazio)")
    n = 0
    for mes in dados.meses:
        for (cid, conta), v in base.items():
            _gravar_verba(db, emp.id, centros, VerbaIn(centro_custo_id=cid, ano=dados.ano, mes=mes, conta=conta,
                                                        valor=round(max(0.0, v * (1 + dados.ajuste_pct / 100)), 2)))
            db.flush()
            n += 1
    db.commit()
    return {"verbas": n}


# --- Aprovações e classificação ----------------------------------------------------------------------

@router.get("/controladoria/aprovacoes")
def aprovacoes(usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    from .financeiro import _out
    return [_out(l) for l in ctl.pendentes(db, usuario)]


class DecisaoIn(BaseModel):
    aprovar: bool
    observacao: str | None = Field(None, max_length=150)


@router.post("/lancamentos/{lanc_id}/aprovar")
def aprovar(lanc_id: int, dados: DecisaoIn, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    from .financeiro import _out
    l = db.get(Lancamento, lanc_id)
    if l is None or l.empresa_id != usuario.empresa_id:
        raise HTTPException(404, "Lançamento não encontrado")
    try:
        ctl.decidir(usuario, l, dados.aprovar, dados.observacao)
    except ctl.ErroControladoria as e:
        _erro(db, e)
    db.commit()
    return _out(l)


class ClassificarIn(BaseModel):
    centro_custo_id: int | None = None
    conta: str | None = None


@router.patch("/lancamentos/{lanc_id}/classificar")
def classificar(lanc_id: int, dados: ClassificarIn, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    from .financeiro import _out, _validar_classificacao
    l = db.get(Lancamento, lanc_id)
    if l is None or l.empresa_id != usuario.empresa_id:
        raise HTTPException(404, "Lançamento não encontrado")
    _validar_classificacao(db, usuario.empresa_id, dados.centro_custo_id, dados.conta)
    campos = dados.model_dump(exclude_unset=True)
    if "centro_custo_id" in campos:
        l.centro_custo_id = campos["centro_custo_id"]
    if "conta" in campos:
        l.conta = campos["conta"] or None
    db.commit()
    db.refresh(l)
    return _out(l)


# --- Consolidação e histórico ------------------------------------------------------------------------

class ConsolidarIn(BaseModel):
    meses: int | None = Field(None, ge=1, le=24)


def execucao_out(e: ExecucaoConsolidacao) -> dict:
    return {"id": e.id, "origem": e.origem, "iniciado_em": e.iniciado_em, "concluido_em": e.concluido_em,
            "status": e.status, "usuario": e.usuario, "resumo": e.resumo}


@router.post("/controladoria/consolidar")
def consolidar(dados: ConsolidarIn, usuario: Usuario = Depends(CONTROLADORIA), db: Session = Depends(get_db)):
    ex = ctl.consolidar(db, usuario.empresa_id, dados.meses, origem="MANUAL", usuario=usuario.nome)
    db.commit()
    return execucao_out(ex)


@router.get("/controladoria/execucoes", dependencies=[Depends(CONTROLADORIA)])
def execucoes(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return [execucao_out(e) for e in db.scalars(select(ExecucaoConsolidacao).where(ExecucaoConsolidacao.empresa_id == emp.id)
                                                .order_by(ExecucaoConsolidacao.id.desc()).limit(30))]


@router.post("/controladoria/historico", dependencies=[Depends(CONTROLADORIA)])
async def importar_historico(arquivo: UploadFile = File(...), emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    bruto = await arquivo.read()
    if len(bruto) > 2_000_000:
        raise HTTPException(422, "Arquivo grande demais para histórico (máx. 2 MB)")
    try:
        r = ctl.importar_historico(db, emp.id, bruto.decode("utf-8-sig", errors="replace"))
    except ctl.ErroControladoria as e:
        _erro(db, e)
    db.commit()
    return r


@router.get("/controladoria/historico-premissas", dependencies=[Depends(CONTROLADORIA)])
def historico_premissas(meses: int = 6, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return ctl.historico_premissas(db, emp.id, max(1, min(meses, 24)))


# --- Relatórios ----------------------------------------------------------------------------------------

@router.get("/controladoria/dre", dependencies=[Depends(CONTROLADORIA)])
def dre(ano: int, regime: str = "COMPETENCIA", centro_custo_id: int | None = None, mes_de: int = 1, mes_ate: int = 12,
        emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        return ctl.dre_gerencial(db, emp.id, ano, regime.upper(), centro_custo_id, mes_de, mes_ate)
    except ctl.ErroControladoria as e:
        _erro(db, e)


@router.get("/controladoria/centros", dependencies=[Depends(CONTROLADORIA)])
def relatorio_centros(ano: int, mes_de: int = 1, mes_ate: int = 12, regime: str = "COMPETENCIA",
                      emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return ctl.relatorio_centros(db, emp.id, ano, mes_de, mes_ate, regime.upper())


def _csv(linhas: list[list], nome: str) -> Response:
    buf = io.StringIO()
    csv.writer(buf, delimiter=";").writerows(linhas)
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _br(v) -> str:
    return "" if v is None else f"{v:.2f}".replace(".", ",")


@router.get("/controladoria/dre.csv", dependencies=[Depends(CONTROLADORIA)])
def dre_csv(ano: int, regime: str = "COMPETENCIA", centro_custo_id: int | None = None,
            emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    d = ctl.dre_gerencial(db, emp.id, ano, regime.upper(), centro_custo_id)
    linhas = [["Conta", "Descrição"] + [f"{m['mes']} real" for m in d["meses"]] + [f"{m['mes']} previsto" for m in d["meses"]]
              + ["Realizado", "Previsto", "Variação"]]
    for l in d["linhas"]:
        linhas.append([l["conta"], l["nome"]] + [_br(m["realizado"].get(l["conta"], 0)) for m in d["meses"]]
                      + [_br(m["previsto"].get(l["conta"], 0)) for m in d["meses"]] + [_br(l["realizado"]), _br(l["previsto"]), _br(l["variacao"])])
    return _csv(linhas, f"dre-gerencial-{ano}-{regime.lower()}.csv")


@router.get("/controladoria/centros.csv", dependencies=[Depends(CONTROLADORIA)])
def centros_csv(ano: int, mes_de: int = 1, mes_ate: int = 12, regime: str = "COMPETENCIA",
                emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    linhas = [["Centro", "Nome", "Responsável", "Verba", "Realizado", "Em aberto", "Saldo", "Consumo %"]]
    for c in ctl.relatorio_centros(db, emp.id, ano, mes_de, mes_ate, regime.upper()):
        linhas.append([c["codigo"], c["nome"], c["responsavel"] or "", _br(c["verba"]), _br(c["realizado"]), _br(c["em_aberto"]),
                       _br(c["saldo"]), _br(c["consumo_pct"])])
    return _csv(linhas, f"centros-de-custo-{ano}.csv")


# --- Custo-hora dos setores a partir do realizado -------------------------------------------------------

class CustoSetoresIn(BaseModel):
    meses: int = Field(3, ge=1, le=12)
    aplicar: bool = False


@router.post("/controladoria/custo-setores", dependencies=[Depends(CONTROLADORIA)])
def custo_setores(dados: CustoSetoresIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Custo mensal de cada setor da fábrica = média das despesas realizadas do centro de custo ligado a ele."""
    hoje = date.today()
    lista = [ctl._soma_mes(hoje.year, hoje.month, -i) for i in range(1, dados.meses + 1)]
    saida = []
    for c in db.scalars(select(CentroCusto).where(CentroCusto.empresa_id == emp.id, CentroCusto.setor_codigo.is_not(None))):
        real = ctl._realizado(db, emp.id, "COMPETENCIA", lista, c.id)
        total = sum(v for _, (_, r) in real.items() for k, v in r.items() if k in ctl.DESPESAS and k != "INVESTIMENTOS")
        media = round(total / dados.meses, 2)
        setor = db.scalar(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id, CentroTrabalho.codigo == c.setor_codigo))
        if setor is None:
            continue
        saida.append({"centro_custo": c.codigo, "setor": setor.codigo, "custo_mensal_atual": setor.custo_mensal, "custo_mensal_realizado": media})
        if dados.aplicar and media > 0:
            setor.custo_mensal = media
    db.commit()
    return {"meses": dados.meses, "setores": saida, "aplicado": dados.aplicar}


# --- Cenários de planejamento (ponto de equilíbrio, meta e markup) -------------------------------------

class CenarioIn(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    premissas: dict


def cenario_out(c: CenarioPlanejamento, com_resultado: bool = True) -> dict:
    d = {"id": c.id, "nome": c.nome, "premissas": markup.completar(c.premissas), "principal": c.principal,
         "criado_por": c.criado_por, "atualizado_em": c.atualizado_em}
    if com_resultado:
        try:
            d["resultado"] = markup.calcular(c.premissas)
        except markup.ErroPremissas as e:
            d["erro"] = str(e)
    return d


def _cenario(db: Session, emp_id: int, cid: int) -> CenarioPlanejamento:
    c = db.get(CenarioPlanejamento, cid)
    if c is None or c.empresa_id != emp_id:
        raise HTTPException(404, "Cenário não encontrado")
    return c


@router.get("/cenarios/padrao", dependencies=[Depends(CONTROLADORIA)])
def premissas_padrao():
    return markup.PREMISSAS_PADRAO


@router.post("/cenarios/simular", dependencies=[Depends(CONTROLADORIA)])
def simular(premissas: dict):
    try:
        return markup.calcular(premissas)
    except markup.ErroPremissas as e:
        raise HTTPException(e.status, str(e))


@router.get("/cenarios", dependencies=[Depends(CONTROLADORIA)])
def listar_cenarios(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return [cenario_out(c) for c in db.scalars(select(CenarioPlanejamento).where(CenarioPlanejamento.empresa_id == emp.id)
                                               .order_by(CenarioPlanejamento.principal.desc(), CenarioPlanejamento.nome))]


@router.post("/cenarios", status_code=201)
def criar_cenario(dados: CenarioIn, usuario: Usuario = Depends(CONTROLADORIA), db: Session = Depends(get_db)):
    try:
        markup.calcular(dados.premissas)
    except markup.ErroPremissas as e:
        raise HTTPException(e.status, str(e))
    primeiro = db.scalar(select(CenarioPlanejamento.id).where(CenarioPlanejamento.empresa_id == usuario.empresa_id)) is None
    c = CenarioPlanejamento(empresa_id=usuario.empresa_id, nome=dados.nome.strip(), premissas=markup.completar(dados.premissas),
                            principal=primeiro, criado_por=usuario.nome)
    db.add(c)
    db.commit()
    return cenario_out(c)


@router.put("/cenarios/{cid}", dependencies=[Depends(CONTROLADORIA)])
def alterar_cenario(cid: int, dados: CenarioIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = _cenario(db, emp.id, cid)
    try:
        markup.calcular(dados.premissas)
    except markup.ErroPremissas as e:
        raise HTTPException(e.status, str(e))
    c.nome, c.premissas = dados.nome.strip(), markup.completar(dados.premissas)
    db.commit()
    return cenario_out(c)


@router.delete("/cenarios/{cid}", dependencies=[Depends(CONTROLADORIA)])
def apagar_cenario(cid: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    db.delete(_cenario(db, emp.id, cid))
    db.commit()
    return {"ok": True}


@router.post("/cenarios/{cid}/principal", dependencies=[Depends(CONTROLADORIA)])
def tornar_principal(cid: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = _cenario(db, emp.id, cid)
    for outro in db.scalars(select(CenarioPlanejamento).where(CenarioPlanejamento.empresa_id == emp.id)):
        outro.principal = outro.id == c.id
    db.commit()
    return cenario_out(c)


@router.post("/cenarios/{cid}/aplicar-metas", dependencies=[Depends(ADMIN)])
def aplicar_metas(cid: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Leva a meta de faturamento e a margem do cenário para a gestão à vista."""
    r = markup.calcular(_cenario(db, emp.id, cid).premissas)
    cfg = gestao.config(db, emp.id)
    margem = 100 - r["premissas"]["variaveis"]["dv_pct"] - r["premissas"]["variaveis"]["imposto_pct"] \
        - r["premissas"]["variaveis"]["rt_pct"] - r["premissas"]["variaveis"]["comissoes_pct"]
    cfg.metas = {**(cfg.metas or {}), "faturamento_mes": r["meta_faturamento"], "margem_pct": round(margem, 1)}
    db.commit()
    return {"metas": cfg.metas}

