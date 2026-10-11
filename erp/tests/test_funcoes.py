from conftest import SENHA, criar_usuario
from test_pos_obra import projeto_liberado


def uid(client, admin, email):
    return next(u["id"] for u in client.get("/api/usuarios", headers=admin).json() if u["email"] == email)


def test_catalogo_e_padrao_do_perfil(client, empresa):
    cat = client.get("/api/funcoes", headers=empresa).json()
    codigos = {f["codigo"] for f in cat["funcoes"]}
    assert {"apontamento", "estorno", "refugo", "fiscal", "usuarios"} <= codigos
    assert cat["padrao_por_perfil"]["OPERADOR"] == ["apontamento"]
    op = criar_usuario(client, empresa, "OPERADOR")
    eu = client.get("/api/auth/eu", headers=op).json()["usuario"]
    assert eu["funcoes_efetivas"] == ["apontamento"] and eu["funcoes_personalizadas"] is False


def test_admin_libera_e_retira_funcoes_na_hora(client, empresa):
    op = criar_usuario(client, empresa, "OPERADOR")
    pid = projeto_liberado(client, empresa)
    assert client.post(f"/api/projetos/{pid}/ops", json={}, headers=op).status_code == 403

    # Operador líder: também gera OP e estorna, sem virar PCP
    r = client.patch(f"/api/usuarios/{uid(client, empresa, 'operador@marcenaria.com')}",
                     json={"funcoes": ["apontamento", "pcp", "estorno"]}, headers=empresa).json()
    assert r["funcoes_personalizadas"] and r["funcoes_efetivas"] == ["apontamento", "estorno", "pcp"]
    assert client.post(f"/api/projetos/{pid}/ops", json={}, headers=op).status_code == 201  # vale sem novo login

    # Retirar a baixa: o mesmo token perde o acesso na hora
    client.patch(f"/api/usuarios/{uid(client, empresa, 'operador@marcenaria.com')}", json={"funcoes": ["pcp"]}, headers=empresa)
    r = client.post("/api/apontamentos", json={"codigo_barras": "00100000100001", "centro_codigo": "CORTE"}, headers=op)
    assert r.status_code == 403 and "Apontamento" in r.json()["detail"]

    # null volta ao padrão do perfil
    r = client.patch(f"/api/usuarios/{uid(client, empresa, 'operador@marcenaria.com')}", json={"funcoes": None}, headers=empresa).json()
    assert r["funcoes_efetivas"] == ["apontamento"] and not r["funcoes_personalizadas"]


def test_validacao_e_regras(client, empresa):
    criar_usuario(client, empresa, "COMPRAS")
    id_c = uid(client, empresa, "compras@marcenaria.com")
    assert client.patch(f"/api/usuarios/{id_c}", json={"funcoes": ["voar"]}, headers=empresa).status_code == 422
    client.patch(f"/api/usuarios/{id_c}", json={"funcoes": ["compras"]}, headers=empresa)
    # Trocar o perfil reaplica o modelo do perfil novo
    r = client.patch(f"/api/usuarios/{id_c}", json={"perfil": "FINANCEIRO"}, headers=empresa).json()
    assert r["funcoes_efetivas"] == ["clientes", "conciliacao", "controladoria", "financeiro", "fiscal"]
    # Administrador opera tudo, sempre (a empresa nunca fica sem quem administre)
    id_admin = uid(client, empresa, "admin@marcenaria.com")
    r = client.patch(f"/api/usuarios/{id_admin}", json={"funcoes": []}, headers=empresa).json()
    assert "usuarios" in r["funcoes_efetivas"] and not r["funcoes_personalizadas"]
    # Criar já com funções escolhidas; e só quem tem "usuarios" mexe nisso
    r = client.post("/api/usuarios", json={"nome": "Ana", "email": "ana@marcenaria.com", "senha": SENHA, "perfil": "OPERADOR",
                                           "funcoes": ["apontamento", "refugo"]}, headers=empresa).json()
    assert r["funcoes_efetivas"] == ["apontamento", "refugo"]
    gestor = criar_usuario(client, empresa, "GESTOR")
    assert client.patch(f"/api/usuarios/{id_c}", json={"funcoes": ["compras"]}, headers=gestor).status_code == 403
