"""Senhas (scrypt) e tokens de sessão (JWT HS256)."""
import base64
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

log = logging.getLogger(__name__)

SECRET = os.getenv("ERP_SECRET")
if not SECRET:
    # Sem segredo fixo, os tokens caem a cada reinício: só serve para desenvolvimento.
    SECRET = secrets.token_urlsafe(48)
    log.warning("ERP_SECRET não definido: usando segredo temporário (sessões expiram ao reiniciar)")

ALGORITMO = "HS256"
VALIDADE = timedelta(hours=int(os.getenv("ERP_SESSAO_HORAS", "12")))
SENHA_MINIMA = 8

_N, _R, _P = 2**14, 8, 1


def gerar_hash(senha: str) -> str:
    sal = os.urandom(16)
    chave = hashlib.scrypt(senha.encode(), salt=sal, n=_N, r=_R, p=_P)
    return "scrypt${}${}".format(base64.b64encode(sal).decode(), base64.b64encode(chave).decode())


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        _, sal, chave = guardado.split("$")
        calculada = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal), n=_N, r=_R, p=_P)
        return hmac.compare_digest(calculada, base64.b64decode(chave))
    except (ValueError, TypeError):
        return False


# Hash fixo para gastar o mesmo tempo quando o e-mail não existe
HASH_FALSO = gerar_hash(secrets.token_hex(8))


def criar_token(usuario_id: int, empresa_id: int, perfil: str) -> str:
    agora = datetime.now(timezone.utc)
    dados = {"sub": str(usuario_id), "emp": empresa_id, "perfil": perfil,
             "iat": agora, "exp": agora + VALIDADE}
    return jwt.encode(dados, SECRET, algorithm=ALGORITMO)


def ler_token(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=[ALGORITMO], options={"require": ["exp", "sub"]})
