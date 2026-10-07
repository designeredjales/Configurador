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
    print(f"Demonstração criada: {r['pecas']} peças importadas do XML.\n"
          "Abra http://localhost:8000 e entre com admin@demo.com / demo12345 "
          "(operador: operador@demo.com, expedição: expedicao@demo.com, vendas: vendas@demo.com, senha demo12345)")
