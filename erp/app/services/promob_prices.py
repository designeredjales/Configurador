"""Integração com o Promob Prices (prices-api.promob.com): tabela de preços vigente da conta.

Endpoints validados contra a API real:
- POST /api/TablesPrices/Search  (ordenar por "description"; a tabela vigente tem active=true)
- GET  /api/TablesPrices/{id}/Products/Csv  -> devolve a URL de um .zip com o CSV dos produtos
O token (JWT da conta) é só de gravação no ERP e nunca é devolvido pela API.
Endereço, tabela e colunas do CSV fazem parte do setup de cada base (ConfigComercial).
"""
import csv
import io
import zipfile
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ..models import ConfigComercial, PrecoPromob

BASE = "https://prices-api.promob.com/api"
HOSTS_PERMITIDOS = ("promob.com",)  # o token só viaja para domínios da Promob
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


def base_url(cfg: ConfigComercial | None = None) -> str:
    url = ((cfg.prices_url if cfg else None) or BASE).strip().rstrip("/")
    validar_url(url)
    return url


def validar_url(url: str) -> None:
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not any(host == h or host.endswith("." + h) for h in HOSTS_PERMITIDOS):
        raise ErroPrices("Endereço do Promob Prices inválido: use https num domínio promob.com", 422)


def listar_tabelas(token: str, base: str = BASE) -> list[dict]:
    corpo = {"pagination": {"skip": 0, "take": 100}, "orderBy": {"sortType": 0, "sortFieldName": "description"}}
    try:
        with _cliente(token) as c:
            r = c.post(f"{base}/TablesPrices/Search", json=corpo)
    except httpx.HTTPError as e:
        raise ErroPrices(f"Não foi possível falar com o Promob Prices ({type(e).__name__})")
    _checa(r, "listar as tabelas")
    return r.json().get("tablesPrices") or []


def _colunas(cabecalho: list[str], mapa: dict | None = None) -> tuple[int, int | None, int]:
    nomes = [c.strip().lower() for c in cabecalho]
    def exata(chave):  # coluna escolhida no setup da base (nome exato do cabeçalho)
        alvo = ((mapa or {}).get(chave) or "").strip().lower()
        if not alvo:
            return None
        if alvo not in nomes:
            raise ErroPrices(f"Coluna '{mapa[chave]}' do setup não existe no CSV. Colunas recebidas: {cabecalho}", 422)
        return nomes.index(alvo)
    def achar(*chaves):
        return next((i for i, n in enumerate(nomes) if any(k in n for k in chaves)), None)
    sku = exata("sku")
    sku = achar("sku", "refer", "código", "codigo", "code") if sku is None else sku
    desc = exata("descricao")
    desc = achar("descri", "description", "nome") if desc is None else desc
    preco = exata("preco")
    preco = achar("preço", "preco", "price", "valor") if preco is None else preco
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


def _linhas(conteudo: bytes) -> tuple[str, list[list[str]]]:
    texto = conteudo.decode("utf-8-sig", errors="replace")
    separador = ";" if texto.split("\n", 1)[0].count(";") >= texto.split("\n", 1)[0].count(",") else ","
    return separador, list(csv.reader(io.StringIO(texto), delimiter=separador))


def ler_csv(conteudo: bytes, mapa: dict | None = None) -> list[tuple[str, str, float]]:
    _, linhas = _linhas(conteudo)
    if not linhas:
        return []
    i_sku, i_desc, i_preco = _colunas(linhas[0], mapa)
    itens = []
    for ln in linhas[1:]:
        if len(ln) <= max(i_sku, i_preco):
            continue
        preco = _numero(ln[i_preco])
        if ln[i_sku].strip() and preco is not None:
            itens.append((ln[i_sku].strip(), ln[i_desc].strip() if i_desc is not None and len(ln) > i_desc else "", preco))
    return itens


