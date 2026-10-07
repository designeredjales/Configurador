from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import empresa_atual
from ..models import Cliente, Empresa, Projeto, StatusProjeto
from ..schemas import ConsumoProjeto, ProjetoIn, ProjetoOut, ProjetoResumo, ResultadoImportacao
from ..services import engenharia
from ..services.importacao import ErroImportacao, importar_csv

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


@router.post("", response_model=ProjetoResumo, status_code=201)
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


@router.get("/{projeto_id}", response_model=ProjetoOut)
def detalhe(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return carregar(db, emp, projeto_id)


@router.post("/{projeto_id}/importar", response_model=ResultadoImportacao)
async def importar(projeto_id: int, arquivo: UploadFile = File(...),
                   emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    projeto = carregar(db, emp, projeto_id)
    if projeto.status not in (StatusProjeto.ORCAMENTO, StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA):
        raise HTTPException(409, f"Projeto {projeto.status}: engenharia travada após a liberação")
    bruto = await arquivo.read()
    try:
        conteudo = bruto.decode("utf-8")
    except UnicodeDecodeError:
        conteudo = bruto.decode("latin-1")
    try:
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


@router.post("/{projeto_id}/liberar", response_model=ProjetoResumo)
def liberar(projeto_id: int, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    projeto = carregar(db, emp, projeto_id)
    erros = engenharia.liberar(db, projeto)
    if erros:
        db.rollback()
        raise HTTPException(422, {"mensagem": "Projeto com pendências de engenharia", "pendencias": erros})
    db.commit()
    return projeto
