"""Engenharia: explosão de consumo (chapa, fita, ferragem) e gate de liberação."""
import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Empresa, Material, Projeto, StatusProjeto


def _iter_pecas(projeto: Projeto):
    for amb in projeto.ambientes:
        for mod in amb.modulos:
            for peca in mod.pecas:
                yield mod, peca


def _iter_itens(projeto: Projeto):
    for amb in projeto.ambientes:
        for mod in amb.modulos:
            for item in mod.itens:
                yield mod, item


def pendencias(db: Session, projeto: Projeto) -> list[str]:
    """O que impede liberar o projeto para a fábrica."""
    materiais = set(db.scalars(
        select(Material.codigo).where(Material.empresa_id == projeto.empresa_id)
    ))
    erros: list[str] = []
    total_pecas = 0
    for mod, peca in _iter_pecas(projeto):
        total_pecas += 1
        ref = f"{mod.codigo}/{peca.codigo}"
        if peca.material_codigo not in materiais:
            erros.append(f"{ref}: chapa '{peca.material_codigo}' sem cadastro")
        for fita in peca.fitas:
            if fita not in materiais:
                erros.append(f"{ref}: fita '{fita}' sem cadastro")
        if peca.comprimento_mm <= 0 or peca.largura_mm <= 0:
            erros.append(f"{ref}: medidas inválidas")
    for mod, item in _iter_itens(projeto):
        if item.material_codigo not in materiais:
            erros.append(f"{mod.codigo}: item '{item.material_codigo}' sem cadastro")
    if total_pecas == 0:
        erros.append("Projeto sem peças: importe a lista do Promob antes de liberar")
    return sorted(set(erros))


def consumo(db: Session, projeto: Projeto) -> dict:
    empresa = db.get(Empresa, projeto.empresa_id)
    materiais = {
        m.codigo: m
        for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))
    }
    perda_chapa = 1 + empresa.perda_chapa_pct / 100
    perda_fita = 1 + empresa.perda_fita_pct / 100

    area_m2: dict[str, float] = defaultdict(float)
    fita_m: dict[str, float] = defaultdict(float)
    itens_qtd: dict[str, float] = defaultdict(float)
    total_pecas = 0

    for mod, peca in _iter_pecas(projeto):
        qtd = peca.quantidade * mod.quantidade
        total_pecas += qtd
        area_m2[peca.material_codigo] += peca.comprimento_mm * peca.largura_mm / 1e6 * qtd
        if peca.fita_codigo and peca.fita_metros:
            fita_m[peca.fita_codigo] += peca.fita_metros * qtd  # metragem do Promob
        for lado, medida in (("fita_c1", peca.comprimento_mm), ("fita_c2", peca.comprimento_mm),
                             ("fita_l1", peca.largura_mm), ("fita_l2", peca.largura_mm)):
            fita = getattr(peca, lado)
            if fita:
                fita_m[fita] += medida / 1000 * qtd

    for mod, item in _iter_itens(projeto):
        itens_qtd[item.material_codigo] += item.quantidade * mod.quantidade

    def linha(codigo, liquida, com_perda, compra, unidade_calc, custo_qtd):
        mat = materiais.get(codigo)
        custo = mat.custo_unitario if mat else 0.0
        return {
            "material_codigo": codigo,
            "descricao": mat.descricao if mat else "(sem cadastro)",
            "tipo": mat.tipo if mat else "?",
            "unidade": unidade_calc,
            "quantidade_liquida": round(liquida, 3),
            "quantidade_com_perda": round(com_perda, 3),
            "quantidade_compra": round(compra, 3),
            "custo_unitario": custo,
            "custo_total": round(custo * custo_qtd, 2),
        }

    chapas = []
    for codigo, area in sorted(area_m2.items()):
        mat = materiais.get(codigo)
        com_perda = area * perda_chapa
        if mat and mat.unidade.upper() != "M2" and mat.comprimento_mm and mat.largura_mm:
            area_chapa = mat.comprimento_mm * mat.largura_mm / 1e6
            n_chapas = math.ceil(com_perda / area_chapa)
            chapas.append(linha(codigo, area, com_perda, n_chapas, "CH", n_chapas))
        else:
            chapas.append(linha(codigo, area, com_perda, com_perda, "M2", com_perda))

    fitas = [
        linha(c, m, m * perda_fita, math.ceil(m * perda_fita), "M", math.ceil(m * perda_fita))
        for c, m in sorted(fita_m.items())
    ]
    itens = [
        linha(c, q, q, q, materiais[c].unidade if c in materiais else "UN", q)
        for c, q in sorted(itens_qtd.items())
    ]

    total = sum(l["custo_total"] for l in chapas + fitas + itens)
    return {
        "projeto_id": projeto.id,
        "chapas": chapas,
        "fitas": fitas,
        "itens": itens,
        "custo_material_total": round(total, 2),
        "total_pecas": total_pecas,
        "pendencias": pendencias(db, projeto),
    }


def liberar(db: Session, projeto: Projeto) -> list[str]:
    """Libera para a fábrica. Retorna pendências; se houver, não libera."""
    if projeto.status not in (StatusProjeto.ENGENHARIA, StatusProjeto.APROVADO):
        return [f"Projeto em status {projeto.status}: só libera a partir de ENGENHARIA/APROVADO"]
    erros = pendencias(db, projeto)
    if erros:
        return erros
    # Amarra o cadastro definitivo às peças/itens antes de produzir
    materiais = {
        m.codigo: m
        for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))
    }
    for _, peca in _iter_pecas(projeto):
        peca.material = materiais[peca.material_codigo]
    for _, item in _iter_itens(projeto):
        item.material = materiais[item.material_codigo]
    projeto.status = StatusProjeto.LIBERADO
    db.flush()
    return []
