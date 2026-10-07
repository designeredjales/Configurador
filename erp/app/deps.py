from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import Empresa


def empresa_atual(
    x_empresa_id: int = Header(..., description="Empresa (tenant) da requisição"),
    db: Session = Depends(get_db),
) -> Empresa:
    # Provisório: o tenant vem no header. A autenticação (JWT por usuário/empresa)
    # substitui isto antes de qualquer cliente real entrar.
    empresa = db.get(Empresa, x_empresa_id)
    if empresa is None:
        raise HTTPException(404, "Empresa não encontrada")
    return empresa
