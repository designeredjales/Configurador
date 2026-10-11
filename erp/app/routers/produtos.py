"""Configurador de produtos: biblioteca da engenharia (linha → grupos → modelos, subconjuntos e acabamentos)
e a configuração na venda (simular, gravar, levar para a proposta ou para o projeto)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import CONFIGURAR, ENGENHARIA, PRODUTOS, empresa_atual
from ..models import Acabamento, ConfiguracaoProduto, Empresa, Modulo, NoProduto, Projeto, StatusProjeto, Usuario
from ..services import configurador as cf
from ..services import formulas

router = APIRouter(prefix="/api", tags=["configurador"])


def _erro(db: Session, e: cf.ErroConfigurador):
    db.rollback()
    if e.detalhes:
        raise HTTPException(e.status, {"mensagem": str(e), "pendencias": e.detalhes})
    raise HTTPException(e.status, str(e))


# --- Biblioteca (engenharia) ----------------------------------------------------------------------

class NoIn(BaseModel):
    pai_id: int | None = None
    tipo: str = Field("MODELO", pattern="^(GRUPO|MODELO|SUBCONJUNTO)$")
    codigo: str = Field(min_length=1, max_length=40)
    nome: str = Field(min_length=2, max_length=160)
    ordem: int = Field(0, ge=0, le=100000)
    ativo: bool = True
    descricao_formula: str | None = Field(None, max_length=400)
    perguntas: list[dict] = []
    componentes: list[dict] = []
    preco: dict | None = None
    observacao: str | None = Field(None, max_length=400)


def _aplicar_no(db: Session, emp: Empresa, no: NoProduto, dados: NoIn, usuario: Usuario):
    codigo = formulas.normalizar(dados.codigo)[:40]
    if not cf._CODIGO.match(codigo):
        raise cf.ErroConfigurador(f"Código '{dados.codigo}' inválido: letras, números e _")
    outro = db.scalar(select(NoProduto).where(NoProduto.empresa_id == emp.id, NoProduto.codigo == codigo))
    if outro is not None and outro.id != no.id:
        raise cf.ErroConfigurador(f"Já existe um item da biblioteca com o código {codigo}", 409)
    if no.id and no.codigo != codigo and db.scalar(select(func.count()).select_from(ConfiguracaoProduto)
                                                   .where(ConfiguracaoProduto.modelo_id == no.id)):
        raise cf.ErroConfigurador("Este modelo já tem configurações vendidas: o código não pode mudar (duplique o modelo)", 409)
    if dados.pai_id is not None:
        pai = cf.carregar_no(db, emp.id, dados.pai_id)
        if pai.tipo != "GRUPO":
            raise cf.ErroConfigurador("O item só fica dentro de um GRUPO (linha, grupo ou subgrupo)")
        atual = pai
        while atual is not None:  # não pode ficar dentro de si mesmo
            if no.id and atual.id == no.id:
                raise cf.ErroConfigurador("Um grupo não pode ficar dentro dele mesmo")
            atual = db.get(NoProduto, atual.pai_id) if atual.pai_id else None
    if no.id and dados.tipo != "GRUPO" and no.tipo == "GRUPO" and db.scalar(
            select(func.count()).select_from(NoProduto).where(NoProduto.pai_id == no.id)):
        raise cf.ErroConfigurador("Este grupo tem itens dentro: mova-os antes de mudar o tipo")
    erro = formulas.erros_modelo_texto(dados.descricao_formula)
    if erro:
        raise cf.ErroConfigurador(f"Descrição: {erro}")
    no.empresa_id, no.pai_id, no.tipo, no.codigo, no.nome = emp.id, dados.pai_id, dados.tipo, codigo, dados.nome.strip()
    no.ordem, no.ativo, no.observacao = dados.ordem, dados.ativo, dados.observacao
    no.descricao_formula = (dados.descricao_formula or "").strip() or None
    no.perguntas = cf.limpar_perguntas(dados.perguntas)
    no.componentes = cf.limpar_componentes(dados.componentes)
    no.preco = cf.limpar_preco(dados.preco)
    no.atualizado_por = usuario.nome


@router.get("/produtos", dependencies=[Depends(PRODUTOS)])
def arvore(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    nos = db.scalars(select(NoProduto).where(NoProduto.empresa_id == emp.id).order_by(NoProduto.ordem, NoProduto.nome))
    vendidos = dict(db.execute(select(ConfiguracaoProduto.modelo_id, func.count()).where(
        ConfiguracaoProduto.empresa_id == emp.id).group_by(ConfiguracaoProduto.modelo_id)).all())
    return [cf.no_out(n) | {"configuracoes": vendidos.get(n.id, 0)} for n in nos]


@router.get("/produtos/{no_id}", dependencies=[Depends(PRODUTOS)])
def ver_no(no_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        no = cf.carregar_no(db, emp.id, no_id)
        ef = cf.efetivo(db, no)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    return cf.no_out(no, completo=True) | {"efetivo": ef}


@router.post("/produtos", status_code=201)
def criar_no(dados: NoIn, usuario: Usuario = Depends(PRODUTOS), emp: Empresa = Depends(empresa_atual),
             db: Session = Depends(get_db)):
    no = NoProduto()
    try:
        _aplicar_no(db, emp, no, dados, usuario)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.add(no)
    db.commit()
    return cf.no_out(no, completo=True)


@router.put("/produtos/{no_id}")
def alterar_no(no_id: int, dados: NoIn, usuario: Usuario = Depends(PRODUTOS), emp: Empresa = Depends(empresa_atual),
               db: Session = Depends(get_db)):
    try:
        no = cf.carregar_no(db, emp.id, no_id)
        _aplicar_no(db, emp, no, dados, usuario)
        db.flush()
        cf.efetivo(db, no)  # confere a herança
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.commit()
    return cf.no_out(no, completo=True)


class DuplicarIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=40)
    nome: str = Field(min_length=2, max_length=160)


@router.post("/produtos/{no_id}/duplicar", status_code=201)
def duplicar_no(no_id: int, dados: DuplicarIn, usuario: Usuario = Depends(PRODUTOS), emp: Empresa = Depends(empresa_atual),
                db: Session = Depends(get_db)):
    try:
        orig = cf.carregar_no(db, emp.id, no_id)
        if orig.tipo == "GRUPO":
            raise cf.ErroConfigurador("Duplique modelos e subconjuntos (o grupo herda para todos abaixo dele)")
        no = NoProduto()
        _aplicar_no(db, emp, no, NoIn(pai_id=orig.pai_id, tipo=orig.tipo, codigo=dados.codigo, nome=dados.nome,
                                      ordem=orig.ordem, descricao_formula=orig.descricao_formula,
                                      perguntas=orig.perguntas or [], componentes=orig.componentes or [],
                                      preco=orig.preco, observacao=orig.observacao), usuario)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.add(no)
    db.commit()
    return cf.no_out(no, completo=True)


@router.delete("/produtos/{no_id}", dependencies=[Depends(PRODUTOS)])
def apagar_no(no_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        no = cf.carregar_no(db, emp.id, no_id)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    if db.scalar(select(func.count()).select_from(NoProduto).where(NoProduto.pai_id == no.id)):
        raise HTTPException(409, "Há itens dentro deste grupo: mova ou apague-os antes")
    if db.scalar(select(func.count()).select_from(ConfiguracaoProduto).where(ConfiguracaoProduto.modelo_id == no.id)):
        raise HTTPException(409, "Este modelo já foi vendido: inative em vez de apagar")
    usado = [n.codigo for n in db.scalars(select(NoProduto).where(NoProduto.empresa_id == emp.id))
             if any(c.get("subconjunto") == no.codigo for c in n.componentes or [])]
    if usado:
        raise HTTPException(409, f"Subconjunto usado em {', '.join(usado[:10])}: retire de lá antes de apagar")
    db.delete(no)
    db.commit()
    return {"ok": True}


@router.get("/produtos/{no_id}/configuracoes", dependencies=[Depends(PRODUTOS)])
def configuracoes_do_modelo(no_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        no = cf.carregar_no(db, emp.id, no_id)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    lista = db.scalars(select(ConfiguracaoProduto).where(ConfiguracaoProduto.modelo_id == no.id)
                       .order_by(ConfiguracaoProduto.sequencial.desc()).limit(200))
    return [{"id": c.id, "codigo": c.codigo, "descricao": c.descricao, "respostas": c.respostas, "custo": c.custo,
             "criado_por": c.criado_por, "criado_em": c.criado_em} for c in lista]


class FormulaIn(BaseModel):
    formula: str = Field(max_length=2000)
    descricao: bool = False


@router.post("/formulas/conferir", dependencies=[Depends(PRODUTOS)])
def conferir_formula(dados: FormulaIn):
    """Confere a sintaxe enquanto a engenharia digita."""
    erro = formulas.erros_modelo_texto(dados.formula) if dados.descricao else formulas.validar(dados.formula)
    nomes = sorted(formulas.nomes_usados(dados.formula)) if not erro and not dados.descricao and dados.formula.strip() else []
    return {"ok": erro is None, "erro": erro, "variaveis": nomes}


# --- Acabamentos (modelo definição → opções com o material de cada componente) -----------------------

class AcabamentoIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=40)
    nome: str = Field(min_length=2, max_length=160)
    componentes: list[str] = Field(min_length=1, max_length=30)
    opcoes: list[dict] = Field(min_length=1, max_length=500)


@router.get("/acabamentos", dependencies=[Depends(CONFIGURAR)])
def listar_acabamentos(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return [cf.acabamento_out(a) for a in db.scalars(select(Acabamento).where(Acabamento.empresa_id == emp.id)
                                                      .order_by(Acabamento.nome))]


def _aplicar_acabamento(db: Session, emp: Empresa, a: Acabamento, dados: AcabamentoIn):
    codigo = formulas.normalizar(dados.codigo)[:40]
    if not cf._CODIGO.match(codigo):
        raise cf.ErroConfigurador(f"Código '{dados.codigo}' inválido: letras, números e _")
    outro = db.scalar(select(Acabamento).where(Acabamento.empresa_id == emp.id, Acabamento.codigo == codigo))
    if outro is not None and outro.id != a.id:
        raise cf.ErroConfigurador(f"Já existe o acabamento {codigo}", 409)
    if a.id and a.codigo != codigo:
        raise cf.ErroConfigurador("O código do acabamento não muda (as perguntas apontam para ele)", 409)
    a.componentes, a.opcoes = cf.limpar_opcoes_acabamento(dados.componentes, dados.opcoes)
    a.empresa_id, a.codigo, a.nome = emp.id, codigo, dados.nome.strip()


@router.post("/acabamentos", status_code=201, dependencies=[Depends(PRODUTOS)])
def criar_acabamento(dados: AcabamentoIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    a = Acabamento()
    try:
        _aplicar_acabamento(db, emp, a, dados)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.add(a)
    db.commit()
    return cf.acabamento_out(a)


@router.put("/acabamentos/{acab_id}", dependencies=[Depends(PRODUTOS)])
def alterar_acabamento(acab_id: int, dados: AcabamentoIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    a = db.get(Acabamento, acab_id)
    if a is None or a.empresa_id != emp.id:
        raise HTTPException(404, "Acabamento não encontrado")
    try:
        _aplicar_acabamento(db, emp, a, dados)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.commit()
    return cf.acabamento_out(a)


@router.delete("/acabamentos/{acab_id}", dependencies=[Depends(PRODUTOS)])
def apagar_acabamento(acab_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    a = db.get(Acabamento, acab_id)
    if a is None or a.empresa_id != emp.id:
        raise HTTPException(404, "Acabamento não encontrado")
    usado = [n.codigo for n in db.scalars(select(NoProduto).where(NoProduto.empresa_id == emp.id))
             if any(p.get("acabamento") == a.codigo for p in n.perguntas or [])]
    if usado:
        raise HTTPException(409, f"Acabamento usado em {', '.join(usado[:10])}")
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.post("/acabamentos/{acab_id}/sugerir", dependencies=[Depends(PRODUTOS)])
def sugerir_materiais(acab_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    a = db.get(Acabamento, acab_id)
    if a is None or a.empresa_id != emp.id:
        raise HTTPException(404, "Acabamento não encontrado")
    return cf.sugerir(db, emp.id, a)


# --- Parâmetros do configurador -------------------------------------------------------------------

class ConfigIn(BaseModel):
    constantes: dict[str, float] = {}
    perda_perfil_pct: float = Field(3.0, ge=0, le=50)
    serra_perfil_mm: float = Field(4.0, ge=0, le=20)
    markup_padrao: float = Field(2.0, gt=0, le=20)


def _config_out(c) -> dict:
    return {"constantes": c.constantes or {}, "perda_perfil_pct": c.perda_perfil_pct, "serra_perfil_mm": c.serra_perfil_mm,
            "markup_padrao": c.markup_padrao}


@router.get("/configurador/config", dependencies=[Depends(CONFIGURAR)])
def ver_config(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = cf.config(db, emp.id)
    db.commit()
    return _config_out(c)


@router.put("/configurador/config", dependencies=[Depends(PRODUTOS)])
def salvar_config(dados: ConfigIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    c = cf.config(db, emp.id)
    constantes = {}
    for k, v in dados.constantes.items():
        nome = formulas.normalizar(k)
        if not cf._CODIGO.match(nome):
            raise HTTPException(422, f"Constante '{k}' inválida: letras, números e _")
        constantes[nome] = float(v)
    c.constantes, c.perda_perfil_pct, c.serra_perfil_mm, c.markup_padrao = (
        constantes, dados.perda_perfil_pct, dados.serra_perfil_mm, dados.markup_padrao)
    db.commit()
    return _config_out(c)


# --- Venda: o vendedor escolhe dentro do que a engenharia liberou ------------------------------------

@router.get("/configurador/modelos", dependencies=[Depends(CONFIGURAR)])
def modelos(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return cf.modelos_a_venda(db, emp.id)


class SimularIn(BaseModel):
    modelo_id: int
    respostas: dict = {}
    quantidade: int = Field(1, ge=1, le=999)


@router.post("/configurador/simular", dependencies=[Depends(CONFIGURAR)])
def simular(dados: SimularIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        modelo = cf.carregar_no(db, emp.id, dados.modelo_id)
        r = cf.simular(db, modelo, dados.respostas, dados.quantidade)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.rollback()  # simular não grava nada
    return r


class ConfiguradoIn(BaseModel):
    modelo_id: int
    respostas: dict = {}
    quantidade: int = Field(1, ge=1, le=999)
    ambiente: str | None = Field(None, max_length=120)


@router.post("/projetos/{projeto_id}/configurados", status_code=201)
def adicionar_ao_projeto(projeto_id: int, dados: ConfiguradoIn, usuario: Usuario = Depends(ENGENHARIA),
                         emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Engenharia acrescenta um produto configurado num projeto ainda em engenharia (ex.: alumínio fora do Promob)."""
    projeto = db.get(Projeto, projeto_id)
    if projeto is None or projeto.empresa_id != emp.id:
        raise HTTPException(404, "Projeto não encontrado")
    if projeto.status not in (StatusProjeto.ORCAMENTO, StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA):
        raise HTTPException(409, f"Projeto {projeto.status}: só recebe produtos enquanto está em engenharia")
    try:
        itens = cf.preparar_itens(db, emp.id, [dados.model_dump()], usuario.nome)
        cf.gerar_modulos(db, projeto, itens)
    except cf.ErroConfigurador as e:
        _erro(db, e)
    db.commit()
    it = itens[0]
    return {"projeto_id": projeto.id, "codigo": it["codigo"], "descricao": it["descricao"], "quantidade": it["quantidade"],
            "ambiente": it["ambiente"], "preco_unitario": it["preco_unitario"]}


@router.delete("/projetos/{projeto_id}/modulos/{modulo_id}", dependencies=[Depends(ENGENHARIA)])
def retirar_modulo_configurado(projeto_id: int, modulo_id: int, emp: Empresa = Depends(empresa_atual),
                               db: Session = Depends(get_db)):
    projeto = db.get(Projeto, projeto_id)
    mod = db.get(Modulo, modulo_id)
    if projeto is None or projeto.empresa_id != emp.id or mod is None or mod.ambiente.projeto_id != projeto.id:
        raise HTTPException(404, "Módulo não encontrado")
    if not mod.configuracao_id:
        raise HTTPException(409, "Só os produtos do configurador saem por aqui (os do Promob vêm do XML)")
    if projeto.status not in (StatusProjeto.ORCAMENTO, StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA):
        raise HTTPException(409, f"Projeto {projeto.status}: já foi para a fábrica")
    amb = mod.ambiente
    db.delete(mod)  # apaga peças e itens junto (cascata explícita: o PostgreSQL confere a chave)
    db.flush()
    db.expire(amb, ["modulos"])
    if not amb.modulos:
        db.delete(amb)
    db.commit()
    return {"ok": True}
