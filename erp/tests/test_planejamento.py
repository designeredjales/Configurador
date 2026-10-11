import os
from datetime import date, timedelta

from conftest import EXEMPLOS, criar_usuario

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def importar(client, h, nome="Cliente · Cozinha"):
    with open(XML, "rb") as f:
        r = client.post("/api/projetos/importar-xml", data={"nome": nome}, files={"arquivo": ("Cozinha.xml", f)}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def material(client, h, codigo, descricao, tipo="CHAPA", unidade="M2", custo=50):
    r = client.post("/api/materiais", json={"codigo": codigo, "descricao": descricao, "tipo": tipo, "unidade": unidade,
                                           "custo_unitario": custo}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_depara_traduz_importacao_reaplica_e_vai_no_setup(client, empresa):
    # Base que exige vínculo: código do Promob sem de-para vira pendência, não material novo
    client.put("/api/empresas/atual", json={"promob_cria_materiais": False}, headers=empresa)
    chapa = material(client, empresa, "MDF18-BRANCO", "MDF Branco TX 18mm")
    caixa = material(client, empresa, "DOB-CX100", "Dobradiça caneco 35mm (caixa c/ 100)", tipo="FERRAGEM", unidade="CX", custo=900)
    r = importar(client, empresa)
    assert r["materiais_criados"] == [] and any("sem de-para" in a for a in r["avisos"])
    pid = r["projeto_id"]
    assert client.post(f"/api/projetos/{pid}/liberar", headers=empresa).status_code == 422

    cods = client.get("/api/depara/codigos", headers=empresa).json()
    assert cods["cria_materiais"] is False
    por = {c["codigo"]: c for c in cods["codigos"]}
    assert por["MDF.COR.18.100"]["situacao"] == "SEM_CADASTRO" and pid and por["MDF.COR.18.100"]["projetos"]
    assert por["MDF.COR.18.100"]["sugestoes"] and por["MDF.COR.18.100"]["sugestoes"][0]["codigo"] == "MDF18-BRANCO"
    # Vincula e reaplica no projeto em engenharia (dobradiça: 1 unidade no Promob = 0,01 caixa)
    assert client.post("/api/depara", json={"codigo_promob": "MDF.COR.18.100", "material_id": chapa["id"]}, headers=empresa).status_code == 201
    dob = next(c for c in por.values() if c["tipo"] == "FERRAGEM" and "DOB" in c["codigo"].upper())
    client.post("/api/depara", json={"codigo_promob": dob["codigo"], "material_id": caixa["id"], "fator": 0.01}, headers=empresa)
    assert client.post("/api/depara", json={"codigo_promob": "X", "material_id": chapa["id"], "fator": 0}, headers=empresa).status_code == 422
    antes = client.get(f"/api/projetos/{pid}/consumo", headers=empresa).json()
    r = client.post("/api/depara/reaplicar", headers=empresa).json()
    assert r["projetos"] == 1 and r["trocas"] > 0
    cons = client.get(f"/api/projetos/{pid}/consumo", headers=empresa).json()
    chapas = {c["material_codigo"] for c in cons["chapas"]}
    assert "MDF18-BRANCO" in chapas and "MDF.COR.18.100" not in chapas
    qtd_dob_promob = next(i for i in antes["itens"] if i["material_codigo"] == dob["codigo"])["quantidade_liquida"]
    assert next(i for i in cons["itens"] if i["material_codigo"] == "DOB-CX100")["quantidade_liquida"] == round(qtd_dob_promob * 0.01, 3)
    por = {c["codigo"]: c for c in client.get("/api/depara/codigos", headers=empresa).json()["codigos"]}
    assert por["MDF.COR.18.100"]["situacao"] == "VINCULADO" and "MDF18-BRANCO" not in por

    # Nova importação já sai traduzida
    r2 = importar(client, empresa, "Outro · Cozinha")
    assert any("de-para" in a for a in r2["avisos"])
    # O setup leva o de-para pelo código do estoque; na outra base, material inexistente é ignorado com aviso
    exp = client.get("/api/setup/exportar", headers=empresa).json()
    assert {"codigo_promob": "MDF.COR.18.100", "material_codigo": "MDF18-BRANCO", "fator": 1.0, "observacao": None} in exp["depara"]
    assert exp["fabrica"]["promob_cria_materiais"] is False
    from conftest import registrar
    outra = registrar(client, empresa="Base Dois", email="adm@dois.com")
    material(client, outra, "MDF18-BRANCO", "MDF Branco 18")
    sim = client.post("/api/setup/aplicar", json={"setup": exp, "secoes": ["depara"], "simular": False}, headers=outra).json()
    textos = " | ".join(m["texto"] for m in sim["mudancas"])
    assert "MDF.COR.18.100: sem vínculo → MDF18-BRANCO" in textos and "DOB-CX100: material não existe" in textos
    pcp = criar_usuario(client, empresa, "PCP", email="pcp@m.com")
    assert client.post("/api/depara", json={"codigo_promob": "A", "material_id": chapa["id"]}, headers=pcp).status_code == 403


def test_custo_hora_entra_no_dre_e_na_margem_comercial(client, empresa):
    centros = {c["codigo"]: c for c in client.get("/api/centros", headers=empresa).json()}
    assert centros["CORTE"]["capacidade_h_dia"] == round(1 * 8.8 * 0.85, 2) and centros["CORTE"]["custo_hora"] == 0
    # Corte: 2 pessoas, R$ 15.000/mês, 1 min por peça + 2 min por m²
    c = client.patch(f"/api/centros/{centros['CORTE']['id']}", json={"pessoas": 2, "custo_mensal": 15000, "minutos_peca": 1,
                                                                       "minutos_m2": 2}, headers=empresa).json()
    horas_mes = 2 * 8.8 * 0.85 * 22
    assert c["custo_hora"] == round(15000 / horas_mes, 2)
    pid = importar(client, empresa)["projeto_id"]
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 2000, "parcelas": 1, "primeiro_vencimento": str(date.today())}, headers=empresa)
    d = client.get(f"/api/projetos/{pid}/dre", headers=empresa).json()
    assert d["mao_de_obra"] > 0 and d["mao_de_obra_setores"][0]["centro_codigo"] == "CORTE"
    # 34 peças × 1 min + m² × 2 min
    m2 = sum(p["comprimento_mm"] * p["largura_mm"] / 1e6 * p["quantidade"] * m["quantidade"]
             for a in client.get(f"/api/projetos/{pid}", headers=empresa).json()["ambientes"] for m in a["modulos"] for p in m["pecas"])
    assert abs(d["mao_de_obra_horas"] - (34 + 2 * m2) / 60) < 0.02
    assert abs(d["mao_de_obra"] - d["mao_de_obra_horas"] * c["custo_hora"]) < 0.2
    # A margem da proposta também desconta a mão de obra padrão
    op = client.post("/api/oportunidades", json={"titulo": "Cozinha", "cliente_nome": "Cliente"}, headers=empresa).json()
    with open(XML, "rb") as f:
        v = client.post(f"/api/oportunidades/{op['id']}/versoes", files={"arquivo": ("c.xml", f)}, headers=empresa).json()
    assert abs(v["calculo"]["mao_de_obra"] - d["mao_de_obra"]) < 0.05
    assert v["calculo"]["custo_producao"] == round(1103.26 + 248.24 + 190.31 + v["calculo"]["mao_de_obra"], 2)
    # Setup leva capacidade e tempos
    exp = client.get("/api/setup/exportar", headers=empresa).json()
    corte = next(s for s in exp["setores"] if s["codigo"] == "CORTE")
    assert corte["custo_mensal"] == 15000 and corte["minutos_m2"] == 2


