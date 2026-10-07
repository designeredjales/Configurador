"""NF-e de venda por emissor integrado (Focus NFe, API v2).

O ERP monta e valida a nota; o emissor assina, transmite à SEFAZ e devolve o
resultado. Tributação (NCM, CFOP, CSOSN) é configuração da empresa e deve ser
validada pelo contador antes de sair de homologação.
"""
import re
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Cliente, Empresa, NotaFiscal, Projeto, StatusNota

URLS = {"homologacao": "https://homologacao.focusnfe.com.br", "producao": "https://api.focusnfe.com.br"}
TRANSPORTE: httpx.BaseTransport | None = None  # testes injetam um transporte simulado


class ErroFiscal(ValueError):
    def __init__(self, mensagem: str, status: int = 422, pendencias: list[str] | None = None):
        super().__init__(mensagem)
        self.status = status
        self.pendencias = pendencias or []


def _digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def pendencias(empresa: Empresa, cliente: Cliente | None, valor: float) -> list[str]:
    erros = []
    if len(_digitos(empresa.cnpj)) != 14:
        erros.append("Empresa: CNPJ com 14 dígitos")
    if not empresa.uf:
        erros.append("Empresa: UF")
    if not empresa.fiscal_token:
        erros.append("Empresa: token do emissor de NF-e")
    if len(_digitos(empresa.ncm_padrao)) != 8:
        erros.append("Empresa: NCM padrão com 8 dígitos")
    if cliente is None:
        erros.append("Projeto sem cliente vinculado")
        return erros
    doc = _digitos(cliente.documento)
    if len(doc) not in (11, 14):
        erros.append("Cliente: CPF (11) ou CNPJ (14 dígitos)")
    for campo, rotulo in (("logradouro", "logradouro"), ("numero", "número"), ("bairro", "bairro"),
                          ("cidade", "município"), ("uf", "UF")):
        if not (getattr(cliente, campo) or "").strip():
            erros.append(f"Cliente: {rotulo}")
    if len(_digitos(cliente.cep)) != 8:
        erros.append("Cliente: CEP com 8 dígitos")
    if valor <= 0:
        erros.append("Valor da nota maior que zero")
    return erros


def montar_payload(empresa: Empresa, projeto: Projeto, cliente: Cliente, valor: float, descricao: str) -> dict:
    interna = (cliente.uf or "").upper() == (empresa.uf or "").upper()
    doc = _digitos(cliente.documento)
    destinatario = {"cpf_destinatario": doc} if len(doc) == 11 else {"cnpj_destinatario": doc}
    return {
        "natureza_operacao": "Venda de produção do estabelecimento",
        "data_emissao": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tipo_documento": 1,
        "local_destino": 1 if interna else 2,
        "finalidade_emissao": 1,
        "consumidor_final": 1,
        "presenca_comprador": 1,
        "cnpj_emitente": _digitos(empresa.cnpj),
        "nome_destinatario": cliente.nome,
        **destinatario,
        "indicador_inscricao_estadual_destinatario": 9,
        "logradouro_destinatario": cliente.logradouro,
        "numero_destinatario": cliente.numero,
        "complemento_destinatario": cliente.complemento or None,
        "bairro_destinatario": cliente.bairro,
        "municipio_destinatario": cliente.cidade,
        "uf_destinatario": (cliente.uf or "").upper(),
        "cep_destinatario": _digitos(cliente.cep),
        "email_destinatario": cliente.email or None,
        "modalidade_frete": 9,
        "valor_produtos": round(valor, 2),
        "valor_total": round(valor, 2),
        "items": [{
            "numero_item": 1,
            "codigo_produto": projeto.codigo,
            "descricao": descricao[:120],
            "cfop": empresa.cfop_interno if interna else empresa.cfop_interestadual,
            "codigo_ncm": _digitos(empresa.ncm_padrao),
            "unidade_comercial": "UN", "quantidade_comercial": 1, "valor_unitario_comercial": round(valor, 2),
            "unidade_tributavel": "UN", "quantidade_tributavel": 1, "valor_unitario_tributavel": round(valor, 2),
            "valor_bruto": round(valor, 2),
            "icms_origem": 0,
            "icms_situacao_tributaria": empresa.csosn_padrao,
            "pis_situacao_tributaria": "07",
            "cofins_situacao_tributaria": "07",
        }],
    }


