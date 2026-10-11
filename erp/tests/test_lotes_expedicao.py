import copy
import os
import xml.etree.ElementTree as ET

import pytest

from conftest import EXEMPLOS, criar_usuario

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")


def xml_dois_ambientes(tmp_path):
    """Mesmo projeto do Promob com um segundo ambiente (Lavanderia), para testar a separação por ambiente."""
    arvore = ET.parse(XML)
    ambientes = arvore.getroot().find("AMBIENTS")
    extra = copy.deepcopy(ambientes.find("AMBIENT"))
    extra.set("DESCRIPTION", "Lavanderia")
    ambientes.append(extra)
    destino = tmp_path / "dois_ambientes.xml"
    arvore.write(destino, encoding="utf-8", xml_declaration=True)
    return destino


def xml_outro_cliente(tmp_path, nome="Família Souza"):
    arvore = ET.parse(XML)
    for d in arvore.getroot().iter("DATA"):
        if d.get("ID") in ("nomecliente", "corporateName"):
            d.set("VALUE", nome)
    destino = tmp_path / "outro_cliente.xml"
    arvore.write(destino, encoding="utf-8", xml_declaration=True)
    return destino


def liberado(client, h, caminho=XML):
    with open(caminho, "rb") as f:
        pid = client.post("/api/projetos/importar-xml", files={"arquivo": ("Projeto.xml", f)}, headers=h).json()["projeto_id"]
    assert client.post(f"/api/projetos/{pid}/liberar", headers=h).status_code == 200
    return pid


def unidades(client, h, op_id):
    return client.get(f"/api/ops/{op_id}", headers=h).json()["unidades"]


def preparar(client, h, u):
    """Dá baixa em tudo menos a EMBALAGEM: a peça fica pronta para ir para a caixa."""
    for e in u["etapas"]:
        if e["centro_codigo"] != "EMBALAGEM" and not e["concluida_em"]:
            assert client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": e["centro_codigo"]},
                               headers=h).status_code == 200


def bipar(client, h, cb, caixa_id=None, nova=False):
    return client.post("/api/expedicao/bipar", json={"codigo_barras": cb, "caixa_id": caixa_id, "nova_caixa": nova}, headers=h)


def test_formacao_e_controle_de_lote(client, empresa):
    p1, p2, p3 = liberado(client, empresa), liberado(client, empresa), liberado(client, empresa)
    r = client.post("/api/lotes", json={"descricao": "Semana 41", "projeto_ids": [p1, p2], "prioridade": 2,
                                         "data_entrega": "2026-11-10"}, headers=empresa)
    assert r.status_code == 201, r.text
    lote = r.json()
    assert lote["numero"] == 1 and lote["status"] == "ABERTO" and lote["total_pecas"] == 68
    assert [p["op_numero"] for p in lote["projetos"]] == [1, 2]
    ops = client.get("/api/ops", headers=empresa).json()
    assert {o["lote_numero"] for o in ops} == {1} and all(o["data_entrega"] == "2026-11-10" for o in ops)

    # Projeto que já está em produção não entra em outro lote; projeto novo entra enquanto o lote não começou
    assert client.post("/api/lotes", json={"descricao": "Outro", "projeto_ids": [p1]}, headers=empresa).status_code == 409
    lote = client.post(f"/api/lotes/{lote['id']}/projetos", json={"projeto_ids": [p3]}, headers=empresa).json()
    assert len(lote["projetos"]) == 3 and lote["total_pecas"] == 102

    # Um plano de corte para o lote inteiro aproveita melhor a chapa do que três planos separados
    plano = client.get(f"/api/lotes/{lote['id']}/plano-corte", headers=empresa).json()
    por_op = sum(client.get(f"/api/ops/{p['op_id']}/plano-corte", headers=empresa).json()["total_chapas"] for p in lote["projetos"])
    assert plano["titulo"] == "Lote 1" and sum(m["total_pecas"] for m in plano["materiais"]) == 102
    assert plano["total_chapas"] <= por_op
    assert any(pc["descricao"].startswith("P-0002 ") for m in plano["materiais"] for ch in m["chapas"] for pc in ch["pecas"])

    # Etiqueta diz de quem é a peça: lote, projeto (cliente) e ambiente
    etq = client.get(f"/api/lotes/{lote['id']}/etiquetas.html", headers=empresa).text
    assert etq.count('class="etq"') == 102 and "L1 P-0003" in etq and "Projeto - Ambiente 3D" in etq
    assert client.get(f"/api/lotes/{lote['id']}/etiquetas.zpl", headers=empresa).text.count("^XA") == 102

    # Começou a produzir: o lote fecha para novos projetos
    cb = unidades(client, empresa, lote["projetos"][0]["op_id"])[0]["codigo_barras"]
    client.post("/api/apontamentos", json={"codigo_barras": cb, "centro_codigo": "CORTE"}, headers=empresa)
    p4 = liberado(client, empresa)
    r = client.post(f"/api/lotes/{lote['id']}/projetos", json={"projeto_ids": [p4]}, headers=empresa)
    assert r.status_code == 409 and "lote novo" in r.json()["detail"]
    assert client.get(f"/api/lotes/{lote['id']}", headers=empresa).json()["status"] == "EM_PRODUCAO"
    c = client.get(f"/api/producao/pecas?lote_id={lote['id']}", headers=empresa).json()
    assert c["total"] == 102 and c["pecas"][0]["lote_numero"] == 1
    assert client.get("/api/lotes", headers=empresa).json()[0]["numero"] == 1

    operador = criar_usuario(client, empresa, "OPERADOR")
    assert client.post("/api/lotes", json={"descricao": "x1", "projeto_ids": [p4]}, headers=operador).status_code == 403


