from datetime import date

from conftest import criar_usuario
from extrato_template import extrato
from test_pos_obra import projeto_liberado

HOJE = date.today()


def enviar(client, h, conteudo):
    return client.post("/api/conciliacao/importar", files={"arquivo": ("extrato.ofx", conteudo)}, headers=h)


def test_importa_extrato_sem_duplicar(client, empresa):
    r = enviar(client, empresa, extrato())
    assert r.status_code == 200 and r.json() == {"lidos": 4, "novos": 4, "repetidos": 0}
    assert enviar(client, empresa, extrato()).json() == {"lidos": 4, "novos": 0, "repetidos": 4}
    assert enviar(client, empresa, b"isto nao e um ofx").status_code == 422


def test_sugere_e_concilia_pelo_valor_e_data(client, empresa):
    pid = projeto_liberado(client, empresa)
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 2093.46, "parcelas": 2,
                                                        "primeiro_vencimento": str(HOJE)}, headers=empresa)
    boleto = client.post("/api/lancamentos", json={"tipo": "PAGAR", "categoria": "MATERIAL", "descricao": "Boleto Leo",
                                                   "valor": 135, "vencimento": str(HOJE)}, headers=empresa).json()
    enviar(client, empresa, extrato())
    movs = {m["descricao"]: m for m in client.get("/api/conciliacao?pendentes=true", headers=empresa).json()}
    pix, pagto = movs["PIX RECEBIDO CLIENTE EXEMPLO"], movs["PAGTO BOLETO LEO MADEIRAS"]
    assert [s["descricao"] for s in pix["sugestoes"]] == ["P-0001 · parcela 1/2"]  # a 2ª vence daqui a 1 mês
    assert [s["lancamento_id"] for s in pagto["sugestoes"]] == [boleto["id"]]
    assert movs["TARIFA PACOTE SERVICOS"]["sugestoes"] == []

    # Entrada não concilia com conta a pagar
    assert client.post(f"/api/conciliacao/{pix['id']}/conciliar", json={"lancamento_id": boleto["id"]},
                       headers=empresa).status_code == 409
    r = client.post(f"/api/conciliacao/{pix['id']}/conciliar", json={"lancamento_id": pix["sugestoes"][0]["lancamento_id"]},
                    headers=empresa).json()
    assert r["situacao"] == "CONCILIADO"
    parcela = client.get(f"/api/lancamentos?projeto_id={pid}", headers=empresa).json()[0]
    assert parcela["situacao"] == "PAGO" and parcela["valor_pago"] == 1046.73 and parcela["pago_em"] == pix["data"]

    # Tarifa sem conta: vira despesa já baixada; transferência é ignorada
    tarifa = client.post(f"/api/conciliacao/{movs['TARIFA PACOTE SERVICOS']['id']}/lancar",
                         json={"categoria": "DESPESA_FIXA"}, headers=empresa).json()
    assert tarifa["situacao"] == "CONCILIADO"
    desp = next(l for l in client.get("/api/lancamentos?tipo=PAGAR", headers=empresa).json() if l["descricao"] == "TARIFA PACOTE SERVICOS")
    assert desp["situacao"] == "PAGO" and desp["valor"] == 29.9
    assert client.post(f"/api/conciliacao/{movs['TRANSFERENCIA ENTRE CONTAS']['id']}/ignorar", headers=empresa).json()["situacao"] == "IGNORADO"
    pendentes = client.get("/api/conciliacao?pendentes=true", headers=empresa).json()
    assert [m["descricao"] for m in pendentes] == ["PAGTO BOLETO LEO MADEIRAS"]


def test_conciliacao_restrita_ao_financeiro(client, empresa):
    for perfil in ("OPERADOR", "COMPRAS", "MONTAGEM"):
        h = criar_usuario(client, empresa, perfil)
        assert enviar(client, h, extrato()).status_code == 403
        assert client.get("/api/conciliacao", headers=h).status_code == 403
