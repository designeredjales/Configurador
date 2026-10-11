"""Configurador de produtos: a engenharia programa (perguntas, regras, componentes, acabamentos) e o
comercial escolhe na venda. Cenário do balcão BL101 do treinamento do configurador e de um aéreo com
portas de alumínio e vidro montado como subconjunto reutilizável."""
import os

import pytest

from conftest import EXEMPLOS, criar_usuario

from app.services import formulas
from app.services.formulas import ErroFormula

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


@pytest.fixture
def biblioteca(client, empresa):
    r = client.post("/api/setup/aplicar", json={"modelo": "produtos-exemplo", "secoes": ["produtos"], "simular": False},
                    headers=empresa)
    assert r.status_code == 200, r.text
    modelos = {m["codigo"]: m for m in client.get("/api/configurador/modelos", headers=empresa).json()}
    return modelos


def simular(client, h, modelo_id, respostas=None, quantidade=1):
    r = client.post("/api/configurador/simular", json={"modelo_id": modelo_id, "respostas": respostas or {},
                                                       "quantidade": quantidade}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def pecas(d):
    return {p["codigo"]: p for p in d["modulo"]["pecas"]}


def itens(d):
    return {i["material_codigo"]: i for i in d["modulo"]["itens"]}


class Amb(formulas.Ambiente):
    def __init__(self, **v):
        self.v = {formulas.normalizar(k): x for k, x in v.items()}

    def variavel(self, nome):
        if nome in self.v:
            return self.v[nome]
        return super().variavel(nome)

    def constante(self, nome):
        return {"TAXACOLA": 0.012}[nome]


def test_linguagem_aceita_catalog_e_focco():
    a = Amb(LARGURA=600, PROFUNDIDADE=610, PW=600, PH=1300, OPCAO_FRENTE="SEM FRENTE")
    av = lambda t: formulas.avaliar(t, a)  # noqa: E731
    assert av("[LARGURA] - 32") == 568 and av("$PW$ - 4") == 596 and av("LARGURA / 2") == 300
    assert av('[OPCAO FRENTE] = "sem frente"') is True and av('[OPCAO FRENTE] <> "SEM FRENTE"') is False
    assert av("($PH$<=700) ? 2 : (($PH$<=1300) ? 3 : 4)") == 3 and av("faixa($PH$, 700, 2, 1300, 3, 4)") == 3
    assert av("[PROFUNDIDADE] = 500 >> 8;\n[PROFUNDIDADE] = 610 >> 10; cavilhas") == 10
    assert av("Math.round(2.345, 2)") == 2.35 and av("se([LARGURA] > 500; 3; 2)") == 3 and av("max(1, 4, 2)") == 4
    assert av("%TAXACOLA% * 1000") == 12 and av('"porta " + "Carvalho"') == "porta Carvalho"
    assert av("NOT ([LARGURA] = 600) OR ([PROFUNDIDADE] >= 610 AND !0)") is True
    assert formulas.modelo_texto("Balcão {[LARGURA]}x{[PROFUNDIDADE]} {se(1 > 2; \"X\")} vão {[LARGURA]*[PROFUNDIDADE]/1e6}", a) \
        == "Balcão 600x610 vão 0,366"
    for ruim in ("[LARGURA - 3", "3 +", "foo(2)", '"abc', "2 ** 3", "1 >> 2 >> 3"):
        assert formulas.validar(ruim), ruim
    with pytest.raises(ErroFormula):
        av("[NAO_EXISTE] + 1")
    with pytest.raises(ErroFormula):
        av("1 / ([LARGURA] - 600)")


def test_balcao_do_treinamento(client, empresa, biblioteca):
    bl = biblioteca["BL101"]
    assert bl["linha"] == "Cozinha › Balcões"
    d = simular(client, empresa, bl["id"])
    assert d["valido"] and d["descricao"] == "Balcão 600x500 mm Branco porta Branco · vão 0,3 m²"
    p = pecas(d)
    medidas = {k: (v["comprimento_mm"], v["largura_mm"], v["quantidade"]) for k, v in p.items()}
    assert medidas == {"LATERAL": (640, 500, 2), "BASE": (568, 500, 1), "TRAVESSA": (568, 56, 2),
                       "PRATELEIRA": (566, 410, 1), "COSTA": (635, 590, 1), "PORTA": (636, 596, 1)}
    assert p["LATERAL"]["material_codigo"] == "MDP15-BR" and p["LATERAL"]["fita_c1"] == "FT22-BR"
    assert p["PORTA"]["material_codigo"] == "MDP18-BR" and p["PORTA"]["espessura_mm"] == 18
    assert all(p["PORTA"][f"fita_{lado}"] == "FT22-BR" for lado in ("c1", "c2", "l1", "l2"))
    assert p["COSTA"]["material_codigo"] == "HDF3-BR" and p["COSTA"]["fita_c1"] is None
    i = itens(d)
    assert i["PE-PLAST"]["quantidade"] == 4  # herdado do grupo Balcões
    assert i["CAVILHA-8"]["quantidade"] == 8 and i["DOBR-35"]["quantidade"] == 2
    assert i["COLA-PVA"]["quantidade"] == pytest.approx((2 * 640 + 3 * 568 + 566 + 2 * (636 + 596)) / 1000 * 0.012, abs=1e-4)
    alt = next(x for x in d["perguntas"] if x["codigo"] == "ALTURA")
    assert alt["sombra"] and alt["origem"] == "BALCOES" and d["modulo"]["altura_mm"] == 700
    # Custo pela geometria: m² da chapa com perda, fita por lado, ferragem por unidade; preço = custo × markup
    c = d["custo"]
    mdp = next(x for x in c["consumo"] if x["material_codigo"] == "MDP15-BR")
    area = (2 * 640 * 500 + 568 * 500 + 2 * 568 * 56 + 566 * 410) / 1e6
    assert mdp["unidade"] == "M2" and mdp["quantidade"] == pytest.approx(area * 1.15, rel=1e-3) or mdp["quantidade"] > area
    assert d["preco"]["markup"] == 2.1 and d["preco"]["unitario"] == round(c["total"] * 2.1, 2)

    # Sem porta (porta de parceiro): a cor da porta some, a porta e as dobradiças saem; 610 de profundidade: 10 cavilhas
    d = simular(client, empresa, bl["id"], {"LARGURA": 400, "PROFUNDIDADE": 610, "OPCAO_FRENTE": "SEM_FRENTE"})
    assert d["valido"] and d["descricao"] == "Balcão 400x610 mm Branco sem porta · vão 0,244 m²"
    assert not next(x for x in d["perguntas"] if x["codigo"] == "FRENTE")["visivel"]
    assert "PORTA" not in pecas(d) and "DOBR-35" not in itens(d) and itens(d)["CAVILHA-8"]["quantidade"] == 10
    assert pecas(d)["BASE"]["comprimento_mm"] == 368 and pecas(d)["PRATELEIRA"]["largura_mm"] == 520

    # Validação: medidas do catálogo, cor liberada no modelo, opção bloqueada por regra e adicional no preço
    d = simular(client, empresa, bl["id"], {"LARGURA": 420, "CORPO": "AM", "FRENTE": "ON"})
    assert not d["valido"] and "400, 450, 500, 600" in d["erros"]["LARGURA"]
    assert "CORPO" in d["erros"] and "FRENTE" in d["erros"]
    corpo = next(x for x in d["perguntas"] if x["codigo"] == "CORPO")
    assert [o["codigo"] for o in corpo["opcoes"]] == ["BR", "MF", "TB"]
    d = simular(client, empresa, bl["id"], {"FRENTE": "Carvalho", "CORPO": "tb"})
    assert d["valido"] and pecas(d)["PORTA"]["material_codigo"] == "MDP18-CV" and pecas(d)["BASE"]["material_codigo"] == "MDP15-TB"
    assert d["preco"]["adicionais"] == [{"pergunta": "FRENTE", "opcao": "Carvalho", "valor": 35.0}]


def test_aluminio_com_subconjunto_reutilizavel(client, empresa, biblioteca):
    al = biblioteca["AEREO_ALU"]
    d = simular(client, empresa, al["id"], {"LARGURA": 800})
    assert d["valido"] and "1 porta(s)" in d["descricao"]
    d = simular(client, empresa, al["id"], {"LARGURA": 1000, "ALTURA": 900, "ALUMINIO": "PRETO", "VIDRO": "ESPELHO"})
    assert d["valido"], d
    assert d["descricao"] == "Aéreo 1000x900x350 mm Branco · 2 porta(s) alumínio Preto vidro Espelho"
    perfis = [i for i in d["modulo"]["itens"] if i["tipo"] == "PERFIL"]
    assert {p["descricao"] for p in perfis} == {"Montante (vertical) · 4 × 896 mm", "Travessa (horizontal) · 4 × 456 mm"}
    assert all(p["material_codigo"] == "PERFIL-AL-PRT" and p["unidade"] == "BR" for p in perfis)
    montante = next(p for p in perfis if p["descricao"].startswith("Montante"))
    assert montante["quantidade"] == pytest.approx(4 * (896 + 4) / 1000 * 1.03 / 6, abs=1e-4)  # fração da barra de 6 m
    vidro = itens(d)["ESP4"]
    assert vidro["unidade"] == "M2" and vidro["quantidade"] == pytest.approx(2 * 0.872 * 0.472, abs=1e-4)
    assert itens(d)["DOBR-ALU"]["quantidade"] == 4 and itens(d)["ESQ-ALU"]["quantidade"] == 8
    porta = next(n for n in d["arvore"] if n["codigo"] == "PORTA")
    assert porta["subconjunto"] == "PORTA_ALU" and porta["quantidade"] == 2 and porta["medidas"] == "496 × 896 × 20"
    assert {f["codigo"] for f in porta["filhos"]} == {"MONTANTE", "TRAVESSA", "VIDRO", "DOBRADICA", "ESQUADRO"}
    assert sum(a["valor"] for a in d["preco"]["adicionais"]) == 100
    # As perguntas do subconjunto aparecem para o vendedor junto com as do modelo
    assert {"ALUMINIO", "VIDRO"} <= {p["codigo"] for p in d["perguntas"]}


def test_heranca_engenharia_e_pendencias(client, empresa, biblioteca):
    bl = biblioteca["BL101"]
    arvore = {n["codigo"]: n for n in client.get("/api/produtos", headers=empresa).json()}
    no = client.get(f"/api/produtos/{bl['id']}", headers=empresa).json()
    assert no["efetivo"]["cadeia"] == ["COZINHA", "BALCOES", "BL101"]
    assert next(c for c in no["efetivo"]["componentes"] if c["codigo"] == "PES")["origem"] == "BALCOES"
    # O modelo substitui o herdado pelo mesmo código e pode retirar um herdado
    corpo = {k: no[k] for k in ("pai_id", "tipo", "codigo", "nome", "descricao_formula", "perguntas", "preco")}
    comps = no["componentes"] + [{"codigo": "PES", "tipo": "ITEM", "material": "PE-PLAST", "quantidade": "6"}]
    r = client.put(f"/api/produtos/{bl['id']}", json={**corpo, "componentes": comps}, headers=empresa)
    assert r.status_code == 200, r.text
    assert itens(simular(client, empresa, bl["id"]))["PE-PLAST"]["quantidade"] == 6
    comps[-1] = {"codigo": "PES", "remover": True}
    client.put(f"/api/produtos/{bl['id']}", json={**corpo, "componentes": comps}, headers=empresa)
    assert "PE-PLAST" not in itens(simular(client, empresa, bl["id"]))
    # Fórmula errada não grava, com a posição do erro
    ruim = comps[:-1] + [{"codigo": "X", "tipo": "PECA", "comprimento": "[LARGURA - 3", "largura": "100", "material": "HDF3-BR"}]
    r = client.put(f"/api/produtos/{bl['id']}", json={**corpo, "componentes": ruim}, headers=empresa)
    assert r.status_code == 422 and "sem fechar" in str(r.json()["detail"])
    assert client.post("/api/formulas/conferir", json={"formula": "[LARGURA] - 32"}, headers=empresa).json() == \
        {"ok": True, "erro": None, "variaveis": ["LARGURA"]}
    # Material sem cadastro e variável inexistente viram pendência de engenharia (a venda não passa)
    quebrado = comps[:-1] + [{"codigo": "TAMPO", "tipo": "PECA", "comprimento": "$PW$", "largura": "[PROFUNDIDADE]",
                              "material": "GRANITO-X"},
                             {"codigo": "SAIA", "tipo": "PECA", "comprimento": "$PW$", "largura": "[BEIRAL]", "material": "HDF3-BR"}]
    client.put(f"/api/produtos/{bl['id']}", json={**corpo, "componentes": quebrado}, headers=empresa)
    d = simular(client, empresa, bl["id"])
    assert not d["valido"] and any("GRANITO-X" in p for p in d["pendencias"]) and any("BEIRAL" in p for p in d["pendencias"])
    op = client.post("/api/oportunidades", json={"titulo": "Balcão", "cliente_nome": "Cliente Teste"}, headers=empresa).json()
    r = client.post(f"/api/oportunidades/{op['id']}/versoes/configurada", json={"itens": [{"modelo_id": bl["id"]}]}, headers=empresa)
    assert r.status_code == 422 and "pendência de engenharia" in r.json()["detail"]["pendencias"][0]
    # Grupo com itens não apaga; modelo vendido não muda de código
    assert client.delete(f"/api/produtos/{arvore['BALCOES']['id']}", headers=empresa).status_code == 409


def test_venda_configurada_reaproveita_codigo_e_gera_o_projeto(client, empresa, biblioteca):
    bl, al = biblioteca["BL101"], biblioteca["AEREO_ALU"]
    op = client.post("/api/oportunidades", json={"titulo": "Cozinha compacta", "cliente_nome": "Família Prado"},
                     headers=empresa).json()
    itens_venda = [{"modelo_id": bl["id"], "respostas": {"LARGURA": 600, "FRENTE": "CV"}, "quantidade": 2, "ambiente": "Cozinha"},
                   {"modelo_id": bl["id"], "respostas": {"LARGURA": 400, "OPCAO_FRENTE": "SEM_FRENTE"}, "ambiente": "Cozinha"},
                   {"modelo_id": al["id"], "respostas": {"LARGURA": 1000}, "ambiente": "Cozinha"}]
    r = client.post(f"/api/oportunidades/{op['id']}/versoes/configurada", json={"itens": itens_venda}, headers=empresa)
    assert r.status_code == 201, r.text
    v = r.json()
    cod = [i["codigo"] for i in v["itens_config"]]
    assert cod == ["BL101.0001", "BL101.0002", "AEREO_ALU.0001"] and not v["tem_xml"]
    res = v["resumo"]
    assert res["total_modulos"] == 4 and res["configurados"]["itens"] == 3
    preco = sum(i["preco_unitario"] * i["quantidade"] for i in v["itens_config"])
    assert res["valor_venda"] == round(preco, 2) and v["calculo"]["preco_base"] == round(preco, 2)
    assert v["calculo"]["custo_producao"] == round(sum(i["custo_material"] * i["quantidade"] for i in v["itens_config"]), 2)
    # A mesma resposta reaproveita o código; resposta nova ganha o próximo sequencial
    v2 = client.post(f"/api/oportunidades/{op['id']}/versoes/configurada", json={"itens": [
        itens_venda[0], {"modelo_id": bl["id"], "respostas": {"LARGURA": 450}}]}, headers=empresa).json()
    assert [i["codigo"] for i in v2["itens_config"]] == ["BL101.0001", "BL101.0003"]
    lista = client.get(f"/api/produtos/{bl['id']}/configuracoes", headers=empresa).json()
    assert [c["codigo"] for c in lista] == ["BL101.0003", "BL101.0002", "BL101.0001"]

    r = client.post(f"/api/oportunidades/{op['id']}/fechar", json={"versao_id": v["id"], "primeiro_vencimento": "2026-11-10"},
                    headers=empresa)
    assert r.status_code == 201, r.text
    pid = r.json()["projeto_id"]
    p = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert p["origem"] == "CONFIGURADOR"
    mods = {m["codigo"]: m for a in p["ambientes"] for m in a["modulos"]}
    assert set(mods) == {"BL101.0001", "BL101.0002", "AEREO_ALU.0001"} and mods["BL101.0001"]["quantidade"] == 2
    porta = next(pc for pc in mods["BL101.0001"]["pecas"] if pc["codigo"] == "PORTA")
    assert porta["material_codigo"] == "MDP18-CV" and porta["largura_mm"] == 596
    consumo = client.get(f"/api/projetos/{pid}/consumo", headers=empresa).json()
    assert consumo["pendencias"] == [] and consumo["total_pecas"] == 2 * 8 + 7 + 6
    assert any(i["material_codigo"] == "PERFIL-AL-NAT" for i in consumo["itens"])
    # Mudou a engenharia: a mesma resposta gera código novo; o que já foi vendido continua congelado
    no = client.get(f"/api/produtos/{bl['id']}", headers=empresa).json()
    corpo = {k: no[k] for k in ("pai_id", "tipo", "codigo", "nome", "descricao_formula", "perguntas", "componentes", "preco")}
    corpo["componentes"] = [c if c["codigo"] != "MINIFIX" else {**c, "quantidade": "10"} for c in corpo["componentes"]]
    assert client.put(f"/api/produtos/{bl['id']}", json=corpo, headers=empresa).status_code == 200
    op2 = client.post("/api/oportunidades", json={"titulo": "Outra", "cliente_nome": "Cliente B"}, headers=empresa).json()
    v3 = client.post(f"/api/oportunidades/{op2['id']}/versoes/configurada", json={"itens": [itens_venda[0]]}, headers=empresa).json()
    assert v3["itens_config"][0]["codigo"] == "BL101.0004"
    corpo["codigo"] = "BL101X"
    r = client.put(f"/api/produtos/{bl['id']}", json=corpo, headers=empresa)
    assert r.status_code == 409 and "duplique" in r.json()["detail"]


def test_promob_mais_configurador_na_mesma_proposta(client, empresa, biblioteca):
    al = biblioteca["AEREO_ALU"]
    op = client.post("/api/oportunidades", json={"titulo": "Cozinha + aéreos de alumínio", "cliente_nome": "Família Rocha"},
                     headers=empresa).json()
    with open(XML, "rb") as f:
        vx = client.post(f"/api/oportunidades/{op['id']}/versoes", files={"arquivo": ("Cozinha.xml", f)}, headers=empresa).json()
    corpo = {"itens": [{"modelo_id": al["id"], "respostas": {"LARGURA": 1000, "VIDRO": "FUME"}, "quantidade": 2,
                        "ambiente": "Cozinha"}], "incluir_xml_da_versao": vx["id"]}
    v = client.post(f"/api/oportunidades/{op['id']}/versoes/configurada", json=corpo, headers=empresa).json()
    assert v["tem_xml"] and v["arquivo"] == "Cozinha.xml + configurador"
    it = v["itens_config"][0]
    r, rx = v["resumo"], vx["resumo"]
    assert r["total_modulos"] == rx["total_modulos"] + 2
    assert r["valor_venda"] == round(rx["valor_venda"] + it["preco_unitario"] * 2, 2)
    assert r["valor_pedido"] == round(rx["valor_pedido"] + it["custo_material"] * 2, 2)
    # A conferência do Promob Prices ignora os produtos do configurador; a nova versão a partir desta não soma duas vezes
    v2 = client.post(f"/api/oportunidades/{op['id']}/versoes/configurada", json={**corpo, "incluir_xml_da_versao": v["id"]},
                     headers=empresa).json()
    assert v2["resumo"]["valor_venda"] == r["valor_venda"] and v2["resumo"]["total_modulos"] == r["total_modulos"]
    fechado = client.post(f"/api/oportunidades/{op['id']}/fechar", json={"versao_id": v["id"], "primeiro_vencimento": "2026-11-10"},
                          headers=empresa)
    assert fechado.status_code == 201, fechado.text
    pid = fechado.json()["projeto_id"]
    p = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    codigos = [m["codigo"] for a in p["ambientes"] for m in a["modulos"]]
    assert "AEREO_ALU.0001" in codigos and len(codigos) > 2 and p["origem"] == "PROMOB_XML"
    # O executivo do Promob reimportado não apaga o produto do configurador
    with open(XML, "rb") as f:
        r = client.post(f"/api/projetos/{pid}/importar", files={"arquivo": ("Executivo.xml", f)}, headers=empresa)
    assert r.status_code == 200, r.text
    assert any("configurador mantido" in a for a in r.json()["avisos"])
    p = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert [m["codigo"] for a in p["ambientes"] for m in a["modulos"]].count("AEREO_ALU.0001") == 1


def test_engenharia_acrescenta_no_projeto_e_permissoes(client, empresa, biblioteca):
    al = biblioteca["AEREO_ALU"]
    pr = client.post("/api/projetos", json={"codigo": "P-ALU", "nome": "Obra com alumínio"}, headers=empresa).json()
    r = client.post(f"/api/projetos/{pr['id']}/configurados", json={"modelo_id": al["id"], "respostas": {"LARGURA": 600},
                                                                     "ambiente": "Lavanderia"}, headers=empresa)
    assert r.status_code == 201, r.text
    assert r.json()["codigo"] == "AEREO_ALU.0001"
    p = client.get(f"/api/projetos/{pr['id']}", headers=empresa).json()
    mod = p["ambientes"][0]["modulos"][0]
    assert p["ambientes"][0]["nome"] == "Lavanderia" and mod["codigo"] == "AEREO_ALU.0001"
    r = client.post(f"/api/projetos/{pr['id']}/configurados", json={"modelo_id": al["id"], "respostas": {"LARGURA": 1500}},
                    headers=empresa)
    assert r.status_code == 422 and any("máximo 1200" in x for x in r.json()["detail"]["pendencias"])
    assert client.delete(f"/api/projetos/{pr['id']}/modulos/{mod['id']}", headers=empresa).status_code == 200
    # Vendedor configura e simula, mas não mexe na engenharia; engenharia de produto programa
    vend = criar_usuario(client, empresa, "VENDEDOR", email="vend@m.com")
    eng = criar_usuario(client, empresa, "ENGENHARIA", email="eng@m.com")
    assert client.get("/api/configurador/modelos", headers=vend).status_code == 200
    assert simular(client, vend, al["id"])["valido"]
    assert client.get("/api/produtos", headers=vend).status_code == 403
    assert client.post("/api/produtos", json={"tipo": "GRUPO", "codigo": "DORM", "nome": "Dormitório"}, headers=vend).status_code == 403
    r = client.post("/api/produtos", json={"tipo": "GRUPO", "codigo": "DORM", "nome": "Dormitório"}, headers=eng)
    assert r.status_code == 201, r.text
    assert client.post("/api/produtos", json={"tipo": "GRUPO", "codigo": "dorm", "nome": "Outro"}, headers=eng).status_code == 409


def test_acabamento_sugere_materiais_e_setup_leva_a_biblioteca(client, empresa, biblioteca):
    acabs = {a["codigo"]: a for a in client.get("/api/acabamentos", headers=empresa).json()}
    novo = {"codigo": "COR_GAVETA", "nome": "Cor da gaveta", "componentes": ["CHAPA15", "FITA"],
            "opcoes": [{"codigo": "TB", "nome": "Tabaco"}, {"codigo": "MF", "nome": "Marfim"}]}
    r = client.post("/api/acabamentos", json=novo, headers=empresa)
    assert r.status_code == 201, r.text
    s = client.post(f"/api/acabamentos/{r.json()['id']}/sugerir", headers=empresa).json()
    assert s["TB"]["CHAPA15"][0]["codigo"] == "MDP15-TB" and s["TB"]["FITA"][0]["codigo"] == "FT22-TB"
    assert s["MF"]["CHAPA15"][0]["codigo"] == "MDP15-MF"
    assert client.delete(f"/api/acabamentos/{acabs['COR_CORPO']['id']}", headers=empresa).status_code == 409
    # O setup exportado leva biblioteca, acabamentos, constantes e os materiais usados para outra base
    setup = client.get("/api/setup/exportar", headers=empresa).json()
    assert {n["codigo"] for n in setup["produtos"]["biblioteca"]} >= {"BL101", "PORTA_ALU"}
    assert setup["produtos"]["config"]["constantes"]["TAXACOLA"] == 0.012
    from conftest import registrar
    outra = registrar(client, empresa="Outra Fábrica", email="admin@outra.com")
    r = client.post("/api/setup/aplicar", json={"setup": setup, "secoes": ["produtos"], "simular": False}, headers=outra)
    assert r.status_code == 200, r.text
    modelos = {m["codigo"]: m for m in client.get("/api/configurador/modelos", headers=outra).json()}
    d = simular(client, outra, modelos["BL101"]["id"])
    assert d["valido"] and pecas(d)["BASE"]["comprimento_mm"] == 568
    # Aplicar de novo não duplica nada
    r = client.post("/api/setup/aplicar", json={"setup": setup, "secoes": ["produtos"], "simular": False}, headers=outra)
    assert r.json()["mudancas"] == []
