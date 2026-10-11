"""Separação de peças: tupia, tamburato, peças que viram outra peça.

A classe vem de palavras-chave procuradas na peça (descrição, código, módulo e
operações do Promob) ou é marcada à mão pelo PCP. Ela aparece na etiqueta, no
apontamento ("SEPARAR"), agrupa o carrinho e pode colocar um setor extra no
roteiro (centro com regra SOB_DEMANDA).
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ClasseSeparacao, Peca, Projeto, StatusProjeto

PADROES = [
    ("TUPIA", "Tupia", "tupia, tupiar, curvo, curva, boleado, arredondado, recorte", True),
    ("TAMBURATO", "Tamburato", "tamburato, colmeia, colméia, colmeia de papel", False),
    ("TRANSFORMACAO", "Vira outra peça", "engrosso, engrossado, engrossamento, duplado, duplagem, colagem", False),
]


def garantir_padroes(db: Session, empresa_id: int) -> list[ClasseSeparacao]:
    classes = list(db.scalars(select(ClasseSeparacao).where(ClasseSeparacao.empresa_id == empresa_id)
                              .order_by(ClasseSeparacao.id)))
    if not classes:
        for codigo, nome, palavras, caixa in PADROES:
            db.add(ClasseSeparacao(empresa_id=empresa_id, codigo=codigo, nome=nome, palavras_chave=palavras,
                                   vai_para_caixa=caixa))
        db.flush()
        classes = list(db.scalars(select(ClasseSeparacao).where(ClasseSeparacao.empresa_id == empresa_id)
                                  .order_by(ClasseSeparacao.id)))
    return classes


def palavras(classe: ClasseSeparacao) -> list[str]:
    return [p.strip().lower() for p in (classe.palavras_chave or "").split(",") if p.strip()]


def classificar(peca: Peca, classes: list[ClasseSeparacao]) -> str | None:
    texto = " ".join(filter(None, [peca.descricao, peca.codigo, peca.modulo.descricao, peca.modulo.codigo,
                                   (peca.operacoes or "").replace(",", " ")])).lower()
    for c in classes:
        if c.ativo and any(p in texto for p in palavras(c)):
            return c.codigo
    return None


def aplicar_projeto(db: Session, projeto: Projeto) -> int:
    """Classifica as peças do projeto pelas regras; as marcadas à mão ficam como estão."""
    classes = garantir_padroes(db, projeto.empresa_id)
    mudou = 0
    for amb in projeto.ambientes:
        for mod in amb.modulos:
            for peca in mod.pecas:
                if peca.separacao_manual:
                    continue
                nova = classificar(peca, classes)
                if nova != peca.separacao:
                    peca.separacao, mudou = nova, mudou + 1
    db.flush()
    return mudou


def reaplicar(db: Session, empresa_id: int) -> dict:
    """Reaplica as regras aos projetos que ainda não foram para a fábrica (engenharia e liberados)."""
    projetos = list(db.scalars(select(Projeto).where(
        Projeto.empresa_id == empresa_id,
        Projeto.status.in_([StatusProjeto.ENGENHARIA, StatusProjeto.LIBERADO]))))
    return {"projetos": len(projetos), "pecas_alteradas": sum(aplicar_projeto(db, p) for p in projetos)}


def mapa(db: Session, empresa_id: int) -> dict[str, ClasseSeparacao]:
    return {c.codigo: c for c in garantir_padroes(db, empresa_id)}
