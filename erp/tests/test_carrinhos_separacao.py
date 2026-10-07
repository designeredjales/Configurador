from conftest import criar_usuario
from test_lotes_expedicao import liberado, unidades, xml_outro_cliente


def lote_dois_clientes(client, h, tmp_path):
    p1, p2 = liberado(client, h), liberado(client, h, xml_outro_cliente(tmp_path))
    lote = client.post("/api/lotes", json={"descricao": "Semana 44", "projeto_ids": [p1, p2]}, headers=h).json()
    return lote, unidades(client, h, lote["projetos"][0]["op_id"]), unidades(client, h, lote["projetos"][1]["op_id"])


def test_carrinho_aponta_agrupa_e_confere(client, empresa, tmp_path):
    lote, u1, u2 = lote_dois_clientes(client, empresa, tmp_path)
    c1, c2 = client.post("/api/carrinhos", json={"quantidade": 2}, headers=empresa).json()
    assert c1["codigo_barras"] == "980010000001" and c2["numero"] == 2

    bip = lambda c, cb, centro="CORTE": client.post(f"/api/carrinhos/{c['id']}/bipar",  # noqa: E731
                                                     json={"codigo_barras": cb, "centro_codigo": centro}, headers=empresa)
    fundo = next(u for u in u1 if [e["centro_codigo"] for e in u["etapas"]] == ["CORTE", "EMBALAGEM"])
    com_borda = [u for u in u1 if "BORDA" in [e["centro_codigo"] for e in u["etapas"]]][:2]
    for u in com_borda + [fundo, u2[0]]:
        r = bip(c1, u["codigo_barras"])
        assert r.status_code == 200 and r.json()["apontou"], r.text
    car = r.json()["carrinho"]
    assert car["total_pecas"] == 4 and [g["quantidade"] for g in car["grupos"]] == [3, 1]
    assert car["grupos"][1]["cliente"] == "Família Souza" and car["grupos"][0]["rotulo"].startswith("Lote 1 · P-0001")
    assert bip(c1, fundo["codigo_barras"]).status_code == 409  # já está neste carrinho

    # Peça já apontada no setor muda de carrinho sem nova baixa
    r = bip(c2, u2[0]["codigo_barras"]).json()
    assert not r["apontou"] and r["veio_de_carrinho"] == 1
    # Peça sem baixa anterior obrigatória é recusada (não entra no carrinho)
    r = bip(c2, u1[-1]["codigo_barras"], "BORDA")
    assert r.status_code in (409, 422)

    # A BORDA bipa o carrinho: baixa em lote só no que espera por ela
    r = client.post("/api/carrinhos/conferir", json={"codigo_barras": c1["codigo_barras"], "centro_codigo": "BORDA"}, headers=empresa).json()
    assert r["baixadas"] == 2 and r["nao_passam"] == 1 and r["ja_feitas"] == 0 and r["bloqueadas"] == []
    r = client.post("/api/carrinhos/conferir", json={"codigo_barras": c1["codigo_barras"], "centro_codigo": "BORDA"}, headers=empresa).json()
    assert r["baixadas"] == 0 and r["ja_feitas"] == 2
    r = client.post("/api/carrinhos/conferir", json={"codigo_barras": c1["codigo_barras"], "centro_codigo": "EMBALAGEM"}, headers=empresa).json()
    assert r["baixadas"] == 1 and len(r["bloqueadas"]) == 2 and "USINAGEM" in r["bloqueadas"][0]["motivo"]

    # Marcadores: um por grupo; etiqueta do carrinho; consulta mostra o carrinho
    m = client.get(f"/api/carrinhos/{c1['id']}/marcadores.html", headers=empresa).text
    assert m.count('class="etq"') == 1 and "MARCADOR 1/1" in m and "LOTE 1" in m
    assert client.get(f"/api/carrinhos/{c2['id']}/marcadores.zpl", headers=empresa).text.count("^XA") == 1
    assert c1["codigo_barras"] in client.get(f"/api/carrinhos/{c1['id']}/etiqueta.html", headers=empresa).text
    p = client.get(f"/api/producao/pecas?busca={fundo['codigo_barras']}", headers=empresa).json()["pecas"][0]
    assert p["carrinho_numero"] == 1

    # Embalar na caixa master tira a peça do carrinho
    assert client.post("/api/expedicao/bipar", json={"codigo_barras": fundo["codigo_barras"]}, headers=empresa).status_code == 200
    assert client.get(f"/api/carrinhos/{c1['id']}", headers=empresa).json()["total_pecas"] == 2
    assert client.post(f"/api/carrinhos/{c1['id']}/esvaziar", headers=empresa).json()["total_pecas"] == 0

    expedicao = criar_usuario(client, empresa, "OPERADOR", email="exp@m.com")
    client.patch(f"/api/usuarios/{next(u['id'] for u in client.get('/api/usuarios', headers=empresa).json() if u['email'] == 'exp@m.com')}",
                 json={"funcoes": ["expedicao"]}, headers=empresa)
    assert bip(c2, u1[5]["codigo_barras"]).status_code == 200
    assert client.post(f"/api/carrinhos/{c2['id']}/bipar", json={"codigo_barras": u1[6]["codigo_barras"], "centro_codigo": "CORTE"},
                       headers=expedicao).status_code == 403


