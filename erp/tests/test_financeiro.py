import os
from datetime import date, timedelta

from conftest import EXEMPLOS, criar_usuario

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def importar(client, h):
    with open(XML, "rb") as f:
        return client.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)}, headers=h).json()["projeto_id"]


def test_xml_traz_o_comercial_do_promob(client, empresa):
    pid = importar(client, empresa)
    p = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert (p["valor_tabela"], p["valor_pedido"], p["valor_venda"]) == (783.41, 1103.26, 2093.46)
    assert (p["frete_orcado"], p["montagem_orcada"]) == (248.24, 190.31)
    assert (p["condicao_pagamento"], p["parcelas_sugeridas"], p["entrada_sugerida"]) == ("1+2", 2, True)
    assert p["contrato_em"] is None


def test_contrato_gera_parcelas_e_nao_duplica(client, empresa):
    pid = importar(client, empresa)
    r = client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 1000, "parcelas": 3,
                                                            "primeiro_vencimento": "2026-01-31"}, headers=empresa)
    assert r.status_code == 200 and r.json()["valor_venda"] == 1000
    parcelas = client.get(f"/api/lancamentos?projeto_id={pid}", headers=empresa).json()
    assert [p["valor"] for p in parcelas] == [333.33, 333.33, 333.34]
    assert [p["vencimento"] for p in parcelas] == ["2026-01-31", "2026-02-28", "2026-03-31"]
    assert all(p["tipo"] == "RECEBER" and p["categoria"] == "VENDA" and p["cliente_nome"] == "Cliente Exemplo"
               for p in parcelas)
    assert client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 1, "parcelas": 1,
                                                               "primeiro_vencimento": "2026-01-01"}, headers=empresa).status_code == 409


def test_recebimento_de_compra_gera_conta_a_pagar(client, empresa):
    importar(client, empresa)
    client.post("/api/projetos/1/liberar", headers=empresa)
    forn = client.post("/api/fornecedores", json={"nome": "Leo", "prazo_pagamento_dias": 28}, headers=empresa).json()
    mat = next(p for p in client.get("/api/estoque", headers=empresa).json() if p["codigo"] == "AGKCTT550")
    ped = client.post("/api/pedidos", json={"fornecedor_id": forn["id"], "itens": [
        {"material_id": mat["material_id"], "quantidade": 4, "custo_unitario": 45}]}, headers=empresa).json()
    client.post(f"/api/pedidos/{ped['id']}/receber", json={"itens": [{"item_id": ped["itens"][0]["id"], "quantidade": 3}]},
                headers=empresa)
    pagar = client.get("/api/lancamentos?tipo=PAGAR", headers=empresa).json()
    assert len(pagar) == 1 and pagar[0]["valor"] == 135 and pagar[0]["categoria"] == "MATERIAL"
    assert pagar[0]["vencimento"] == str(date.today() + timedelta(days=28)) and pagar[0]["fornecedor_nome"] == "Leo"


def test_dre_por_obra_com_material_realizado_e_custos_diretos(client, empresa):
    assert client.put("/api/empresas/atual", json={"imposto_venda_pct": 6}, headers=empresa).status_code == 200
    pid = importar(client, empresa)
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 5000, "parcelas": 2,
                                                        "primeiro_vencimento": str(date.today())}, headers=empresa)
    client.post(f"/api/projetos/{pid}/liberar", headers=empresa)

    previsto = client.get(f"/api/projetos/{pid}/dre", headers=empresa).json()
    assert previsto["material_base"] == "PREVISTO" and previsto["impostos"] == 300 and previsto["receita_liquida"] == 4700

    client.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "MONTAGEM", "descricao": "Montador",
                                          "valor": 400, "vencimento": str(date.today()), "projeto_id": pid}, headers=empresa)
    frete = client.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "FRETE", "descricao": "Frete",
                                                  "valor": 200, "vencimento": str(date.today()), "projeto_id": pid},
                        headers=empresa).json()
    client.post(f"/api/lancamentos/{frete['id']}/baixar", json={"data": str(date.today()), "valor": 180}, headers=empresa)

    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=empresa).json()
    for u in client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"]:
        for e in u["etapas"]:
            client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": e["centro_codigo"]},
                        headers=empresa)
    dre = client.get(f"/api/projetos/{pid}/dre", headers=empresa).json()
    assert dre["status"] == "CONCLUIDO" and dre["material_base"] == "REALIZADO"
    assert abs(dre["material"] - previsto["material"]) < 0.05  # mesmo custo médio: realizado = previsto
    assert dre["custos_diretos"] == {"FRETE": 180, "MONTAGEM": 400} and dre["total_custos_diretos"] == 580
    esperado = round(5000 - 300 - dre["material"] - 580, 2)
    assert dre["margem_contribuicao"] == esperado and dre["margem_pct"] == round(100 * esperado / 5000, 1)
    assert dre["a_receber"] == 5000 and dre["recebido"] == 0


def test_fluxo_de_caixa_e_baixas(client, empresa):
    pid = importar(client, empresa)
    hoje = date.today()
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 2093.46, "parcelas": 2,
                                                        "primeiro_vencimento": str(hoje - timedelta(days=5))}, headers=empresa)
    parcelas = client.get(f"/api/lancamentos?projeto_id={pid}", headers=empresa).json()
    assert parcelas[0]["situacao"] == "VENCIDO"
    fluxo = client.get("/api/financeiro/fluxo?meses=3", headers=empresa).json()
    assert fluxo["vencido_receber"] == 1046.73
    assert fluxo["meses"][0]["receber_previsto"] >= 1046.73  # atrasado cai no mês corrente

    r = client.post(f"/api/lancamentos/{parcelas[0]['id']}/baixar", json={"data": str(hoje)}, headers=empresa)
    assert r.json()["situacao"] == "PAGO" and r.json()["valor_pago"] == 1046.73
    assert client.post(f"/api/lancamentos/{parcelas[0]['id']}/baixar", json={"data": str(hoje)}, headers=empresa).status_code == 409
    assert client.delete(f"/api/lancamentos/{parcelas[0]['id']}", headers=empresa).status_code == 409
    fluxo = client.get("/api/financeiro/fluxo?meses=3", headers=empresa).json()
    assert fluxo["vencido_receber"] == 0 and fluxo["meses"][0]["recebido"] == 1046.73
    assert client.get("/api/lancamentos?situacao=EM_ABERTO", headers=empresa).json()[0]["id"] == parcelas[1]["id"]


def test_financeiro_e_restrito(client, empresa):
    pid = importar(client, empresa)
    for perfil in ("OPERADOR", "ENGENHARIA", "PCP", "COMPRAS"):
        h = criar_usuario(client, empresa, perfil)
        assert client.get("/api/lancamentos", headers=h).status_code == 403
        assert client.get(f"/api/projetos/{pid}/dre", headers=h).status_code == 403
    fin = criar_usuario(client, empresa, "FINANCEIRO")
    assert client.get("/api/financeiro/fluxo", headers=fin).status_code == 200
    assert client.put("/api/empresas/atual", json={"nome": "X"}, headers=fin).status_code == 403
    antes = client.get("/api/empresas/atual", headers=empresa).json()
    depois = client.put("/api/empresas/atual", json={"nome": "Nova Razão", "serra_mm": 3.2}, headers=empresa).json()
    assert depois["serra_mm"] == 3.2 and depois["perda_chapa_pct"] == antes["perda_chapa_pct"]
    assert client.put("/api/empresas/atual", json={"nome": None}, headers=empresa).status_code == 422