def _base(empresa: Empresa) -> str:
    return URLS.get(empresa.fiscal_ambiente, URLS["homologacao"])


def _cliente(empresa: Empresa) -> httpx.Client:
    return httpx.Client(base_url=_base(empresa),
                        auth=(empresa.fiscal_token or "", ""), timeout=30, transport=TRANSPORTE)


def _aplicar_retorno(nota: NotaFiscal, dados: dict, base: str) -> None:
    status = dados.get("status", "")
    if status == "autorizado":
        nota.status = StatusNota.AUTORIZADA
    elif status in ("erro_autorizacao", "denegado"):
        nota.status = StatusNota.ERRO
    elif status == "cancelado":
        nota.status = StatusNota.CANCELADA
    else:
        nota.status = StatusNota.PROCESSANDO
    nota.numero = dados.get("numero") or nota.numero
    nota.serie = dados.get("serie") or nota.serie
    nota.chave = dados.get("chave_nfe") or nota.chave
    if dados.get("caminho_danfe"):
        nota.url_danfe = base + dados["caminho_danfe"]
    if dados.get("caminho_xml_nota_fiscal"):
        nota.url_xml = base + dados["caminho_xml_nota_fiscal"]
    nota.mensagem = dados.get("mensagem_sefaz") or dados.get("mensagem") or nota.mensagem
    nota.atualizado_em = datetime.now()


def emitir(db: Session, empresa: Empresa, projeto: Projeto, valor: float | None, descricao: str | None,
           usuario_id: int | None) -> NotaFiscal:
    ativa = db.scalar(select(NotaFiscal).where(
        NotaFiscal.projeto_id == projeto.id, NotaFiscal.status.in_([StatusNota.PROCESSANDO, StatusNota.AUTORIZADA])))
    if ativa:
        raise ErroFiscal(f"O projeto já tem a nota {ativa.ref} {ativa.status.lower()}", 409)
    valor = round(valor if valor is not None else (projeto.valor_venda or 0), 2)
    cliente = projeto.cliente
    faltando = pendencias(empresa, cliente, valor)
    if faltando:
        raise ErroFiscal("Dados incompletos para emitir a NF-e", 422, faltando)
    ambientes = ", ".join(a.nome for a in projeto.ambientes) or "projeto"
    descricao = descricao or f"Móveis sob medida ({ambientes}) conforme projeto {projeto.codigo}"
    tentativa = db.scalar(select(NotaFiscal.id).where(NotaFiscal.projeto_id == projeto.id).order_by(NotaFiscal.id.desc()))
    ref = f"E{empresa.id}-{projeto.codigo}-{(tentativa or 0) + 1}"
    nota = NotaFiscal(empresa_id=empresa.id, projeto_id=projeto.id, ref=ref, ambiente=empresa.fiscal_ambiente,
                      valor=valor, usuario_id=usuario_id)
    db.add(nota)
    payload = montar_payload(empresa, projeto, cliente, valor, descricao)
    try:
        with _cliente(empresa) as http:
            r = http.post("/v2/nfe", params={"ref": ref}, json=payload)
    except httpx.HTTPError as e:
        raise ErroFiscal(f"Não foi possível falar com o emissor de NF-e: {e}", 502) from e
    dados = _json(r)
    if r.status_code >= 400:
        detalhes = "; ".join(f"{x.get('campo', '')}: {x.get('mensagem', '')}" for x in dados.get("erros", []))
        nota.status = StatusNota.ERRO
        nota.mensagem = (dados.get("mensagem") or f"Erro {r.status_code}") + (f" ({detalhes})" if detalhes else "")
    else:
        _aplicar_retorno(nota, dados, _base(empresa))
    db.flush()
    return nota


def consultar(empresa: Empresa, nota: NotaFiscal) -> None:
    try:
        with _cliente(empresa) as http:
            r = http.get(f"/v2/nfe/{nota.ref}")
    except httpx.HTTPError as e:
        raise ErroFiscal(f"Não foi possível falar com o emissor de NF-e: {e}", 502) from e
    if r.status_code >= 400:
        raise ErroFiscal(_json(r).get("mensagem") or f"Erro {r.status_code} ao consultar a nota", 502)
    _aplicar_retorno(nota, _json(r), _base(empresa))


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {"mensagem": r.text[:300]}