def test_setor_sem_conferencia_fecha_sozinho(client, empresa):
    centros = {c["codigo"]: c for c in client.get("/api/centros", headers=empresa).json()}
    for codigo in ("BORDA", "EMBALAGEM"):
        r = client.patch(f"/api/centros/{centros[codigo]['id']}", json={"exige_apontamento": False}, headers=empresa)
        assert r.status_code == 200 and r.json()["exige_apontamento"] is False
    pid = liberado(client, empresa)
    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=empresa).json()
    u = next(x for x in unidades(client, empresa, op["id"]) if [e["centro_codigo"] for e in x["etapas"]] == ["CORTE", "BORDA", "USINAGEM", "EMBALAGEM"])
    ap = lambda c: client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": c}, headers=empresa)  # noqa: E731
    assert ap("CORTE").json()["proxima_etapa"] == "USINAGEM"  # BORDA sem conferência fechou junto
    fila = {c["centro_codigo"]: c["na_fila"] for c in client.get("/api/painel", headers=empresa).json()["centros"]}
    assert fila["BORDA"] == 0 and fila["USINAGEM"] >= 1  # setor sem conferência não acumula fila
    r = ap("USINAGEM").json()
    assert r["proxima_etapa"] is None  # EMBALAGEM sem conferência fechou junto
    etapas = next(x for x in unidades(client, empresa, op["id"]) if x["codigo_barras"] == u["codigo_barras"])["etapas"]
    assert [e["operador"] for e in etapas] == ["Admin", "Sem conferência", "Admin", "Sem conferência"]
    # Peça pronta vai direto para a caixa master, mesmo sem bipar a EMBALAGEM
    assert client.post("/api/expedicao/bipar", json={"codigo_barras": u["codigo_barras"]}, headers=empresa).status_code == 200
    operador = criar_usuario(client, empresa, "OPERADOR")
    assert client.patch(f"/api/centros/{centros['BORDA']['id']}", json={"exige_apontamento": True}, headers=operador).status_code == 403


