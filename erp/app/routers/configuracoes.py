"""Configurações gerais de produção: setores (conferência) e separação de peças."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ADMIN, PCP, empresa_atual
from ..models import CentroTrabalho, ClasseSeparacao, Empresa, OrdemProducao, Peca
from ..schemas import CentroAtualizar, CentroOut, ClasseAtualizar, ClasseIn, ClasseOut, SeparacaoPecaIn
from ..services import separacao

router = APIRouter(prefix="/api", tags=["configuracoes"])


@router.patch("/centros/{centro_id}", response_model=CentroOut, dependencies=[Depends(ADMIN)])
def atualizar_centro(centro_id: int, dados: CentroAtualizar, emp: Empresa = Depends(empresa_atual),
                     db: Session = Depends(get_db)):
    centro = db.get(CentroTrabalho, centro_id)
    if centro is None or centro.empresa_id != emp.id:
        raise HTTPException(404, "Setor não encontrado")
    for k, v in dados.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(centro, k, v)
    db.commit()
    from ..services.custos import anotar
    return anotar(db, emp.id, [centro])[0]


@router.get("/separacoes", response_model=list[ClasseOut])
def listar_classes(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    classes = separacao.garantir_padroes(db, emp.id)
    db.commit()
    return classes


def _validar_centro(db: Session, emp: Empresa, codigo: str | None) -> str | None:
    if not codigo:
        return None
    codigo = codigo.strip().upper()
    if db.scalar(select(CentroTrabalho).where(CentroTrabalho.empresa_id == emp.id, CentroTrabalho.codigo == codigo)) is None:
        raise HTTPException(422, f"Setor {codigo} não existe: cadastre o setor antes (regra 'Só peças separadas')")
    return codigo


@router.post("/separacoes", response_model=ClasseOut, status_code=201, dependencies=[Depends(ADMIN)])
def criar_classe(dados: ClasseIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    separacao.garantir_padroes(db, emp.id)
    classe = ClasseSeparacao(empresa_id=emp.id, **{**dados.model_dump(), "codigo": dados.codigo.upper(),
                                                   "centro_codigo": _validar_centro(db, emp, dados.centro_codigo)})
    db.add(classe)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Separação {dados.codigo.upper()} já existe")
    return classe


@router.patch("/separacoes/{classe_id}", response_model=ClasseOut, dependencies=[Depends(ADMIN)])
def atualizar_classe(classe_id: int, dados: ClasseAtualizar, emp: Empresa = Depends(empresa_atual),
                     db: Session = Depends(get_db)):
    classe = db.get(ClasseSeparacao, classe_id)
    if classe is None or classe.empresa_id != emp.id:
        raise HTTPException(404, "Separação não encontrada")
    campos = dados.model_dump(exclude_unset=True)
    if "centro_codigo" in campos:
        campos["centro_codigo"] = _validar_centro(db, emp, campos["centro_codigo"])
    for k, v in campos.items():
        if v is not None or k == "centro_codigo":
            setattr(classe, k, v)
    db.commit()
    return classe


@router.post("/separacoes/reaplicar", dependencies=[Depends(ADMIN)])
def reaplicar(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    r = separacao.reaplicar(db, emp.id)
    db.commit()
    return r


@router.put("/pecas/{peca_id}/separacao", dependencies=[Depends(PCP)])
def marcar_peca(peca_id: int, dados: SeparacaoPecaIn, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    """O PCP marca (ou desmarca) a separação de uma peça; null devolve a peça às regras."""
    peca = db.get(Peca, peca_id)
    if peca is None or peca.modulo.ambiente.projeto.empresa_id != emp.id:
        raise HTTPException(404, "Peça não encontrada")
    classes = separacao.mapa(db, emp.id)
    if dados.separacao and dados.separacao.upper() not in classes:
        raise HTTPException(422, f"Separação {dados.separacao} não existe")
    if dados.separacao is None:
        peca.separacao_manual = False
        peca.separacao = separacao.classificar(peca, list(classes.values()))
    else:
        peca.separacao_manual, peca.separacao = True, dados.separacao.upper()
    em_producao = db.scalar(select(OrdemProducao.id).where(OrdemProducao.projeto_id == peca.modulo.ambiente.projeto_id,
                                                           OrdemProducao.status.in_(["ABERTA", "EM_PRODUCAO"])).limit(1))
    db.commit()
    return {"peca_id": peca.id, "separacao": peca.separacao, "manual": peca.separacao_manual,
            "aviso": "O roteiro das OPs já geradas não muda; reimprima as etiquetas." if em_producao else None}
