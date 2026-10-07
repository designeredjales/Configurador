import json
import os

# SQLite em memória por padrão; ERP_TEST_DATABASE_URL roda a suíte em outro banco (ex.: PostgreSQL)
os.environ["DATABASE_URL"] = os.getenv("ERP_TEST_DATABASE_URL", "sqlite://")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


EXEMPLOS = os.path.join(os.path.dirname(__file__), "..", "exemplos")
EXEMPLO = os.path.join(EXEMPLOS, "cozinha_silva.csv")
with open(os.path.join(EXEMPLOS, "materiais.json"), encoding="utf-8") as f:
    MATERIAIS = json.load(f)


@pytest.fixture
def client():
    from app.services import limite
    limite.falhas_login._eventos.clear()
    limite.pedidos_redefinicao._eventos.clear()
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


SENHA = "senha-forte-123"


def registrar(client, empresa="Marcenaria Teste", email="admin@marcenaria.com"):
    r = client.post("/api/auth/registrar", json={"empresa": empresa, "nome": "Admin",
                                                 "email": email, "senha": SENHA})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def criar_usuario(client, admin, perfil, email=None, nome=None):
    email = email or f"{perfil.lower()}@marcenaria.com"
    r = client.post("/api/usuarios", json={"nome": nome or perfil.title(), "email": email,
                                           "senha": SENHA, "perfil": perfil}, headers=admin)
    assert r.status_code == 201, r.text
    login = client.post("/api/auth/login", json={"email": email, "senha": SENHA})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


@pytest.fixture
def empresa(client):
    """Cabeçalho de sessão do administrador de uma empresa nova."""
    return registrar(client)


@pytest.fixture
def materiais(client, empresa):
    for m in MATERIAIS:
        assert client.post("/api/materiais", json=m, headers=empresa).status_code == 201


def importar_exemplo(client, headers, codigo="P-001"):
    projeto = client.post("/api/projetos", json={"codigo": codigo, "nome": "Cozinha Silva"},
                          headers=headers).json()
    with open(EXEMPLO, "rb") as f:
        r = client.post(f"/api/projetos/{projeto['id']}/importar",
                        files={"arquivo": ("cozinha.csv", f, "text/csv")}, headers=headers)
    assert r.status_code == 200, r.text
    return projeto["id"], r.json()
