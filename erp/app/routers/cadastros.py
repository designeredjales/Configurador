from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import empresa_atual
from ..models import CentroTrabalho, Cliente, Empresa, Material
from ..schemas import (
    CentroIn,
    CentroOut,
    ClienteIn,
    ClienteOut,
    EmpresaIn,
    EmpresaOut,
    MaterialIn,
    MaterialOut,
)
from ..services.pcp import criar_centros_padrao

router = APIRouter(prefix="/api", tags=["cadastros"])


@router.post("/empresas", response_model=EmpresaOut, status_code=201)
def criar_empresa(dados: EmpresaIn, db: Session = Depends(get_db)):
    empresa = Empresa(**dados.model_dump())
    db.add(empresa)
    db.flush()
    criar_centros_padrao(db, empresa.id)
    db.commit()
    return empresa


@router.get("/empresas/atual", response_model=EmpresaOut)
def empresa(emp: Empresa = Depends(empresa_atual)):
    return emp


# --- Clientes ----------------------------------------------------------------

@router.get("/clientes", response_model=list[ClienteOut])
def listar_clientes(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return db.scalars(select(Cliente).where(Cliente.empresa_id == emp.id).order_by(Cliente.nome))


@router.post("/clientes", response_model=ClienteOut, status_code=201)
def criar_cliente(dados: ClienteIn, emp: Empresa = Depends(empresa_atual),
                  db: Session = Depends(get_db)):
    cliente = Cliente(empresa_id=emp.id, **dados.model_dump())
    db.add(cliente)
    db.commit()
    return cliente


# --- Materiais ---------------------------------------------------------------

@router.get("/materiais", response_model=list[MaterialOut])
def listar_materiais(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return db.scalars(select(Material).where(Material.empresa_id == emp.id).order_by(Material.codigo))


@router.post("/materiais", response_model=MaterialOut, status_code=201)
def criar_material(dados: MaterialIn, emp: Empresa = Depends(empresa_atual),
                   db: Session = Depends(get_db)):
    material = Material(empresa_id=emp.id, **dados.model_dump())
    db.add(material)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Material {dados.codigo} já cadastrado")
    return material


@router.put("/materiais/{material_id}", response_model=MaterialOut)
def atualizar_material(material_id: int, dados: MaterialIn, emp: Empresa = Depends(empresa_atual),
                       db: Session = Depends(get_db)):
    material = db.get(Material, material_id)
    if material is None or material.empresa_id != emp.id:
        raise HTTPException(404, "Material não encontrado")
    for campo, valor in dados.model_dump().items():
        setattr(material, campo, valor)
    db.commit()
    return material


# --- Centros de trabalho -----------------------------------------------------

@router.get("/centros", response_model=list[CentroOut])
def listar_centros(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    return db.scalars(
        select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id)
        .order_by(CentroTrabalho.sequencia)
    )


@router.post("/centros", response_model=CentroOut, status_code=201)
def criar_centro(dados: CentroIn, emp: Empresa = Depends(empresa_atual),
                 db: Session = Depends(get_db)):
    centro = CentroTrabalho(empresa_id=emp.id, **dados.model_dump())
    centro.codigo = centro.codigo.upper()
    db.add(centro)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Centro {dados.codigo} já cadastrado")
    return centro
