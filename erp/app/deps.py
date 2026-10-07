from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from .db import get_db
from .models import Empresa, Perfil, Usuario
from .security import ler_token

bearer = HTTPBearer(auto_error=False)

NAO_AUTENTICADO = HTTPException(401, "Sessão inválida ou expirada. Entre novamente.",
                                headers={"WWW-Authenticate": "Bearer"})


def usuario_atual(cred: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> Usuario:
    if cred is None:
        raise NAO_AUTENTICADO
    try:
        dados = ler_token(cred.credentials)
        usuario = db.get(Usuario, int(dados["sub"]))
    except (InvalidTokenError, KeyError, ValueError):
        raise NAO_AUTENTICADO
    # O perfil e o status valem do banco, não do token: desativar corta o acesso na hora
    if usuario is None or not usuario.ativo or usuario.empresa_id != dados.get("emp"):
        raise NAO_AUTENTICADO
    return usuario


def empresa_atual(usuario: Usuario = Depends(usuario_atual)) -> Empresa:
    """A empresa (tenant) sai sempre do usuário logado, nunca da requisição."""
    return usuario.empresa


def exigir(*perfis: Perfil):
    permitidos = {Perfil.ADMIN, *perfis}

    def checar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if usuario.perfil not in permitidos:
            raise HTTPException(403, f"Seu perfil ({usuario.perfil}) não tem permissão para esta ação.")
        return usuario
    return checar


# Grupos de permissão usados nas rotas
ENGENHARIA = exigir(Perfil.GESTOR, Perfil.ENGENHARIA)
PCP = exigir(Perfil.GESTOR, Perfil.PCP)
APONTAR = exigir(Perfil.GESTOR, Perfil.PCP, Perfil.OPERADOR)
CADASTROS = exigir(Perfil.GESTOR, Perfil.ENGENHARIA, Perfil.COMPRAS)
COMPRAS = exigir(Perfil.GESTOR, Perfil.COMPRAS)
FINANCEIRO = exigir(Perfil.GESTOR, Perfil.FINANCEIRO)
POS_OBRA = exigir(Perfil.GESTOR, Perfil.MONTAGEM, Perfil.PCP)
ADMIN = exigir()
