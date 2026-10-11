import os
from datetime import date, datetime

from conftest import EXEMPLOS, criar_usuario, registrar

from app.db import SessionLocal
from app.models import MovimentoBancario
from app.services import agendador, controladoria, markup

XML = os.path.join(EXEMPLOS, "promob_cozinha.xml")
HOJE = date.today()
MES = f"{HOJE.year}-{HOJE.month:02d}"


def mes_antes(n):
    t = HOJE.year * 12 + HOJE.month - 1 - n
    return t // 12, t % 12 + 1


def usuario(client, admin, perfil, email, funcoes=None):
    h = criar_usuario(client, admin, perfil, email=email, nome=email.split("@")[0].title())
    uid = next(u["id"] for u in client.get("/api/usuarios", headers=admin).json() if u["email"] == email)
    if funcoes is not None:
        client.patch(f"/api/usuarios/{uid}", json={"funcoes": funcoes}, headers=admin)
    return h, uid


def obra_concluida(client, h, valor=3000):
    with open(XML, "rb") as f:
        pid = client.post("/api/projetos/importar-xml", files={"arquivo": ("c.xml", f)}, headers=h).json()["projeto_id"]
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": valor, "parcelas": 1, "primeiro_vencimento": str(HOJE)}, headers=h)
    assert client.post(f"/api/projetos/{pid}/liberar", headers=h).status_code == 200
    op = client.post(f"/api/projetos/{pid}/ops", json={"prioridade": 1}, headers=h).json()
    for u in client.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"]:
        for e in u["etapas"]:
            client.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": e["centro_codigo"]}, headers=h)
    assert client.get(f"/api/projetos/{pid}", headers=h).json()["status"] == "CONCLUIDO"
    return pid


