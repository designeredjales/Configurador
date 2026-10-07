"""Importação da lista de peças/itens de um projeto (CSV canônico).

Layout (separador `;` ou `,`, cabeçalho obrigatório, decimal com vírgula ou ponto):

    AMBIENTE;MODULO_CODIGO;MODULO_DESCRICAO;MODULO_QTD;TIPO;CODIGO;DESCRICAO;MATERIAL;
    COMPRIMENTO;LARGURA;ESPESSURA;QUANTIDADE;VEIO;FITA_C1;FITA_C2;FITA_L1;FITA_L2;USINAGEM;UNIDADE

TIPO = PECA (chapa cortada) ou ITEM (ferragem/acessório). Colunas ausentes ficam vazias.
É o formato-ponte até termos o adaptador do XML nativo do Promob validado com
arquivos reais.
"""
import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Ambiente, ItemModulo, Material, Modulo, Peca, Projeto

OBRIGATORIAS = {"AMBIENTE", "MODULO_CODIGO", "TIPO", "CODIGO", "MATERIAL", "QUANTIDADE"}


class ErroImportacao(ValueError):
    pass


def _num(valor: str | None, padrao: float | None = None) -> float | None:
    if valor is None or not valor.strip():
        return padrao
    texto = valor.strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def _txt(valor: str | None) -> str | None:
    valor = (valor or "").strip()
    return valor or None


def _sim(valor: str | None) -> bool:
    return (valor or "").strip().upper() in {"S", "SIM", "Y", "1", "TRUE", "X"}


def ler_csv(conteudo: str) -> list[dict[str, str]]:
    conteudo = conteudo.lstrip("﻿")
    primeira = conteudo.splitlines()[0] if conteudo.strip() else ""
    separador = ";" if primeira.count(";") >= primeira.count(",") else ","
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=separador)
    if not leitor.fieldnames:
        raise ErroImportacao("Arquivo vazio.")
    leitor.fieldnames = [c.strip().upper() for c in leitor.fieldnames]
    faltando = OBRIGATORIAS - set(leitor.fieldnames)
    if faltando:
        raise ErroImportacao(f"Colunas obrigatórias ausentes: {', '.join(sorted(faltando))}")
    return list(leitor)


def importar_csv(db: Session, projeto: Projeto, conteudo: str, origem: str = "CSV") -> dict:
    linhas = ler_csv(conteudo)
    materiais = {
        m.codigo: m
        for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))
    }

    # Reimportar substitui a engenharia anterior do projeto
    projeto.ambientes.clear()
    db.flush()

    ambientes: dict[str, Ambiente] = {}
    modulos: dict[tuple[str, str], Modulo] = {}
    avisos: list[str] = []
    n_pecas = n_itens = 0

    for n, linha in enumerate(linhas, start=2):
        g = lambda chave: linha.get(chave)  # noqa: E731
        try:
            nome_amb = _txt(g("AMBIENTE")) or "GERAL"
            cod_mod = _txt(g("MODULO_CODIGO"))
            tipo = (_txt(g("TIPO")) or "").upper()
            codigo = _txt(g("CODIGO"))
            mat_cod = _txt(g("MATERIAL"))
            qtd = _num(g("QUANTIDADE"), 1)
            if not cod_mod or not codigo or not mat_cod:
                raise ErroImportacao("MODULO_CODIGO, CODIGO e MATERIAL são obrigatórios")
            if tipo not in {"PECA", "ITEM"}:
                raise ErroImportacao(f"TIPO inválido '{tipo}' (use PECA ou ITEM)")

            amb = ambientes.get(nome_amb)
            if amb is None:
                amb = Ambiente(nome=nome_amb)
                projeto.ambientes.append(amb)
                ambientes[nome_amb] = amb

            mod = modulos.get((nome_amb, cod_mod))
            if mod is None:
                mod = Modulo(
                    codigo=cod_mod,
                    descricao=_txt(g("MODULO_DESCRICAO")) or cod_mod,
                    quantidade=int(_num(g("MODULO_QTD"), 1)),
                )
                amb.modulos.append(mod)
                modulos[(nome_amb, cod_mod)] = mod

            material = materiais.get(mat_cod)
            if material is None:
                avisos.append(f"Linha {n}: material '{mat_cod}' não cadastrado")

            if tipo == "PECA":
                comp, larg = _num(g("COMPRIMENTO")), _num(g("LARGURA"))
                if not comp or not larg:
                    raise ErroImportacao("PECA exige COMPRIMENTO e LARGURA")
                mod.pecas.append(Peca(
                    codigo=codigo,
                    descricao=_txt(g("DESCRICAO")) or codigo,
                    material=material,
                    material_codigo=mat_cod,
                    comprimento_mm=comp,
                    largura_mm=larg,
                    espessura_mm=_num(g("ESPESSURA"), material.espessura_mm if material else None),
                    quantidade=int(qtd),
                    veio=_sim(g("VEIO")),
                    fita_c1=_txt(g("FITA_C1")),
                    fita_c2=_txt(g("FITA_C2")),
                    fita_l1=_txt(g("FITA_L1")),
                    fita_l2=_txt(g("FITA_L2")),
                    programa_usinagem=_txt(g("USINAGEM")),
                ))
                n_pecas += 1
            else:
                mod.itens.append(ItemModulo(
                    material=material,
                    material_codigo=mat_cod,
                    descricao=_txt(g("DESCRICAO")) or (material.descricao if material else mat_cod),
                    quantidade=qtd,
                    unidade=_txt(g("UNIDADE")) or (material.unidade if material else "UN"),
                ))
                n_itens += 1
        except (ErroImportacao, ValueError) as e:
            raise ErroImportacao(f"Linha {n}: {e}") from e

    projeto.origem = origem
    db.flush()
    return {
        "projeto_id": projeto.id,
        "ambientes": len(ambientes),
        "modulos": len(modulos),
        "pecas": n_pecas,
        "itens": n_itens,
        "avisos": avisos,
    }
