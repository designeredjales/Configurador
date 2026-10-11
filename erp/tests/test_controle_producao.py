import os

from conftest import EXEMPLOS, criar_usuario

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def op_aberta(client, h, contrato=None):
    with open(XML, "rb") as f:
        pid = client.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)}, headers=h).json()["projeto_id"]
    if contrato:
        client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": contrato, "parcelas": 1, "primeiro_vencimento": "2026-10-01"}, headers=h)
    client.post(f"/api/projetos/{pid}/liberar", headers=h)
    return pid, client.post(f"/api/projetos/{pid}/ops", json={}, headers=h).json()


def baixa(client, h, cb, centro):
    return client.post("/api/apontamentos", json={"codigo_barras": cb, "centro_codigo": centro}, headers=h)


def test_estorno_so_da_ultima_baixa_com_motivo(client, empresa):
    _, op = op_aberta(client, empresa)
    cb = "00100000100003"  # Lateral Direita: CORTE > BORDA > USINAGEM > EMBALAGEM
    baixa(client, empresa, cb, "CORTE"); baixa(client, empresa, cb, "BORDA")
    est = lambda c, m="bipei no setor errado": client.post("/api/apontamentos/estorno",  # noqa: E731
                                                          json={"codigo_barras": cb, "centro_codigo": c, "motivo": m}, headers=empresa)
    assert est("CORTE").status_code == 409 and "BORDA" in est("CORTE").json()["detail"]
    assert est("BORDA", "x").status_code == 422  # motivo obrigatório
    r = est("BORDA").json()
    assert r["tipo"] == "ESTORNO" and r["usuario"] == "Admin" and r["centro_codigo"] == "BORDA"
    assert baixa(client, empresa, cb, "BORDA").status_code == 200  # pode bipar de novo
    unidade = next(u for u in client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"] if u["codigo_barras"] == cb)
    assert [bool(e["concluida_em"]) for e in unidade["etapas"]] == [True, True, False, False]
    # Estornar tudo devolve a OP para ABERTA
    est("BORDA"); est("CORTE")
    assert client.get(f"/api/ops/{op['id']}", headers=empresa).json()["status"] == "ABERTA"


def test_refugo_gera_reposicao_baixa_material_e_entra_no_dre(client, empresa):
    pid, op = op_aberta(client, empresa, contrato=5000)
    cb = "00100000100003"
    baixa(client, empresa, cb, "CORTE")
    est_antes = {p["codigo"]: p for p in client.get("/api/estoque", headers=empresa).json()}["MDF.COR.18.100"]
    r = client.post("/api/apontamentos/refugo", json={"codigo_barras": cb, "centro_codigo": "BORDA",
                                                      "motivo": "Lascou na coladeira"}, headers=empresa).json()
    nova = r["nova_etiqueta"]
    assert r["tipo"] == "REFUGO" and nova == "00100000100035"
    area = 0.72 * 0.61
    assert abs(r["custo_material"] - round(area * 55, 2)) < 0.01  # m² perdido × custo do MDF 18
    est = {p["codigo"]: p for p in client.get("/api/estoque", headers=empresa).json()}["MDF.COR.18.100"]
    assert abs((est_antes["saldo"] - est["saldo"]) - area) < 0.001

    det = client.get(f"/api/ops/{op['id']}", headers=empresa).json()
    assert det["total_unidades"] == 35
    ref = next(u for u in det["unidades"] if u["codigo_barras"] == cb)
    rep = next(u for u in det["unidades"] if u["codigo_barras"] == nova)
    assert ref["status"] == "REFUGADA" and rep["reposicao"] and [e["centro_codigo"] for e in rep["etapas"]] == \
        ["CORTE", "BORDA", "USINAGEM", "EMBALAGEM"]
    r = baixa(client, empresa, cb, "BORDA")
    assert r.status_code == 409 and "reposição" in r.json()["detail"]
    assert client.post("/api/apontamentos/refugo", json={"codigo_barras": cb, "centro_codigo": "BORDA", "motivo": "de novo"},
                       headers=empresa).status_code == 409

    # Etiquetas só das reposições e DRE com a linha de refugo
    zpl = client.get(f"/api/ops/{op['id']}/etiquetas.zpl?apenas_reposicoes=true", headers=empresa).text
    assert zpl.count("^XA") == 1 and nova in zpl
    assert client.get(f"/api/ops/{op['id']}/etiquetas.zpl", headers=empresa).text.count("^XA") == 34
    dre = client.get(f"/api/projetos/{pid}/dre", headers=empresa).json()
    assert dre["material_refugo"] == r_custo if (r_custo := round(area * 55, 2)) else False

    # Concluindo todas as peças ativas, a OP fecha mesmo com a refugada pendente
    for u in client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"]:
        if u["status"] == "ATIVA":
            for e in u["etapas"]:
                if not e["concluida_em"]:
                    baixa(client, empresa, u["codigo_barras"], e["centro_codigo"])
    assert client.get(f"/api/ops/{op['id']}", headers=empresa).json()["status"] == "CONCLUIDA"
    ind = client.get("/api/indicadores", headers=empresa).json()
    assert ind["qualidade"]["refugos"] == 1 and ind["qualidade"]["custo_refugo"] == r_custo
    r = client.post("/api/apontamentos/estorno", json={"codigo_barras": nova, "centro_codigo": "EMBALAGEM", "motivo": "teste"},
                    headers=empresa)
    assert r.status_code == 409 and "Assistência" in r.json()["detail"]


def test_consulta_de_pecas_e_historico(client, empresa):
    _, op = op_aberta(client, empresa)
    for cb in ("00100000100001", "00100000100002"):
        baixa(client, empresa, cb, "CORTE")
    baixa(client, empresa, "00100000100002", "EMBALAGEM")  # fundo: CORTE > EMBALAGEM → concluída
    c = client.get("/api/producao/pecas", headers=empresa).json()
    assert c["total"] == 34 and c["por_situacao"] == {"AGUARDANDO": 32, "EM_PROCESSO": 1, "CONCLUIDA": 1, "REFUGADA": 0}
    na_borda = client.get("/api/producao/pecas?centro=BORDA", headers=empresa).json()
    assert [p["codigo_barras"] for p in na_borda["pecas"]] == ["00100000100001"]
    assert na_borda["pecas"][0]["ultima_etapa"] == "CORTE" and na_borda["pecas"][0]["ultimo_operador"] == "Admin"
    gaveta = client.get("/api/producao/pecas?busca=gaveta&situacao=AGUARDANDO", headers=empresa).json()
    assert gaveta["pecas"] and all("gaveta" in (p["peca"] + p["modulo_descricao"] + p["codigo_barras"]).lower() for p in gaveta["pecas"])
    h = client.get("/api/producao/baixas", headers=empresa).json()
    assert h["total"] == 3 and h["por_centro"] == {"CORTE": 2, "EMBALAGEM": 1} and h["por_operador"] == {"Admin": 3}


def test_funcoes_de_estorno_e_refugo(client, empresa):
    _, op = op_aberta(client, empresa)
    baixa(client, empresa, "00100000100001", "CORTE")
    operador = criar_usuario(client, empresa, "OPERADOR")
    corpo = {"codigo_barras": "00100000100001", "centro_codigo": "CORTE", "motivo": "erro de bipe"}
    assert client.post("/api/apontamentos/estorno", json=corpo, headers=operador).status_code == 403
    assert client.post("/api/apontamentos/refugo", json=corpo, headers=operador).status_code == 403
    assert client.get("/api/producao/pecas", headers=operador).status_code == 200  # consulta é aberta
    pcp = criar_usuario(client, empresa, "PCP")
    assert client.post("/api/apontamentos/estorno", json=corpo, headers=pcp).status_code == 200
