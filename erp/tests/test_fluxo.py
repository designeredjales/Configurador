from conftest import importar_exemplo


def test_importacao_monta_arvore_do_projeto(client, empresa, materiais):
    pid, res = importar_exemplo(client, empresa)
    assert (res["ambientes"], res["modulos"], res["pecas"], res["itens"]) == (1, 2, 6, 3)
    assert res["avisos"] == []
    projeto = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert projeto["status"] == "ENGENHARIA"
    aereo = projeto["ambientes"][0]["modulos"][1]
    assert aereo["codigo"] == "AER-800" and aereo["quantidade"] == 2


def test_consumo_aplica_perda_e_quantidade_do_modulo(client, empresa, materiais):
    pid, _ = importar_exemplo(client, empresa)
    c = client.get(f"/api/projetos/{pid}/consumo", headers=empresa).json()
    # 2 lat + 1 base + 1 fundo + 2 portas (balcão) + 2x(2 lat + 2 portas) (aéreos)
    assert c["total_pecas"] == 14
    chapas = {l["material_codigo"]: l for l in c["chapas"]}
    branco = chapas["MDF-BR-18"]
    area = (720 * 560 * 2 + 764 * 560 + 700 * 330 * 2 * 2) / 1e6
    assert branco["quantidade_liquida"] == round(area, 3)
    assert branco["quantidade_com_perda"] == round(area * 1.15, 3)
    assert branco["quantidade_compra"] == 1  # 1 chapa 2750x1850
    dob = {l["material_codigo"]: l for l in c["itens"]}["DOB-35-AMORT"]
    assert dob["quantidade_compra"] == 4 + 4 * 2
    assert dob["custo_total"] == 12 * 12.5
    fita_freijo = {l["material_codigo"]: l for l in c["fitas"]}["FT-FREIJO-22"]
    perimetro_m = (2 * (716 + 397) * 2 + 2 * (696 + 397) * 2 * 2) / 1000
    assert fita_freijo["quantidade_liquida"] == round(perimetro_m, 3)
    assert c["pendencias"] == []


def test_gate_de_engenharia_bloqueia_material_sem_cadastro(client, empresa):
    pid, res = importar_exemplo(client, empresa)  # sem cadastrar materiais
    assert res["avisos"]
    r = client.post(f"/api/projetos/{pid}/liberar", headers=empresa)
    assert r.status_code == 422
    assert any("MDF-BR-18" in p for p in r.json()["detail"]["pendencias"])
    r = client.post(f"/api/projetos/{pid}/ops", json={}, headers=empresa)
    assert r.status_code == 409


def test_fluxo_completo_op_e_apontamentos(client, empresa, materiais):
    pid, _ = importar_exemplo(client, empresa)
    assert client.post(f"/api/projetos/{pid}/liberar", headers=empresa).json()["status"] == "LIBERADO"

    # Engenharia travada após liberar
    with open(__import__("conftest").EXEMPLO, "rb") as f:
        r = client.post(f"/api/projetos/{pid}/importar", files={"arquivo": ("x.csv", f)},
                        headers=empresa)
    assert r.status_code == 409

    op = client.post(f"/api/projetos/{pid}/ops", json={"prioridade": 1}, headers=empresa).json()
    assert op["numero"] == 1 and op["total_unidades"] == 14 and op["status"] == "ABERTA"

    det = client.get(f"/api/ops/{op['id']}", headers=empresa).json()
    roteiros = {u["peca_codigo"]: [e["centro_codigo"] for e in u["etapas"]] for u in det["unidades"]}
    assert roteiros["FUNDO"] == ["CORTE", "EMBALAGEM"]
    assert roteiros["PORTA"] == ["CORTE", "BORDA", "USINAGEM", "EMBALAGEM"]

    porta = next(u for u in det["unidades"] if u["peca_codigo"] == "PORTA")
    ap = lambda cb, c: client.post("/api/apontamentos",  # noqa: E731
                                   json={"codigo_barras": cb, "centro_codigo": c}, headers=empresa)

    r = ap(porta["codigo_barras"], "BORDA")
    assert r.status_code == 409 and "CORTE" in r.json()["detail"]
    r = ap(porta["codigo_barras"], "corte")
    assert r.status_code == 200 and r.json()["proxima_etapa"] == "BORDA"
    assert r.json()["op_status"] == "EM_PRODUCAO"
    assert ap(porta["codigo_barras"], "CORTE").status_code == 409
    fundo = next(u for u in det["unidades"] if u["peca_codigo"] == "FUNDO")
    assert ap(fundo["codigo_barras"], "BORDA").status_code == 422
    assert ap("999", "CORTE").status_code == 404

    painel = client.get("/api/painel", headers=empresa).json()
    fila = {c["centro_codigo"]: c for c in painel["centros"]}
    assert fila["CORTE"]["na_fila"] == 13 and fila["CORTE"]["concluidas_hoje"] == 1
    assert fila["BORDA"]["na_fila"] == 1

    # Fecha a OP inteira
    for u in client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"]:
        for e in u["etapas"]:
            if not e["concluida_em"]:
                assert ap(u["codigo_barras"], e["centro_codigo"]).status_code == 200
    fim = client.get(f"/api/ops/{op['id']}", headers=empresa).json()
    assert fim["status"] == "CONCLUIDA" and fim["progresso_pct"] == 100.0
    assert client.get(f"/api/projetos/{pid}", headers=empresa).json()["status"] == "CONCLUIDO"


def test_isolamento_entre_empresas(client, empresa, materiais):
    pid, _ = importar_exemplo(client, empresa)
    outra = {"X-Empresa-Id": str(client.post("/api/empresas", json={"nome": "Outra"}).json()["id"])}
    assert client.get(f"/api/projetos/{pid}", headers=outra).status_code == 404
    assert client.get("/api/materiais", headers=outra).json() == []
    assert client.get("/api/projetos", headers=empresa).json()[0]["id"] == pid


def test_csv_invalido_retorna_linha_do_erro(client, empresa, materiais):
    p = client.post("/api/projetos", json={"codigo": "X", "nome": "X"}, headers=empresa).json()
    csv = "AMBIENTE;MODULO_CODIGO;TIPO;CODIGO;MATERIAL;QUANTIDADE\nA;M1;PECA;P1;MDF-BR-18;1\n"
    r = client.post(f"/api/projetos/{p['id']}/importar", files={"arquivo": ("x.csv", csv)},
                    headers=empresa)
    assert r.status_code == 422 and "Linha 2" in r.json()["detail"]
