"""Popula uma empresa de demonstração: materiais, projeto da cozinha de exemplo e OP.

Uso:  python seed_demo.py   (usa DATABASE_URL, padrão sqlite:///./marcenaria_erp.db)
"""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

EXEMPLOS = Path(__file__).parent / "exemplos"
EXEMPLO = EXEMPLOS / "cozinha_silva.csv"
MATERIAIS = json.loads((EXEMPLOS / "materiais.json").read_text(encoding="utf-8"))

with TestClient(app) as c:
    empresa = c.post("/api/empresas", json={"nome": "Marcenaria Demonstração"}).json()
    h = {"X-Empresa-Id": str(empresa["id"])}
    for m in MATERIAIS:
        c.post("/api/materiais", json=m, headers=h)
    projeto = c.post("/api/projetos", json={"codigo": "P-001", "nome": "Cozinha Família Silva",
                                            "data_entrega": "2026-11-20"}, headers=h).json()
    with open(EXEMPLO, "rb") as f:
        c.post(f"/api/projetos/{projeto['id']}/importar", files={"arquivo": ("cozinha.csv", f)}, headers=h)
    c.post(f"/api/projetos/{projeto['id']}/liberar", headers=h)
    op = c.post(f"/api/projetos/{projeto['id']}/ops", json={"prioridade": 1}, headers=h).json()
    for u in c.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"][:6]:
        c.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE",
                                          "operador": "João"}, headers=h)
    print(f"Empresa de demonstração criada (id {empresa['id']}). "
          f"Abra http://localhost:8000/?empresa={empresa['id']}")
