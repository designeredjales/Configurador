"""Plano de corte guilhotinado (seccionadora), por material.

Heurística: peças em ordem decrescente de área, encaixadas no retângulo livre
de melhor ajuste (menor sobra de área), com corte guilhotina pelo eixo mais
curto da sobra. A espessura da serra soma em cada peça e o refilo sai da
borda da chapa. Peça com veio não gira.
"""
from dataclasses import dataclass, field


@dataclass
class PecaCorte:
    ref: str            # identificação (ex.: etiqueta ou módulo/peça)
    comprimento: float  # no sentido do comprimento da chapa (veio)
    largura: float
    veio: bool = False


@dataclass
class Posicao:
    ref: str
    x: float
    y: float
    comprimento: float  # dimensão ocupada no eixo x
    largura: float      # dimensão ocupada no eixo y
    girada: bool


@dataclass
class Chapa:
    comprimento: float
    largura: float
    pecas: list[Posicao] = field(default_factory=list)

    @property
    def area_usada(self) -> float:
        return sum(p.comprimento * p.largura for p in self.pecas)

    @property
    def aproveitamento(self) -> float:
        return self.area_usada / (self.comprimento * self.largura)


@dataclass
class _Livre:
    x: float
    y: float
    c: float
    l: float


def otimizar(pecas: list[PecaCorte], comprimento: float, largura: float,
             serra: float = 4.0, refilo: float = 10.0) -> tuple[list[Chapa], list[str]]:
    """Retorna as chapas com as peças posicionadas e as peças que não cabem."""
    util_c, util_l = comprimento - 2 * refilo, largura - 2 * refilo
    nao_cabem: list[str] = []
    chapas: list[tuple[Chapa, list[_Livre]]] = []

    def cabe(p: PecaCorte, livre: _Livre):
        opcoes = [(p.comprimento, p.largura, False)]
        if not p.veio:
            opcoes.append((p.largura, p.comprimento, True))
        melhor = None
        for c, l, girada in opcoes:
            # A serra só conta entre peças: a última peça pode encostar na borda útil
            if c <= livre.c + 1e-6 and l <= livre.l + 1e-6:
                sobra = livre.c * livre.l - (c + serra) * (l + serra)
                if melhor is None or sobra < melhor[0]:
                    melhor = (sobra, c, l, girada)
        return melhor

    for p in sorted(pecas, key=lambda p: (p.comprimento * p.largura, max(p.comprimento, p.largura)), reverse=True):
        if cabe(p, _Livre(0, 0, util_c, util_l)) is None:
            nao_cabem.append(p.ref)
            continue
        escolha = None
        for i, (chapa, livres) in enumerate(chapas):
            for j, livre in enumerate(livres):
                ajuste = cabe(p, livre)
                if ajuste and (escolha is None or ajuste[0] < escolha[0]):
                    escolha = (ajuste[0], i, j, ajuste)
        if escolha is None:
            chapas.append((Chapa(comprimento, largura), [_Livre(refilo, refilo, util_c, util_l)]))
            i, j = len(chapas) - 1, 0
            ajuste = cabe(p, chapas[i][1][0])
        else:
            _, i, j, ajuste = escolha
        chapa, livres = chapas[i]
        livre = livres.pop(j)
        _, c, l, girada = ajuste
        chapa.pecas.append(Posicao(p.ref, round(livre.x, 1), round(livre.y, 1), c, l, girada))
        # Corte guilhotina: a sobra é dividida pelo eixo mais curto
        resto_c, resto_l = livre.c - c - serra, livre.l - l - serra
        if resto_c < resto_l:
            direita = _Livre(livre.x + c + serra, livre.y, resto_c, l)
            acima = _Livre(livre.x, livre.y + l + serra, livre.c, resto_l)
        else:
            direita = _Livre(livre.x + c + serra, livre.y, resto_c, livre.l)
            acima = _Livre(livre.x, livre.y + l + serra, c, resto_l)
        livres.extend(r for r in (direita, acima) if r.c > 0 and r.l > 0)

    return [c for c, _ in chapas], nao_cabem
