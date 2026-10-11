"""De-para Promob → estoque: cada código da biblioteca do Promob aponta para um material do cadastro.

O Promob tem um código por acabamento, fornecedor de biblioteca ou embalagem; o estoque tem o
código de compra. O de-para traduz na importação (e na reaplicação dos projetos em engenharia),
com fator de conversão para itens comprados em outra unidade (ex.: parafuso por unidade no Promob,
caixa com 500 no estoque → fator 0,002).
"""
import re
from collections import defaultdict
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeParaMaterial, Material, Projeto, StatusProjeto

EDITAVEIS = (StatusProjeto.ORCAMENTO, StatusProjeto.APROVADO, StatusProjeto.ENGENHARIA)
ABERTOS = EDITAVEIS + (StatusProjeto.LIBERADO, StatusProjeto.PRODUCAO)


class ErroDePara(ValueError):
    status = 422


def mapa(db: Session, empresa_id: int) -> dict[str, DeParaMaterial]:
    return {d.codigo_promob: d for d in db.scalars(select(DeParaMaterial).where(DeParaMaterial.empresa_id == empresa_id))}


def depara_out(d: DeParaMaterial) -> dict:
    m = d.material
    return {"id": d.id, "codigo_promob": d.codigo_promob, "material_id": m.id, "material_codigo": m.codigo,
            "material_descricao": m.descricao, "unidade": m.unidade, "fator": d.fator, "observacao": d.observacao}


def salvar(db: Session, empresa_id: int, codigo_promob: str, material_id: int, fator: float = 1.0,
           observacao: str | None = None) -> DeParaMaterial:
    codigo = (codigo_promob or "").strip()
    if not codigo:
        raise ErroDePara("Informe o código do Promob")
    if not fator or fator <= 0:
        raise ErroDePara("O fator de conversão precisa ser maior que zero")
    material = db.get(Material, material_id)
    if material is None or material.empresa_id != empresa_id:
        raise ErroDePara("Material do estoque não encontrado")
    if material.codigo == codigo and fator != 1:
        raise ErroDePara("Mesmo código no Promob e no estoque não leva fator: ajuste a unidade do material")
    d = db.scalar(select(DeParaMaterial).where(DeParaMaterial.empresa_id == empresa_id,
                                               DeParaMaterial.codigo_promob == codigo))
    if d is None:
        d = DeParaMaterial(empresa_id=empresa_id, codigo_promob=codigo)
        db.add(d)
    d.material_id, d.fator, d.observacao = material.id, fator, (observacao or "").strip()[:200] or None
    db.flush()
    db.refresh(d)
    return d


def traduzir(m: dict[str, DeParaMaterial], codigo: str | None) -> tuple[str | None, float]:
    """Código do estoque e fator para um código do Promob (sem de-para: o próprio código, fator 1)."""
    if not codigo:
        return codigo, 1.0
    d = m.get(codigo)
    return (d.material.codigo, d.fator) if d else (codigo, 1.0)


def reaplicar(db: Session, empresa_id: int) -> dict:
    """Troca os códigos do Promob pelos do estoque nos projetos que ainda estão na engenharia."""
    m = mapa(db, empresa_id)
    if not m:
        return {"projetos": 0, "trocas": 0}
    materiais = {d.material.codigo: d.material for d in m.values()}
    projetos = db.scalars(select(Projeto).where(Projeto.empresa_id == empresa_id, Projeto.status.in_(EDITAVEIS)))
    n_proj = trocas = 0
    for p in projetos:
        antes = trocas
        for a in p.ambientes:
            for mod in a.modulos:
                for pc in mod.pecas:
                    novo, _ = traduzir(m, pc.material_codigo)
                    if novo != pc.material_codigo:
                        pc.material_codigo, pc.material = novo, materiais[novo]
                        trocas += 1
                    for campo in ("fita_codigo", "fita_c1", "fita_c2", "fita_l1", "fita_l2"):
                        atual = getattr(pc, campo)
                        novo, _ = traduzir(m, atual)
                        if novo != atual:
                            setattr(pc, campo, novo)
                            trocas += 1
                for it in mod.itens:
                    novo, fator = traduzir(m, it.material_codigo)
                    if novo != it.material_codigo:
                        it.material_codigo, it.material, it.unidade = novo, materiais[novo], materiais[novo].unidade
                        it.quantidade = round(it.quantidade * fator, 4)
                        trocas += 1
        n_proj += trocas > antes
    db.flush()
    return {"projetos": n_proj, "trocas": trocas}