def test_centros_verbas_e_fluxo_de_aprovacao(client, empresa):
    fin, fin_id = usuario(client, empresa, "FINANCEIRO", "fin@m.com")
    gestor, _ = usuario(client, empresa, "GESTOR", "gestor@m.com")
    fin2, _ = usuario(client, empresa, "FINANCEIRO", "fin2@m.com")
    vend, _ = usuario(client, empresa, "VENDEDOR", "vend@m.com")
    cc = lambda d: client.post("/api/centros-custo", json=d, headers=fin)  # noqa: E731
    adm = cc({"codigo": "ADM", "nome": "Administrativo", "responsavel_id": fin_id}).json()
    com = cc({"codigo": "COM", "nome": "Comercial", "tipo": "COMERCIAL", "responsavel_id": fin_id}).json()
    prod = cc({"codigo": "PROD", "nome": "Fábrica", "tipo": "PRODUTIVO", "setor_codigo": "CORTE"}).json()
    assert prod["setor_codigo"] == "CORTE" and adm["responsavel"] == "Fin"
    assert cc({"codigo": "X1", "nome": "Erro", "setor_codigo": "PINTURA"}).status_code == 422
    assert cc({"codigo": "ADM", "nome": "Dup"}).status_code == 409
    assert client.post("/api/centros-custo", json={"codigo": "V1", "nome": "Vend"}, headers=vend).status_code == 403
    assert client.put("/api/controladoria/config", json={"alcada_valor": 5000}, headers=fin).status_code == 403
    client.put("/api/controladoria/config", json={"alcada_valor": 5000, "centros_padrao": {"RECEITA": com["id"]}}, headers=empresa)

    verbas = [{"centro_custo_id": adm["id"], "ano": HOJE.year, "mes": HOJE.month, "conta": "OCUPACAO", "valor": 4000},
              {"centro_custo_id": adm["id"], "ano": HOJE.year, "mes": HOJE.month, "conta": "ADMINISTRATIVAS", "valor": 1000}]
    assert client.put("/api/verbas", json=verbas, headers=fin).json()["gravadas"] == 2
    assert client.put("/api/verbas", json=[{**verbas[0], "conta": "RECEITA"}], headers=fin).status_code == 422

    def despesa(h, valor, centro, conta="OCUPACAO"):
        return client.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "DESPESA_FIXA", "descricao": f"Despesa {valor}",
                                                     "valor": valor, "vencimento": str(HOJE), "centro_custo_id": centro, "conta": conta}, headers=h)
    a = despesa(fin, 3000, adm["id"]).json()
    assert a["aprovacao"] == "LIVRE" and a["centro_custo"] == "ADM" and a["conta"] == "OCUPACAO"
    b = despesa(fin, 2500, adm["id"]).json()  # 5.500 > verba de 5.000: sobe para a gestão
    assert b["aprovacao"] == "PENDENTE" and "estoura a verba de ADM" in b["aprovacao_motivo"]
    assert client.post(f"/api/lancamentos/{b['id']}/baixar", json={"data": str(HOJE)}, headers=fin).status_code == 409
    assert client.post(f"/api/lancamentos/{b['id']}/aprovar", json={"aprovar": True}, headers=fin).status_code == 403
    assert [x["id"] for x in client.get("/api/controladoria/aprovacoes", headers=gestor).json()] == [b["id"]]
    assert [x["id"] for x in client.get("/api/controladoria/aprovacoes", headers=fin).json()] == []
    r = client.post(f"/api/lancamentos/{b['id']}/aprovar", json={"aprovar": True, "observacao": "reajuste do aluguel"}, headers=gestor).json()
    assert r["aprovacao"] == "APROVADA" and r["aprovado_por"] == "Gestor" and "reajuste" in r["aprovacao_motivo"]
    assert client.post(f"/api/lancamentos/{b['id']}/baixar", json={"data": str(HOJE)}, headers=fin).status_code == 200
    c = despesa(fin2, 6000, com["id"], "COMERCIAL").json()  # sem verba, acima da alçada: o responsável libera
    assert c["aprovacao"] == "PENDENTE" and "[RESPONSAVEL]" in c["aprovacao_motivo"]
    proprio = despesa(fin, 6000, com["id"], "COMERCIAL").json()  # o responsável não aprova a própria despesa
    assert proprio["aprovacao"] == "PENDENTE"
    assert client.post(f"/api/lancamentos/{proprio['id']}/aprovar", json={"aprovar": True}, headers=fin).status_code == 403
    client.delete(f"/api/lancamentos/{proprio['id']}", headers=fin)
    assert client.post(f"/api/lancamentos/{c['id']}/aprovar", json={"aprovar": False}, headers=fin).json()["aprovacao"] == "RECUSADA"
    assert despesa(empresa, 9000, com["id"], "COMERCIAL").json()["aprovacao"] == "APROVADA"  # quem aprova não espera
    assert despesa(fin, 10, 999).status_code == 422
    client.put("/api/controladoria/config", json={"exige_centro": True}, headers=empresa)
    assert despesa(fin, 10, None).status_code == 422
    # Reclassificação de lançamento gerado pelo sistema
    lista = client.get(f"/api/lancamentos?centro_custo_id={adm['id']}", headers=fin).json()
    assert len(lista) == 2
    r = client.patch(f"/api/lancamentos/{lista[0]['id']}/classificar", json={"conta": "MANUTENCAO"}, headers=fin).json()
    assert r["conta"] == "MANUTENCAO"

    # Relatório por centro: verba, realizado, saldo e consumo
    client.post("/api/controladoria/consolidar", json={"meses": 1}, headers=fin)
    rel = {x["codigo"]: x for x in client.get(f"/api/controladoria/centros?ano={HOJE.year}&mes_de={HOJE.month}&mes_ate={HOJE.month}",
                                              headers=fin).json()}
    assert rel["ADM"]["verba"] == 5000 and rel["ADM"]["realizado"] == 5500 and rel["ADM"]["consumo_pct"] == 110.0
    assert rel["COM"]["realizado"] == 9000 and rel["COM"]["por_conta"] == {"COMERCIAL": 9000}
    assert client.get(f"/api/controladoria/centros.csv?ano={HOJE.year}", headers=fin).text.startswith("﻿Centro;")
    assert client.get(f"/api/controladoria/dre?ano={HOJE.year}", headers=vend).status_code == 403


