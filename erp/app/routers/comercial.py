"""Módulo Comercial: configurações, parceiros, funil, versões do Promob, negociação, proposta e venda."""
import html
import os
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ADMIN, APROVAR_VENDA, COMERCIAL, empresa_atual
from ..funcoes import efetivas
from ..models import (
    Empresa,
    ImagemProposta,
    Oportunidade,
    Parceiro,
    Perfil,
    PrecoPromob,
    Usuario,
    VersaoProposta,
)
from ..services import comercial, promob_prices
from ..services.importacao import eh_xml
from ..services.promob_xml import ErroXMLPromob, ler_xml_promob
from .projetos import carregar as carregar_projeto

router = APIRouter(tags=["comercial"])
TIPOS_IMAGEM = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def pasta_arquivos() -> Path:
    return Path(os.getenv("ERP_PASTA_ARQUIVOS", "arquivos"))


def _erro(db: Session, e: Exception):
    db.rollback()
    raise HTTPException(getattr(e, "status", 409), str(e))


# --- Configurações do módulo (administrador) -------------------------------------------

class CondicaoIn(BaseModel):
    nome: str = Field(min_length=1, max_length=60)
    parcelas: int = Field(ge=1, le=60)
    ajuste_pct: float = Field(ge=-50, le=50)


class ConfigIn(BaseModel):
    desconto_max_vendedor: float | None = Field(None, ge=0, le=100)
    desconto_max_gerente: float | None = Field(None, ge=0, le=100)
    margem_minima: float | None = Field(None, ge=-100, le=100)
    comissao_vendedor_pct: float | None = Field(None, ge=0, le=50)
    limite_divergencia_pct: float | None = Field(None, ge=0, le=100)
    validade_proposta_dias: int | None = Field(None, ge=1, le=180)
    etapas: list[str] | None = None
    condicoes: list[CondicaoIn] | None = None
    prices_token: str | None = Field(None, max_length=2000)
    prices_url: str | None = Field(None, max_length=300)
    prices_tabela_preferida: str | None = Field(None, max_length=200)
    prices_colunas: dict[str, str] | None = None


def config_out(db: Session, cfg) -> dict:
    itens = db.query(PrecoPromob).filter(PrecoPromob.empresa_id == cfg.empresa_id).count()
    return {"desconto_max_vendedor": cfg.desconto_max_vendedor, "desconto_max_gerente": cfg.desconto_max_gerente,
            "margem_minima": cfg.margem_minima, "comissao_vendedor_pct": cfg.comissao_vendedor_pct,
            "limite_divergencia_pct": cfg.limite_divergencia_pct, "validade_proposta_dias": cfg.validade_proposta_dias,
            "etapas": cfg.etapas or comercial.ETAPAS_PADRAO, "condicoes": cfg.condicoes or comercial.CONDICOES_PADRAO,
            "prices_token_configurado": bool(cfg.prices_token), "prices_tabela": cfg.prices_tabela,
            "prices_sincronizado_em": cfg.prices_sincronizado_em, "prices_itens": itens,
            "prices_url": cfg.prices_url or promob_prices.BASE, "prices_tabela_preferida": cfg.prices_tabela_preferida,
            "prices_colunas": cfg.prices_colunas or {}}


