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


def importar_promob_xml(db: Session, projeto: Projeto, conteudo: bytes) -> dict:
    """Grava no projeto a engenharia lida do XML do Promob.

    Códigos com de-para viram o material do estoque (com o fator de conversão). Os demais,
    se ainda não existem no cadastro, entram automaticamente com o código, a descrição, a
    unidade e o preço de tabela do Promob, a menos que a base desligue a criação automática:
    aí ficam como pendência de engenharia até alguém vincular o de-para.
    """
    from ..models import Cliente, Empresa, TipoMaterial
    from .depara import mapa, traduzir
    from .promob_xml import ErroXMLPromob, ler_xml_promob

    try:
        lido = ler_xml_promob(conteudo)
    except ErroXMLPromob as e:
        raise ErroImportacao(str(e)) from e

    materiais = {
        m.codigo: m
        for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))
    }
    dp = mapa(db, projeto.empresa_id)
    for d in dp.values():
        materiais.setdefault(d.material.codigo, d.material)
    cria = db.get(Empresa, projeto.empresa_id).promob_cria_materiais
    criados: list[str] = []
    sem_vinculo: list[str] = []
    traduzidos = 0
    for mx in lido.materiais.values():
        if mx.codigo in dp:
            traduzidos += 1
            continue
        if mx.codigo in materiais:
            continue
        if not cria:
            sem_vinculo.append(mx.codigo)
            continue
        material = Material(
            empresa_id=projeto.empresa_id, codigo=mx.codigo, descricao=mx.descricao,
            tipo=TipoMaterial(mx.tipo), unidade=mx.unidade, espessura_mm=mx.espessura_mm,
            custo_unitario=mx.custo,
        )
        db.add(material)
        materiais[mx.codigo] = material
        criados.append(mx.codigo)

    avisos = list(lido.avisos)
    if traduzidos:
        avisos.append(f"{traduzidos} código(s) do Promob trocados pelo material do estoque (de-para)")
    if sem_vinculo:
        avisos.append(f"Código(s) do Promob sem de-para nem cadastro (vincule em Materiais → De-para): {', '.join(sorted(sem_vinculo)[:20])}")
    sem_custo = sorted(c for c in criados if not materiais[c].custo_unitario)
    if sem_custo:
        avisos.append(f"Material cadastrado sem custo (preencha no cadastro): {', '.join(sem_custo)}")

    cliente_nome = None
    if lido.cliente:
        cliente_nome = lido.cliente
        if projeto.cliente_id is None:
            cliente = db.scalar(select(Cliente).where(
                Cliente.empresa_id == projeto.empresa_id, Cliente.nome == lido.cliente))
            if cliente is None:
                cliente = Cliente(empresa_id=projeto.empresa_id, nome=lido.cliente, email=lido.email)
                db.add(cliente)
            projeto.cliente = cliente

    projeto.ambientes.clear()
    db.flush()

    n_mod = n_pecas = n_itens = 0
    for nome_amb, modulos in lido.ambientes.items():
        amb = Ambiente(nome=nome_amb)
        projeto.ambientes.append(amb)
        for mx in modulos:
            n_mod += 1
            mod = Modulo(
                codigo=mx.codigo, descricao=mx.descricao, largura_mm=mx.largura_mm,
                altura_mm=mx.altura_mm, profundidade_mm=mx.profundidade_mm,
                quantidade=max(1, round(mx.quantidade)),
            )
            amb.modulos.append(mod)
            for px in mx.pecas:
                chapa, _ = traduzir(dp, px.material_codigo)
                mod.pecas.append(Peca(
                    codigo=px.codigo, descricao=px.descricao,
                    material=materiais.get(chapa), material_codigo=chapa,
                    comprimento_mm=px.comprimento_mm, largura_mm=px.largura_mm,
                    espessura_mm=px.espessura_mm, quantidade=max(1, round(px.quantidade)),
                    fita_codigo=traduzir(dp, px.fita_codigo)[0], fita_metros=px.fita_metros or None,
                    operacoes=",".join(px.operacoes) or None,
                ))
                n_pecas += 1
            # Ferragens repetidas peça a peça viram uma linha por código no módulo
            somadas: dict[str, ItemModulo] = {}
            for ix in mx.itens:
                codigo, fator = traduzir(dp, ix.codigo)
                item = somadas.get(codigo)
                if item is None:
                    mat = materiais.get(codigo)
                    item = ItemModulo(material=mat, material_codigo=codigo, descricao=mat.descricao if codigo != ix.codigo else ix.descricao,
                                      quantidade=0, unidade=mat.unidade if codigo != ix.codigo else ix.unidade)
                    somadas[codigo] = item
                    mod.itens.append(item)
                    n_itens += 1
                item.quantidade = round(item.quantidade + ix.quantidade * fator, 4)

    c = lido.comercial
    projeto.valor_tabela, projeto.valor_pedido = c.valor_tabela, c.valor_pedido
    if not projeto.contrato_em:  # depois do contrato, o valor vendido não muda com o XML executivo
        projeto.valor_venda = c.valor_venda
    projeto.frete_orcado, projeto.montagem_orcada = c.frete, c.montagem
    projeto.condicao_pagamento, projeto.parcelas_sugeridas, projeto.entrada_sugerida = c.condicao, c.parcelas, c.entrada
    projeto.origem = "PROMOB_XML"
    db.flush()
    return {
        "projeto_id": projeto.id,
        "origem": "PROMOB_XML",
        "cliente": cliente_nome,
        "ambientes": len(lido.ambientes),
        "modulos": n_mod,
        "pecas": n_pecas,
        "itens": n_itens,
        "materiais_criados": criados,
        "avisos": avisos,
    }


def eh_xml(conteudo: bytes) -> bool:
    return conteudo.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<")
