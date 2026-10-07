"""Popula uma empresa de demonstração a partir do XML de exemplo do Promob.

Uso:  python seed_demo.py   (usa DATABASE_URL, padrão sqlite:///./marcenaria_erp.db)
"""
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

XML = Path(__file__).parent / "exemplos" / "promob_cozinha.xml"

with TestClient(app) as c:
    sessao = c.post("/api/auth/registrar", json={
        "empresa": "Marcenaria Demonstração", "nome": "Administrador",
        "email": "admin@demo.com", "senha": "demo12345"}).json()
    h = {"Authorization": f"Bearer {sessao['token']}"}
    c.post("/api/usuarios", json={"nome": "João (corte)", "email": "operador@demo.com",
                                  "senha": "demo12345", "perfil": "OPERADOR"}, headers=h)
    c.post("/api/carrinhos", json={"quantidade": 3}, headers=h)  # carrinhos da fábrica
    # Capacidade, tempos padrão e custo-hora dos setores; de-para da dobradiça (comprada em caixa com 100)
    centros = {x["codigo"]: x["id"] for x in c.get("/api/centros", headers=h).json()}
    for cod, dados in {"CORTE": {"pessoas": 2, "custo_mensal": 14000, "minutos_peca": 1, "minutos_m2": 2},
                       "BORDA": {"pessoas": 1, "custo_mensal": 7000, "minutos_peca": 2.5},
                       "USINAGEM": {"pessoas": 1, "custo_mensal": 8000, "minutos_peca": 1.5},
                       "EMBALAGEM": {"pessoas": 1, "custo_mensal": 5000, "minutos_peca": 0.8}}.items():
        c.patch(f"/api/centros/{centros[cod]}", json=dados, headers=h)
    cx = c.post("/api/materiais", json={"codigo": "DOB-CX100", "descricao": "Dobradiça caneco 35mm (caixa c/ 100)",
                                        "tipo": "FERRAGEM", "unidade": "CX", "custo_unitario": 690}, headers=h).json()
    c.post("/api/depara", json={"codigo_promob": "DOBTA", "material_id": cx["id"], "fator": 0.01}, headers=h)
    # Estação de expedição isolada: só a função de caixa master
    c.post("/api/usuarios", json={"nome": "Marcos (expedição)", "email": "expedicao@demo.com", "senha": "demo12345",
                                  "perfil": "OPERADOR", "funcoes": ["expedicao"]}, headers=h)
    with open(XML, "rb") as f:
        r = c.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)}, headers=h).json()
    pid = r["projeto_id"]
    hoje = date.today()
    c.put("/api/empresas/atual", json={"imposto_venda_pct": 6}, headers=h)
    c.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 2093.46, "parcelas": 2,
                                                  "primeiro_vencimento": str(hoje)}, headers=h)
    c.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "MONTAGEM", "descricao": "Montador da obra",
                                     "valor": 190.31, "vencimento": str(hoje + timedelta(days=20)),
                                     "projeto_id": pid}, headers=h)
    c.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "DESPESA_FIXA", "descricao": "Aluguel do galpão",
                                     "valor": 3500, "vencimento": str(hoje + timedelta(days=10))}, headers=h)
    c.post(f"/api/projetos/{pid}/liberar", headers=h)

    # Segunda obra: ciclo completo até a entrega, com uma assistência resolvida
    with open(XML, "rb") as f:
        p2 = c.post("/api/projetos/importar-xml", data={"nome": "Família Souza · Cozinha"},
                    files={"arquivo": ("Cozinha.xml", f)}, headers=h).json()["projeto_id"]
    c.patch(f"/api/projetos/{pid}", json={"data_entrega": str(hoje + timedelta(days=30))}, headers=h)
    c.patch(f"/api/projetos/{p2}", json={"data_entrega": str(hoje + timedelta(days=5))}, headers=h)
    c.post(f"/api/projetos/{p2}/contrato", json={"valor_venda": 2400, "parcelas": 3,
                                                 "primeiro_vencimento": str(hoje)}, headers=h)
    c.post(f"/api/projetos/{p2}/liberar", headers=h)
    op2 = c.post(f"/api/projetos/{p2}/ops", json={"prioridade": 2}, headers=h).json()
    for u in c.get(f"/api/ops/{op2['id']}", headers=h).json()["unidades"]:
        for e in u["etapas"]:
            c.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": e["centro_codigo"]},
                   headers=h)
    mont = c.post("/api/montagens", json={"projeto_id": p2, "data_inicio": str(hoje), "data_fim": str(hoje),
                                          "equipe": "Paulo e Jonas"}, headers=h).json()
    c.post(f"/api/montagens/{mont['id']}/iniciar", headers=h)
    for item in mont["itens"]:
        c.post(f"/api/montagens/{mont['id']}/checklist/{item['id']}", json={"ok": True}, headers=h)
    c.post(f"/api/montagens/{mont['id']}/concluir", json={"recebido_por": "Sr. Souza"}, headers=h)
    cham = c.post("/api/chamados", json={"projeto_id": p2, "tipo": "AJUSTE", "descricao": "Frente de gaveta desalinhada"},
                  headers=h).json()
    c.post(f"/api/chamados/{cham['id']}/resolver", json={"causa": "MONTAGEM", "solucao": "Regulagem da corrediça",
                                                         "custo": 60}, headers=h)
    op = c.post(f"/api/projetos/{pid}/ops", json={"prioridade": 1}, headers=h).json()
    for u in c.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"][:8]:
        c.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE"},
               headers=h)
    # Comercial: vendedora, arquiteta com RT e uma negociação aberta com a versão do Promob
    c.post("/api/usuarios", json={"nome": "Ana (vendas)", "email": "vendas@demo.com", "senha": "demo12345",
                                  "perfil": "VENDEDOR"}, headers=h)
    hv = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "vendas@demo.com", "senha": "demo12345"}).json()["token"]}
    c.put("/api/comercial/config", json={"margem_minima": 8}, headers=h)  # obra de exemplo tem valores pequenos
    arq = c.post("/api/parceiros", json={"nome": "Arq. Paula Lima", "tipo": "ARQUITETO", "rt_pct": 5}, headers=h).json()
    neg = c.post("/api/oportunidades", json={"titulo": "Cozinha e área gourmet", "cliente_nome": "Família Rocha",
                                             "telefone": "(19) 99999-0000", "parceiro_id": arq["id"],
                                             "link_3d": "https://galeria3d.promob.com/EVOLXmoY",
                                             "proxima_acao": "Apresentar no showroom",
                                             "proxima_acao_em": str(hoje + timedelta(days=2))}, headers=hv).json()
    c.patch(f"/api/oportunidades/{neg['id']}", json={"etapa": "Negociação"}, headers=hv)
    with open(XML, "rb") as f:
        v = c.post(f"/api/oportunidades/{neg['id']}/versoes", files={"arquivo": ("Cozinha.xml", f)}, headers=hv).json()
    c.post(f"/api/versoes/{v['id']}/negociar", json={"desconto_pct": 8, "condicao": "6x sem juros"}, headers=hv)
    c.post("/api/oportunidades", json={"titulo": "Dormitório casal", "cliente_nome": "Carlos Mendes",
                                       "proxima_acao": "Visita técnica para medição"}, headers=hv)
    # Controladoria: centros de custo, verbas, alçada, histórico de antes do ERP, cenário de planejamento
    c.post("/api/usuarios", json={"nome": "Rafael (financeiro)", "email": "financeiro@demo.com", "senha": "demo12345",
                                  "perfil": "FINANCEIRO"}, headers=h)
    hf = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "financeiro@demo.com", "senha": "demo12345"}).json()["token"]}
    ccs = {}
    for cod, nome, tipo, setor in (("ADM", "Administrativo", "ADMINISTRATIVO", None), ("COM", "Comercial e marketing", "COMERCIAL", None),
                                   ("FAB", "Fábrica · corte", "PRODUTIVO", "CORTE")):
        ccs[cod] = c.post("/api/centros-custo", json={"codigo": cod, "nome": nome, "tipo": tipo, "setor_codigo": setor,
                                                     "responsavel_id": 1}, headers=h).json()["id"]
    c.put("/api/controladoria/config", json={"alcada_valor": 5000, "centros_padrao": {"RECEITA": ccs["COM"], "MATERIAL": ccs["FAB"]}}, headers=h)
    c.put("/api/verbas", json=[{"centro_custo_id": ccs[cc], "ano": hoje.year, "mes": hoje.month, "conta": conta, "valor": v}
                               for cc, conta, v in (("ADM", "OCUPACAO", 4000), ("ADM", "ADMINISTRATIVAS", 1500), ("COM", "COMERCIAL", 3000),
                                                    ("FAB", "PESSOAL", 14000), ("FAB", "MANUTENCAO", 1200))], headers=h)
    for l in c.get("/api/lancamentos?tipo=PAGAR", headers=h).json():
        if l["descricao"] == "Aluguel do galpão":
            c.patch(f"/api/lancamentos/{l['id']}/classificar", json={"centro_custo_id": ccs["ADM"], "conta": "OCUPACAO"}, headers=h)
    c.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "DESPESA_FIXA", "descricao": "Campanha Instagram", "valor": 1800,
                                     "vencimento": str(hoje), "centro_custo_id": ccs["COM"], "conta": "COMERCIAL"}, headers=hf)
    c.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "DESPESA_FIXA", "descricao": "Feira Movelsul (estande)", "valor": 6500,
                                     "vencimento": str(hoje + timedelta(days=15)), "centro_custo_id": ccs["COM"], "conta": "COMERCIAL"}, headers=hf)
    linhas = ["mes;conta;valor;regime;centro"]
    for n in (3, 2, 1):
        t = hoje.year * 12 + hoje.month - 1 - n
        mes = f"{t // 12}-{t % 12 + 1:02d}"
        for conta, v, cc in (("RECEITA", 118000 + 6000 * n, ""), ("IMPOSTOS", 7300, ""), ("MATERIAL", 61000, "FAB"), ("COMISSOES", 5900, "COM"),
                             ("FRETE_MONTAGEM", 4200, ""), ("PESSOAL", 13500, "FAB"), ("PESSOAL", 14500, "ADM"), ("OCUPACAO", 6800, "ADM"),
                             ("ADMINISTRATIVAS", 3400, "ADM"), ("COMERCIAL", 2600, "COM"), ("MANUTENCAO", 1100, "FAB")):
            linhas.append(f"{mes};{conta};{v};COMPETENCIA;{cc}")
    c.post("/api/controladoria/historico", files={"arquivo": ("historico.csv", "\n".join(linhas).encode())}, headers=h)
    c.post("/api/cenarios", json={"nome": "Plano da fábrica", "premissas": {
        "imovel": {"situacao": "LOCADO", "frente_m": 20, "fundo_m": 30, "locacao_m2": 30, "valor_m2": 3500},
        "investimentos": [{"nome": "Seccionadora", "tipo": "MAQUINA", "valor": 180000}, {"nome": "Coladeira de borda", "tipo": "MAQUINA", "valor": 90000},
                          {"nome": "Furadeira CNC", "tipo": "MAQUINA", "valor": 60000}, {"nome": "Caminhão", "tipo": "FROTA", "valor": 120000},
                          {"nome": "Showroom", "tipo": "OUTRO", "valor": 40000}],
        "pessoal": {"funcionarios": 9, "folha": 16000, "encargos_pct": 70, "pro_labore": 8000, "encargos_pro_labore_pct": 27.5},
        "fixos": {"modo": "RESUMO", "resumo": 8500}, "crescimento": {"marketing": 2500},
        "variaveis": {"dv_pct": 52, "rt_pct": 0, "comissoes_pct": 5, "imposto_pct": 6}, "lucro_pct": 15,
        "maquinas": {"quantidade": 3, "dias": 21, "horas": 7, "operador": 2800, "horas_ociosas": 25}}}, headers=h)
    c.post("/api/controladoria/consolidar", json={"meses": 2}, headers=h)
    print(f"Demonstração criada: {r['pecas']} peças importadas do XML.\n"
          "Abra http://localhost:8000 e entre com admin@demo.com / demo12345 "
          "(operador: operador@demo.com, expedição: expedicao@demo.com, vendas: vendas@demo.com, financeiro: financeiro@demo.com, senha demo12345)")