def test_consolidacao_dre_gerencial_bancario_historico_e_agendador(client, empresa):
    client.put("/api/empresas/atual", json={"imposto_venda_pct": 6}, headers=empresa)
    pid = obra_concluida(client, empresa, 3000)
    client.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "COMISSAO", "descricao": "Comissão obra", "valor": 90,
                                          "vencimento": str(HOJE), "projeto_id": pid}, headers=empresa)
    aluguel = client.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "DESPESA_FIXA", "descricao": "Aluguel", "valor": 2000,
                                                    "vencimento": str(HOJE), "conta": "OCUPACAO"}, headers=empresa).json()
    client.post(f"/api/lancamentos/{aluguel['id']}/baixar", json={"data": str(HOJE)}, headers=empresa)
    receber = client.get(f"/api/lancamentos?projeto_id={pid}&tipo=RECEBER", headers=empresa).json()[0]
    client.post(f"/api/lancamentos/{receber['id']}/baixar", json={"data": str(HOJE)}, headers=empresa)
    emp_id = client.get("/api/empresas/atual", headers=empresa).json()["id"]
    with SessionLocal() as db:  # tarifa no extrato ainda sem conciliar
        db.add(MovimentoBancario(empresa_id=emp_id, fitid="T1", data=HOJE, valor=-35.5, descricao="Tarifa pacote"))
        db.commit()

    ex = client.post("/api/controladoria/consolidar", json={"meses": 2}, headers=empresa).json()
    assert ex["status"] == "OK" and ex["resumo"]["meses"][0]["receita"] == 3000 and ex["resumo"]["nao_conciliados"] == 1
    d = client.get(f"/api/controladoria/dre?ano={HOJE.year}&mes_de={HOJE.month}&mes_ate={HOJE.month}", headers=empresa).json()
    m = d["meses"][0]
    assert m["fonte"] == "ERP" and m["realizado"]["RECEITA"] == 3000 and m["realizado"]["IMPOSTOS"] == 180
    assert m["realizado"]["MATERIAL"] > 0 and m["realizado"]["COMISSOES"] == 90 and m["realizado"]["OCUPACAO"] == 2000
    t = d["totais"]
    assert t["margem_contribuicao"] == round(3000 - 180 - m["realizado"]["MATERIAL"] - 90, 2)
    assert t["resultado"] == round(t["margem_contribuicao"] - 2000, 2)
    cx = client.get(f"/api/controladoria/dre?ano={HOJE.year}&regime=CAIXA&mes_de={HOJE.month}&mes_ate={HOJE.month}", headers=empresa).json()
    mc = cx["meses"][0]["realizado"]
    assert mc["RECEITA"] == 3000 and mc["OCUPACAO"] == 2000 and mc["NAO_CONCILIADO"] == 35.5 and "MATERIAL" not in mc
    assert client.get(f"/api/controladoria/dre?ano={HOJE.year}&regime=XPTO", headers=empresa).status_code == 422
    assert "Conta;Descrição" in client.get(f"/api/controladoria/dre.csv?ano={HOJE.year}", headers=empresa).text

    # Histórico de antes do ERP: entra nos meses sem dados e alimenta as premissas
    a3, m3 = mes_antes(3)
    a2, m2 = mes_antes(2)
    csv = "mes;conta;valor;centro\n" + "".join(f"{a}-{m:02d};{c};{v};\n" for a, m in ((a3, m3), (a2, m2))
                                                for c, v in (("RECEITA", "100.000,00"), ("MATERIAL", 55000), ("PESSOAL", 20000),
                                                             ("OCUPACAO", 6000), ("COMISSOES", 5000), ("IMPOSTOS", 8000)))
    r = client.post("/api/controladoria/historico", files={"arquivo": ("hist.csv", csv.encode())}, headers=empresa).json()
    assert r["linhas"] == 12
    assert client.post("/api/controladoria/historico", files={"arquivo": ("h.csv", b"mes;conta;valor\n2025-01;XPTO;1\n")},
                       headers=empresa).status_code == 422
    h = client.get(f"/api/controladoria/dre?ano={a3}&mes_de={m3}&mes_ate={m3}", headers=empresa).json()
    assert h["meses"][0]["fonte"] == "HISTORICO" and h["meses"][0]["realizado"]["RECEITA"] == 100000
    hp = client.get("/api/controladoria/historico-premissas?meses=6", headers=empresa).json()
    assert hp["meses_com_dados"] == 2 and hp["dv_pct"] == 55.0 and hp["comissoes_pct"] == 5.0 and hp["pessoal_medio"] == 20000

    # Agendador: uma consolidação por empresa e dia, mesmo chamado de novo (ou por outra instância)
    feitas = agendador.rodar_pendentes(datetime.combine(HOJE, datetime.max.time().replace(microsecond=0)))
    assert any(f["empresa_id"] == emp_id for f in feitas)
    assert agendador.rodar_pendentes(datetime.combine(HOJE, datetime.max.time().replace(microsecond=0))) == []
    client.put("/api/controladoria/config", json={"consolidacao_hora": 23}, headers=empresa)
    ex = client.get("/api/controladoria/execucoes", headers=empresa).json()
    assert ex[0]["origem"] == "AGENDADA" and ex[1]["origem"] == "MANUAL"


