"""Leitor do XML do Promob: listagem "Orçamento-Explodido c/ Operação".

Estrutura usada (LISTING > AMBIENTS > AMBIENT > CATEGORIES > CATEGORY > ITEMS > ITEM...):

- ITEM de nível 0 ............ módulo (balcão, gaveteiro, porta, frente)
- ITEM COMPONENT="Y" ......... peça; medidas WIDTH x HEIGHT(espessura) x DEPTH
- ITEM sem COMPONENT/STRUCTURE e com ITEMS ... conjunto intermediário (ex.: gaveta)
- ITEM STRUCTURE="Y" ......... estrutura da peça, pelo STRUCTUREKEY:
    CHAPA / CHAPA_* ...... material da peça (m²)
    FITA_BORDA ........... fita de borda (metros)
    CORTE, BORDA, FURAR, RASGO, ... operações do roteiro produtivo
- ITEM FAMILY="Ferragens" .... ferragem/acessório comprado

As quantidades são relativas ao pai: a quantidade efetiva é o produto da cadeia
desde o módulo. ITEMSWITHOUTPRICE repete itens da árvore e não é importado.
"""
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field


class ErroXMLPromob(ValueError):
    pass


@dataclass
class MaterialXML:
    codigo: str
    descricao: str
    tipo: str            # CHAPA, FITA, FERRAGEM
    unidade: str
    custo: float
    espessura_mm: float | None = None


@dataclass
class PecaXML:
    codigo: str
    descricao: str
    material_codigo: str
    comprimento_mm: float
    largura_mm: float
    espessura_mm: float
    quantidade: float
    fita_codigo: str | None
    fita_metros: float
    operacoes: list[str]


@dataclass
class ItemXML:
    codigo: str
    descricao: str
    quantidade: float
    unidade: str


@dataclass
class ModuloXML:
    codigo: str
    descricao: str
    largura_mm: float | None
    altura_mm: float | None
    profundidade_mm: float | None
    quantidade: float
    pecas: list[PecaXML] = field(default_factory=list)
    itens: list[ItemXML] = field(default_factory=list)


@dataclass
class ProjetoXML:
    cliente: str | None
    email: str | None
    guid: str | None
    ambientes: dict[str, list[ModuloXML]]
    materiais: dict[str, MaterialXML]
    avisos: list[str]


def _f(valor: str | None, padrao: float | None = None) -> float | None:
    if valor is None or not valor.strip():
        return padrao
    try:
        return float(valor.replace(",", "."))
    except ValueError:
        return padrao


def _filhos(item: ET.Element) -> list[ET.Element]:
    itens = item.find("ITEMS")
    return list(itens) if itens is not None else []


def _preco_tabela(item: ET.Element) -> float:
    preco = item.find("PRICE")
    return _f(preco.get("TABLE"), 0.0) if preco is not None else 0.0


def _e_ferragem(item: ET.Element) -> bool:
    marca = item.find("REFERENCES/FERRAGEM")
    marcada = marca is not None and (marca.get("REFERENCE") or "").upper() == "SIM"
    return item.get("FAMILY") == "Ferragens" or marcada


def _desc(item: ET.Element) -> str:
    return (item.get("DESCRIPTION") or "").strip()


class _Leitor:
    def __init__(self):
        self.materiais: dict[str, MaterialXML] = {}
        self.avisos: list[str] = []
        self.repeticoes = 0

    def _material(self, codigo, descricao, tipo, unidade, custo, espessura=None):
        if codigo not in self.materiais:
            self.materiais[codigo] = MaterialXML(codigo, descricao, tipo, unidade, custo, espessura)
        elif custo and not self.materiais[codigo].custo:
            self.materiais[codigo].custo = custo

    def _quantidade(self, item: ET.Element) -> float:
        if (item.get("REPETITION") or "1") not in ("1", ""):
            self.repeticoes += 1
        return _f(item.get("QUANTITY"), 1.0)

    def peca(self, item: ET.Element, qtd: float, modulo: ModuloXML) -> None:
        chapa = fita = None
        fita_metros = 0.0
        operacoes: list[str] = []
        for sub in _filhos(item):
            chave = (sub.get("STRUCTUREKEY") or "").upper()
            if sub.get("STRUCTURE") == "Y":
                if chave.startswith("CHAPA"):
                    chapa = sub
                elif chave == "FITA_BORDA":
                    fita = sub
                    fita_metros += _f(sub.get("QUANTITY"), 0.0)
                elif chave and chave not in operacoes:
                    operacoes.append(chave)
            elif _e_ferragem(sub):
                self.ferragem(sub, qtd, modulo)
            elif sub.get("COMPONENT") == "Y":
                self.peca(sub, qtd * self._quantidade(sub), modulo)

        ref = f"{modulo.descricao} / {_desc(item)}"
        if chapa is None:
            self.avisos.append(f"{ref}: peça sem chapa no XML (ignorada)")
            return

        largura = _f(item.get("WIDTH"), 0.0)
        espessura = _f(item.get("HEIGHT"), 0.0)
        profundidade = _f(item.get("DEPTH"), 0.0)
        # O Promob entrega a peça como comprimento x espessura x largura; se a
        # espessura não for a menor medida, ordena para não trocar as dimensões.
        dims = [largura, espessura, profundidade]
        if espessura != min(dims):
            dims.sort()
            espessura, largura, profundidade = dims[0], dims[2], dims[1]

        mat_cod = chapa.get("REFERENCE") or ""
        self._material(mat_cod, _desc(chapa), "CHAPA", chapa.get("UNIT") or "M2",
                       _preco_tabela(chapa), espessura)
        fita_cod = None
        if fita is not None:
            fita_cod = fita.get("REFERENCE") or None
            if fita_cod:
                self._material(fita_cod, _desc(fita), "FITA", fita.get("UNIT") or "M",
                               _preco_tabela(fita))

        modulo.pecas.append(PecaXML(
            codigo=item.get("REFERENCE") or item.get("ITEM_BASE") or _desc(item),
            descricao=_desc(item),
            material_codigo=mat_cod,
            comprimento_mm=largura,
            largura_mm=profundidade,
            espessura_mm=espessura,
            quantidade=qtd,
            fita_codigo=fita_cod,
            fita_metros=round(fita_metros, 4),
            operacoes=operacoes,
        ))

    def ferragem(self, item: ET.Element, qtd_pai: float, modulo: ModuloXML) -> None:
        codigo = item.get("REFERENCE") or item.get("ITEM_BASE") or _desc(item)
        unidade = item.get("UNIT") or "UN"
        self._material(codigo, _desc(item), "FERRAGEM", unidade, _preco_tabela(item))
        modulo.itens.append(ItemXML(codigo, _desc(item), qtd_pai * self._quantidade(item), unidade))

    def conjunto(self, item: ET.Element, qtd: float, modulo: ModuloXML) -> None:
        for sub in _filhos(item):
            if sub.get("STRUCTURE") == "Y":
                continue  # operação do conjunto (ex.: MONTAGEM)
            q = qtd * self._quantidade(sub)
            if _e_ferragem(sub):
                self.ferragem(sub, qtd, modulo)
            elif sub.get("COMPONENT") == "Y":
                self.peca(sub, q, modulo)
            elif _filhos(sub):
                self.conjunto(sub, q, modulo)
            else:
                self.avisos.append(f"{modulo.descricao}: item '{_desc(sub)}' sem classificação (ignorado)")