@router.get("/api/comercial/config", dependencies=[Depends(COMERCIAL)])
def ver_config(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    cfg = comercial.config(db, emp.id)
    db.commit()
    return config_out(db, cfg)


@router.put("/api/comercial/config", dependencies=[Depends(ADMIN)])
def salvar_config(dados: ConfigIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    cfg = comercial.config(db, emp.id)
    campos = dados.model_dump(exclude_unset=True)
    if campos.get("etapas") is not None:
        etapas = [e.strip()[:40] for e in campos["etapas"] if e and e.strip()]
        if len(etapas) < 2:
            raise HTTPException(422, "O funil precisa de pelo menos duas etapas")
        campos["etapas"] = etapas
    if campos.get("condicoes") is not None and not campos["condicoes"]:
        raise HTTPException(422, "Cadastre ao menos uma condição de pagamento")
    token = campos.pop("prices_token", None)
    if token:  # vazio não apaga o token já salvo
        cfg.prices_token = token.strip()
    # Campos do setup da integração: vazio volta ao padrão
    if "prices_url" in campos:
        url = (campos.pop("prices_url") or "").strip().rstrip("/")
        if url:
            try:
                promob_prices.validar_url(url)
            except promob_prices.ErroPrices as e:
                raise HTTPException(e.status, str(e))
        cfg.prices_url = None if not url or url == promob_prices.BASE else url
    if "prices_tabela_preferida" in campos:
        cfg.prices_tabela_preferida = (campos.pop("prices_tabela_preferida") or "").strip() or None
    if "prices_colunas" in campos:
        mapa = {k: v.strip() for k, v in (campos.pop("prices_colunas") or {}).items()
                if k in ("sku", "descricao", "preco") and v and v.strip()}
        cfg.prices_colunas = mapa or None
    for k, v in campos.items():
        if v is not None:
            setattr(cfg, k, v)
    if cfg.desconto_max_vendedor > cfg.desconto_max_gerente:
        raise HTTPException(422, "O limite do vendedor não pode passar o do gerente")
    db.commit()
    return config_out(db, cfg)


@router.post("/api/comercial/prices/sincronizar", dependencies=[Depends(ADMIN)])
def sincronizar_prices(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        r = promob_prices.sincronizar(db, comercial.config(db, emp.id))
    except promob_prices.ErroPrices as e:
        _erro(db, e)
    db.commit()
    return r


@router.post("/api/comercial/prices/diagnostico", dependencies=[Depends(ADMIN)])
def diagnosticar_prices(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """Mostra o formato real das tabelas e do CSV da conta (nada é gravado)."""
    try:
        return promob_prices.diagnosticar(comercial.config(db, emp.id))
    except promob_prices.ErroPrices as e:
        _erro(db, e)


# --- Parceiros (arquitetos, designers, lojas) --------------------------------------------

class ParceiroIn(BaseModel):
    nome: str = Field(min_length=2, max_length=160)
    tipo: str = Field("ARQUITETO", max_length=20)
    documento: str | None = Field(None, max_length=20)
    telefone: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=160)
    rt_pct: float = Field(0.0, ge=0, le=30)
    ativo: bool = True


def parceiro_out(p: Parceiro) -> dict:
    return {k: getattr(p, k) for k in ("id", "nome", "tipo", "documento", "telefone", "email", "rt_pct", "ativo")}


@router.get("/api/parceiros", dependencies=[Depends(COMERCIAL)])
def listar_parceiros(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return [parceiro_out(p) for p in db.scalars(select(Parceiro).where(Parceiro.empresa_id == emp.id).order_by(Parceiro.nome))]


@router.post("/api/parceiros", status_code=201, dependencies=[Depends(ADMIN)])
def criar_parceiro(dados: ParceiroIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    p = Parceiro(empresa_id=emp.id, **dados.model_dump())
    db.add(p)
    db.commit()
    return parceiro_out(p)


@router.put("/api/parceiros/{parceiro_id}", dependencies=[Depends(ADMIN)])
def alterar_parceiro(parceiro_id: int, dados: ParceiroIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    p = db.get(Parceiro, parceiro_id)
    if p is None or p.empresa_id != emp.id:
        raise HTTPException(404, "Parceiro não encontrado")
    for k, v in dados.model_dump().items():
        setattr(p, k, v)
    db.commit()
    return parceiro_out(p)


# --- Funil ---------------------------------------------------------------------------------

def _ve_tudo(u: Usuario) -> bool:
    return u.perfil == Perfil.ADMIN or "aprovar_venda" in efetivas(u)


def carregar_op(db: Session, usuario: Usuario, op_id: int) -> Oportunidade:
    op = db.get(Oportunidade, op_id)
    if op is None or op.empresa_id != usuario.empresa_id:
        raise HTTPException(404, "Oportunidade não encontrada")
    if not _ve_tudo(usuario) and op.vendedor_id not in (None, usuario.id):
        raise HTTPException(403, "Oportunidade de outro vendedor")
    return op


def carregar_versao(db: Session, usuario: Usuario, versao_id: int) -> VersaoProposta:
    v = db.get(VersaoProposta, versao_id)
    if v is None:
        raise HTTPException(404, "Versão não encontrada")
    carregar_op(db, usuario, v.oportunidade_id)
    return v


def versao_out(v: VersaoProposta) -> dict:
    return {"id": v.id, "numero": v.numero, "arquivo": v.arquivo, "resumo": v.resumo, "desconto_pct": v.desconto_pct,
            "condicao": v.condicao, "calculo": v.calculo, "aprovacao": v.aprovacao, "aprovacao_motivo": v.aprovacao_motivo,
            "aprovado_por": v.aprovado_por, "proposta_link": f"/p/{v.token_publico}" if v.token_publico else None,
            "proposta_validade": v.proposta_validade, "aceite_em": v.aceite_em, "aceite_nome": v.aceite_nome,
            "criado_por": v.criado_por, "criado_em": v.criado_em}


def op_out(op: Oportunidade, detalhe: bool = False) -> dict:
    ultima = op.versoes[-1] if op.versoes else None
    d = {"id": op.id, "numero": op.numero, "titulo": op.titulo, "cliente_nome": op.cliente_nome, "telefone": op.telefone,
         "email": op.email, "etapa": op.etapa, "status": op.status, "origem": op.origem, "parceiro_id": op.parceiro_id,
         "parceiro": op.parceiro.nome if op.parceiro else None, "vendedor_id": op.vendedor_id,
         "vendedor": op.vendedor.nome if op.vendedor else None, "valor_estimado": op.valor_estimado,
         "valor_atual": (ultima.calculo or {}).get("preco_final") if ultima else None,
         "margem_pct": (ultima.calculo or {}).get("margem_pct") if ultima else None,
         "aprovacao": ultima.aprovacao if ultima else None, "versoes": len(op.versoes),
         "link_3d": op.link_3d, "link_2020": op.link_2020,
         "token_2020": f"…{op.token_2020[-6:]}" if op.token_2020 else None,
         "proxima_acao": op.proxima_acao, "proxima_acao_em": op.proxima_acao_em, "motivo_perda": op.motivo_perda,
         "projeto_id": op.projeto_id, "criado_em": op.criado_em, "fechado_em": op.fechado_em}
    if detalhe:
        d["lista_versoes"] = [versao_out(v) for v in reversed(op.versoes)]
        d["imagens"] = [{"id": i.id, "nome": i.nome, "legenda": i.legenda} for i in op.imagens]
    return d


class OportunidadeIn(BaseModel):
    titulo: str | None = Field(None, min_length=2, max_length=160)
    cliente_nome: str | None = Field(None, min_length=2, max_length=160)
    telefone: str | None = Field(None, max_length=30)
    email: str | None = Field(None, max_length=160)
    etapa: str | None = Field(None, max_length=40)
    origem: str | None = Field(None, max_length=60)
    parceiro_id: int | None = None
    vendedor_id: int | None = None
    valor_estimado: float | None = Field(None, ge=0)
    link_3d: str | None = Field(None, max_length=400)
    link_2020: str | None = Field(None, max_length=400)
    token_2020: str | None = Field(None, max_length=400)
    proxima_acao: str | None = Field(None, max_length=200)
    proxima_acao_em: date | None = None


def _aplicar(db: Session, usuario: Usuario, op: Oportunidade, dados: OportunidadeIn, cfg) -> None:
    campos = dados.model_dump(exclude_unset=True)
    if "etapa" in campos and campos["etapa"] not in (cfg.etapas or comercial.ETAPAS_PADRAO):
        raise HTTPException(422, f"Etapa '{campos['etapa']}' não existe no funil")
    if campos.get("parceiro_id"):
        p = db.get(Parceiro, campos["parceiro_id"])
        if p is None or p.empresa_id != usuario.empresa_id:
            raise HTTPException(422, "Parceiro não encontrado")
    if "vendedor_id" in campos and campos["vendedor_id"] and campos["vendedor_id"] != usuario.id:
        if not _ve_tudo(usuario):
            raise HTTPException(403, "Só quem aprova vendas distribui oportunidades entre vendedores")
        v = db.get(Usuario, campos["vendedor_id"])
        if v is None or v.empresa_id != usuario.empresa_id:
            raise HTTPException(422, "Vendedor não encontrado")
    for k in ("link_3d", "link_2020"):
        if campos.get(k) and not str(campos[k]).startswith(("https://", "http://")):
            raise HTTPException(422, "Os links precisam começar com https://")
    for k, v in campos.items():
        if k == "token_2020" and not v:
            continue
        setattr(op, k, v)


@router.get("/api/oportunidades")
def listar(status: str | None = None, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    q = select(Oportunidade).where(Oportunidade.empresa_id == usuario.empresa_id)
    if status:
        q = q.where(Oportunidade.status == status.upper())
    if not _ve_tudo(usuario):
        q = q.where(or_(Oportunidade.vendedor_id == usuario.id, Oportunidade.vendedor_id.is_(None)))
    return [op_out(o) for o in db.scalars(q.order_by(Oportunidade.numero.desc()).limit(500))]


@router.post("/api/oportunidades", status_code=201)
def criar(dados: OportunidadeIn, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    if not dados.titulo or not dados.cliente_nome:
        raise HTTPException(422, "Informe o cliente e um título para a oportunidade (ex.: Cozinha e área gourmet)")
    cfg = comercial.config(db, usuario.empresa_id)
    op = Oportunidade(empresa_id=usuario.empresa_id, numero=comercial.numero_oportunidade(db, usuario.empresa_id),
                      titulo=dados.titulo, cliente_nome=dados.cliente_nome, etapa=(cfg.etapas or comercial.ETAPAS_PADRAO)[0],
                      vendedor_id=usuario.id)
    _aplicar(db, usuario, op, dados, cfg)
    db.add(op)
    db.commit()
    return op_out(op, True)


@router.get("/api/oportunidades/{op_id}")
def detalhe(op_id: int, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    return op_out(carregar_op(db, usuario, op_id), True)


@router.patch("/api/oportunidades/{op_id}")
def alterar(op_id: int, dados: OportunidadeIn, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    op = carregar_op(db, usuario, op_id)
    if op.status != "ABERTA":
        raise HTTPException(409, f"Oportunidade {op.status}")
    _aplicar(db, usuario, op, dados, comercial.config(db, usuario.empresa_id))
    db.commit()
    return op_out(op, True)


class PerdaIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=200)


@router.post("/api/oportunidades/{op_id}/perder")
def perder(op_id: int, dados: PerdaIn, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    op = carregar_op(db, usuario, op_id)
    if op.status != "ABERTA":
        raise HTTPException(409, f"Oportunidade {op.status}")
    from datetime import datetime
    op.status, op.motivo_perda, op.fechado_em = "PERDIDA", dados.motivo.strip(), datetime.now()
    db.commit()
    return op_out(op, True)


# --- Versões do Promob, negociação, aprovação e proposta -----------------------------------

@router.post("/api/oportunidades/{op_id}/versoes", status_code=201)
async def nova_versao(op_id: int, arquivo: UploadFile = File(...), usuario: Usuario = Depends(COMERCIAL),
                      emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    op = carregar_op(db, usuario, op_id)
    if op.status != "ABERTA":
        raise HTTPException(409, f"Oportunidade {op.status}")
    bruto = await arquivo.read()
    if not eh_xml(bruto) or len(bruto) > 20_000_000:
        raise HTTPException(422, "Envie o XML exportado do Promob (Orçamento-Explodido c/ Operação)")
    try:
        lido = ler_xml_promob(bruto)
    except ErroXMLPromob as e:
        raise HTTPException(422, str(e))
    texto = bruto.decode("utf-8", errors="replace")
    v = VersaoProposta(oportunidade=op, numero=len(op.versoes) + 1, arquivo=(arquivo.filename or "projeto.xml")[:200],
                       xml=texto, resumo=comercial.resumo_xml(lido), criado_por=usuario.nome)
    db.add(v)
    db.flush()
    try:
        comercial.negociar(db, emp, usuario, v, 0.0, None)
    except comercial.ErroComercial as e:
        _erro(db, e)
    if not op.valor_estimado:
        op.valor_estimado = v.calculo["preco_final"]
    db.commit()
    return versao_out(v)


class NegociacaoIn(BaseModel):
    desconto_pct: float = Field(0, ge=0, le=100)
    condicao: str | None = None


@router.post("/api/versoes/{versao_id}/negociar")
def negociar(versao_id: int, dados: NegociacaoIn, usuario: Usuario = Depends(COMERCIAL),
             emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    v = carregar_versao(db, usuario, versao_id)
    try:
        comercial.negociar(db, emp, usuario, v, dados.desconto_pct, dados.condicao)
    except comercial.ErroComercial as e:
        _erro(db, e)
    db.commit()
    return versao_out(v)


class DecisaoIn(BaseModel):
    aprovar: bool
    observacao: str | None = Field(None, max_length=150)


@router.post("/api/versoes/{versao_id}/decidir")
def decidir(versao_id: int, dados: DecisaoIn, usuario: Usuario = Depends(APROVAR_VENDA), db: Session = Depends(get_db)):
    v = carregar_versao(db, usuario, versao_id)
    try:
        comercial.decidir(db, usuario, v, dados.aprovar, dados.observacao)
    except comercial.ErroComercial as e:
        _erro(db, e)
    db.commit()
    return versao_out(v)


@router.post("/api/versoes/{versao_id}/proposta")
def proposta(versao_id: int, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    v = carregar_versao(db, usuario, versao_id)
    try:
        comercial.gerar_proposta(db, comercial.config(db, usuario.empresa_id), v)
    except comercial.ErroComercial as e:
        _erro(db, e)
    db.commit()
    return versao_out(v)


class FecharIn(BaseModel):
    versao_id: int
    primeiro_vencimento: date
    data_entrega: date | None = None


@router.post("/api/oportunidades/{op_id}/fechar", status_code=201)
def fechar(op_id: int, dados: FecharIn, usuario: Usuario = Depends(COMERCIAL),
           emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    op = carregar_op(db, usuario, op_id)
    v = carregar_versao(db, usuario, dados.versao_id)
    try:
        projeto = comercial.fechar(db, emp, usuario, op, v, dados.primeiro_vencimento, dados.data_entrega)
    except comercial.ErroComercial as e:
        _erro(db, e)
    db.commit()
    return {"projeto_id": projeto.id, "projeto_codigo": projeto.codigo, "oportunidade": op_out(op, True)}


# --- Imagens (renders) ---------------------------------------------------------------------

@router.post("/api/oportunidades/{op_id}/imagens", status_code=201)
async def enviar_imagem(op_id: int, arquivo: UploadFile = File(...), legenda: str | None = Form(None),
                        usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    op = carregar_op(db, usuario, op_id)
    ext = TIPOS_IMAGEM.get(arquivo.content_type or "")
    if ext is None:
        raise HTTPException(422, "Envie imagens JPG, PNG ou WEBP (os renders do Promob)")
    bruto = await arquivo.read()
    if len(bruto) > 12_000_000:
        raise HTTPException(422, "Imagem acima de 12 MB: exporte o render em resolução menor")
    pasta = pasta_arquivos() / str(op.empresa_id) / "propostas" / str(op.id)
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{uuid.uuid4().hex}{ext}"
    (pasta / nome).write_bytes(bruto)
    img = ImagemProposta(oportunidade=op, nome=(arquivo.filename or nome)[:200], tipo=arquivo.content_type,
                         caminho=str(Path(str(op.empresa_id)) / "propostas" / str(op.id) / nome),
                         legenda=(legenda or "").strip()[:160] or None)
    db.add(img)
    db.commit()
    return {"id": img.id, "nome": img.nome, "legenda": img.legenda}


def _arquivo(img: ImagemProposta) -> FileResponse:
    caminho = pasta_arquivos() / img.caminho
    if not caminho.is_file():
        raise HTTPException(404, "Arquivo da imagem não encontrado")
    return FileResponse(caminho, media_type=img.tipo)


@router.get("/api/imagens/{imagem_id}")
def ver_imagem(imagem_id: int, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    img = db.get(ImagemProposta, imagem_id)
    if img is None:
        raise HTTPException(404, "Imagem não encontrada")
    carregar_op(db, usuario, img.oportunidade_id)
    return _arquivo(img)


@router.delete("/api/imagens/{imagem_id}")
def apagar_imagem(imagem_id: int, usuario: Usuario = Depends(COMERCIAL), db: Session = Depends(get_db)):
    img = db.get(ImagemProposta, imagem_id)
    if img is None:
        raise HTTPException(404, "Imagem não encontrada")
    carregar_op(db, usuario, img.oportunidade_id)
    (pasta_arquivos() / img.caminho).unlink(missing_ok=True)
    db.delete(img)
    db.commit()
    return {"ok": True}


# --- Auditoria do projeto vendido -------------------------------------------------------------

@router.get("/api/projetos/{projeto_id}/auditoria-venda")
def auditoria(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    r = comercial.auditoria(db, carregar_projeto(db, emp, projeto_id))
    if r is None:
        raise HTTPException(404, "Projeto sem venda registrada pelo módulo comercial")
    return r


@router.post("/api/projetos/{projeto_id}/auditoria-venda/ciencia")
def ciencia(projeto_id: int, usuario: Usuario = Depends(APROVAR_VENDA), emp: Empresa = Depends(empresa_atual),
            db: Session = Depends(get_db)):
    from datetime import datetime
    projeto = carregar_projeto(db, emp, projeto_id)
    if not projeto.venda_resumo:
        raise HTTPException(404, "Projeto sem venda registrada pelo módulo comercial")
    projeto.auditoria_ciente_por, projeto.auditoria_ciente_em = usuario.nome, datetime.now()
    db.commit()
    return comercial.auditoria(db, projeto)


# --- Página pública da proposta (o cliente abre pelo link, sem login) --------------------------

def _versao_publica(db: Session, token: str) -> VersaoProposta:
    v = db.scalar(select(VersaoProposta).where(VersaoProposta.token_publico == token)) if len(token) >= 16 else None
    if v is None:
        raise HTTPException(404, "Proposta não encontrada ou substituída por uma versão mais nova")
    return v


def _brl(v: float) -> str:
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


@router.get("/p/{token}", response_class=HTMLResponse, include_in_schema=False)
def pagina_proposta(token: str, db: Session = Depends(get_db), aceita: int = 0):
    v = _versao_publica(db, token)
    op, c, r, e = v.oportunidade, v.calculo, v.resumo, html.escape
    empresa = db.get(Empresa, op.empresa_id)
    vencida = v.proposta_validade and v.proposta_validade < date.today()
    imagens = "".join(f'<figure><img src="/p/{e(token)}/imagens/{i.id}" alt="{e(i.legenda or i.nome)}" loading="lazy">'
                      f'{f"<figcaption>{e(i.legenda)}</figcaption>" if i.legenda else ""}</figure>' for i in op.imagens)
    ambientes = "".join(f"<li><b>{e(a['nome'])}</b> · {a['modulos']:g} módulo(s)</li>" for a in r["ambientes"])
    if v.aceite_em:
        acao = f'<div class="ok">Proposta aceita por <b>{e(v.aceite_nome)}</b> em {v.aceite_em:%d/%m/%Y %H:%M}. Obrigado!</div>'
    elif vencida or op.status != "ABERTA":
        acao = '<div class="aviso">Esta proposta não está mais disponível. Fale com seu consultor para uma versão atualizada.</div>'
    else:
        acao = f'''<form method="post" action="/p/{e(token)}/aceitar"><label>Seu nome completo
<input name="nome" required minlength="3" autocomplete="name"></label>
<button type="submit">Aceitar a proposta</button></form>'''
    return HTMLResponse(f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Proposta · {e(op.titulo)}</title><style>
body{{margin:0;font:16px/1.5 system-ui,Segoe UI,Roboto,sans-serif;background:#f6f4f1;color:#1d2330}}
main{{max-width:880px;margin:0 auto;padding:24px 16px 48px}} h1{{font-size:26px;margin:0}} .marca{{color:#b5651d;font-weight:700}}
.card{{background:#fff;border-radius:14px;padding:20px;margin-top:16px;box-shadow:0 1px 3px rgb(0 0 0/.08)}}
.galeria{{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}} figure{{margin:0}}
img{{width:100%;border-radius:10px;display:block}} figcaption{{font-size:13px;color:#677085;margin-top:4px}}
.valor{{font-size:34px;font-weight:800}} .sub{{color:#677085}} a.btn,button{{display:inline-block;background:#b5651d;color:#fff;border:0;
border-radius:10px;padding:12px 20px;font:inherit;font-weight:600;text-decoration:none;cursor:pointer}}
input{{font:inherit;padding:10px;border:1px solid #ccc;border-radius:8px;width:100%;margin:6px 0 12px;box-sizing:border-box}}
.ok{{background:#e3f4ea;padding:14px;border-radius:10px}} .aviso{{background:#fdf0dc;padding:14px;border-radius:10px}}
ul{{padding-left:20px}}</style></head><body><main>
<div class="marca">{e(empresa.nome)}</div>
<h1>{e(op.titulo)}</h1><div class="sub">Proposta para {e(op.cliente_nome)} · versão {v.numero}{f" · válida até {v.proposta_validade:%d/%m/%Y}" if v.proposta_validade else ""}</div>
{f'<div class="card"><div class="galeria">{imagens}</div></div>' if imagens else ""}
{f'<div class="card"><a class="btn" href="{e(op.link_3d)}" target="_blank" rel="noopener">Ver o projeto em 3D</a></div>' if op.link_3d else ""}
<div class="card"><b>Ambientes</b><ul>{ambientes}</ul></div>
<div class="card"><div class="sub">Investimento</div><div class="valor">{_brl(c["preco_final"])}</div>
<div>{e(c["condicao"])}{f" · {c['parcelas']}x de {_brl(c['parcela_valor'])}" if c["parcelas"] > 1 else ""}</div></div>
<div class="card">{acao}</div>
</main></body></html>""")


@router.get("/p/{token}/imagens/{imagem_id}", include_in_schema=False)
def imagem_publica(token: str, imagem_id: int, db: Session = Depends(get_db)):
    v = _versao_publica(db, token)
    img = db.get(ImagemProposta, imagem_id)
    if img is None or img.oportunidade_id != v.oportunidade_id:
        raise HTTPException(404, "Imagem não encontrada")
    return _arquivo(img)


@router.post("/p/{token}/aceitar", response_class=HTMLResponse, include_in_schema=False)
def aceitar_proposta(token: str, request: Request, nome: str = Form(""), db: Session = Depends(get_db)):
    v = _versao_publica(db, token)
    try:
        comercial.aceitar(db, v, nome, request.client.host if request.client else None)
    except comercial.ErroComercial as e:
        db.rollback()
        return HTMLResponse(f"<p style='font:16px system-ui;padding:24px'>{html.escape(str(e))}. <a href='/p/{html.escape(token)}'>Voltar</a></p>", status_code=e.status)
    db.commit()
    return pagina_proposta(token, db)
