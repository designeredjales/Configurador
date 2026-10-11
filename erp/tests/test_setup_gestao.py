import io
import os
import zipfile
from datetime import date, datetime, timedelta

import httpx

from conftest import EXEMPLOS, criar_usuario, registrar

from app.db import SessionLocal
from app.models import EtapaUnidade, OrdemProducao, Projeto
from app.services import promob_prices

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def importar(client, h, nome="Cliente · Cozinha"):
    with open(XML, "rb") as f:
        r = client.post("/api/projetos/importar-xml", data={"nome": nome}, files={"arquivo": ("Cozinha.xml", f)}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["projeto_id"]


def test_setup_exporta_simula_e_aplica_sem_segredos(client, empresa):
    client.put("/api/comercial/config", json={"prices_token": "token-secreto-da-conta", "margem_minima": 18}, headers=empresa)
    client.post("/api/parceiros", json={"nome": "Arq. Paula", "rt_pct": 5}, headers=empresa)
    exp = client.get("/api/setup/exportar", headers=empresa).json()
    assert exp["formato"] == "erp-moveleiro-setup" and "token-secreto" not in str(exp) and "fiscal_token" not in str(exp)
    assert [s["codigo"] for s in exp["setores"]] == ["CORTE", "BORDA", "USINAGEM", "EMBALAGEM"]
    assert exp["comercial"]["margem_minima"] == 18 and exp["parceiros"][0]["rt_pct"] == 5

    # Outra base recebe o modelo da indústria: a simulação mostra tudo e não grava nada
    outra = registrar(client, empresa="Fábrica Dois", email="admin@dois.com")
    modelos = client.get("/api/setup/modelos", headers=outra).json()["modelos"]
    assert {m["codigo"] for m in modelos} >= {"marcenaria-sob-medida", "industria-tupia-tamburato"}
    sim = client.post("/api/setup/aplicar", json={"modelo": "industria-tupia-tamburato"}, headers=outra).json()
    textos = " | ".join(m["texto"] for m in sim["mudancas"])
    assert sim["simulado"] and "Novo setor TUPIA" in textos and "Novo setor PRENSA" in textos and "margem_minima" in textos
    assert len(client.get("/api/centros", headers=outra).json()) == 4
    r = client.post("/api/setup/aplicar", json={"modelo": "industria-tupia-tamburato", "simular": False}, headers=outra).json()
    assert not r["simulado"]
    setores = {c["codigo"]: c for c in client.get("/api/centros", headers=outra).json()}
    assert setores["TUPIA"]["regra"] == "SOB_DEMANDA" and setores["PRENSA"]["sequencia"] == 35
    seps = {s["codigo"]: s for s in client.get("/api/separacoes", headers=outra).json()}
    assert seps["TUPIA"]["centro_codigo"] == "TUPIA" and seps["TAMBURATO"]["centro_codigo"] == "PRENSA"
    assert client.get("/api/comercial/config", headers=outra).json()["margem_minima"] == 25
    assert client.get("/api/gestao/config", headers=outra).json()["metas"]["m2_produzido_mes"] == 900
    # Reaplicar não muda nada (idempotente) e a primeira empresa ficou intacta
    again = client.post("/api/setup/aplicar", json={"modelo": "industria-tupia-tamburato", "simular": False}, headers=outra).json()
    assert [m for m in again["mudancas"] if "mantido" not in m["texto"]] == []
    assert len(client.get("/api/centros", headers=empresa).json()) == 4

    # Arquivo exportado aplica só as seções escolhidas na outra base
    r = client.post("/api/setup/aplicar", json={"setup": exp, "secoes": ["parceiros"], "simular": False}, headers=outra).json()
    assert r["secoes"] == ["parceiros"] and client.get("/api/parceiros", headers=outra).json()[0]["nome"] == "Arq. Paula"
    assert client.get("/api/comercial/config", headers=outra).json()["margem_minima"] == 25

    # Validações e permissão
    ruim = dict(exp, separacoes=[{"codigo": "LACA", "nome": "Laca", "centro_codigo": "PINTURA"}])
    r = client.post("/api/setup/aplicar", json={"setup": ruim, "simular": False}, headers=outra)
    assert r.status_code == 422 and "PINTURA" in r.json()["detail"]
    assert client.post("/api/setup/aplicar", json={"setup": {"nome": "x"}}, headers=outra).status_code == 422
    assert client.post("/api/setup/aplicar", json={"setup": dict(exp, comercial={"prices_url": "https://evil.example.com/api"})},
                       headers=outra).status_code == 422
    pcp = criar_usuario(client, outra, "PCP", email="pcp@dois.com")
    assert client.get("/api/setup/exportar", headers=pcp).status_code == 403


def test_prices_configuravel_e_diagnostico_de_formatos(client, empresa, monkeypatch):
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as z:
        z.writestr("produtos.csv", "Referencia,Nome do item,Valor Tabela,Valor Promo\nA1,Balcão,\"1.020,50\",900\nB2,Aéreo,310,300\n")
    vistos = []

    def responder(req):
        vistos.append(str(req.url))
        if req.url.path.endswith("/TablesPrices/Search"):
            return httpx.Response(200, json={"tablesPrices": [{"id": 7, "description": "Promo Outubro", "active": False, "validity": "2026-10"},
                                                              {"id": 9, "description": "Tabela 2026", "active": True}]})
        if req.url.path.endswith("/Products/Csv"):
            return httpx.Response(200, text='"https://blob.promob.com/x/t.zip?sig=1"')
        if req.url.host == "blob.promob.com":
            return httpx.Response(200, content=pacote.getvalue())
        return httpx.Response(404)

    monkeypatch.setattr(promob_prices, "TRANSPORTE", httpx.MockTransport(responder))
    assert client.put("/api/comercial/config", json={"prices_url": "http://prices-api.promob.com/api"}, headers=empresa).status_code == 422
    assert client.put("/api/comercial/config", json={"prices_url": "https://prices.evil.com/api"}, headers=empresa).status_code == 422
    client.put("/api/comercial/config", json={"prices_token": "tk", "prices_tabela_preferida": "Promo Outubro"}, headers=empresa)
    d = client.post("/api/comercial/prices/diagnostico", headers=empresa).json()
    assert d["tabela_escolhida"] == "Promo Outubro" and d["separador"] == "," and d["total_linhas"] == 2
    assert d["cabecalho"][0] == "Referencia" and "validity" in d["campos_da_tabela"] and "/TablesPrices/7/" in vistos[1]
    assert d["mapeamento"] == {"sku": "Referencia", "descricao": "Nome do item", "preco": "Valor Tabela"}
    # O setup escolhe outra coluna de preço; coluna inexistente é explicada
    cfg = client.put("/api/comercial/config", json={"prices_colunas": {"preco": "Valor Promo"}}, headers=empresa).json()
    assert cfg["prices_colunas"] == {"preco": "Valor Promo"} and cfg["prices_tabela_preferida"] == "Promo Outubro"
    r = client.post("/api/comercial/prices/sincronizar", headers=empresa).json()
    assert r["itens"] == 2 and r["tabela"] == "Promo Outubro"
    client.put("/api/comercial/config", json={"prices_colunas": {"preco": "Preço Final"}}, headers=empresa)
    d = client.post("/api/comercial/prices/diagnostico", headers=empresa).json()
    assert d["mapeamento"] is None and "Preço Final" in d["erro_mapeamento"]
    client.put("/api/comercial/config", json={"prices_tabela_preferida": "Não existe", "prices_colunas": {}}, headers=empresa)
    r = client.post("/api/comercial/prices/diagnostico", headers=empresa)
    assert r.status_code == 422 and "Tabela 2026" in r.json()["detail"]
    assert client.get("/api/comercial/config", headers=empresa).json()["prices_colunas"] == {}


def test_gestao_a_vista(client, empresa):
    client.put("/api/empresas/atual", json={"imposto_venda_pct": 6}, headers=empresa)
    hoje = date.today()
    p1 = importar(client, empresa, "Família A · Cozinha")
    client.post(f"/api/projetos/{p1}/contrato", json={"valor_venda": 2000, "parcelas": 1, "primeiro_vencimento": str(hoje)}, headers=empresa)
    client.patch(f"/api/projetos/{p1}", json={"data_entrega": str(hoje + timedelta(days=20))}, headers=empresa)
    assert client.post(f"/api/projetos/{p1}/liberar", headers=empresa).status_code == 200
    op = client.post(f"/api/projetos/{p1}/ops", json={"prioridade": 1}, headers=empresa).json()
    unidades = client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"]
    for u in unidades[:10]:  # 10 peças cortadas, 4 delas terminadas
        client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE"}, headers=empresa)
    for u in unidades[:4]:
        for e in u["etapas"]:
            client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": e["centro_codigo"]}, headers=empresa)
    p2 = importar(client, empresa, "Família B · Cozinha")  # vencida e ainda na engenharia
    client.patch(f"/api/projetos/{p2}", json={"data_entrega": str(hoje - timedelta(days=2))}, headers=empresa)
    # Obra liberada há 10 dias com entrega em 2 dias e nada produzido: pulmão vermelho
    p3 = importar(client, empresa, "Família C · Cozinha")
    client.patch(f"/api/projetos/{p3}", json={"data_entrega": str(hoje + timedelta(days=2))}, headers=empresa)
    client.post(f"/api/projetos/{p3}/liberar", headers=empresa)
    with SessionLocal() as db:
        db.get(Projeto, p3).liberado_em = datetime.now() - timedelta(days=10)
        db.commit()

    cfg = client.put("/api/gestao/config", json={"metas": {"m2_produzido_mes": 300, "faturamento_mes": 100000, "refugo_pct": 2,
                                                            "inexistente": 5},
                                                  "limites_wip": {"ENGENHARIA": 1, "PRODUCAO": 3}, "dias_uteis_mes": 20}, headers=empresa).json()
    assert cfg["metas"] == {"m2_produzido_mes": 300, "faturamento_mes": 100000, "refugo_pct": 2} and cfg["dias_uteis_mes"] == 20
    pcp = criar_usuario(client, empresa, "PCP", email="pcp@m.com")
    assert client.put("/api/gestao/config", json={"dias_uteis_mes": 10}, headers=pcp).status_code == 403
    assert client.get("/api/gestao/painel", headers=pcp).status_code == 403  # painel é da gestão (função indicadores)

    g = client.get("/api/gestao/painel", headers=empresa).json()
    k = {x["codigo"]: x for x in g["kpis"]}
    assert k["faturamento_mes"]["valor"] == 2000 and k["m2_vendido_mes"]["valor"] > 4
    assert k["m2_produzido_mes"]["valor"] > 0 and abs(k["preco_m2"]["valor"] - 2000 / k["m2_vendido_mes"]["valor"]) < 1
    assert k["refugo_pct"]["status"] == "OK" and k["conversao_pct"]["status"] is None
    assert g["takt"]["takt_m2_dia"] == 15 and g["takt"]["ritmo_m2_dia"] > 0 and len(g["takt"]["serie"]) == 14
    s = {x["centro_codigo"]: x for x in g["setores"]}
    assert s["CORTE"]["fila_pecas"] > 0 and s["BORDA"]["fila_pecas"] > 0 and g["restricao"] in s
    col = {c["codigo"]: c for c in g["kanban"]}
    assert col["ENGENHARIA"]["quantidade"] == 1 and col["ENGENHARIA"]["itens"][0]["atrasado"]
    assert col["PRODUCAO"]["quantidade"] == 1 and col["LIBERADO"]["quantidade"] == 1 and not col["PRODUCAO"]["excedido"]
    zonas = {b["codigo"]: b["zona"] for b in g["pulmoes"]}
    assert zonas[client.get(f"/api/projetos/{p3}", headers=empresa).json()["codigo"]] == "VERMELHO"
    assert any("2%" not in a["texto"] and "usado" in a["texto"] for a in g["andon"])
    with SessionLocal() as db:  # entrega vencida em produção vira PRETO e alerta crítico
        db.get(Projeto, p1).data_entrega = hoje - timedelta(days=1)
        db.commit()
    g = client.get("/api/gestao/painel", headers=empresa).json()
    assert g["pulmoes"][0]["zona"] == "PRETO" and g["andon"][0]["nivel"] == "CRITICO"
    # Limite de WIP estourado aparece no kanban e no andon
    importar(client, empresa, "Família D · Cozinha")
    g = client.get("/api/gestao/painel", headers=empresa).json()
    assert next(c for c in g["kanban"] if c["codigo"] == "ENGENHARIA")["excedido"]
    assert any("Kanban Engenharia" in a["texto"] for a in g["andon"])
