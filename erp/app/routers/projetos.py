from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ENGENHARIA, empresa_atual
from ..models import Cliente, Empresa, Projeto, StatusProjeto
from ..schemas import ConsumoProjeto, ProjetoIn, ProjetoOut, ProjetoResumo, ResultadoImportacao
from ..services import engenharia
from ..services.importacao import ErroImportacao, eh_xml, importar_csv, importar_promob_xml

router = APIRouter(prefix="/api/projetos", tags=["engenharia"])


def carregar(db: Session, emp: Empresa, projeto_id: int) -> Projeto:
    projeto = db.get(Projeto, projeto_id)
    if projeto is None or projeto.empresa_id != emp.id:
        raise HTTPException(404, "Projeto não encontrado")
    return projeto


@router.get("", response_model=list[ProjetoResumo])
def listar(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return db.scalars(
        select(Projeto).where(Projeto.empresa_id == emp.id).order_by(Projeto.criado_em.desc())
    )


@router.post("", response_model=ProjetoResumo, status_code=201, dependencies=[Depends(ENGENHARIA)])
def criar(dados: ProjetoIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    if dados.cliente_id is not None:
        cliente = db.get(Cliente, dados.cliente_id)
        if cliente is None or cliente.empresa_id != emp.id:
            raise HTTPException(404, "Cliente não encontrado")
    projeto = Projeto(empresa_id=emp.id, **dados.model_dump())
    db.add(projeto)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Projeto {dados.codigo} já existe")
    return projeto


@router.post("/importar-xml", response_model=ResultadoImportacao, status_code=201,
             dependencies=[Depends(ENGENHARIA)])
async def novo_por_xml(arquivo: UploadFile = File(...), codigo: str | None = Form(None),
                       nome: str | None = Form(None), emp: Empresa = Depends(empresa_atual),
                       db: Session = Depends(get_db)):
    """Cria o projeto inteiro a partir do XML do Promob (entrada padrão do ERP)."""
    bruto = await arquivo.read()
    if not eh_xml(bruto):
        raise HTTPException(422, "Envie o XML exportado do Promob (Orçamento-Explodido c/ Operação).")
    base = (arquivo.filename or "Projeto Promob").rsplit(".", 1)[0]
    codigo = (codigo or "").strip() or _proximo_codigo(db, emp.id)
    projeto = Projeto(empresa_id=emp.id, codigo=codigo, nome=(nome or "").strip() or base)
    db.add(projeto)
    try:
        db.flush()
        resultado = importar_promob_xml(db, projeto, bruto)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Projeto {codigo} já existe")
    except ErroImportacao as e:
        db.rollback()
        raise HTTPException(422, str(e))
    if resultado["cliente"] and not (nome or "").strip():
        projeto.nome = f"{resultado['cliente']} · {base}"
    db.commit()
    return resultado


def _proximo_codigo(db: Session, empresa_id: int) -> str:
    total = db.scalar(select(func.count()).select_from(Projeto).where(Projeto.empresa_id == empresa_id))
    n = (total or 0) + 1
    while db.scalar(select(Projeto.id).where(Projeto.empresa_id == empresa_id,
                                             Projeto.codigo == f"P-{n:04d}")):
        n += 1
    return f"P-{n:04d}"


@router.get("/{projeto_id}", response_model=ProjetoOut)
def detalhe(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return carregar(db, emp, projeto_id)


@router.post("/{projeto_id}/importar", response_model=ResultadoImportacao, dependencies=[Depends(ENGENHARIA)])
async def importar(projeto_id: int, arquivo: UploadFile = File(...),
                   emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    projeto = carregar(db, emp, projeto_id)
    if projeto.status not in (StatusProjeto.ORCAMENTO, StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA):
        raise HTTPException(409, f"Projeto {projeto.status}: engenharia travada após a liberação")
    bruto = await arquivo.read()
    try:
        if eh_xml(bruto):
            resultado = importar_promob_xml(db, projeto, bruto)
        else:
            try:
                conteudo = bruto.decode("utf-8")
            except UnicodeDecodeError:
                conteudo = bruto.decode("latin-1")
            resultado = importar_csv(db, projeto, conteudo)
    except ErroImportacao as e:
        db.rollback()
        raise HTTPException(422, str(e))
    projeto.status = StatusProjeto.ENGENHARIA
    db.commit()
    return resultado


@router.get("/{projeto_id}/consumo", response_model=ConsumoProjeto)
def consumo(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return engenharia.consumo(db, carregar(db, emp, projeto_id))


@router.post("/{projeto_id}/liberar", response_model=ProjetoResumo, dependencies=[Depends(ENGENHARIA)])
def liberar(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    projeto = carregar(db, emp, projeto_id)
    erros = engenharia.liberar(db, projeto)
    if erros:
        db.rollback()
        raise HTTPException(422, {"mensagem": "Projeto com pendências de engenharia", "pendencias": erros})
    db.commit()
    return projeto
