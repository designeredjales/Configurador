from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import FINANCEIRO, exigir
from ..models import Perfil
from ..models import Fornecedor, Lancamento, MovimentoBancario, NotaFiscal, Projeto, TipoLancamento, Usuario
from ..schemas import (
    BaixaIn,
    ConciliarIn,
    ContratoIn,
    DREObra,
    EmitirNotaIn,
    FluxoCaixa,
    LancamentoIn,
    LancamentoOut,
    LancarMovimentoIn,
    MovimentoBancarioOut,
    NotaOut,
    ProjetoResumo,
)
from ..services import conciliacao, financeiro, fiscal, indicadores

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


@router.get("/indicadores")
def painel_do_dono(dias: int = 90, usuario: Usuario = Depends(exigir(Perfil.GESTOR)),
                   db: Session = Depends(get_db)):
    """Indicadores consolidados (administrador e gestor)."""
    return indicadores.calcular(db, usuario.empresa_id, max(7, min(dias, 730)))


# --- Conciliação bancária ---------------------------------------------------------

def _mov_out(db: Session, m: MovimentoBancario) -> dict:
    situacao = "CONCILIADO" if m.lancamento_id else ("IGNORADO" if m.ignorado else "PENDENTE")
    sug = conciliacao.sugestoes(db, m.empresa_id, m) if situacao == "PENDENTE" else []
    return {
        "id": m.id, "data": m.data, "valor": m.valor, "descricao": m.descricao, "situacao": situacao,
        "lancamento_id": m.lancamento_id, "lancamento_descricao": m.lancamento.descricao if m.lancamento else None,
        "sugestoes": [{"lancamento_id": l.id, "descricao": l.descricao, "vencimento": l.vencimento, "valor": l.valor} for l in sug],
    }


def _mov(db: Session, empresa_id: int, mov_id: int) -> MovimentoBancario:
    m = db.get(MovimentoBancario, mov_id)
    if m is None or m.empresa_id != empresa_id:
        raise HTTPException(404, "Movimento não encontrado")
    return m


@router.post("/conciliacao/importar")
async def importar_extrato(arquivo: UploadFile = File(...), usuario: Usuario = Depends(FINANCEIRO),
                           db: Session = Depends(get_db)):
    try:
        resultado = conciliacao.importar(db, usuario.empresa_id, await arquivo.read(), usuario.id)
    except (conciliacao.ErroOFX, ValueError) as e:
        db.rollback()
        raise HTTPException(422, str(e))
    db.commit()
    return resultado


@router.get("/conciliacao", response_model=list[MovimentoBancarioOut])
def movimentos_bancarios(pendentes: bool = False, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    consulta = select(MovimentoBancario).where(MovimentoBancario.empresa_id == usuario.empresa_id)
    if pendentes:
        consulta = consulta.where(MovimentoBancario.lancamento_id.is_(None), MovimentoBancario.ignorado.is_(False))
    return [_mov_out(db, m) for m in db.scalars(consulta.order_by(MovimentoBancario.data.desc(), MovimentoBancario.id))]


@router.post("/conciliacao/{mov_id}/conciliar", response_model=MovimentoBancarioOut)
def conciliar(mov_id: int, dados: ConciliarIn, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    m = _mov(db, usuario.empresa_id, mov_id)
    lanc = _carregar(db, usuario.empresa_id, dados.lancamento_id)
    try:
        conciliacao.conciliar(db, m, lanc)
    except conciliacao.ErroOFX as e:
        raise HTTPException(409, str(e))
    db.commit()
    return _mov_out(db, m)


@router.post("/conciliacao/{mov_id}/lancar", response_model=MovimentoBancarioOut)
def lancar(mov_id: int, dados: LancarMovimentoIn, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    """Movimento sem conta correspondente (tarifa, despesa sem lançamento): cria a conta já baixada."""
    m = _mov(db, usuario.empresa_id, mov_id)
    if m.lancamento_id or m.ignorado:
        raise HTTPException(409, "Movimento já conciliado ou ignorado.")
    if dados.projeto_id is not None:
        _projeto(db, usuario.empresa_id, dados.projeto_id)
    lanc = Lancamento(
        empresa_id=usuario.empresa_id, tipo=TipoLancamento.RECEBER if m.valor > 0 else TipoLancamento.PAGAR,
        categoria=dados.categoria, descricao=(dados.descricao or m.descricao or "Movimento bancário")[:200],
        valor=abs(m.valor), vencimento=m.data, pago_em=m.data, valor_pago=abs(m.valor),
        projeto_id=dados.projeto_id, usuario_id=usuario.id,
    )
    db.add(lanc)
    db.flush()
    m.lancamento_id = lanc.id
    db.commit()
    return _mov_out(db, m)


@router.post("/conciliacao/{mov_id}/ignorar", response_model=MovimentoBancarioOut)
def ignorar(mov_id: int, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    m = _mov(db, usuario.empresa_id, mov_id)
    if m.lancamento_id:
        raise HTTPException(409, "Movimento já conciliado.")
    m.ignorado = True
    db.commit()
    return _mov_out(db, m)


# --- NF-e ------------------------------------------------------------------------

def _nota(db: Session, empresa_id: int, nota_id: int) -> NotaFiscal:
    n = db.get(NotaFiscal, nota_id)
    if n is None or n.empresa_id != empresa_id:
        raise HTTPException(404, "Nota não encontrada")
    return n


@router.post("/projetos/{projeto_id}/nfe", response_model=NotaOut, status_code=201)
def emitir_nfe(projeto_id: int, dados: EmitirNotaIn, usuario: Usuario = Depends(FINANCEIRO),
               db: Session = Depends(get_db)):
    projeto = _projeto(db, usuario.empresa_id, projeto_id)
    try:
        nota = fiscal.emitir(db, usuario.empresa, projeto, dados.valor, dados.descricao, usuario.id)
    except fiscal.ErroFiscal as e:
        db.rollback()
        detalhe = {"mensagem": str(e), "pendencias": e.pendencias} if e.pendencias else str(e)
        raise HTTPException(e.status, detalhe)
    db.commit()
    return nota


@router.get("/notas", response_model=list[NotaOut])
def notas(projeto_id: int | None = None, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    consulta = select(NotaFiscal).where(NotaFiscal.empresa_id == usuario.empresa_id)
    if projeto_id:
        consulta = consulta.where(NotaFiscal.projeto_id == projeto_id)
    return db.scalars(consulta.order_by(NotaFiscal.id.desc()))


@router.post("/notas/{nota_id}/consultar", response_model=NotaOut)
def consultar_nfe(nota_id: int, usuario: Usuario = Depends(FINANCEIRO), db: Session = Depends(get_db)):
    nota = _nota(db, usuario.empresa_id, nota_id)
    try:
        fiscal.consultar(usuario.empresa, nota)
    except fiscal.ErroFiscal as e:
        raise HTTPException(e.status, str(e))
    db.commit()
    return nota
