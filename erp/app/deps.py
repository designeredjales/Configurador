from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from .db import get_db
from .funcoes import CATALOGO, efetivas
from .models import Empresa, Usuario
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
    if dados.get("ver", 1) != usuario.versao_sessao:  # senha trocada depois deste login
        raise NAO_AUTENTICADO
    return usuario


def empresa_atual(usuario: Usuario = Depends(usuario_atual)) -> Empresa:
    """A empresa (tenant) sai sempre do usuário logado, nunca da requisição."""
    return usuario.empresa


def funcao(codigo: str):
    """Exige que o usuário opere a função (catálogo em app/funcoes.py), conferida no banco a cada requisição."""
    nome = CATALOGO[codigo][1]

    def checar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if codigo not in efetivas(usuario):
            raise HTTPException(403, f"Você não opera a função \"{nome}\". Peça ao administrador para liberá-la.")
        return usuario
    return checar


# Grupos usados nas rotas: cada um confere uma função
INDICADORES = funcao("indicadores")
ENGENHARIA = funcao("projetos")
CADASTROS = funcao("materiais")
CADASTRO_CLIENTE = funcao("clientes")
PCP = funcao("pcp")
APONTAR = funcao("apontamento")
ESTORNO = funcao("estorno")
REFUGO = funcao("refugo")
EXPEDICAO = funcao("expedicao")
COMERCIAL = funcao("comercial")
APROVAR_VENDA = funcao("aprovar_venda")
MONTAGEM = funcao("montagem")
ASSISTENCIA = funcao("assistencia")
ESTOQUE = funcao("estoque")
COMPRAS = funcao("compras")
FINANCEIRO = funcao("financeiro")
FISCAL = funcao("fiscal")
CONCILIACAO = funcao("conciliacao")
ADMIN = funcao("usuarios")
