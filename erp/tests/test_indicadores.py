from datetime import date, timedelta

from conftest import criar_usuario
from test_pos_obra import HOJE, agendar, produzir, projeto_liberado


def ciclo_completo(client, h, valor=4000, entrega=None):
    pid = projeto_liberado(client, h)
    if entrega:
        assert client.patch(f"/api/projetos/{pid}", json={"data_entrega": str(entrega)}, headers=h).status_code == 200
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": valor, "parcelas": 2,
                                                        "primeiro_vencimento": str(HOJE)}, headers=h)
    produzir(client, h, pid)
    m = agendar(client, h, pid).json()
    client.post(f"/api/montagens/{m['id']}/iniciar", headers=h)
    for item in m["itens"]:
        client.post(f"/api/montagens/{m['id']}/checklist/{item['id']}", json={"ok": True}, headers=h)
    client.post(f"/api/montagens/{m['id']}/concluir", json={"recebido_por": "Cliente"}, headers=h)
    return pid


def test_indicadores_batem_com_as_fontes(client, empresa):
    p1 = ciclo_completo(client, empresa, 4000, entrega=HOJE + timedelta(days=10))
    p2 = ciclo_completo(client, empresa, 6000, entrega=HOJE - timedelta(days=3))  # entregue com atraso
    c = client.post("/api/chamados", json={"projeto_id": p1, "tipo": "AJUSTE", "descricao": "Gaveta pesada"}, headers=empresa).json()
    client.post(f"/api/chamados/{c['id']}/resolver", json={"causa": "PRODUCAO", "solucao": "Corrediça trocada", "custo": 100},
                headers=empresa)

    ind = client.get("/api/indicadores?dias=30", headers=empresa).json()
    assert ind["comercial"]["faturamento"] == 10000 and ind["comercial"]["contratos"] == 2
    assert ind["comercial"]["ticket_medio"] == 5000 and ind["comercial"]["por_mes"][-1]["valor"] == 10000

    dres = [client.get(f"/api/projetos/{p}/dre", headers=empresa).json() for p in (p1, p2)]
    esperado = round(100 * sum(d["margem_contribuicao"] for d in dres) / 10000, 1)
    assert ind["margem"]["margem_media_pct"] == esperado and ind["margem"]["obras"] == 2

    prazo = ind["prazo"]
    assert prazo["entregas"] == 2 and prazo["pontualidade_pct"] == 50.0
    assert prazo["lead_time_venda_dias"] == 0 and prazo["lead_time_fabrica_dias"] is not None
    assert prazo["atrasados_hoje"] == []  # entregue, mesmo atrasado, sai da lista

    setores = {s["centro_codigo"]: s for s in ind["fabrica"]["setores"]}
    assert setores["CORTE"]["pecas_no_periodo"] == 68 and setores["EMBALAGEM"]["pecas_no_periodo"] == 68
    assert setores["BORDA"]["pecas_no_periodo"] < 68  # fundos não passam pela borda
    assert ind["fabrica"]["gargalo"] is None  # tudo baixado na hora: sem tempo medido e sem fila

    q = ind["qualidade"]
    assert (q["retrabalhos"], q["taxa_retrabalho_pct"], q["custo_assistencia"]) == (1, 50.0, 100)
    assert q["custo_assistencia_pct"] == 1.0 and q["por_causa"] == {"PRODUCAO": 1}


def test_projeto_atrasado_aparece_e_acesso_restrito(client, empresa):
    pid = projeto_liberado(client, empresa)
    client.patch(f"/api/projetos/{pid}", json={"data_entrega": str(date.today() - timedelta(days=5))}, headers=empresa)
    assert client.patch(f"/api/projetos/{pid}", json={"nome": ""}, headers=empresa).status_code == 422
    assert client.patch(f"/api/projetos/{pid}", json={"data_entrega": None},
                        headers=criar_usuario(client, empresa, "OPERADOR", email="op2@x.com")).status_code == 403
    ind = client.get("/api/indicadores", headers=empresa).json()
    assert [(a["codigo"], a["dias_atraso"]) for a in ind["prazo"]["atrasados_hoje"]] == [("P-0001", 5)]
    assert ind["caixa"]["materiais_em_falta"] > 0  # reservado sem estoque
    for perfil in ("OPERADOR", "FINANCEIRO", "COMPRAS", "MONTAGEM"):
        assert client.get("/api/indicadores", headers=criar_usuario(client, empresa, perfil)).status_code == 403
    assert client.get("/api/indicadores", headers=criar_usuario(client, empresa, "GESTOR")).status_code == 200
