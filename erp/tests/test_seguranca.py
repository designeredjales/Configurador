import re

import pytest

from app.services import email
from conftest import SENHA, criar_usuario


@pytest.fixture
def caixa(monkeypatch):
    enviados = []
    monkeypatch.setattr(email, "enviar", lambda para, assunto, texto: enviados.append((para, assunto, texto)))
    return enviados


def token_do_link(texto: str) -> str:
    return re.search(r"#redefinir=([\w-]+)", texto).group(1)


def test_esqueci_e_redefinir_senha(client, empresa, caixa):
    r = client.post("/api/auth/esqueci", json={"email": "admin@marcenaria.com"})
    nao_existe = client.post("/api/auth/esqueci", json={"email": "ninguem@x.com"})
    assert r.status_code == nao_existe.status_code == 202 and r.json() == nao_existe.json()  # não revela cadastro
    assert len(caixa) == 1 and caixa[0][0] == "admin@marcenaria.com"
    token = token_do_link(caixa[0][2])

    assert client.post("/api/auth/redefinir", json={"token": token, "senha": "curta"}).status_code == 422
    r = client.post("/api/auth/redefinir", json={"token": token, "senha": "senha-nova-456"})
    assert r.status_code == 200 and r.json()["usuario"]["email"] == "admin@marcenaria.com"
    # O link é de uso único, a senha antiga caiu e a sessão anterior também
    assert client.post("/api/auth/redefinir", json={"token": token, "senha": "outra-senha-789"}).status_code == 400
    assert client.post("/api/auth/login", json={"email": "admin@marcenaria.com", "senha": SENHA}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@marcenaria.com", "senha": "senha-nova-456"}).status_code == 200
    assert client.get("/api/projetos", headers=empresa).status_code == 401
    assert client.post("/api/auth/redefinir", json={"token": "x" * 40, "senha": "senha-nova-456"}).status_code == 400


def test_link_expirado_e_limite_de_pedidos(client, empresa, caixa):
    from datetime import datetime, timedelta

    from app.db import SessionLocal
    from app.models import RedefinicaoSenha
    client.post("/api/auth/esqueci", json={"email": "admin@marcenaria.com"})
    with SessionLocal() as s:
        for r in s.query(RedefinicaoSenha):
            r.expira_em = datetime.now() - timedelta(minutes=1)
        s.commit()
    assert client.post("/api/auth/redefinir", json={"token": token_do_link(caixa[0][2]), "senha": "senha-nova-456"}).status_code == 400
    for _ in range(5):
        client.post("/api/auth/esqueci", json={"email": "admin@marcenaria.com"})
    assert len(caixa) == 3  # no máximo 3 e-mails por hora para o mesmo endereço


def test_trocar_senha_derruba_outras_sessoes(client, empresa):
    outra_sessao = {"Authorization": "Bearer " + client.post("/api/auth/login", json={"email": "admin@marcenaria.com", "senha": SENHA}).json()["token"]}
    assert client.post("/api/auth/senha", json={"senha_atual": "errada-123", "senha_nova": "senha-nova-456"}, headers=empresa).status_code == 400
    r = client.post("/api/auth/senha", json={"senha_atual": SENHA, "senha_nova": "senha-nova-456"}, headers=empresa)
    assert r.status_code == 200
    nova = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/projetos", headers=outra_sessao).status_code == 401
    assert client.get("/api/projetos", headers=empresa).status_code == 401
    assert client.get("/api/projetos", headers=nova).status_code == 200


def test_admin_trocando_senha_ou_perfil_derruba_sessao_do_usuario(client, empresa):
    op = criar_usuario(client, empresa, "OPERADOR")
    uid = next(u["id"] for u in client.get("/api/usuarios", headers=empresa).json() if u["perfil"] == "OPERADOR")
    client.patch(f"/api/usuarios/{uid}", json={"perfil": "PCP"}, headers=empresa)
    assert client.get("/api/projetos", headers=op).status_code == 401
    novo = client.post("/api/auth/login", json={"email": "operador@marcenaria.com", "senha": SENHA}).json()
    assert novo["usuario"]["perfil"] == "PCP"


def test_limite_de_tentativas_de_login(client, empresa):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "admin@marcenaria.com", "senha": "chute-0000"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "admin@marcenaria.com", "senha": SENHA})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0  # nem a senha certa entra durante o bloqueio
    assert client.post("/api/auth/login", json={"email": "outro@marcenaria.com", "senha": "x" * 10}).status_code == 401


def test_cabecalhos_e_saude(client):
    r = client.get("/api/saude")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_producao_exige_segredo_forte(monkeypatch):
    import importlib

    import app.security as seguranca
    monkeypatch.setenv("ERP_AMBIENTE", "producao")
    monkeypatch.setenv("ERP_SECRET", "curto")
    with pytest.raises(RuntimeError, match="ERP_SECRET"):
        importlib.reload(seguranca)
    monkeypatch.setenv("ERP_SECRET", "x" * 40)
    importlib.reload(seguranca)
    monkeypatch.delenv("ERP_AMBIENTE")
    monkeypatch.delenv("ERP_SECRET")
    importlib.reload(seguranca)
