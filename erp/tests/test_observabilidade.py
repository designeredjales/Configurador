import os
import time

from conftest import SENHA, criar_usuario, registrar

from app import observabilidade
from app.main import app


def _quebra():
    raise RuntimeError("falha simulada no servidor")


if not any(getattr(r, "path", "") == "/api/teste/erro" for r in app.router.routes):
    app.add_api_route("/api/teste/erro", _quebra, methods=["POST"])


def registros(client, h, **filtros):
    q = "&".join(f"{k}={v}" for k, v in filtros.items())
    return client.get(f"/api/auditoria?{q}", headers=h).json()["registros"]


def test_auditoria_registra_quem_alterou_o_que(client, empresa):
    client.get("/api/projetos", headers=empresa)  # consulta não entra
    client.post("/api/usuarios", json={"nome": "Ana", "email": "ana@m.com", "senha": SENHA, "perfil": "PCP"}, headers=empresa)
    client.put("/api/empresas/atual", json={"imposto_venda_pct": 7.5, "fiscal_token": "segredo-do-emissor"}, headers=empresa)
    client.post("/api/auth/login", json={"email": "ana@m.com", "senha": "senha-errada-1"})
    ana = client.post("/api/auth/login", json={"email": "ana@m.com", "senha": SENHA}).json()["token"]
    r = client.post("/api/carrinhos", json={"quantidade": 2}, headers={"Authorization": f"Bearer {ana}"})
    assert r.status_code == 201
    regs = registros(client, empresa)
    acoes = [(x["usuario"], x["acao"], x["resultado"]) for x in regs]
    assert acoes == [("Ana", "Cadastrou carrinhos", "ok"), ("Ana", "Entrou no sistema", "ok"),
                     ("Ana", "Entrou no sistema", "recusado"), ("Admin", "Alterou configurações da empresa", "ok"),
                     ("Admin", "Criou usuário", "ok"), ("Admin", "Cadastrou a empresa", "ok")]
    # Senhas e tokens nunca são gravados; o resto do que foi enviado fica
    criou = next(x for x in regs if x["acao"] == "Criou usuário")["detalhes"]
    assert criou["senha"] == "***" and criou["email"] == "ana@m.com"
    cfg = next(x for x in regs if x["acao"].startswith("Alterou config"))["detalhes"]
    assert cfg == {"imposto_venda_pct": 7.5, "fiscal_token": "***"}
    assert all("senha-errada" not in str(x["detalhes"]) for x in regs)

    # Registro afetado, recusa por permissão e filtros
    operador = criar_usuario(client, empresa, "OPERADOR")
    pid = client.post("/api/projetos", json={"codigo": "P-9", "nome": "Teste"}, headers=empresa).json()["id"]
    assert client.post(f"/api/projetos/{pid}/liberar", headers=operador).status_code == 403
    rec = registros(client, empresa, busca="Liberou")[0]
    assert rec["usuario"] == "Operador" and rec["resultado"] == "recusado" and rec["entidade_id"] == str(pid)
    assert {x["usuario"] for x in registros(client, empresa, usuario="Ana")} == {"Ana"}
    assert client.get("/api/auditoria", headers=operador).status_code == 403

    # Outra empresa não enxerga nada disto
    outra = registrar(client, empresa="Outra Fábrica", email="dono@outra.com")
    assert [x["acao"] for x in registros(client, outra)] == ["Cadastrou a empresa"]


def test_erro_inesperado_ganha_codigo_e_vai_para_o_painel(client, empresa, monkeypatch):
    capturados = []
    monkeypatch.setattr(observabilidade, "SENTRY_ATIVO", True)
    import sentry_sdk
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: capturados.append(exc))
    r = client.post("/api/teste/erro", headers=empresa)
    assert r.status_code == 500 and r.headers["x-content-type-options"] == "nosniff"
    codigo = r.json()["erro_id"]
    assert codigo in r.json()["detail"] and "falha simulada" not in r.json()["detail"]  # não expõe detalhe técnico
    assert len(capturados) == 1 and isinstance(capturados[0], RuntimeError)
    s = client.get("/api/sistema", headers=empresa).json()
    assert s["erros_24h"] == 1 and s["erros"][0]["codigo"] == codigo and s["erros"][0]["tipo"] == "RuntimeError"
    assert s["banco"] in ("sqlite", "postgresql") and s["sentry"] is True and s["alteracoes_24h"] >= 1
    outra = registrar(client, empresa="Outra", email="x@outra.com")
    assert client.get("/api/sistema", headers=outra).json()["erros_24h"] == 0


def test_status_do_backup(client, empresa, tmp_path, monkeypatch):
    monkeypatch.setenv("ERP_PASTA_BACKUP", str(tmp_path / "nao-existe"))
    assert client.get("/api/sistema", headers=empresa).json()["backup"]["configurado"] is False
    monkeypatch.setenv("ERP_PASTA_BACKUP", str(tmp_path))
    assert client.get("/api/sistema", headers=empresa).json()["backup"]["mensagem"] == "Nenhum backup gerado ainda"
    velho = tmp_path / "erp_20261001_0300.dump"; velho.write_bytes(b"x" * 10)
    os.utime(velho, (time.time() - 3 * 86400,) * 2)
    b = client.get("/api/sistema", headers=empresa).json()["backup"]
    assert b["arquivo"] == velho.name and b["alerta"] is True
    novo = tmp_path / "erp_20261007_0300.dump"; novo.write_bytes(b"y" * 2_000_000)
    b = client.get("/api/sistema", headers=empresa).json()["backup"]
    assert b["arquivo"] == novo.name and b["alerta"] is False and b["quantidade"] == 2 and b["tamanho_mb"] == 2.0


def test_sentry_so_liga_com_dsn(monkeypatch):
    import sentry_sdk
    chamadas = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: chamadas.append(kw))
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observabilidade.configurar_sentry() is False and not chamadas
    monkeypatch.setenv("SENTRY_DSN", "https://chave@exemplo.ingest.sentry.io/1")
    assert observabilidade.configurar_sentry() is True and chamadas[0]["send_default_pii"] is False
    monkeypatch.setattr(observabilidade, "SENTRY_ATIVO", False)