def test_separacao_tupia_tamburato_transformacao(client, empresa, tmp_path):
    classes = {c["codigo"]: c for c in client.get("/api/separacoes", headers=empresa).json()}
    assert set(classes) == {"TUPIA", "TAMBURATO", "TRANSFORMACAO"} and not classes["TRANSFORMACAO"]["vai_para_caixa"]
    # Setor de tupia só para as peças que pedem
    assert client.post("/api/centros", json={"codigo": "TUPIA", "nome": "Tupia", "sequencia": 25, "regra": "SOB_DEMANDA"},
                       headers=empresa).status_code == 201
    assert client.patch(f"/api/separacoes/{classes['TUPIA']['id']}", json={"centro_codigo": "NAOEXISTE"}, headers=empresa).status_code == 422
    client.patch(f"/api/separacoes/{classes['TUPIA']['id']}", json={"centro_codigo": "tupia"}, headers=empresa)
    # Regra por palavra-chave: "travessa" vira tamburato
    client.patch(f"/api/separacoes/{classes['TAMBURATO']['id']}", json={"palavras_chave": "travessa"}, headers=empresa)

    pid = liberado(client, empresa)
    pecas = [pc for a in client.get(f"/api/projetos/{pid}", headers=empresa).json()["ambientes"] for m in a["modulos"] for pc in m["pecas"]]
    lateral = next(pc for pc in pecas if pc["descricao"] == "Lateral Direita")
    base = next(pc for pc in pecas if pc["descricao"] == "Base Inferior")
    r = client.put(f"/api/pecas/{lateral['id']}/separacao", json={"separacao": "TUPIA"}, headers=empresa).json()
    assert r["separacao"] == "TUPIA" and r["manual"]
    client.put(f"/api/pecas/{base['id']}/separacao", json={"separacao": "TRANSFORMACAO"}, headers=empresa)
    assert client.post("/api/separacoes/reaplicar", headers=empresa).json()["pecas_alteradas"] >= 1
    assert client.put(f"/api/pecas/{base['id']}/separacao", json={"separacao": "VOAR"}, headers=empresa).status_code == 422

    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=empresa).json()
    us = unidades(client, empresa, op["id"])
    u_lat = next(u for u in us if u["peca_descricao"] == "Lateral Direita")
    assert [e["centro_codigo"] for e in u_lat["etapas"]] == ["CORTE", "BORDA", "TUPIA", "USINAGEM", "EMBALAGEM"]
    assert all("TUPIA" not in [e["centro_codigo"] for e in u["etapas"]] for u in us if u["peca_descricao"] != "Lateral Direita")
    etq = client.get(f"/api/ops/{op['id']}/etiquetas.html", headers=empresa).text
    assert "SEPARAR TUPIA" in etq and "SEPARAR TAMBURATO" in etq and "SEPARAR TRANSFORMACAO" in etq

    r = client.post("/api/apontamentos", json={"codigo_barras": u_lat["codigo_barras"], "centro_codigo": "CORTE"}, headers=empresa).json()
    assert r["separacao"] == "TUPIA" and r["separacao_nome"] == "Tupia" and r["projeto_codigo"] == "P-0001"
    car = client.post("/api/carrinhos", json={}, headers=empresa).json()[0]
    trav = next(u for u in us if u["peca_descricao"] == "Travessa")
    fundo = next(u for u in us if u["peca_descricao"] == "Fundo")
    for u in (u_lat, trav, fundo):
        client.post(f"/api/carrinhos/{car['id']}/bipar", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE"}, headers=empresa)
    grupos = client.get(f"/api/carrinhos/{car['id']}", headers=empresa).json()["grupos"]
    assert sorted(g["separacao"] or "-" for g in grupos) == ["-", "TAMBURATO", "TUPIA"]
    assert client.get(f"/api/carrinhos/{car['id']}/marcadores.html", headers=empresa).text.count('class="etq"') == 3

    # Peça que vira outra peça não vai para caixa master
    u_base = next(u for u in us if u["peca_descricao"] == "Base Inferior")
    for e in u_base["etapas"][:-1]:
        client.post("/api/apontamentos", json={"codigo_barras": u_base["codigo_barras"], "centro_codigo": e["centro_codigo"]}, headers=empresa)
    r = client.post("/api/expedicao/bipar", json={"codigo_barras": u_base["codigo_barras"]}, headers=empresa)
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "SEPARACAO"
    assert client.get(f"/api/producao/pecas?busca={u_lat['codigo_barras']}", headers=empresa).json()["pecas"][0]["separacao"] == "TUPIA"
