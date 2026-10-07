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
    op = c.post(f"/api/projetos/{pid}/ops", json={"prioridade": 1}, headers=h).json()
    for u in c.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"][:8]:
        c.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE"},
               headers=h)
    print(f"Demonstração criada: {r['pecas']} peças importadas do XML.\n"
          "Abra http://localhost:8000 e entre com admin@demo.com / demo12345 "
          "(operador: operador@demo.com / demo12345)")
