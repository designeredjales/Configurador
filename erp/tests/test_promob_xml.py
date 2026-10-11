import os
import xml.etree.ElementTree as ET
from collections import defaultdict

from conftest import EXEMPLOS

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def enviar_xml(client, headers, **form):
    with open(XML, "rb") as f:
        return client.post("/api/projetos/importar-xml", data=form,
                           files={"arquivo": ("Cozinha.xml", f, "application/xml")}, headers=headers)


def test_xml_cria_projeto_completo_com_cliente_e_materiais(client, empresa):
    r = enviar_xml(client, empresa)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["origem"] == "PROMOB_XML" and res["cliente"] == "Cliente Exemplo"
    assert (res["ambientes"], res["modulos"], res["pecas"]) == (1, 6, 34)
    assert {"MDF.COR.18.100", "MDF.COR.15.100", "MDF.COR.6.100", "FTPVC.1.22.100",
            "FTPVC.1.19.100", "AGKCTT550", "DOBTA"} <= set(res["materiais_criados"])
    assert any("sem preço" in a for a in res["avisos"])

    projeto = client.get(f"/api/projetos/{res['projeto_id']}", headers=empresa).json()
    assert projeto["codigo"] == "P-0001" and projeto["nome"] == "Cliente Exemplo · Cozinha"
    gaveteiro = next(m for m in projeto["ambientes"][0]["modulos"] if m["descricao"].startswith("Balcão 2 Gavetas"))
    assert len(gaveteiro["pecas"]) == 22
    ferragens = {i["material_codigo"]: i["quantidade"] for i in gaveteiro["itens"]}
    assert ferragens["AGKCTT550"] == 3  # uma corrediça por gaveta, consolidada no módulo
    lateral = next(p for p in gaveteiro["pecas"] if p["descricao"] == "Lateral Direita")
    assert (lateral["comprimento_mm"], lateral["largura_mm"], lateral["espessura_mm"]) == (720, 610, 18)
    assert lateral["operacoes"] == "BORDA,CORTE,FURAR,RASGO"
    assert lateral["fita_codigo"] == "FTPVC.1.22.100" and lateral["fita_metros"] == 2.66

    cliente = client.get("/api/clientes", headers=empresa).json()
    assert [c["nome"] for c in cliente] == ["Cliente Exemplo"]


def test_consumo_bate_com_os_m2_e_metros_do_promob(client, empresa):
    pid = enviar_xml(client, empresa).json()["projeto_id"]
    c = client.get(f"/api/projetos/{pid}/consumo", headers=empresa).json()

    # Soma o que o próprio Promob gravou nas estruturas CHAPA e FITA_BORDA
    # (ITEMSWITHOUTPRICE repete itens da árvore e fica de fora)
    esperado = defaultdict(float)
    for item in ET.parse(XML).getroot().find("AMBIENTS").iter("ITEM"):
        chave = item.get("STRUCTUREKEY") or ""
        if item.get("STRUCTURE") == "Y" and (chave.startswith("CHAPA") or chave == "FITA_BORDA"):
            esperado[item.get("REFERENCE")] += float(item.get("QUANTITY"))

    calculado = {l["material_codigo"]: l["quantidade_liquida"] for l in c["chapas"] + c["fitas"]}
    assert set(calculado) == set(esperado)
    for codigo, qtd in esperado.items():
        assert abs(calculado[codigo] - qtd) < 0.01, (codigo, calculado[codigo], qtd)

    chapa18 = next(l for l in c["chapas"] if l["material_codigo"] == "MDF.COR.18.100")
    assert chapa18["unidade"] == "M2" and chapa18["custo_unitario"] == 55.0
    assert c["pendencias"] == []


def test_roteiro_da_op_vem_das_operacoes_do_promob(client, empresa):
    pid = enviar_xml(client, empresa).json()["projeto_id"]
    assert client.post(f"/api/projetos/{pid}/liberar", headers=empresa).status_code == 200
    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=empresa).json()
    assert op["total_unidades"] == 34
    det = client.get(f"/api/ops/{op['id']}", headers=empresa).json()
    roteiros = {u["peca_descricao"]: [e["centro_codigo"] for e in u["etapas"]] for u in det["unidades"]}
    assert roteiros["Fundo"] == ["CORTE", "EMBALAGEM"]
    assert roteiros["Lateral Direita"] == ["CORTE", "BORDA", "USINAGEM", "EMBALAGEM"]


def test_reimportar_xml_substitui_a_engenharia(client, empresa):
    pid = enviar_xml(client, empresa).json()["projeto_id"]
    with open(XML, "rb") as f:
        r = client.post(f"/api/projetos/{pid}/importar", files={"arquivo": ("x.xml", f)}, headers=empresa)
    assert r.status_code == 200 and r.json()["materiais_criados"] == []
    projeto = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert sum(len(m["pecas"]) for a in projeto["ambientes"] for m in a["modulos"]) == 34


def test_xml_sem_operacoes_explica_qual_relatorio_exportar(client, empresa):
    xml = '<?xml version="1.0"?><LISTING DESCRIPTION="Orçamento"><AMBIENTS><AMBIENT DESCRIPTION="A">' \
          '<CATEGORIES><CATEGORY><ITEMS><ITEM DESCRIPTION="Balcão" QUANTITY="1"/></ITEMS></CATEGORY>' \
          '</CATEGORIES></AMBIENT></AMBIENTS></LISTING>'
    r = client.post("/api/projetos/importar-xml", files={"arquivo": ("x.xml", xml)}, headers=empresa)
    assert r.status_code == 422 and "Orçamento-Explodido c/ Operação" in r.json()["detail"]
    r = client.post("/api/projetos/importar-xml", files={"arquivo": ("x.xml", "<LISTING><quebrado")},
                    headers=empresa)
    assert r.status_code == 422 and "XML inválido" in r.json()["detail"]
    assert client.get("/api/projetos", headers=empresa).json() == []
