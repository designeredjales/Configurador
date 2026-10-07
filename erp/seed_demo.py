"""Popula uma empresa de demonstração a partir do XML de exemplo do Promob.

Uso:  python seed_demo.py   (usa DATABASE_URL, padrão sqlite:///./marcenaria_erp.db)
"""
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
    c.post(f"/api/projetos/{pid}/liberar", headers=h)
    op = c.post(f"/api/projetos/{pid}/ops", json={"prioridade": 1}, headers=h).json()
    for u in c.get(f"/api/ops/{op['id']}", headers=h).json()["unidades"][:8]:
        c.post("/api/apontamentos", json={"codigo_barras": u["codigo_barras"], "centro_codigo": "CORTE"},
               headers=h)
    print(f"Demonstração criada: {r['pecas']} peças importadas do XML.\n"
          "Abra http://localhost:8000 e entre com admin@demo.com / demo12345 "
          "(operador: operador@demo.com / demo12345)")
