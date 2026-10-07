"""Popula uma empresa de demonstração a partir do XML de exemplo do Promob.

Uso:  python seed_demo.py   (usa DATABASE_URL, padrão sqlite:///./marcenaria_erp.db)
"""
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

XML = Path(__file__).parent / "exemplos" / "promob_cozinha.xml"

with TestClient(app) as c:
    empresa = c.post("/api/empresas", json={"nome": "Marcenaria Demonstração"}).json()
    h = {"X-Empresa-Id": str(empresa["id"])}
    with open(XML, "rb") as f:
        r = c.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)}, headers=h).json()
    pid = r["projeto_id"]
    c.post(f"/api/projetos/{pid}/liberar", headers=h)
    op = c.post(f"/api/projetos/{pid}/ops", json={"prioridade": 1}, headers=h).json()
    for u in c.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"][:8]:
        c.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE",
                                          "operador": "João"}, headers=h)
    print(f"Empresa de demonstração criada (id {empresa['id']}): {r['pecas']} peças importadas do XML. "
          f"Abra http://localhost:8000/?empresa={empresa['id']}")
