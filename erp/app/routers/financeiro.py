from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import FINANCEIRO
from ..models import Fornecedor, Lancamento, Projeto, TipoLancamento, Usuario
from ..schemas import BaixaIn, ContratoIn, DREObra, FluxoCaixa, LancamentoIn, LancamentoOut, ProjetoResumo
from ..services import financeiro

router = APIRouter(prefix="/api", tags=["financeiro"])
# Valores financeiros só para administrador, gestor e financeiro (leitura inclusive)


def _projeto(db: Session, empresa_id: int, projeto_id: int) -> Projeto:
    projeto = db.get(Projeto, projeto_id)
    if projeto is None or projeto.empresa_id != empresa_id:
        raise HTTPException(404, "Projeto não encontrado")
    return projeto


def _out(l: Lancamento) -> dict:
    hoje = date.today()
    situacao = "PAGO" if l.pago_em else ("VENCIDO" if l.vencimento < hoje else "ABERTO")
    return {
        "id": l.id, "tipo": l.tipo, "categoria": l.categoria, "descricao": l.descricao, "valor": l.valor,
        "vencimento": l.vencimento, "pago_em": l.pago_em, "valor_pago": l.valor_pago,
        "projeto_id": l.projeto_id, "projeto_codigo": l.projeto.codigo if l.projeto else None,
        "pedido_id": l.pedido_id, "fornecedor_nome": l.fornecedor.nome if l.fornecedor else None,
        "cliente_nome": l.cliente.nome if l.cliente else None, "situacao": situacao,
    }


@router.post("/projetos/{projeto_id}/contrato", response_model=ProjetoResumo)
def contrato(projeto_id: int, dados: ContratoIn, usuario: Usuario = Depends(FINANCEIRO),
             db: Session = Depends(get_db)):
    projeto = _projeto(db, usuario.empresa_id, projeto_id)
    try:
        financeiro.registrar_contrato(db, projeto, dados.valor_venda, dados.parcelas,
                                      dados.primeiro_vencimento, usuario.id)
    except financeiro.ErroFinanceiro as e:
        db.rollback()
        raise HTTPException(e.status, str(e))
    db.commit()
    return projeto


@router.get("/projetos/{projeto_id}/dre", response_model=DREObra)
def dre(projeto_id: int, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    return financeiro.dre_obra(db, _projeto(db, usuario.empresa_id, projeto_id))


@router.get("/lancamentos", response_model=list[LancamentoOut])
def listar(tipo: TipoLancamento | None = None, situacao: str | None = None, projeto_id: int | None = None,
           usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    consulta = select(Lancamento).where(Lancamento.empresa_id == usuario.empresa_id)
    if tipo:
        consulta = consulta.where(Lancamento.tipo == tipo)
    if projeto_id:
        consulta = consulta.where(Lancamento.projeto_id == projeto_id)
    saida = [_out(l) for l in db.scalars(consulta.order_by(Lancamento.vencimento, Lancamento.id))]
    if situacao:
        saida = [l for l in saida if l["situacao"] == situacao.upper()
                 or (situacao.upper() == "EM_ABERTO" and l["situacao"] != "PAGO")]
    return saida


@router.post("/lancamentos", response_model=LancamentoOut, status_code=201)
def criar(dados: LancamentoIn, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    if dados.projeto_id is not None:
        _projeto(db, usuario.empresa_id, dados.projeto_id)
    if dados.fornecedor_id is not None:
        f = db.get(Fornecedor, dados.fornecedor_id)
        if f is None or f.empresa_id != usuario.empresa_id:
            raise HTTPException(404, "Fornecedor não encontrado")
    lanc = Lancamento(empresa_id=usuario.empresa_id, usuario_id=usuario.id, **dados.model_dump())
    db.add(lanc)
    db.commit()
    return _out(lanc)


def _carregar(db: Session, empresa_id: int, lanc_id: int) -> Lancamento:
    lanc = db.get(Lancamento, lanc_id)
    if lanc is None or lanc.empresa_id != empresa_id:
        raise HTTPException(404, "Lançamento não encontrado")
    return lanc


@router.post("/lancamentos/{lanc_id}/baixar", response_model=LancamentoOut)
def baixar(lanc_id: int, dados: BaixaIn, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    lanc = _carregar(db, usuario.empresa_id, lanc_id)
    try:
        financeiro.baixar(lanc, dados.data, dados.valor)
    except financeiro.ErroFinanceiro as e:
        raise HTTPException(e.status, str(e))
    db.commit()
    return _out(lanc)


@router.delete("/lancamentos/{lanc_id}", status_code=204)
def excluir(lanc_id: int, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    lanc = _carregar(db, usuario.empresa_id, lanc_id)
    if lanc.pago_em:
        raise HTTPException(409, "Lançamento já baixado não pode ser excluído")
    db.delete(lanc)
    db.commit()


@router.get("/financeiro/fluxo", response_model=FluxoCaixa)
def fluxo(meses: int = 6, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    return financeiro.fluxo_caixa(db, usuario.empresa_id, max(1, min(meses, 24)))
