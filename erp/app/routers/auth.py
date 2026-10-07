import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ADMIN, usuario_atual
from ..models import Empresa, Perfil, RedefinicaoSenha, Usuario
from ..schemas import (
    EsqueciIn,
    LoginIn,
    RedefinirIn,
    TrocarSenhaIn,
    RegistroIn,
    Sessao,
    UsuarioAtualizar,
    UsuarioIn,
    UsuarioOut,
)
from ..security import HASH_FALSO, conferir_senha, criar_token, gerar_hash, hash_token, token_redefinicao
from ..services import email
from ..services.limite import falhas_login, pedidos_redefinicao
from ..services.pcp import criar_centros_padrao

router = APIRouter(prefix="/api", tags=["acesso"])


def _email(valor: str) -> str:
    return valor.strip().lower()


def _sessao(usuario: Usuario) -> dict:
    return {
        "token": criar_token(usuario.id, usuario.empresa_id, usuario.perfil, usuario.versao_sessao),
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
def login(dados: LoginIn, request: Request, db: Session = Depends(get_db)):
    chave = f"{_email(dados.email)}|{request.client.host if request.client else '-'}"
    espera = falhas_login.bloqueado(chave)
    if espera:
        raise HTTPException(429, f"Muitas tentativas. Tente de novo em {espera // 60 + 1} minuto(s) ou redefina a senha.",
                            headers={"Retry-After": str(espera)})
    usuario = db.scalar(select(Usuario).where(Usuario.email == _email(dados.email)))
    # Confere sempre um hash, para a resposta não revelar se o e-mail existe
    ok = conferir_senha(dados.senha, usuario.senha_hash if usuario else HASH_FALSO)
    if not usuario or not ok:
        falhas_login.registrar(chave)
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if not usuario.ativo:
        raise HTTPException(403, "Usuário desativado. Fale com o administrador da sua empresa.")
    falhas_login.zerar(chave)
    usuario.ultimo_acesso = datetime.now()
    db.commit()
    return _sessao(usuario)


RESPOSTA_ESQUECI = {"mensagem": "Se o e-mail estiver cadastrado, enviamos um link para redefinir a senha. Ele vale por 1 hora."}


@router.post("/auth/esqueci", status_code=202)
def esqueci(dados: EsqueciIn, db: Session = Depends(get_db)):
    email_ = _email(dados.email)
    if pedidos_redefinicao.bloqueado(email_):
        return RESPOSTA_ESQUECI  # mesma resposta: não revela nada nem vira canal de spam
    pedidos_redefinicao.registrar(email_)
    usuario = db.scalar(select(Usuario).where(Usuario.email == email_))
    if usuario and usuario.ativo:
        token, token_hash = token_redefinicao()
        db.add(RedefinicaoSenha(usuario_id=usuario.id, token_hash=token_hash,
                                expira_em=datetime.now() + timedelta(hours=1)))
        db.commit()
        url = os.getenv("ERP_URL_PUBLICA", "http://localhost:8000").rstrip("/")
        email.enviar(usuario.email, "Redefinição de senha · ERP Moveleiro",
                     f"Olá, {usuario.nome}.\n\nPara criar uma nova senha, abra o link abaixo (válido por 1 hora):\n"
                     f"{url}/#redefinir={token}\n\nSe não foi você que pediu, ignore este e-mail: sua senha continua a mesma.")
    return RESPOSTA_ESQUECI


@router.post("/auth/redefinir", response_model=Sessao)
def redefinir(dados: RedefinirIn, db: Session = Depends(get_db)):
    pedido = db.scalar(select(RedefinicaoSenha).where(RedefinicaoSenha.token_hash == hash_token(dados.token)))
    if pedido is None or pedido.usado_em or pedido.expira_em < datetime.now() or not pedido.usuario.ativo:
        raise HTTPException(400, "Link inválido ou expirado. Peça um novo em \"Esqueci a senha\".")
    usuario = pedido.usuario
    usuario.senha_hash = gerar_hash(dados.senha)
    usuario.versao_sessao += 1
    agora = datetime.now()
    for outro in db.scalars(select(RedefinicaoSenha).where(RedefinicaoSenha.usuario_id == usuario.id,
                                                          RedefinicaoSenha.usado_em.is_(None))):
        outro.usado_em = agora  # um link usado invalida os demais
    usuario.ultimo_acesso = agora
    db.commit()
    return _sessao(usuario)


@router.post("/auth/senha", response_model=Sessao)
def trocar_senha(dados: TrocarSenhaIn, usuario: Usuario = Depends(usuario_atual), db: Session = Depends(get_db)):
    if not conferir_senha(dados.senha_atual, usuario.senha_hash):
        raise HTTPException(400, "A senha atual não confere.")
    usuario.senha_hash = gerar_hash(dados.senha_nova)
    usuario.versao_sessao += 1  # derruba as outras sessões; esta recebe um token novo
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
    if dados.perfil is not None and dados.perfil != usuario.perfil:
        usuario.perfil = dados.perfil
        usuario.versao_sessao += 1  # perfil novo exige login novo: nenhum token com o perfil antigo circula
    if dados.ativo is not None:
        usuario.ativo = dados.ativo
    if dados.senha is not None:
        usuario.senha_hash = gerar_hash(dados.senha)
        usuario.versao_sessao += 1
    db.commit()
    return usuario
