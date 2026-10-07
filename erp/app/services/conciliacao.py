"""Conciliação bancária: lê o extrato OFX e casa os movimentos com as contas em aberto."""
import re
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Lancamento, MovimentoBancario, TipoLancamento

JANELA_DIAS = 7  # tolerância entre vencimento e data do movimento


class ErroOFX(ValueError):
    pass


def _campo(bloco: str, tag: str) -> str | None:
    # OFX 1.x (SGML, sem fechamento) e 2.x (XML) usam <TAG>valor
    m = re.search(rf"<{tag}>([^<\r\n]*)", bloco, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _data(valor: str) -> date:
    return datetime.strptime(valor[:8], "%Y%m%d").date()


def ler_ofx(conteudo: bytes) -> list[dict]:
    try:
        texto = conteudo.decode("utf-8")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1")  # OFX 1.x de bancos brasileiros costuma vir em CP1252/latin-1
    if "<OFX>" not in texto.upper():
        raise ErroOFX("Arquivo não parece um extrato OFX. Exporte o extrato no internet banking em formato OFX.")
    movimentos = []
    for bloco in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", texto, re.S | re.I):
        valor, data, fitid = _campo(bloco, "TRNAMT"), _campo(bloco, "DTPOSTED"), _campo(bloco, "FITID")
        if not (valor and data and fitid):
            continue
        movimentos.append({
            "fitid": fitid, "data": _data(data), "valor": round(float(valor.replace(",", ".")), 2),
            "descricao": _campo(bloco, "MEMO") or _campo(bloco, "NAME") or "",
        })
    if not movimentos:
        raise ErroOFX("Nenhum movimento encontrado no extrato.")
    return movimentos


def sugestoes(db: Session, empresa_id: int, mov: MovimentoBancario) -> list[Lancamento]:
    """Contas em aberto do mesmo sentido e valor, com vencimento perto da data do movimento."""
    tipo = TipoLancamento.RECEBER if mov.valor > 0 else TipoLancamento.PAGAR
    candidatos = db.scalars(select(Lancamento).where(
        Lancamento.empresa_id == empresa_id, Lancamento.tipo == tipo, Lancamento.pago_em.is_(None),
        Lancamento.vencimento.between(mov.data - timedelta(days=JANELA_DIAS), mov.data + timedelta(days=JANELA_DIAS)),
    ))
    iguais = [l for l in candidatos if abs(l.valor - abs(mov.valor)) < 0.01]
    return sorted(iguais, key=lambda l: abs((l.vencimento - mov.data).days))


def importar(db: Session, empresa_id: int, conteudo: bytes, usuario_id: int | None) -> dict:
    lidos = ler_ofx(conteudo)
    existentes = set(db.scalars(select(MovimentoBancario.fitid).where(MovimentoBancario.empresa_id == empresa_id)))
    novos = 0
    for m in lidos:
        if m["fitid"] in existentes:
            continue
        db.add(MovimentoBancario(empresa_id=empresa_id, usuario_id=usuario_id, **m))
        existentes.add(m["fitid"])
        novos += 1
    db.flush()
    return {"lidos": len(lidos), "novos": novos, "repetidos": len(lidos) - novos}


def conciliar(db: Session, mov: MovimentoBancario, lanc: Lancamento) -> None:
    if mov.lancamento_id or mov.ignorado:
        raise ErroOFX("Movimento já conciliado ou ignorado.")
    if lanc.pago_em:
        raise ErroOFX(f"O lançamento '{lanc.descricao}' já foi baixado.")
    if (mov.valor > 0) != (lanc.tipo == TipoLancamento.RECEBER):
        raise ErroOFX("Entrada no banco só concilia com conta a receber, e saída com conta a pagar.")
    lanc.pago_em, lanc.valor_pago = mov.data, abs(mov.valor)
    mov.lancamento_id = lanc.id
