import os
from datetime import date, timedelta

from conftest import EXEMPLOS, criar_usuario

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")
HOJE = date.today()


def projeto_liberado(client, h):
    with open(XML, "rb") as f:
        pid = client.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)}, headers=h).json()["projeto_id"]
    client.post(f"/api/projetos/{pid}/liberar", headers=h)
    return pid


def produzir(client, h, pid):
    op = client.post(f"/api/projetos/{pid}/ops", json={}, headers=h).json()
    for u in client.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"]:
        for e in u["etapas"]:
            client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": e["centro_codigo"]}, headers=h)


def agendar(client, h, pid):
    return client.post("/api/montagens", json={"projeto_id": pid, "data_inicio": str(HOJE), "data_fim": str(HOJE + timedelta(days=1)),
                                               "equipe": "Equipe Paulo", "endereco": "Rua das Flores, 10"}, headers=h)


def test_montagem_so_inicia_com_producao_concluida_e_entrega_exige_checklist(client, empresa):
    pid = projeto_liberado(client, empresa)
    montador = criar_usuario(client, empresa, "MONTAGEM", nome="Paulo Montador")
    m = agendar(client, montador, pid).json()
    assert m["status"] == "AGENDADA" and len(m["itens"]) == 7 and not m["producao_concluida"]
    assert agendar(client, montador, pid).status_code == 409  # uma montagem ativa por projeto
    r = client.post(f"/api/montagens/{m['id']}/iniciar", headers=montador)
    assert r.status_code == 409 and "produção" in r.json()["detail"]

    produzir(client, empresa, pid)
    p = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert p["status"] == "CONCLUIDO" and p["liberado_em"] and p["producao_concluida_em"]

    m = client.post(f"/api/montagens/{m['id']}/iniciar", headers=montador).json()
    assert m["status"] == "EM_ANDAMENTO"
    for item in m["itens"][:-1]:
        client.post(f"/api/montagens/{m['id']}/checklist/{item['id']}", json={"ok": True}, headers=montador)
    r = client.post(f"/api/montagens/{m['id']}/concluir", json={"recebido_por": "Sra. Silva"}, headers=montador)
    assert r.status_code == 422 and "orientado" in r.json()["detail"]
    ultimo = m["itens"][-1]["id"]
    m = client.post(f"/api/montagens/{m['id']}/checklist/{ultimo}", json={"ok": True, "observacao": "manual entregue"},
                    headers=montador).json()
    assert m["itens"][-1]["conferido_por"] == "Paulo Montador"
    assert client.post(f"/api/montagens/{m['id']}/concluir", json={"recebido_por": " "}, headers=montador).status_code == 422
    m = client.post(f"/api/montagens/{m['id']}/concluir", json={"recebido_por": "Sra. Silva"}, headers=montador).json()
    assert m["status"] == "CONCLUIDA" and m["recebido_por"] == "Sra. Silva"
    p = client.get(f"/api/projetos/{pid}", headers=empresa).json()
    assert p["status"] == "ENTREGUE" and p["entregue_em"]


def test_assistencia_com_causa_raiz_custo_no_dre_e_garantia(client, empresa):
    pid = projeto_liberado(client, empresa)
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 3000, "parcelas": 1, "primeiro_vencimento": str(HOJE)}, headers=empresa)
    assert client.post("/api/chamados", json={"projeto_id": pid, "tipo": "AJUSTE", "descricao": "Porta raspando"},
                       headers=empresa).status_code == 409  # ainda em produção
    produzir(client, empresa, pid)
    m = agendar(client, empresa, pid).json()
    client.post(f"/api/montagens/{m['id']}/iniciar", headers=empresa)
    for item in m["itens"]:
        client.post(f"/api/montagens/{m['id']}/checklist/{item['id']}", json={"ok": True}, headers=empresa)
    client.post(f"/api/montagens/{m['id']}/concluir", json={"recebido_por": "Cliente"}, headers=empresa)

    c = client.post("/api/chamados", json={"projeto_id": pid, "tipo": "AJUSTE", "descricao": "Porta do balcão raspando"},
                    headers=empresa).json()
    assert c["numero"] == 1 and c["em_garantia"] and c["status"] == "ABERTO"
    c = client.patch(f"/api/chamados/{c['id']}", json={"agendado_para": str(HOJE + timedelta(days=2))}, headers=empresa).json()
    assert c["status"] == "AGENDADO"
    dre_antes = client.get(f"/api/projetos/{pid}/dre", headers=empresa).json()
    c = client.post(f"/api/chamados/{c['id']}/resolver", json={"causa": "MONTAGEM", "solucao": "Dobradiça regulada e trocada",
                                                               "custo": 85.5}, headers=empresa).json()
    assert c["status"] == "RESOLVIDO" and c["retrabalho"] is True
    dre = client.get(f"/api/projetos/{pid}/dre", headers=empresa).json()
    assert dre["custos_diretos"]["ASSISTENCIA"] == 85.5
    assert round(dre_antes["margem_contribuicao"] - dre["margem_contribuicao"], 2) == 85.5
    assert client.post(f"/api/chamados/{c['id']}/resolver", json={"causa": "CLIENTE", "solucao": "x"}, headers=empresa).status_code == 409

    c2 = client.post("/api/chamados", json={"projeto_id": pid, "tipo": "DANO", "descricao": "Risco por uso"}, headers=empresa).json()
    c2 = client.post(f"/api/chamados/{c2['id']}/resolver", json={"causa": "CLIENTE", "solucao": "Orientação"}, headers=empresa).json()
    assert c2["retrabalho"] is False
    assert [x["numero"] for x in client.get("/api/chamados?abertos=true", headers=empresa).json()] == []


def test_permissoes_do_pos_obra(client, empresa):
    pid = projeto_liberado(client, empresa)
    for perfil in ("OPERADOR", "COMPRAS", "FINANCEIRO", "ENGENHARIA"):
        h = criar_usuario(client, empresa, perfil)
        assert agendar(client, h, pid).status_code == 403
        assert client.get("/api/montagens", headers=h).status_code == 200  # agenda é visível a todos