def ler_xml_promob(conteudo: bytes | str) -> ProjetoXML:
    try:
        raiz = ET.fromstring(conteudo)
    except ET.ParseError as e:
        raise ErroXMLPromob(f"XML inválido: {e}") from e
    if raiz.tag != "LISTING":
        raise ErroXMLPromob("Não é uma listagem do Promob (raiz LISTING não encontrada).")

    tem_estrutura = any(i.get("STRUCTURE") == "Y" for i in raiz.iter("ITEM"))
    if not tem_estrutura:
        raise ErroXMLPromob(
            f"A listagem '{raiz.get('DESCRIPTION')}' não traz chapas e operações. "
            "Exporte no Promob o relatório 'Orçamento-Explodido c/ Operação'."
        )

    leitor = _Leitor()
    ambientes: dict[str, list[ModuloXML]] = {}
    for amb in raiz.iterfind("AMBIENTS/AMBIENT"):
        nome = (amb.get("DESCRIPTION") or "Ambiente").strip()
        modulos = ambientes.setdefault(nome, [])
        for cat in amb.iterfind("CATEGORIES/CATEGORY"):
            for item in cat.iterfind("ITEMS/ITEM"):
                modulo = ModuloXML(
                    codigo=item.get("REFERENCE") or item.get("ID") or _desc(item),
                    descricao=_desc(item),
                    largura_mm=_f(item.get("WIDTH")),
                    altura_mm=_f(item.get("HEIGHT")),
                    profundidade_mm=_f(item.get("DEPTH")),
                    quantidade=_f(item.get("QUANTITY"), 1.0),
                )
                if item.get("COMPONENT") == "Y":
                    leitor.peca(item, 1.0, modulo)  # peça avulsa no nível do módulo
                elif _e_ferragem(item):
                    leitor.ferragem(item, 1.0, modulo)
                else:
                    leitor.conjunto(item, 1.0, modulo)
                if modulo.pecas or modulo.itens:
                    modulos.append(modulo)
                else:
                    leitor.avisos.append(f"Módulo '{modulo.descricao}' sem peças nem ferragens (ignorado)")

    if not any(ambientes.values()):
        raise ErroXMLPromob("Nenhum módulo com peças foi encontrado no XML.")

    sem_preco = raiz.find("ITEMSWITHOUTPRICE")
    if sem_preco is not None and len(sem_preco):
        cont = Counter(_desc(i) for i in sem_preco)
        lista = ", ".join(f"{d} ({n})" for d, n in cont.most_common(5))
        leitor.avisos.append(f"{len(sem_preco)} item(ns) sem preço na tabela do Promob: {lista}")
    if leitor.repeticoes:
        leitor.avisos.append(f"{leitor.repeticoes} item(ns) com REPETITION diferente de 1: confira as quantidades")

    dados = {d.get("ID"): (d.get("VALUE") or "").strip() for d in raiz.iterfind("CUSTOMERSDATA/DATA")}
    guid = raiz.find("PROJECTGUID")
    return ProjetoXML(
        cliente=dados.get("nomecliente") or dados.get("corporateName") or None,
        email=dados.get("email") or None,
        guid=guid.get("GUID") if guid is not None else None,
        ambientes=ambientes,
        materiais=leitor.materiais,
        avisos=leitor.avisos,
    )
