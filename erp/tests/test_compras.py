import os

from conftest import EXEMPLOS, criar_usuario

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def projeto_liberado(client, h):
    with open(XML, "rb") as f:
        pid = client.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)},
                          headers=h).json()["projeto_id"]
    assert client.post(f"/api/projetos/{pid}/liberar", headers=h).status_code == 200
    return pid


def posicao(client, h):
    return {p["codigo"]: p for p in client.get("/api/estoque", headers=h).json()}


def test_liberar_reserva_e_mrp_sugere_compra(client, empresa):
    projeto_liberado(client, empresa)
    pos = posicao(client, empresa)
    chapa = pos["MDF.COR.18.100"]  # cadastrada pelo XML em M2
    consumo = client.get("/api/projetos/1/consumo", headers=empresa).json()
    com_perda = next(l for l in consumo["chapas"] if l["material_codigo"] == "MDF.COR.18.100")["quantidade_com_perda"]
    assert chapa["reservado"] == round(com_perda, 3) and chapa["saldo"] == 0
    assert chapa["disponivel"] == -chapa["reservado"] and chapa["sugestao_compra"] == chapa["reservado"]
    assert pos["AGKCTT550"]["reservado"] == 3 and pos["AGKCTT550"]["sugestao_compra"] == 3
    assert pos["CAV"]["sugestao_compra"] == 36


def test_ciclo_pedido_recebimento_custo_medio(client, empresa):
    projeto_liberado(client, empresa)
    compras = criar_usuario(client, empresa, "COMPRAS")
    forn = client.post("/api/fornecedores", json={"nome": "Leo Madeiras", "prazo_dias": 3}, headers=compras).json()
    pos = posicao(client, compras)
    corr, cav = pos["AGKCTT550"], pos["CAV"]

    pedido = client.post("/api/pedidos", json={"fornecedor_id": forn["id"], "itens": [
        {"material_id": corr["material_id"], "quantidade": 5, "custo_unitario": 40.0},
        {"material_id": cav["material_id"], "quantidade": 36},
    ]}, headers=compras).json()
    assert pedido["numero"] == 1 and pedido["status"] == "RASCUNHO" and pedido["total"] == 5 * 40 + 36 * 0.03
    assert posicao(client, compras)["AGKCTT550"]["em_pedido"] == 5
    assert posicao(client, compras)["AGKCTT550"]["sugestao_compra"] == 0  # já está a caminho

    assert client.post(f"/api/pedidos/{pedido['id']}/enviar", headers=compras).json()["status"] == "ENVIADO"
    it_corr = next(i for i in pedido["itens"] if i["material_id"] == corr["material_id"])

    # Recebimento parcial, depois o resto; não aceita receber além do pedido
    r = client.post(f"/api/pedidos/{pedido['id']}/receber",
                    json={"itens": [{"item_id": it_corr["id"], "quantidade": 2}]}, headers=compras)
    assert r.json()["status"] == "PARCIAL"
    r = client.post(f"/api/pedidos/{pedido['id']}/receber",
                    json={"itens": [{"item_id": it_corr["id"], "quantidade": 9}]}, headers=compras)
    assert r.status_code == 422
    r = client.post(f"/api/pedidos/{pedido['id']}/receber", json={"itens": [
        {"item_id": it_corr["id"], "quantidade": 3},
        {"item_id": next(i["id"] for i in pedido["itens"] if i["material_id"] == cav["material_id"]), "quantidade": 36},
    ]}, headers=compras)
    assert r.json()["status"] == "RECEBIDO"

    p = posicao(client, compras)["AGKCTT550"]
    assert (p["saldo"], p["reservado"], p["disponivel"], p["em_pedido"]) == (5, 3, 2, 0)
    assert p["custo_unitario"] == 40.0  # saldo zero antes: custo médio = custo da compra

    # Segunda compra mais cara: custo médio ponderado
    p2 = client.post("/api/pedidos", json={"fornecedor_id": forn["id"], "itens": [
        {"material_id": corr["material_id"], "quantidade": 5, "custo_unitario": 60.0}]}, headers=compras).json()
    client.post(f"/api/pedidos/{p2['id']}/receber",
                json={"itens": [{"item_id": p2["itens"][0]["id"], "quantidade": 5}]}, headers=compras)
    assert posicao(client, compras)["AGKCTT550"]["custo_unitario"] == 50.0
    movs = client.get(f"/api/estoque/movimentos?material_id={corr['material_id']}", headers=compras).json()
    assert [m["origem"] for m in movs] == ["RECEBIMENTO"] * 3 and movs[0]["usuario"] == "Compras"


def test_conclusao_do_projeto_baixa_a_reserva(client, empresa):
    pid = projeto_liberado(client, empresa)
    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=empresa).json()
    for u in client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"]:
        for e in u["etapas"]:
            client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"],
                                                   "centro_codigo": e["centro_codigo"]}, headers=empresa)
    assert client.get(f"/api/projetos/{pid}", headers=empresa).json()["status"] == "CONCLUIDO"
    p = posicao(client, empresa)["AGKCTT550"]
    assert (p["saldo"], p["reservado"]) == (-3, 0)  # consumiu sem ter dado entrada: saldo negativo acusa
    movs = client.get(f"/api/estoque/movimentos?material_id={p['material_id']}", headers=empresa).json()
    assert movs[0]["origem"] == "CONSUMO" and movs[0]["referencia"] == "Projeto P-0001"


def test_inventario_ajusta_pela_diferenca(client, empresa):
    projeto_liberado(client, empresa)
    mat = posicao(client, empresa)["DOBTA"]
    r = client.post("/api/estoque/inventario", json={"material_id": mat["material_id"], "quantidade_contada": 10,
                                                     "observacao": "contagem mensal"}, headers=empresa)
    assert r.json()["saldo"] == 10
    r = client.post("/api/estoque/inventario", json={"material_id": mat["material_id"], "quantidade_contada": 7},
                    headers=empresa)
    assert r.json()["saldo"] == 7
    movs = client.get(f"/api/estoque/movimentos?material_id={mat['material_id']}", headers=empresa).json()
    assert [m["quantidade"] for m in movs] == [-3, 10]


def test_permissoes_e_isolamento_de_compras(client, empresa):
    projeto_liberado(client, empresa)
    operador = criar_usuario(client, empresa, "OPERADOR")
    assert client.get("/api/estoque", headers=operador).status_code == 200
    assert client.post("/api/fornecedores", json={"nome": "X"}, headers=operador).status_code == 403
    mat = posicao(client, empresa)["CAV"]["material_id"]
    assert client.post("/api/estoque/inventario", json={"material_id": mat, "quantidade_contada": 1},
                       headers=operador).status_code == 403
    from conftest import registrar
    outra = registrar(client, "Outra", "dono@outra.com")
    forn = client.post("/api/fornecedores", json={"nome": "Forn Outra"}, headers=outra).json()
    r = client.post("/api/pedidos", json={"fornecedor_id": forn["id"], "itens": [
        {"material_id": mat, "quantidade": 1}]}, headers=outra)
    assert r.status_code == 404  # não compra material de outra empresa
