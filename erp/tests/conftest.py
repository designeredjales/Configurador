import json
import os

os.environ["DATABASE_URL"] = "sqlite://"

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
    Base.metadata.drop_all(engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def empresa(client):
    r = client.post("/api/empresas", json={"nome": "Marcenaria Teste"})
    assert r.status_code == 201
    return {"X-Empresa-Id": str(r.json()["id"])}


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