def test_sequencia_pela_restricao(client, empresa):
    hoje = date.today()
    ids = {c["codigo"]: c["id"] for c in client.get("/api/centros", headers=empresa).json()}
    # Tempos: a borda é a mais lenta (vira o tambor)
    for cod, mp in (("CORTE", 1), ("BORDA", 6), ("USINAGEM", 2), ("EMBALAGEM", 0.5)):
        client.patch(f"/api/centros/{ids[cod]}", json={"minutos_peca": mp, "horas_dia": 8, "eficiencia_pct": 100}, headers=empresa)
    projetos = []
    for nome, dias in (("Obra Longe", 40), ("Obra Perto", 3), ("Obra Media", 15)):
        pid = importar(client, empresa, nome)["projeto_id"]
        client.patch(f"/api/projetos/{pid}", json={"data_entrega": str(hoje + timedelta(days=dias))}, headers=empresa)
        assert client.post(f"/api/projetos/{pid}/liberar", headers=empresa).status_code == 200
        projetos.append(pid)
    op = client.post(f"/api/projetos/{projetos[0]}/ops", json={"prioridade": 5}, headers=empresa).json()

    s = client.get("/api/pcp/sequencia", headers=empresa).json()
    assert s["unidade"] == "h" and s["tambor"]["centro_codigo"] == "BORDA" and not s["tambor_fixo"]
    nomes = [i["nome"] for i in s["itens"]]
    assert nomes == ["Obra Perto", "Obra Media", "Obra Longe"]  # data de entrega manda
    perto = s["itens"][0]
    assert perto["tipo"] == "PROJETO" and perto["liberar_ja"] and perto["carga_tambor"] > 0
    assert perto["status"] in ("RISCO", "ATRASA") and s["itens"][2]["tipo"] == "OP" and s["itens"][2]["status"] == "OK"
    assert s["itens"][2]["prioridade_sugerida"] == 3

    # Pulmão maior e tambor fixado no setup
    client.put("/api/gestao/config", json={"pulmao_dias": 5, "tambor_codigo": "CORTE"}, headers=empresa)
    s2 = client.get("/api/pcp/sequencia", headers=empresa).json()
    assert s2["tambor"]["centro_codigo"] == "CORTE" and s2["tambor_fixo"] and s2["pulmao_dias"] == 5
    assert client.put("/api/gestao/config", json={"tambor_codigo": "XYZ"}, headers=empresa).status_code == 422
    client.put("/api/gestao/config", json={"tambor_codigo": ""}, headers=empresa)
    assert client.get("/api/pcp/sequencia", headers=empresa).json()["tambor"]["centro_codigo"] == "BORDA"

    # Aplicar prioridades na OP e formar lote com o que cabe no tambor
    r = client.post("/api/pcp/sequencia/prioridades", headers=empresa).json()
    assert r["ops_alteradas"] == 1 and client.get(f"/api/ops/{op['id']}", headers=empresa).json()["prioridade"] == 3
    lote = client.post("/api/pcp/sequencia/lote", json={"dias": 0.1}, headers=empresa).json()
    assert lote["projetos"] == 1  # sempre leva ao menos a primeira obra da fila
    s3 = client.get("/api/pcp/sequencia", headers=empresa).json()
    assert [i["tipo"] for i in s3["itens"]].count("PROJETO") == 1
    vend = criar_usuario(client, empresa, "VENDEDOR", email="v@m.com")
    assert client.get("/api/pcp/sequencia", headers=vend).status_code == 403


def test_sequencia_sem_tempos_usa_m2(client, empresa):
    pid = importar(client, empresa)["projeto_id"]
    client.post(f"/api/projetos/{pid}/liberar", headers=empresa)
    s = client.get("/api/pcp/sequencia", headers=empresa).json()
    assert s["unidade"] == "m²" and s["itens"][0]["status"] == "SEM_DATA" and s["itens"][0]["carga_total"] > 0
