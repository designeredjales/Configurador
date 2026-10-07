import copy
import io
import os
import xml.etree.ElementTree as ET
import zipfile

import httpx
import pytest

from conftest import EXEMPLOS, SENHA, criar_usuario

from app.services import promob_prices

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")
PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


@pytest.fixture(autouse=True)
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("ERP_PASTA_ARQUIVOS", str(tmp_path / "arquivos"))


def usuario(client, admin, perfil, email, funcoes=None):
    h = criar_usuario(client, admin, perfil, email=email, nome=email.split("@")[0].title())
    if funcoes is not None:
        uid = next(u["id"] for u in client.get("/api/usuarios", headers=admin).json() if u["email"] == email)
        client.patch(f"/api/usuarios/{uid}", json={"funcoes": funcoes}, headers=admin)
    return h


def enviar_xml(client, h, op_id, caminho=XML):
    with open(caminho, "rb") as f:
        r = client.post(f"/api/oportunidades/{op_id}/versoes", files={"arquivo": ("Cozinha.xml", f)}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def cenario(client, empresa):
    client.put("/api/comercial/config", json={"margem_minima": 10, "prices_token": "token-secreto-da-conta"}, headers=empresa)
    parceiro = client.post("/api/parceiros", json={"nome": "Arq. Paula Lima", "rt_pct": 5}, headers=empresa).json()
    vend = usuario(client, empresa, "VENDEDOR", "ana@m.com")
    gerente = usuario(client, empresa, "GESTOR", "gerente@m.com")
    op = client.post("/api/oportunidades", json={"titulo": "Cozinha e área gourmet", "cliente_nome": "Família Rocha",
                                                 "parceiro_id": parceiro["id"], "link_3d": "https://galeria3d.promob.com/EVOLXmoY",
                                                 "token_2020": "CIEuJtAwtwCIEHsvrsDJwCtHGIAtv"}, headers=vend).json()
    return {"vend": vend, "gerente": gerente, "admin": empresa, "op": op, "parceiro": parceiro}


def test_politica_comercial_e_token_so_gravacao(client, empresa, cenario):
    cfg = client.get("/api/comercial/config", headers=empresa).json()
    assert cfg["prices_token_configurado"] and "prices_token" not in cfg and "token-secreto" not in str(cfg)
    assert cfg["etapas"][0] == "Contato" and cfg["condicoes"][0]["nome"] == "À vista"
    assert client.put("/api/comercial/config", json={"desconto_max_vendedor": 50}, headers=empresa).status_code == 422
    assert client.put("/api/comercial/config", json={"margem_minima": 5}, headers=cenario["vend"]).status_code == 403
    assert cenario["op"]["token_2020"] == "…HGIAtv" and cenario["op"]["etapa"] == "Contato" and cenario["op"]["vendedor"] == "Ana"


def test_negociacao_respeita_alcadas(client, cenario):
    vend, gerente, admin, op = cenario["vend"], cenario["gerente"], cenario["admin"], cenario["op"]
    v = enviar_xml(client, vend, op["id"])
    r = v["resumo"]
    assert r["total_modulos"] == 6 and r["total_pecas"] == 34 and r["m2_chapa"] > 4 and r["valor_venda"] == 2093.46
    c = v["calculo"]
    assert c["preco_final"] == round(2093.46 * 0.95, 2) and c["rt"] == round(c["preco_final"] * 0.05, 2)
    assert c["custo_producao"] == round(1103.26 + 248.24 + 190.31, 2) and c["preco_m2"] > 0 and v["aprovacao"] == "LIVRE"

    neg = lambda h, d, cond="6x sem juros": client.post(f"/api/versoes/{v['id']}/negociar",  # noqa: E731
                                                        json={"desconto_pct": d, "condicao": cond}, headers=h).json()
    assert neg(vend, 4)["aprovacao"] == "LIVRE"
    x = neg(vend, 8)
    assert x["aprovacao"] == "PENDENTE" and "limite do vendedor" in x["aprovacao_motivo"]
    assert client.post(f"/api/versoes/{v['id']}/proposta", headers=vend).status_code == 409
    assert client.post(f"/api/versoes/{v['id']}/decidir", json={"aprovar": True}, headers=vend).status_code == 403
    x = client.post(f"/api/versoes/{v['id']}/decidir", json={"aprovar": True, "observacao": "cliente fiel"}, headers=gerente).json()
    assert x["aprovacao"] == "APROVADA" and x["aprovado_por"] == "Gerente"
    # Acima do gerente: só o administrador
    x = neg(vend, 15)
    assert x["calculo"]["nivel_exigido"] == "ADMIN"
    r = client.post(f"/api/versoes/{v['id']}/decidir", json={"aprovar": True}, headers=gerente)
    assert r.status_code == 403 and "administrador" in r.json()["detail"]
    assert client.post(f"/api/versoes/{v['id']}/decidir", json={"aprovar": False}, headers=admin).json()["aprovacao"] == "RECUSADA"
    # Margem abaixo do mínimo também pede aprovação, mesmo com desconto pequeno
    client.put("/api/comercial/config", json={"margem_minima": 40}, headers=admin)
    x = neg(vend, 1)
    assert x["aprovacao"] == "PENDENTE" and "margem" in x["aprovacao_motivo"]
    assert neg(gerente, 1)["aprovacao"] == "APROVADA"  # quem aprova negocia já aprovado
    assert client.post(f"/api/versoes/{v['id']}/negociar", json={"desconto_pct": 1, "condicao": "30x"}, headers=vend).status_code == 422


def test_proposta_publica_aceite_e_imagens(client, cenario):
    vend, op = cenario["vend"], cenario["op"]
    v = enviar_xml(client, vend, op["id"])
    img = client.post(f"/api/oportunidades/{op['id']}/imagens", files={"arquivo": ("render1.png", PNG, "image/png")},
                      data={"legenda": "Cozinha, vista da ilha"}, headers=vend).json()
    assert client.post(f"/api/oportunidades/{op['id']}/imagens", files={"arquivo": ("x.txt", b"oi", "text/plain")},
                       headers=vend).status_code == 422
    link = client.post(f"/api/versoes/{v['id']}/proposta", headers=vend).json()["proposta_link"]
    pagina = client.get(link).text  # sem login
    assert "Família Rocha" in pagina and "R$ 1.988,79" in pagina and "galeria3d.promob.com/EVOLXmoY" in pagina
    assert "margem" not in pagina.lower() and "1103" not in pagina and "custo" not in pagina.lower()
    assert client.get(f"{link}/imagens/{img['id']}").content == PNG
    # Renegociar invalida o link antigo
    client.post(f"/api/versoes/{v['id']}/negociar", json={"desconto_pct": 2}, headers=vend)
    assert client.get(link).status_code == 404
    link = client.post(f"/api/versoes/{v['id']}/proposta", headers=vend).json()["proposta_link"]
    assert client.post(f"{link}/aceitar", data={"nome": "Jo"}).status_code == 422
    r = client.post(f"{link}/aceitar", data={"nome": "Marcos Rocha"})
    assert r.status_code == 200 and "aceita por <b>Marcos Rocha</b>" in r.text
    assert client.post(f"{link}/aceitar", data={"nome": "Outra Pessoa"}).status_code == 409
    d = client.get(f"/api/oportunidades/{op['id']}", headers=vend).json()["lista_versoes"][0]
    assert d["aceite_nome"] == "Marcos Rocha"
    assert client.post(f"/api/versoes/{v['id']}/negociar", json={"desconto_pct": 0}, headers=vend).status_code == 409


def test_vendedor_ve_so_as_suas(client, cenario):
    outro = usuario(client, cenario["admin"], "VENDEDOR", "bia@m.com")
    assert client.get(f"/api/oportunidades/{cenario['op']['id']}", headers=outro).status_code == 403
    assert client.get("/api/oportunidades", headers=outro).json() == []
    assert len(client.get("/api/oportunidades", headers=cenario["gerente"]).json()) == 1
    assert client.get("/api/oportunidades", headers=criar_usuario(client, cenario["admin"], "OPERADOR")).status_code == 403


def xml_com_modulo_a_mais(tmp_path):
    arvore = ET.parse(XML)
    itens = arvore.getroot().find(".//CATEGORY/ITEMS")
    itens.append(copy.deepcopy(itens.find("ITEM")))
    destino = tmp_path / "executivo.xml"
    arvore.write(destino, encoding="utf-8", xml_declaration=True)
    return destino


def test_fechar_venda_comissoes_e_auditoria(client, cenario, tmp_path):
    vend, gerente, admin, op = cenario["vend"], cenario["gerente"], cenario["admin"], cenario["op"]
    v = enviar_xml(client, vend, op["id"])
    v = client.post(f"/api/versoes/{v['id']}/negociar", json={"desconto_pct": 3, "condicao": "Entrada + 3x"}, headers=vend).json()
    preco = v["calculo"]["preco_final"]
    r = client.post(f"/api/oportunidades/{op['id']}/fechar", json={"versao_id": v["id"], "primeiro_vencimento": "2026-11-10"},
                    headers=vend)
    assert r.status_code == 201, r.text
    pid = r.json()["projeto_id"]
    assert r.json()["oportunidade"]["status"] == "GANHA"
    assert client.post(f"/api/oportunidades/{op['id']}/fechar", json={"versao_id": v["id"], "primeiro_vencimento": "2026-11-10"},
                       headers=vend).status_code == 409
    lancs = client.get("/api/lancamentos?situacao=", headers=admin).json()
    receber = [x for x in lancs if x["tipo"] == "RECEBER" and x["projeto_id"] == pid]
    comissoes = [x for x in lancs if x["categoria"] == "COMISSAO"]
    assert len(receber) == 4 and round(sum(x["valor"] for x in receber), 2) == preco
    assert len(comissoes) == 8 and any(x["descricao"].startswith("RT Arq. Paula Lima") for x in comissoes)
    assert round(sum(x["valor"] for x in comissoes if x["descricao"].startswith("RT")), 2) == pytest.approx(preco * 0.05, abs=0.03)

    a = client.get(f"/api/projetos/{pid}/auditoria-venda", headers=admin).json()
    assert a["divergencia_pct"] == 0 and not a["exige_ciencia"] and a["vendido"]["preco_final"] == preco

    # Engenharia sobe o executivo com um módulo a mais: o valor vendido não muda e a auditoria acusa
    with open(xml_com_modulo_a_mais(tmp_path), "rb") as f:
        assert client.post(f"/api/projetos/{pid}/importar", files={"arquivo": ("exec.xml", f)}, headers=admin).status_code == 200
    proj = next(p for p in client.get("/api/projetos", headers=admin).json() if p["id"] == pid)
    assert client.get(f"/api/projetos/{pid}", headers=admin).json()["valor_venda"] == preco
    a = client.get(f"/api/projetos/{pid}/auditoria-venda", headers=admin).json()
    assert a["diferencas"]["modulos"] == 1 and a["diferencas"]["m2_pct"] > 3 and a["exige_ciencia"]
    assert a["modulos_acrescentados"][0]["codigo"] == "2103.50.72.61.100" and a["modulos_retirados"] == []
    r = client.post(f"/api/projetos/{pid}/liberar", headers=admin)
    assert r.status_code == 422 and any("diverge" in p for p in r.json()["detail"]["pendencias"])
    assert client.post(f"/api/projetos/{pid}/auditoria-venda/ciencia", headers=vend).status_code == 403
    a = client.post(f"/api/projetos/{pid}/auditoria-venda/ciencia", headers=gerente).json()
    assert a["ciente_por"] == "Gerente" and not a["exige_ciencia"]
    assert client.post(f"/api/projetos/{pid}/liberar", headers=admin).status_code == 200
    assert proj["status"] in ("ENGENHARIA", "APROVADO")


def test_sincroniza_tabela_do_promob_prices(client, cenario, monkeypatch):
    chamadas = []
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w") as z:
        z.writestr("tabela.csv", "SKU;Descrição;Preço\n2103.50.72.61.100;Balcão 1 Porta;310,50\n"
                                 "2203.40.72.61.100;Balcão gavetas;1.020,00\nXYZ;Outro;5\n")

    def responder(req: httpx.Request) -> httpx.Response:
        chamadas.append((req.method, str(req.url), req.headers.get("authorization")))
        if req.url.path.endswith("/TablesPrices/Search"):
            return httpx.Response(200, json={"tablesPrices": [{"id": 7, "description": "Antiga", "active": False},
                                                              {"id": 9, "description": "Tabela 2026", "active": True}]})
        if req.url.path.endswith("/TablesPrices/9/Products/Csv"):
            return httpx.Response(200, text='"https://blob.promob.com/x/tabela.zip?sig=abc"')
        if req.url.host == "blob.promob.com":
            return httpx.Response(200, content=pacote.getvalue())
        return httpx.Response(404)

    monkeypatch.setattr(promob_prices, "TRANSPORTE", httpx.MockTransport(responder))
    admin = cenario["admin"]
    r = client.post("/api/comercial/prices/sincronizar", headers=admin).json()
    assert r["tabela"] == "Tabela 2026" and r["itens"] == 3
    assert chamadas[0][2] == "Bearer token-secreto-da-conta" and chamadas[2][2] is None  # blob sem o token
    v = enviar_xml(client, cenario["vend"], cenario["op"]["id"])
    p = v["calculo"]["prices"]
    assert p["modulos_encontrados"] == 2 and p["modulos_total"] == 6 and "7201.18.100" in p["faltando"]
    assert client.get("/api/comercial/config", headers=admin).json()["prices_itens"] == 3

    monkeypatch.setattr(promob_prices, "TRANSPORTE", httpx.MockTransport(lambda req: httpx.Response(401)))
    r = client.post("/api/comercial/prices/sincronizar", headers=admin)
    assert r.status_code == 422 and "token" in r.json()["detail"]
