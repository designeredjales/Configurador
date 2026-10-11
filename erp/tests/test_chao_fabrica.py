import os
import random

from app.services.corte import PecaCorte, otimizar
from conftest import EXEMPLOS

SERRA, REFILO = 4.0, 10.0


def validar(chapas, comp, larg):
    for chapa in chapas:
        for i, a in enumerate(chapa.pecas):
            # dentro da área útil (descontado o refilo)
            assert a.x >= REFILO - 1e-6 and a.y >= REFILO - 1e-6
            assert a.x + a.comprimento <= comp - REFILO + 1e-6 and a.y + a.largura <= larg - REFILO + 1e-6
            for b in chapa.pecas[i + 1:]:
                # nenhuma sobreposição, com a serra entre as peças
                separadas = (a.x + a.comprimento + SERRA <= b.x + 1e-6 or b.x + b.comprimento + SERRA <= a.x + 1e-6 or
                             a.y + a.largura + SERRA <= b.y + 1e-6 or b.y + b.largura + SERRA <= a.y + 1e-6)
                assert separadas, (a, b)


def test_otimizador_respeita_geometria_em_lote_aleatorio():
    rnd = random.Random(42)
    pecas = [PecaCorte(f"P{i}", rnd.randint(80, 2200), rnd.randint(60, 900), veio=rnd.random() < 0.3)
             for i in range(120)]
    chapas, nao_cabem = otimizar(pecas, 2750, 1850, SERRA, REFILO)
    assert nao_cabem == []
    assert sum(len(c.pecas) for c in chapas) == 120
    validar(chapas, 2750, 1850)
    # nunca pior que o limite físico de área
    area = sum(p.comprimento * p.largura for p in pecas)
    assert len(chapas) >= area / (2730 * 1830)
    for c in chapas:
        for pos in c.pecas:
            peca = next(p for p in pecas if p.ref == pos.ref)
            if peca.veio:
                assert not pos.girada and pos.comprimento == peca.comprimento


def test_peca_maior_que_a_chapa_e_reportada():
    chapas, nao_cabem = otimizar([PecaCorte("GRANDE", 2800, 600), PecaCorte("OK", 2700, 600),
                                  PecaCorte("VEIO", 1000, 2000, veio=True)], 2750, 1850, SERRA, REFILO)
    assert sorted(nao_cabem) == ["GRANDE", "VEIO"]
    assert [p.ref for c in chapas for p in c.pecas] == ["OK"]


def test_pecas_exatas_aproveitam_a_chapa_inteira():
    # 4 peças que somadas à serra ocupam exatamente a área útil
    c, l = (2730 - SERRA) / 2, (1830 - SERRA) / 2
    chapas, _ = otimizar([PecaCorte(str(i), c, l, veio=True) for i in range(4)], 2750, 1850, SERRA, REFILO)
    assert len(chapas) == 1
    validar(chapas, 2750, 1850)


def op_do_xml(client, h):
    with open(os.path.join(EXEMPLOS, "promob_cozinha.xml"), "rb") as f:
        pid = client.post("/api/projetos/importar-xml", files={"arquivo": ("Cozinha.xml", f)},
                          headers=h).json()["projeto_id"]
    client.post(f"/api/projetos/{pid}/liberar", headers=h)
    return client.post(f"/api/projetos/{pid}/ops", json={}, headers=h).json()


def test_plano_de_corte_da_op(client, empresa):
    op = op_do_xml(client, empresa)
    plano = client.get(f"/api/ops/{op['id']}/plano-corte", headers=empresa).json()
    por_mat = {m["material_codigo"]: m for m in plano["materiais"]}
    assert set(por_mat) == {"MDF.COR.18.100", "MDF.COR.15.100", "MDF.COR.6.100"}
    assert sum(m["total_pecas"] for m in plano["materiais"]) == 34
    assert all(m["nao_cabem"] == [] and m["medida_padrao"] for m in plano["materiais"])
    m18 = por_mat["MDF.COR.18.100"]
    assert m18["total_chapas"] == 1 and m18["chapa_comprimento_mm"] == 2750
    assert 60 < m18["aproveitamento_pct"] < 75  # 3,37 m² de peças numa chapa de 5,09 m²
    etiquetas = {p["ref"] for m in plano["materiais"] for c in m["chapas"] for p in c["pecas"]}
    unidades = client.get(f"/api/ops/{op['id']}", headers=empresa).json()["unidades"]
    assert etiquetas == {u["codigo_barras"] for u in unidades}


def test_etiquetas_zpl(client, empresa):
    op = op_do_xml(client, empresa)
    r = client.get(f"/api/ops/{op['id']}/etiquetas.zpl", headers=empresa)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    zpl = r.text
    assert zpl.count("^XA") == zpl.count("^XZ") == 34
    assert "^BCN,120,Y,N,N^FD00100000100001^FS" in zpl
    assert "Lateral Direita" in zpl and "CORTE > BORDA > USINAGEM > EMBALAGEM" in zpl
    assert client.get(f"/api/ops/{op['id']}/etiquetas.zpl").status_code == 401


def test_etiquetas_html_com_codigo_de_barras(client, empresa):
    op = op_do_xml(client, empresa)
    r = client.get(f"/api/ops/{op['id']}/etiquetas.html", headers=empresa)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.text.count('<section class="etq">') == 34 and r.text.count("<svg") == 34
    assert "size: 100mm 50mm" in r.text and "00100000100001" in r.text


def test_code128_segue_a_norma_inclusive_com_par_99():
    from app.services import code128
    # Verificador = (105 + Σ posição × valor) mod 103
    seq = code128.modulos("99999999999999")
    valores = [105] + [99] * 7
    esperado = (105 + sum(i * 99 for i in range(1, 8))) % 103
    assert esperado == 96
    assert seq == "".join(code128.PADROES[v] for v in valores + [esperado]) + code128.PARADA
    # Todo símbolo tem 11 módulos (6 elementos); a parada tem 13
    assert len(seq) == 11 * 9 + 13
    assert all(len(p) == 11 for p in code128.PADROES) and len(code128.PADROES) == 106
    # Exemplo de referência: "00100000100001" → 105 + 2×10 + 5×10 + 7×1 = 182; 182 mod 103 = 79
    vals = [105, 0, 10, 0, 0, 10, 0, 1]
    assert (vals[0] + sum(i * v for i, v in enumerate(vals[1:], 1))) % 103 == 79
    assert code128.modulos("00100000100001").endswith(code128.PADROES[79] + code128.PARADA)