@pytest.fixture
def lote_misto(client, empresa, tmp_path):
    """Lote com dois clientes: P-0001 tem Cozinha e Lavanderia; P-0002 (Família Souza) só Cozinha."""
    p1 = liberado(client, empresa, xml_dois_ambientes(tmp_path))
    p2 = liberado(client, empresa, xml_outro_cliente(tmp_path))
    lote = client.post("/api/lotes", json={"descricao": "Misto", "projeto_ids": [p1, p2]}, headers=empresa).json()
    u1 = unidades(client, empresa, lote["projetos"][0]["op_id"])
    u2 = unidades(client, empresa, lote["projetos"][1]["op_id"])
    return p1, p2, u1, u2, lote["projetos"][1]["op_id"]


def test_caixa_master_trava_cliente_e_ambiente(client, empresa, lote_misto):
    p1, p2, u1, u2, op2 = lote_misto
    cozinha = [u for u in u1 if u["ambiente"] == "Projeto - Ambiente 3D"]
    lavand = [u for u in u1 if u["ambiente"] == "Lavanderia"]
    mod = cozinha[0]["modulo"]
    mesmo_mod = [u for u in cozinha if u["modulo"] == mod]
    outro_mod = next(u for u in cozinha if u["modulo"] != mod)

    # Peça que ainda não passou pela fábrica não entra na caixa
    r = bipar(client, empresa, mesmo_mod[0]["codigo_barras"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "PRODUCAO_PENDENTE"

    for u in mesmo_mod[:2] + [outro_mod, lavand[0], u2[0]]:
        preparar(client, empresa, u)
    r = bipar(client, empresa, mesmo_mod[0]["codigo_barras"])
    assert r.status_code == 200, r.text
    caixa = r.json()["caixa"]
    assert r.json()["acao"] == "ADICIONADA" and r.json()["embalagem_apontada"] and caixa["numero"] == 1
    assert caixa["codigo_barras"] == "990010000001" and caixa["ambiente"] == "Projeto - Ambiente 3D"
    assert bipar(client, empresa, mesmo_mod[1]["codigo_barras"], caixa["id"]).json()["caixa"]["total_itens"] == 2

    # Outro cliente: recusa, e a peça continua sem a baixa da embalagem
    r = bipar(client, empresa, u2[0]["codigo_barras"], caixa["id"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "CLIENTE_DIFERENTE"
    assert "OUTRO CLIENTE" in r.json()["detail"]["mensagem"] and r.json()["detail"]["sugestao"] == "SEPARAR"
    assert "Família Souza" in r.json()["detail"]["mensagem"]
    recusada = next(u for u in unidades(client, empresa, op2) if u["codigo_barras"] == u2[0]["codigo_barras"])
    assert not recusada["etapas"][-1]["concluida_em"]

    # Mesmo cliente, outra obra: também não mistura (são entregas diferentes)
    p3 = liberado(client, empresa)
    op3 = client.post(f"/api/projetos/{p3}/ops", json={}, headers=empresa).json()["id"]
    u3 = unidades(client, empresa, op3)[0]
    preparar(client, empresa, u3)
    r = bipar(client, empresa, u3["codigo_barras"], caixa["id"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "OUTRA_OBRA" and "OUTRA OBRA" in r.json()["detail"]["mensagem"]

    # Mesmo cliente, outro ambiente: sugere outra caixa master; aceitar abre a caixa 2
    r = bipar(client, empresa, lavand[0]["codigo_barras"], caixa["id"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "MODULO_DISTINTO" and r.json()["detail"]["sugestao"] == "NOVA_CAIXA"
    c2 = bipar(client, empresa, lavand[0]["codigo_barras"], caixa["id"], nova=True).json()["caixa"]
    assert c2["numero"] == 2 and c2["ambiente"] == "Lavanderia" and c2["volumes_projeto"] == 2

    # Limite de módulos por caixa (configurável na empresa)
    client.put("/api/empresas/atual", json={"caixa_max_modulos": 1}, headers=empresa)
    r = bipar(client, empresa, outro_mod["codigo_barras"], caixa["id"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "MODULO_DISTINTO" and "limite é 1" in r.json()["detail"]["mensagem"]
    client.put("/api/empresas/atual", json={"caixa_max_modulos": 3}, headers=empresa)
    assert bipar(client, empresa, outro_mod["codigo_barras"], caixa["id"]).json()["caixa"]["modulos"] == [mod, outro_mod["modulo"]]

    # Bipar duas vezes, bipar a etiqueta da caixa, peça de outro cliente abre a caixa dele
    r = bipar(client, empresa, mesmo_mod[0]["codigo_barras"], c2["id"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "JA_EMBALADA"
    r = bipar(client, empresa, caixa["codigo_barras"])
    assert r.json()["acao"] == "CAIXA_SELECIONADA" and r.json()["caixa"]["id"] == caixa["id"]
    c3 = bipar(client, empresa, u2[0]["codigo_barras"], caixa["id"], nova=True).json()["caixa"]
    assert c3["projeto_id"] == p2 and c3["volume"] == 1


def test_fechar_carregar_romaneio_e_controle(client, empresa, lote_misto):
    p1, _, u1, _, _ = lote_misto
    a, b = u1[0], u1[1]
    preparar(client, empresa, a); preparar(client, empresa, b)
    caixa = bipar(client, empresa, a["codigo_barras"]).json()["caixa"]
    bipar(client, empresa, b["codigo_barras"], caixa["id"])

    # Peça embalada não estorna; refugada sai da caixa
    r = client.post("/api/apontamentos/estorno", json={"codigo_barras": a["codigo_barras"], "centro_codigo": "EMBALAGEM",
                                                         "motivo": "teste"}, headers=empresa)
    assert r.status_code == 409 and "caixa master 1" in r.json()["detail"]
    client.post("/api/apontamentos/refugo", json={"codigo_barras": b["codigo_barras"], "centro_codigo": "EMBALAGEM",
                                                    "motivo": "riscou na embalagem"}, headers=empresa)
    assert client.get(f"/api/caixas/{caixa['id']}", headers=empresa).json()["total_itens"] == 1

    # Carregar só caixa fechada, só pela etiqueta da caixa, uma única vez
    assert client.post("/api/expedicao/carregar", json={"codigo_barras": caixa["codigo_barras"]}, headers=empresa).status_code == 409
    assert client.post("/api/expedicao/carregar", json={"codigo_barras": a["codigo_barras"]}, headers=empresa).status_code == 422
    assert client.post(f"/api/caixas/{caixa['id']}/fechar", headers=empresa).json()["status"] == "FECHADA"
    r = bipar(client, empresa, caixa["codigo_barras"])
    assert r.status_code == 409 and r.json()["detail"]["tipo"] == "CAIXA_FECHADA"
    assert client.post("/api/expedicao/carregar", json={"codigo_barras": caixa["codigo_barras"]}, headers=empresa).json()["status"] == "EXPEDIDA"
    assert client.post("/api/expedicao/carregar", json={"codigo_barras": caixa["codigo_barras"]}, headers=empresa).status_code == 409
    assert client.post(f"/api/caixas/{caixa['id']}/reabrir", headers=empresa).status_code == 409

    r = client.get(f"/api/projetos/{p1}/expedicao", headers=empresa).json()
    assert r["embaladas"] == 1 and r["expedidas"] == 1 and r["total_pecas"] == len(u1) and not r["pronto_para_expedir"]
    assert len(r["pendentes"]) == len(u1) - 1  # a reposição da refugada também está pendente
    rom = client.get(f"/api/projetos/{p1}/romaneio.html", headers=empresa).text
    assert "Volume 1/1" in rom and a["codigo_barras"] in rom and "fora de caixa" in rom
    etq = client.get(f"/api/caixas/{caixa['id']}/etiqueta.html", headers=empresa).text
    assert "VOLUME 1/1" in etq and caixa["codigo_barras"] in etq
    assert caixa["codigo_barras"] in client.get(f"/api/caixas/{caixa['id']}/etiqueta.zpl", headers=empresa).text
    pecas = client.get(f"/api/producao/pecas?busca={a['codigo_barras']}", headers=empresa).json()["pecas"]
    assert pecas[0]["caixa_numero"] == 1

    operador = criar_usuario(client, empresa, "OPERADOR")
    assert bipar(client, operador, a["codigo_barras"]).status_code == 403


def test_remover_e_caixa_vazia(client, empresa, lote_misto):
    _, _, u1, _, _ = lote_misto
    preparar(client, empresa, u1[0])
    caixa = bipar(client, empresa, u1[0]["codigo_barras"]).json()["caixa"]
    r = client.post(f"/api/caixas/{caixa['id']}/remover", json={"codigo_barras": u1[0]["codigo_barras"]}, headers=empresa)
    assert r.json()["total_itens"] == 0
    r = client.post(f"/api/caixas/{caixa['id']}/fechar", headers=empresa)
    assert r.status_code == 422 and r.json()["detail"]["tipo"] == "CAIXA_VAZIA"
    # A peça removida pode ser bipada de novo (a baixa da embalagem já ficou feita)
    r = bipar(client, empresa, u1[0]["codigo_barras"], caixa["id"])
    assert r.status_code == 200 and not r.json()["embalagem_apontada"]


def test_voltar_para_programacao_projeto_e_lote(client, empresa):
    p1, p2, p3 = liberado(client, empresa), liberado(client, empresa), liberado(client, empresa)
    lote = client.post("/api/lotes", json={"descricao": "Semana 42", "projeto_ids": [p1, p2, p3]}, headers=empresa).json()
    op1, op2, op3 = (p["op_id"] for p in lote["projetos"])

    # Projeto a projeto: a OP sai da fábrica e o projeto volta a LIBERADO
    r = client.post(f"/api/ops/{op1}/voltar-programacao", headers=empresa)
    assert r.status_code == 200 and r.json()["status"] == "CANCELADA" and "Voltou para programação" in r.json()["motivo_cancelamento"]
    assert next(p for p in client.get("/api/projetos", headers=empresa).json() if p["id"] == p1)["status"] == "LIBERADO"
    lote = client.get(f"/api/lotes/{lote['id']}", headers=empresa).json()
    assert [p["projeto_id"] for p in lote["projetos"]] == [p2, p3] and lote["total_pecas"] == 68
    # Etiqueta da OP que voltou não vale mais no leitor; o projeto pode ganhar OP nova (número novo)
    cb_antiga = unidades(client, empresa, op1)[0]["codigo_barras"]
    assert client.post("/api/apontamentos", json={"codigo_barras": cb_antiga, "centro_codigo": "CORTE"}, headers=empresa).status_code == 409
    nova = client.post(f"/api/projetos/{p1}/ops", json={}, headers=empresa).json()
    assert nova["numero"] == 4

    # Fábrica já tocou: não volta, e o lote não volta pela metade
    cb = unidades(client, empresa, op2)[0]["codigo_barras"]
    client.post("/api/apontamentos", json={"codigo_barras": cb, "centro_codigo": "CORTE"}, headers=empresa)
    r = client.post(f"/api/ops/{op2}/voltar-programacao", headers=empresa)
    assert r.status_code == 409 and "1 baixa(s)" in r.json()["detail"]
    r = client.post(f"/api/lotes/{lote['id']}/voltar-programacao", headers=empresa)
    assert r.status_code == 409 and "não pode voltar inteiro" in r.json()["detail"]
    assert client.get(f"/api/ops/{op3}", headers=empresa).json()["status"] == "ABERTA"  # nada mudou

    # Estornada a baixa, o lote inteiro volta e os projetos ficam livres para outro lote
    client.post("/api/apontamentos/estorno", json={"codigo_barras": cb, "centro_codigo": "CORTE", "motivo": "teste"}, headers=empresa)
    r = client.post(f"/api/lotes/{lote['id']}/voltar-programacao", headers=empresa)
    assert r.status_code == 409 and "estorno ou refugo" in r.json()["detail"]  # OP com histórico de ocorrência: cancelar, não reprogramar
    client.post(f"/api/ops/{op2}/cancelar", headers=empresa)
    r = client.post(f"/api/lotes/{lote['id']}/voltar-programacao", headers=empresa)
    assert r.status_code == 200 and r.json()["status"] == "CANCELADO"
    assert next(p for p in client.get("/api/projetos", headers=empresa).json() if p["id"] == p3)["status"] == "LIBERADO"
    outro = client.post("/api/lotes", json={"descricao": "Semana 43", "projeto_ids": [p3]}, headers=empresa)
    assert outro.status_code == 201 and outro.json()["numero"] == 2

    operador = criar_usuario(client, empresa, "OPERADOR")
    assert client.post(f"/api/ops/{nova['id']}/voltar-programacao", headers=operador).status_code == 403