def _tipo(v) -> str:
    return str(getattr(v, "value", v))


def _tokens(t: str) -> set[str]:
    return set(re.findall(r"[a-z]+|\d+", (t or "").lower()))


def _parecido(a: str, b: str) -> float:
    """Semelhança entre textos: sequência de caracteres ou cobertura das palavras/números de `a` em `b`."""
    ta = _tokens(a)
    cobertura = len(ta & _tokens(b)) / len(ta) if ta else 0.0
    return max(SequenceMatcher(None, a.lower(), b.lower()).ratio(), cobertura)


def codigos_em_uso(db: Session, empresa_id: int) -> list[dict]:
    """Códigos usados nos projetos abertos, com situação e sugestão de material para vincular."""
    m = mapa(db, empresa_id)
    materiais = list(db.scalars(select(Material).where(Material.empresa_id == empresa_id)))
    por_codigo = {x.codigo: x for x in materiais}
    uso: dict[str, dict] = {}
    projetos_por: dict[str, set] = defaultdict(set)

    def registrar(codigo, descricao, tipo, projeto):
        if not codigo:
            return
        u = uso.setdefault(codigo, {"codigo": codigo, "descricao": descricao, "tipo": tipo, "ocorrencias": 0})
        u["ocorrencias"] += 1
        projetos_por[codigo].add(projeto.codigo)

    for p in db.scalars(select(Projeto).where(Projeto.empresa_id == empresa_id, Projeto.status.in_(ABERTOS))):
        for a in p.ambientes:
            for mod in a.modulos:
                for pc in mod.pecas:
                    mat = por_codigo.get(pc.material_codigo)
                    registrar(pc.material_codigo, mat.descricao if mat else "Chapa sem cadastro", "CHAPA", p)
                    for f in pc.fitas:
                        fm = por_codigo.get(f)
                        registrar(f, fm.descricao if fm else "Fita de borda", "FITA", p)
                for it in mod.itens:
                    registrar(it.material_codigo, it.descricao, "FERRAGEM", p)
    # Códigos já traduzidos não aparecem mais nos projetos: mostra o de-para cadastrado também
    for d in m.values():
        uso.setdefault(d.codigo_promob, {"codigo": d.codigo_promob, "descricao": d.material.descricao,
                                         "tipo": d.material.tipo, "ocorrencias": 0})
    destinos = {d.material.codigo for d in m.values()}
    lista = []
    for codigo, u in uso.items():
        d = m.get(codigo)
        if d:
            situacao = "VINCULADO"
        elif codigo in destinos:
            continue  # é código do estoque, resultado de um de-para
        elif codigo in por_codigo:
            situacao = "MESMO_CODIGO"
        else:
            situacao = "SEM_CADASTRO"
        sugestoes = []
        if situacao != "VINCULADO":
            mesmo_tipo = [x for x in materiais if x.codigo != codigo and _tipo(x.tipo) == _tipo(u["tipo"])] or \
                         [x for x in materiais if x.codigo != codigo]
            notas = sorted(((max(_parecido(u["descricao"], x.descricao), _parecido(codigo, x.codigo),
                                 _parecido(codigo, x.descricao)), x) for x in mesmo_tipo),
                           key=lambda t: -t[0])[:3]
            sugestoes = [{"material_id": x.id, "codigo": x.codigo, "descricao": x.descricao, "semelhanca": round(n * 100)}
                         for n, x in notas if n >= 0.45]
        lista.append({**u, "tipo": _tipo(u["tipo"]), "situacao": situacao,
                      "projetos": sorted(projetos_por[codigo]),
                      "depara": depara_out(d) if d else None, "sugestoes": sugestoes})
    ordem = {"SEM_CADASTRO": 0, "MESMO_CODIGO": 1, "VINCULADO": 2}
    return sorted(lista, key=lambda x: (ordem[x["situacao"]], x["tipo"], x["codigo"]))
