"""Integração com o Promob Prices (prices-api.promob.com): tabela de preços vigente da conta.

Endpoints validados contra a API real:
- POST /api/TablesPrices/Search  (ordenar por "description"; a tabela vigente tem active=true)
- GET  /api/TablesPrices/{id}/Products/Csv  -> devolve a URL de um .zip com o CSV dos produtos
O token (JWT da conta) é só de gravação no ERP e nunca é devolvido pela API.
"""
import csv
import io
import zipfile
from datetime import datetime

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import ConfigComercial, PrecoPromob

BASE = "https://prices-api.promob.com/api"
TRANSPORTE: httpx.BaseTransport | None = None  # os testes injetam um Promob simulado


class ErroPrices(Exception):
    def __init__(self, mensagem: str, status: int = 502):
        super().__init__(mensagem)
        self.status = status


def _cliente(token: str | None = None) -> httpx.Client:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.Client(transport=TRANSPORTE, headers=headers, timeout=60, follow_redirects=True)


def _checa(r: httpx.Response, acao: str) -> None:
    if r.status_code in (401, 403):
        raise ErroPrices("O Promob Prices recusou o token: gere um token novo na conta e salve nas configurações comerciais", 422)
    if r.status_code >= 400:
        raise ErroPrices(f"Promob Prices respondeu {r.status_code} ao {acao}")


def listar_tabelas(token: str) -> list[dict]:
    corpo = {"pagination": {"skip": 0, "take": 100}, "orderBy": {"sortType": 0, "sortFieldName": "description"}}
    try:
        with _cliente(token) as c:
            r = c.post(f"{BASE}/TablesPrices/Search", json=corpo)
    except httpx.HTTPError as e:
        raise ErroPrices(f"Não foi possível falar com o Promob Prices ({type(e).__name__})")
    _checa(r, "listar as tabelas")
    return r.json().get("tablesPrices") or []


def _colunas(cabecalho: list[str]) -> tuple[int, int | None, int]:
    nomes = [c.strip().lower() for c in cabecalho]
    def achar(*chaves):
        return next((i for i, n in enumerate(nomes) if any(k in n for k in chaves)), None)
    sku = achar("sku", "refer", "código", "codigo", "code")
    desc = achar("descri", "description", "nome")
    preco = achar("preço", "preco", "price", "valor")
    if sku is None or preco is None:
        raise ErroPrices(f"CSV do Promob Prices em formato inesperado: colunas {cabecalho}", 422)
    return sku, desc, preco


def _numero(texto: str) -> float | None:
    t = (texto or "").strip().replace("R$", "").replace(" ", "")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def ler_csv(conteudo: bytes) -> list[tuple[str, str, float]]:
    texto = conteudo.decode("utf-8-sig", errors="replace")
    separador = ";" if texto.split("\n", 1)[0].count(";") >= texto.split("\n", 1)[0].count(",") else ","
    linhas = list(csv.reader(io.StringIO(texto), delimiter=separador))
    if not linhas:
        return []
    i_sku, i_desc, i_preco = _colunas(linhas[0])
    itens = []
    for ln in linhas[1:]:
        if len(ln) <= max(i_sku, i_preco):
            continue
        preco = _numero(ln[i_preco])
        if ln[i_sku].strip() and preco is not None:
            itens.append((ln[i_sku].strip(), ln[i_desc].strip() if i_desc is not None and len(ln) > i_desc else "", preco))
    return itens


def sincronizar(db: Session, cfg: ConfigComercial) -> dict:
    if not cfg.prices_token:
        raise ErroPrices("Salve o token do Promob Prices nas configurações comerciais antes de sincronizar", 422)
    tabelas = listar_tabelas(cfg.prices_token)
    ativa = next((t for t in tabelas if t.get("active")), None)
    if ativa is None:
        raise ErroPrices("Nenhuma tabela ativa na conta do Promob Prices", 422)
    try:
        with _cliente(cfg.prices_token) as c:
            r = c.get(f"{BASE}/TablesPrices/{ativa['id']}/Products/Csv")
            _checa(r, "exportar a tabela")
            url = r.text.strip().strip('"')
            with _cliente() as livre:  # o .zip fica num armazenamento público com assinatura na URL
                z = livre.get(url)
            _checa(z, "baixar o arquivo da tabela")
    except httpx.HTTPError as e:
        raise ErroPrices(f"Não foi possível baixar a tabela do Promob Prices ({type(e).__name__})")
    with zipfile.ZipFile(io.BytesIO(z.content)) as arq:
        nome = next((n for n in arq.namelist() if n.lower().endswith(".csv")), None)
        if nome is None:
            raise ErroPrices("O arquivo do Promob Prices não trouxe CSV", 422)
        itens = ler_csv(arq.read(nome))
    db.execute(delete(PrecoPromob).where(PrecoPromob.empresa_id == cfg.empresa_id))
    db.add_all(PrecoPromob(empresa_id=cfg.empresa_id, sku=s[:80], descricao=d[:300], preco=p) for s, d, p in itens)
    cfg.prices_tabela = str(ativa.get("description") or ativa.get("id"))[:200]
    cfg.prices_sincronizado_em = datetime.now()
    db.flush()
    return {"tabela": cfg.prices_tabela, "itens": len(itens), "sincronizado_em": cfg.prices_sincronizado_em}