def test_cenarios_markup_metas_custo_setores_e_setup(client, empresa):
    base = client.get("/api/cenarios/padrao", headers=empresa).json()
    sim = client.post("/api/cenarios/simular", json=base, headers=empresa).json()
    # Mesmos números da planilha "Ponto de equilíbrio 2.0" com as premissas padrão
    assert sim["venda_necessaria"] == 880237.56 and sim["meta_faturamento"] == 1137385.61
    assert sim["markup"]["markup"] == 1.9312 and sim["markup"]["markup_promob_pct"] == 104.12
    assert sim["maquina"]["custo_hora"] == 485.1 and len(sim["meses"]) == 12
    proprio = client.post("/api/cenarios/simular", json={"imovel": {"situacao": "PROPRIO"}}, headers=empresa).json()
    assert proprio["retorno"]["mercado"] > sim["retorno"]["mercado"]
    assert client.post("/api/cenarios/simular", json={"lucro_pct": 80}, headers=empresa).status_code == 422

    c1 = client.post("/api/cenarios", json={"nome": "Base 2026", "premissas": base}, headers=empresa).json()
    assert c1["principal"] and c1["resultado"]["meta_faturamento"] == 1137385.61
    c2 = client.post("/api/cenarios", json={"nome": "Expansão", "premissas": {"lucro_pct": 20, "pessoal": {"funcionarios": 30}}},
                     headers=empresa).json()
    assert not c2["principal"] and c2["premissas"]["pessoal"]["folha"] == 56000 and c2["resultado"]["markup"]["lucro_pct"] == 20
    client.post(f"/api/cenarios/{c2['id']}/principal", headers=empresa)
    lista = client.get("/api/cenarios", headers=empresa).json()
    assert lista[0]["nome"] == "Expansão" and lista[0]["principal"] and not lista[1]["principal"]
    metas = client.post(f"/api/cenarios/{c2['id']}/aplicar-metas", headers=empresa).json()["metas"]
    assert metas["faturamento_mes"] == c2["resultado"]["meta_faturamento"] and metas["margem_pct"] == 9.0
    assert client.get("/api/gestao/config", headers=empresa).json()["metas"]["faturamento_mes"] == metas["faturamento_mes"]
    # O DRE gerencial usa o cenário principal como previsto da receita e dos variáveis
    d = client.get(f"/api/controladoria/dre?ano={HOJE.year}&mes_de=1&mes_ate=1", headers=empresa).json()
    assert d["meses"][0]["previsto"]["RECEITA"] == c2["resultado"]["meses"][0]["faturamento"]

    # Custo do setor da fábrica a partir do realizado do centro de custo ligado a ele
    client.post("/api/centros-custo", json={"codigo": "PROD", "nome": "Corte", "tipo": "PRODUTIVO", "setor_codigo": "CORTE"}, headers=empresa)
    a1, m1 = mes_antes(1)
    csv = f"mes;conta;valor;centro\n{a1}-{m1:02d};PESSOAL;12000;PROD\n{a1}-{m1:02d};MANUTENCAO;3000;PROD\n"
    client.post("/api/controladoria/historico", files={"arquivo": ("h.csv", csv.encode())}, headers=empresa)
    r = client.post("/api/controladoria/custo-setores", json={"meses": 1, "aplicar": True}, headers=empresa).json()
    assert r["setores"] == [{"centro_custo": "PROD", "setor": "CORTE", "custo_mensal_atual": 0.0, "custo_mensal_realizado": 15000.0}]
    corte = next(c for c in client.get("/api/centros", headers=empresa).json() if c["codigo"] == "CORTE")
    assert corte["custo_mensal"] == 15000 and corte["custo_hora"] > 0
    # Gerar verbas a partir do realizado (média) com reajuste
    v = client.post("/api/verbas/gerar", json={"ano": HOJE.year, "meses": [HOJE.month], "meses_base": 1, "ajuste_pct": 10}, headers=empresa).json()
    assert v["verbas"] == 2
    vb = {x["conta"]: x["valor"] for x in client.get(f"/api/verbas?ano={HOJE.year}", headers=empresa).json()}
    assert vb == {"PESSOAL": 13200.0, "MANUTENCAO": 3300.0}

    # Setup leva centros, regras e cenário principal para outra base
    client.put("/api/controladoria/config", json={"alcada_valor": 8000}, headers=empresa)
    exp = client.get("/api/setup/exportar", headers=empresa).json()
    assert exp["controladoria"]["cenario"]["nome"] == "Expansão" and exp["controladoria"]["alcada_valor"] == 8000
    outra = registrar(client, empresa="Base Dois", email="adm@dois.com")
    r = client.post("/api/setup/aplicar", json={"setup": exp, "secoes": ["controladoria"], "simular": False}, headers=outra).json()
    textos = " | ".join(x["texto"] for x in r["mudancas"])
    assert "Novo centro de custo PROD" in textos and "Novo cenário principal: Expansão" in textos
    assert client.get("/api/cenarios", headers=outra).json()[0]["principal"]
    assert client.get("/api/controladoria/config", headers=outra).json()["alcada_valor"] == 8000
    assert markup.calcular(None)["meta_faturamento"] == 1137385.61 and "RECEITA" in controladoria.NOMES
