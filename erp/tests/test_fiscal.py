import json

import httpx
import pytest

from app.services import fiscal
from conftest import criar_usuario
from test_pos_obra import projeto_liberado

EMPRESA_FISCAL = {"cnpj": "12.345.678/0001-90", "uf": "sp", "fiscal_token": "token-secreto-123", "ncm_padrao": "9403.40.00"}
CLIENTE = {"nome": "Cliente Exemplo", "documento": "123.456.789-09", "email": "cliente@exemplo.com", "logradouro": "Rua das Flores",
           "numero": "10", "bairro": "Centro", "cidade": "Campinas", "uf": "sp", "cep": "13010-000"}


@pytest.fixture
def emissor():
    """Emissor Focus NFe simulado: registra o que recebe e responde como a API v2."""
    estado = {"pedidos": [], "status": "processando_autorizacao"}

    def responder(req: httpx.Request):
        estado["pedidos"].append(req)
        assert req.headers["authorization"].startswith("Basic ")  # token como usuário do Basic Auth
        if req.method == "POST":
            corpo = json.loads(req.content)
            if corpo["valor_total"] == 13.13:
                return httpx.Response(422, json={"codigo": "requisicao_invalida", "mensagem": "Requisição inválida",
                                                 "erros": [{"campo": "cep_destinatario", "mensagem": "CEP inexistente"}]})
            return httpx.Response(202, json={"status": "processando_autorizacao", "ref": req.url.params["ref"]})
        if estado["status"] == "autorizado":
            return httpx.Response(200, json={"status": "autorizado", "numero": "123", "serie": "1",
                                             "chave_nfe": "NFe35261012345678000190550010000001231000001234",
                                             "caminho_danfe": "/arquivos/danfe.pdf", "caminho_xml_nota_fiscal": "/arquivos/nota.xml",
                                             "mensagem_sefaz": "Autorizado o uso da NF-e"})
        return httpx.Response(200, json={"status": "processando_autorizacao"})

    fiscal.TRANSPORTE = httpx.MockTransport(responder)
    yield estado
    fiscal.TRANSPORTE = None


def preparar(client, h):
    pid = projeto_liberado(client, h)
    client.post(f"/api/projetos/{pid}/contrato", json={"valor_venda": 2093.46, "parcelas": 1, "primeiro_vencimento": "2026-10-01"}, headers=h)
    return pid


def test_token_nunca_sai_pela_api(client, empresa):
    r = client.put("/api/empresas/atual", json=EMPRESA_FISCAL, headers=empresa).json()
    assert r["fiscal_token_configurado"] is True and "token-secreto" not in json.dumps(r)
    assert client.put("/api/empresas/atual", json={"fiscal_token": ""}, headers=empresa).json()["fiscal_token_configurado"]
    assert client.put("/api/empresas/atual", json={"cfop_interno": "51O1"}, headers=empresa).status_code == 422


def test_pendencias_antes_de_emitir(client, empresa, emissor):
    pid = preparar(client, empresa)
    r = client.post(f"/api/projetos/{pid}/nfe", json={}, headers=empresa)
    assert r.status_code == 422
    pend = r.json()["detail"]["pendencias"]
    assert "Empresa: CNPJ com 14 dígitos" in pend and "Cliente: CEP com 8 dígitos" in pend
    assert emissor["pedidos"] == []  # nada é enviado ao emissor com dado faltando


def test_emite_consulta_e_autoriza(client, empresa, emissor):
    pid = preparar(client, empresa)
    client.put("/api/empresas/atual", json=EMPRESA_FISCAL, headers=empresa)
    cliente_id = client.get(f"/api/projetos/{pid}", headers=empresa).json()["cliente_id"]
    assert client.put(f"/api/clientes/{cliente_id}", json=CLIENTE, headers=empresa).status_code == 200

    nota = client.post(f"/api/projetos/{pid}/nfe", json={}, headers=empresa).json()
    assert nota["status"] == "PROCESSANDO" and nota["ref"] == "E1-P-0001-1" and nota["valor"] == 2093.46
    enviado = json.loads(emissor["pedidos"][0].content)
    assert emissor["pedidos"][0].url.host == "homologacao.focusnfe.com.br"
    assert enviado["cpf_destinatario"] == "12345678909" and enviado["cep_destinatario"] == "13010000"
    assert enviado["local_destino"] == 1 and enviado["items"][0]["cfop"] == "5101"
    assert enviado["items"][0]["codigo_ncm"] == "94034000" and enviado["items"][0]["icms_situacao_tributaria"] == "102"
    assert "Projeto - Ambiente 3D" in enviado["items"][0]["descricao"]

    assert client.post(f"/api/projetos/{pid}/nfe", json={}, headers=empresa).status_code == 409  # sem nota dupla
    emissor["status"] = "autorizado"
    nota = client.post(f"/api/notas/{nota['id']}/consultar", headers=empresa).json()
    assert nota["status"] == "AUTORIZADA" and nota["numero"] == "123" and nota["chave"].startswith("NFe35")
    assert nota["url_danfe"] == "https://homologacao.focusnfe.com.br/arquivos/danfe.pdf"


def test_cliente_de_outro_estado_usa_cfop_interestadual(client, empresa, emissor):
    pid = preparar(client, empresa)
    client.put("/api/empresas/atual", json=EMPRESA_FISCAL, headers=empresa)
    cid = client.get(f"/api/projetos/{pid}", headers=empresa).json()["cliente_id"]
    client.put(f"/api/clientes/{cid}", json={**CLIENTE, "uf": "MG", "documento": "12.345.678/0001-90"}, headers=empresa)
    client.post(f"/api/projetos/{pid}/nfe", json={}, headers=empresa)
    enviado = json.loads(emissor["pedidos"][0].content)
    assert enviado["local_destino"] == 2 and enviado["items"][0]["cfop"] == "6101" and enviado["cnpj_destinatario"] == "12345678000190"


def test_erro_do_emissor_fica_registrado_e_permite_nova_tentativa(client, empresa, emissor):
    pid = preparar(client, empresa)
    client.put("/api/empresas/atual", json=EMPRESA_FISCAL, headers=empresa)
    cid = client.get(f"/api/projetos/{pid}", headers=empresa).json()["cliente_id"]
    client.put(f"/api/clientes/{cid}", json=CLIENTE, headers=empresa)
    nota = client.post(f"/api/projetos/{pid}/nfe", json={"valor": 13.13}, headers=empresa).json()
    assert nota["status"] == "ERRO" and "CEP inexistente" in nota["mensagem"]
    nova = client.post(f"/api/projetos/{pid}/nfe", json={}, headers=empresa).json()
    assert nova["ref"] == "E1-P-0001-2" and nova["status"] == "PROCESSANDO"


def test_nfe_restrita(client, empresa):
    pid = preparar(client, empresa)
    for perfil in ("OPERADOR", "COMPRAS", "ENGENHARIA"):
        assert client.post(f"/api/projetos/{pid}/nfe", json={}, headers=criar_usuario(client, empresa, perfil)).status_code == 403