def _escolher_tabela(cfg: ConfigComercial, tabelas: list[dict]) -> dict:
    preferida = (cfg.prices_tabela_preferida or "").strip().lower()
    if preferida:
        t = next((t for t in tabelas if str(t.get("description") or "").strip().lower() == preferida
                  or str(t.get("id")) == preferida), None)
        if t is None:
            nomes = ", ".join(str(t.get("description")) for t in tabelas[:15])
            raise ErroPrices(f"Tabela '{cfg.prices_tabela_preferida}' não encontrada na conta. Tabelas: {nomes}", 422)
        return t
    ativa = next((t for t in tabelas if t.get("active")), None)
    if ativa is None:
        raise ErroPrices("Nenhuma tabela ativa na conta do Promob Prices", 422)
    return ativa


def _baixar_csv(cfg: ConfigComercial, base: str, tabela: dict) -> tuple[str, bytes]:
    try:
        with _cliente(cfg.prices_token) as c:
            r = c.get(f"{base}/TablesPrices/{tabela['id']}/Products/Csv")
            _checa(r, "exportar a tabela")
            url = r.text.strip().strip('"')
            with _cliente() as livre:  # o .zip fica num armazenamento público com assinatura na URL
                z = livre.get(url)
            _checa(z, "baixar o arquivo da tabela")
    except httpx.HTTPError as e:
        raise ErroPrices(f"Não foi possível baixar a tabela do Promob Prices ({type(e).__name__})")
    try:
        with zipfile.ZipFile(io.BytesIO(z.content)) as arq:
            nome = next((n for n in arq.namelist() if n.lower().endswith(".csv")), None)
            if nome is None:
                raise ErroPrices(f"O arquivo do Promob Prices não trouxe CSV (conteúdo: {arq.namelist()[:10]})", 422)
            return nome, arq.read(nome)
    except zipfile.BadZipFile:
        raise ErroPrices("O Promob Prices não devolveu um .zip na exportação da tabela", 422)


def _exigir_token(cfg: ConfigComercial) -> None:
    if not cfg.prices_token:
        raise ErroPrices("Salve o token do Promob Prices nas configurações comerciais antes de sincronizar", 422)


def diagnosticar(cfg: ConfigComercial) -> dict:
    """Mostra os formatos que a conta devolve (tabelas e CSV), sem gravar nada: base para ajustar o setup."""
    _exigir_token(cfg)
    base = base_url(cfg)
    tabelas = listar_tabelas(cfg.prices_token, base)
    escolhida = _escolher_tabela(cfg, tabelas)
    nome, conteudo = _baixar_csv(cfg, base, escolhida)
    separador, linhas = _linhas(conteudo)
    cabecalho = linhas[0] if linhas else []
    try:
        i_sku, i_desc, i_preco = _colunas(cabecalho, cfg.prices_colunas)
        mapeamento, erro = {"sku": cabecalho[i_sku], "descricao": cabecalho[i_desc] if i_desc is not None else None,
                            "preco": cabecalho[i_preco]}, None
    except ErroPrices as e:
        mapeamento, erro = None, str(e)
    campos = sorted({k for t in tabelas for k in t.keys()})
    return {"endereco": base, "tabelas": [{k: t.get(k) for k in ("id", "description", "active")} for t in tabelas],
            "campos_da_tabela": campos, "tabela_escolhida": escolhida.get("description") or escolhida.get("id"),
            "arquivo_csv": nome, "separador": separador, "cabecalho": cabecalho, "linhas_exemplo": linhas[1:6],
            "total_linhas": max(0, len(linhas) - 1), "mapeamento": mapeamento, "erro_mapeamento": erro}


def sincronizar(db: Session, cfg: ConfigComercial) -> dict:
    _exigir_token(cfg)
    base = base_url(cfg)
    ativa = _escolher_tabela(cfg, listar_tabelas(cfg.prices_token, base))
    _, conteudo = _baixar_csv(cfg, base, ativa)
    itens = ler_csv(conteudo, cfg.prices_colunas)
    db.execute(delete(PrecoPromob).where(PrecoPromob.empresa_id == cfg.empresa_id))
    db.add_all(PrecoPromob(empresa_id=cfg.empresa_id, sku=s[:80], descricao=d[:300], preco=p) for s, d, p in itens)
    cfg.prices_tabela = str(ativa.get("description") or ativa.get("id"))[:200]
    cfg.prices_sincronizado_em = datetime.now()
    db.flush()
    return {"tabela": cfg.prices_tabela, "itens": len(itens), "sincronizado_em": cfg.prices_sincronizado_em}
