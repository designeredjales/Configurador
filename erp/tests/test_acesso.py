import jwt

from conftest import SENHA, criar_usuario, importar_exemplo, registrar


def test_sem_login_nada_abre(client, empresa):
    for rota in ("/api/projetos", "/api/materiais", "/api/ops", "/api/painel", "/api/usuarios"):
        assert client.get(rota).status_code == 401
    assert client.get("/api/projetos", headers={"Authorization": "Bearer lixo"}).status_code == 401
    # O header antigo de tenant não dá mais acesso a nada
    assert client.get("/api/projetos", headers={"X-Empresa-Id": "1"}).status_code == 401


def test_login_e_senha(client, empresa):
    assert client.post("/api/auth/login", json={"email": "ADMIN@marcenaria.com ", "senha": SENHA}).status_code == 200
    errada = client.post("/api/auth/login", json={"email": "admin@marcenaria.com", "senha": "x" * 10})
    inexistente = client.post("/api/auth/login", json={"email": "ninguem@x.com", "senha": SENHA})
    assert errada.status_code == inexistente.status_code == 401
    assert errada.json() == inexistente.json()  # não revela se o e-mail existe
    eu = client.get("/api/auth/eu", headers=empresa).json()
    assert eu["usuario"]["perfil"] == "ADMIN" and eu["empresa"]["nome"] == "Marcenaria Teste"
    assert "senha_hash" not in eu["usuario"]


def test_registro_valida_dados(client):
    base = {"empresa": "X Móveis", "nome": "Ana", "email": "ana@x.com", "senha": SENHA}
    assert client.post("/api/auth/registrar", json={**base, "senha": "curta"}).status_code == 422
    assert client.post("/api/auth/registrar", json={**base, "email": "sem-arroba"}).status_code == 422
    assert client.post("/api/auth/registrar", json=base).status_code == 201
    assert client.post("/api/auth/registrar", json={**base, "empresa": "Outra"}).status_code == 409


def test_token_adulterado_ou_de_outra_empresa_e_recusado(client, empresa):
    token = empresa["Authorization"].split()[1]
    dados = jwt.decode(token, options={"verify_signature": False})
    forjado = jwt.encode({**dados, "perfil": "ADMIN", "emp": 999}, "chute", algorithm="HS256")
    assert client.get("/api/projetos", headers={"Authorization": f"Bearer {forjado}"}).status_code == 401
    sem_assinatura = jwt.encode({**dados}, None, algorithm="none")
    assert client.get("/api/projetos", headers={"Authorization": f"Bearer {sem_assinatura}"}).status_code == 401


def test_perfis_limitam_as_acoes(client, empresa, materiais):
    operador = criar_usuario(client, empresa, "OPERADOR", nome="João Corte")
    engenharia = criar_usuario(client, empresa, "ENGENHARIA")
    pcp = criar_usuario(client, empresa, "PCP")

    # Operador consulta, mas não importa, não libera, não gera OP, não cadastra
    assert client.get("/api/projetos", headers=operador).status_code == 200
    assert client.post("/api/projetos", json={"codigo": "X", "nome": "X"}, headers=operador).status_code == 403
    assert client.post("/api/materiais", json={"codigo": "Z", "descricao": "Z", "tipo": "OUTRO"},
                       headers=operador).status_code == 403
    assert client.get("/api/usuarios", headers=operador).status_code == 403

    pid, _ = importar_exemplo(client, engenharia)
    assert client.post(f"/api/projetos/{pid}/ops", json={}, headers=engenharia).status_code == 403
    assert client.post(f"/api/projetos/{pid}/liberar", headers=operador).status_code == 403
    assert client.post(f"/api/projetos/{pid}/liberar", headers=engenharia).status_code == 200
    assert client.post(f"/api/projetos/{pid}/ops", json={}, headers=operador).status_code == 403
    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=pcp).json()

    unidade = client.get(f"/api/ops/{op['id']}", headers=operador).json()["unidades"][0]
    r = client.post("/api/apontamentos", json={"codigo_barras": unidade["codigo_barras"],
                                               "centro_codigo": "CORTE"}, headers=operador)
    assert r.status_code == 200
    assert client.post("/api/apontamentos", json={"codigo_barras": unidade["codigo_barras"],
                                                  "centro_codigo": "BORDA"}, headers=engenharia).status_code == 403
    etapa = client.get(f"/api/ops/{op['id']}", headers=pcp).json()["unidades"][0]["etapas"][0]
    assert etapa["operador"] == "João Corte"  # quem baixou vem do login


def test_admin_gerencia_usuarios_e_desativa_na_hora(client, empresa):
    operador = criar_usuario(client, empresa, "OPERADOR")
    usuarios = client.get("/api/usuarios", headers=empresa).json()
    alvo = next(u for u in usuarios if u["perfil"] == "OPERADOR")
    r = client.patch(f"/api/usuarios/{alvo['id']}", json={"ativo": False}, headers=empresa)
    assert r.status_code == 200 and r.json()["ativo"] is False
    # Token já emitido deixa de valer imediatamente, e o login é recusado
    assert client.get("/api/projetos", headers=operador).status_code == 401
    assert client.post("/api/auth/login", json={"email": alvo["email"], "senha": SENHA}).status_code == 403

    # Promoção vale na próxima requisição, sem novo login
    client.patch(f"/api/usuarios/{alvo['id']}", json={"ativo": True, "perfil": "PCP",
                                                      "senha": "nova-senha-456"}, headers=empresa)
    novo = client.post("/api/auth/login", json={"email": alvo["email"], "senha": "nova-senha-456"})
    assert novo.status_code == 200 and novo.json()["usuario"]["perfil"] == "PCP"

    # A empresa nunca fica sem administrador
    admin_id = next(u["id"] for u in usuarios if u["perfil"] == "ADMIN")
    assert client.patch(f"/api/usuarios/{admin_id}", json={"perfil": "GESTOR"}, headers=empresa).status_code == 409
    assert client.patch(f"/api/usuarios/{admin_id}", json={"ativo": False}, headers=empresa).status_code == 409


def test_admin_nao_mexe_em_usuario_de_outra_empresa(client, empresa):
    outra = registrar(client, "Outra", "dono@outra.com")
    id_outra = client.get("/api/usuarios", headers=outra).json()[0]["id"]
    assert client.patch(f"/api/usuarios/{id_outra}", json={"ativo": False}, headers=empresa).status_code == 404
    assert [u["email"] for u in client.get("/api/usuarios", headers=empresa).json()] == ["admin@marcenaria.com"]
