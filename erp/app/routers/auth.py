from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ADMIN, usuario_atual
from ..models import Empresa, Perfil, Usuario
from ..schemas import (
    LoginIn,
    RegistroIn,
    Sessao,
    UsuarioAtualizar,
    UsuarioIn,
    UsuarioOut,
)
from ..security import HASH_FALSO, conferir_senha, criar_token, gerar_hash
from ..services.pcp import criar_centros_padrao

router = APIRouter(prefix="/api", tags=["acesso"])


def _email(valor: str) -> str:
    return valor.strip().lower()


def _sessao(usuario: Usuario) -> dict:
    return {
        "token": criar_token(usuario.id, usuario.empresa_id, usuario.perfil),
        "usuario": usuario,
        "empresa": usuario.empresa,
    }


def _email_livre(db: Session, email: str) -> None:
    if db.scalar(select(Usuario.id).where(Usuario.email == email)):
        raise HTTPException(409, "Já existe um usuário com este e-mail.")


@router.post("/auth/registrar", response_model=Sessao, status_code=201)
def registrar(dados: RegistroIn, db: Session = Depends(get_db)):
    """Cria a empresa e o primeiro usuário, que é o administrador."""
    email = _email(dados.email)
    _email_livre(db, email)
    empresa = Empresa(nome=dados.empresa.strip(), cnpj=dados.cnpj)
    db.add(empresa)
    db.flush()
    criar_centros_padrao(db, empresa.id)
    usuario = Usuario(empresa=empresa, nome=dados.nome.strip(), email=email,
                      senha_hash=gerar_hash(dados.senha), perfil=Perfil.ADMIN,
                      ultimo_acesso=datetime.now())
    db.add(usuario)
    db.commit()
    return _sessao(usuario)


@router.post("/auth/login", response_model=Sessao)
def login(dados: LoginIn, db: Session = Depends(get_db)):
    usuario = db.scalar(select(Usuario).where(Usuario.email == _email(dados.email)))
    # Confere sempre um hash, para a resposta não revelar se o e-mail existe
    ok = conferir_senha(dados.senha, usuario.senha_hash if usuario else HASH_FALSO)
    if not usuario or not ok:
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if not usuario.ativo:
        raise HTTPException(403, "Usuário desativado. Fale com o administrador da sua empresa.")
    usuario.ultimo_acesso = datetime.now()
    db.commit()
    return _sessao(usuario)


@router.get("/auth/eu", response_model=Sessao)
def eu(usuario: Usuario = Depends(usuario_atual)):
    return _sessao(usuario)  # renova o token a cada consulta


# --- Usuários da empresa (somente administrador) --------------------------------

@router.get("/usuarios", response_model=list[UsuarioOut])
def listar(admin: Usuario = Depends(ADMIN), db: Session = Depends(get_db)):
    return db.scalars(select(Usuario).where(Usuario.empresa_id == admin.empresa_id).order_by(Usuario.nome))


@router.post("/usuarios", response_model=UsuarioOut, status_code=201)
def criar(dados: UsuarioIn, admin: Usuario = Depends(ADMIN), db: Session = Depends(get_db)):
    email = _email(dados.email)
    _email_livre(db, email)
    usuario = Usuario(empresa_id=admin.empresa_id, nome=dados.nome.strip(), email=email,
                      senha_hash=gerar_hash(dados.senha), perfil=dados.perfil)
    db.add(usuario)
    db.commit()
    return usuario


@router.patch("/usuarios/{usuario_id}", response_model=UsuarioOut)
def atualizar(usuario_id: int, dados: UsuarioAtualizar, admin: Usuario = Depends(ADMIN),
              db: Session = Depends(get_db)):
    usuario = db.get(Usuario, usuario_id)
    if usuario is None or usuario.empresa_id != admin.empresa_id:
        raise HTTPException(404, "Usuário não encontrado")
    perde_admin = (dados.perfil not in (None, Perfil.ADMIN)) or dados.ativo is False
    if usuario.perfil == Perfil.ADMIN and perde_admin:
        admins = db.scalar(select(func.count()).select_from(Usuario).where(
            Usuario.empresa_id == admin.empresa_id, Usuario.perfil == Perfil.ADMIN,
            Usuario.ativo.is_(True)))
        if admins <= 1:
            raise HTTPException(409, "A empresa precisa de pelo menos um administrador ativo.")
    if dados.nome is not None:
        usuario.nome = dados.nome.strip()
    if dados.perfil is not None:
        usuario.perfil = dados.perfil
    if dados.ativo is not None:
        usuario.ativo = dados.ativo
    if dados.senha is not None:
        usuario.senha_hash = gerar_hash(dados.senha)
    db.commit()
    return usuario
