"""Configurador de produtos: a engenharia programa o que fica disponível, o comercial escolhe na venda.

Biblioteca (lógica do Promob Catalog): GRUPO → MODELO, com herança — o que está no grupo vale para os modelos
abaixo, e o filho substitui pelo mesmo código. SUBCONJUNTO é um conjunto reutilizável (REF de agregados).

Cada modelo tem:
- perguntas (Focco: variáveis): número, escolha, texto, sim/não ou acabamento; padrão, faixa permitida,
  medidas de catálogo (valores propostos), exibir só se..., validações, opções bloqueadas por condição e
  perguntas-sombra calculadas por fórmula;
- componentes (Catalog: agregados): peça de chapa, perfil, vidro, item comprado ou subconjunto, cada um com
  condição de entrada, quantidade e medidas por fórmula sobre as medidas de quem o contém ($PW$, $PH$, $PD$);
- o material de cada componente vem do acabamento escolhido (`@CORPO.CHAPA`: Catalog modelo definição/tipo),
  de um código fixo ou de uma fórmula — a engenharia não digita quantidade de matéria-prima: o consumo sai da
  geometria (m² da chapa, metros de fita por lado, metros de perfil + serra, m² de vidro, unidades).

A configuração gera o módulo no mesmo formato do XML do Promob (peças + itens): corte, PCP, compras, custo e DRE
seguem iguais. A mesma resposta com a mesma engenharia reaproveita o código (BL101.0001); engenharia mudou,
código novo — o que foi vendido fica congelado.
"""
import hashlib
import json
import re
from collections import OrderedDict

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Acabamento,
    Ambiente,
    ConfigProduto,
    ConfiguracaoProduto,
    Empresa,
    ItemModulo,
    Material,
    Modulo,
    NoProduto,
    Peca,
    Projeto,
)
from . import formulas
from .formulas import ErroFormula, normalizar, verdadeiro

TIPOS_NO = ("GRUPO", "MODELO", "SUBCONJUNTO")
TIPOS_PERGUNTA = ("NUMERO", "ESCOLHA", "TEXTO", "SIM_NAO", "ACABAMENTO")
TIPOS_COMPONENTE = ("PECA", "PERFIL", "VIDRO", "ITEM", "SUBCONJUNTO")
ALIAS_MEDIDAS = {"W": "LARGURA", "H": "ALTURA", "D": "PROFUNDIDADE", "PW": "LARGURA", "PH": "ALTURA", "PD": "PROFUNDIDADE"}
NIVEIS_MAX = 8
_CODIGO = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_REF_ACAB = re.compile(r"^@([^.\s]+)\.([^.\s]+)$")


class ErroConfigurador(ValueError):
    def __init__(self, mensagem: str, status: int = 422, detalhes: list[str] | None = None):
        super().__init__(mensagem)
        self.status = status
        self.detalhes = detalhes or []


# --- Cadastro: estrutura validada antes de gravar ------------------------------------------------------

class _M(BaseModel):
    model_config = ConfigDict(extra="ignore")


def _cod(v: str) -> str:
    c = normalizar(v or "")
    if not _CODIGO.match(c):
        raise ValueError(f"código '{v}' inválido: use letras, números e _ (começando por letra)")
    return c[:40]


def _formula(v, campo: str):
    if v is None or not str(v).strip():
        return None
    erro = formulas.validar(str(v))
    if erro:
        raise ValueError(f"{campo}: {erro}")
    return str(v).strip()


def _ref_material(v, campo: str):
    """Material: código fixo, @PERGUNTA.COMPONENTE (do acabamento escolhido) ou =fórmula."""
    if v is None or not str(v).strip():
        return None
    s = str(v).strip()
    if s.startswith("@"):
        m = _REF_ACAB.match(s)
        if not m:
            raise ValueError(f"{campo}: use @PERGUNTA.COMPONENTE (ex.: @CORPO.CHAPA)")
        return f"@{normalizar(m.group(1))}.{normalizar(m.group(2))}"
    if s.startswith("="):
        _formula(s[1:], campo)
        return s
    return s[:60]


class Opcao(_M):
    codigo: str = Field(min_length=1, max_length=40)
    nome: str = Field(min_length=1, max_length=120)
    adicional: float = Field(0.0, ge=-1e7, le=1e7)
    padrao: bool = False

    @field_validator("codigo")
    @classmethod
    def _c(cls, v):
        return normalizar(v)[:40]


class Validacao(_M):
    regra: str = Field(min_length=1, max_length=600)
    mensagem: str = Field(min_length=2, max_length=200)

    @field_validator("regra")
    @classmethod
    def _r(cls, v):
        return _formula(v, "validação")


class Bloqueio(_M):
    opcoes: list[str] = Field(min_length=1)
    se: str = Field(min_length=1, max_length=600)

    @field_validator("opcoes")
    @classmethod
    def _o(cls, v):
        return [normalizar(x) for x in v]

    @field_validator("se")
    @classmethod
    def _s(cls, v):
        return _formula(v, "bloqueio")


class Pergunta(_M):
    codigo: str
    rotulo: str | None = Field(None, max_length=160)
    tipo: str = "NUMERO"
    unidade: str | None = Field(None, max_length=10)
    padrao: float | str | bool | None = None
    formula: str | None = Field(None, max_length=2000)
    sombra: bool = False
    minimo: float | None = None
    maximo: float | None = None
    propostos: list[float] | None = None
    somente_propostos: bool = False
    opcoes: list[Opcao] | None = None
    acabamento: str | None = None
    liberadas: list[str] | None = None
    exibir_se: str | None = Field(None, max_length=600)
    validacoes: list[Validacao] = []
    bloqueios: list[Bloqueio] = []
    obrigatoria: bool = True
    remover: bool = False

    @field_validator("codigo")
    @classmethod
    def _c(cls, v):
        return _cod(v)

    @field_validator("tipo")
    @classmethod
    def _t(cls, v):
        v = (v or "").upper()
        if v not in TIPOS_PERGUNTA:
            raise ValueError(f"tipo de pergunta '{v}' inválido ({', '.join(TIPOS_PERGUNTA)})")
        return v

    @field_validator("formula")
    @classmethod
    def _f(cls, v):
        return _formula(v, "fórmula")

    @field_validator("exibir_se")
    @classmethod
    def _e(cls, v):
        return _formula(v, "exibir se")

    @field_validator("acabamento")
    @classmethod
    def _a(cls, v):
        return _cod(v) if v else None

    @field_validator("liberadas")
    @classmethod
    def _l(cls, v):
        return [normalizar(x) for x in v] if v is not None else None

    @model_validator(mode="after")
    def _coerente(self):
        if self.remover:
            return self
        self.rotulo = self.rotulo or self.codigo.replace("_", " ").title()
        if self.sombra and not self.formula:
            raise ValueError(f"pergunta {self.codigo}: sombra precisa de fórmula")
        if self.tipo == "ESCOLHA" and not self.opcoes:
            raise ValueError(f"pergunta {self.codigo}: escolha precisa de opções")
        if self.tipo == "ACABAMENTO" and not self.acabamento:
            raise ValueError(f"pergunta {self.codigo}: informe o acabamento (modelo definição)")
        if self.minimo is not None and self.maximo is not None and self.minimo > self.maximo:
            raise ValueError(f"pergunta {self.codigo}: mínimo maior que o máximo")
        return self


class Componente(_M):
    codigo: str
    descricao: str | None = Field(None, max_length=200)
    tipo: str = "PECA"
    se: str | None = Field(None, max_length=600)
    quantidade: str | None = Field("1", max_length=600)
    comprimento: str | None = Field(None, max_length=600)
    largura: str | None = Field(None, max_length=600)
    altura: str | None = Field(None, max_length=600)
    profundidade: str | None = Field(None, max_length=600)
    espessura: str | None = Field(None, max_length=600)
    material: str | None = Field(None, max_length=600)
    fitas: dict[str, str | None] | None = None
    veio: bool = False
    operacoes: str | None = Field(None, max_length=200)
    usinagem: str | None = Field(None, max_length=120)
    subconjunto: str | None = None
    remover: bool = False

    @field_validator("codigo")
    @classmethod
    def _c(cls, v):
        return _cod(v)

    @field_validator("tipo")
    @classmethod
    def _t(cls, v):
        v = (v or "").upper()
        if v not in TIPOS_COMPONENTE:
            raise ValueError(f"tipo de componente '{v}' inválido ({', '.join(TIPOS_COMPONENTE)})")
        return v

    @field_validator("se", "quantidade", "comprimento", "largura", "altura", "profundidade", "espessura")
    @classmethod
    def _f(cls, v, info):
        return _formula(v, info.field_name)

    @field_validator("material")
    @classmethod
    def _m(cls, v):
        return _ref_material(v, "material")

    @field_validator("fitas")
    @classmethod
    def _fi(cls, v):
        if not v:
            return None
        out = {}
        for lado, ref in v.items():
            lado = lado.lower()
            if lado not in ("c1", "c2", "l1", "l2"):
                raise ValueError(f"fita: lado '{lado}' inválido (c1, c2 no comprimento; l1, l2 na largura)")
            r = _ref_material(ref, f"fita {lado}")
            if r:
                out[lado] = r
        return out or None

    @field_validator("subconjunto")
    @classmethod
    def _s(cls, v):
        return _cod(v) if v else None

    @field_validator("operacoes")
    @classmethod
    def _o(cls, v):
        return ",".join(o.strip().upper() for o in v.split(",") if o.strip()) or None if v else None

    @model_validator(mode="after")
    def _coerente(self):
        if self.remover:
            return self
        self.descricao = self.descricao or self.codigo.replace("_", " ").title()
        exige = {"PECA": ("comprimento", "largura", "material"), "PERFIL": ("comprimento", "material"),
                 "VIDRO": ("comprimento", "largura", "material"), "ITEM": ("material",), "SUBCONJUNTO": ("subconjunto",)}
        faltam = [c for c in exige[self.tipo] if not getattr(self, c)]
        if faltam:
            raise ValueError(f"componente {self.codigo} ({self.tipo}): informe {', '.join(faltam)}")
        erro = formulas.erros_modelo_texto(self.descricao)
        if erro:
            raise ValueError(f"componente {self.codigo}, descrição: {erro}")
        return self


class Preco(_M):
    modo: str | None = None  # MARKUP (custo × markup) ou TABELA (fórmula de preço)
    markup: float | None = Field(None, gt=0, le=20)
    formula: str | None = Field(None, max_length=1000)

    @field_validator("modo")
    @classmethod
    def _m(cls, v):
        if v is None:
            return None
        v = v.upper()
        if v not in ("MARKUP", "TABELA"):
            raise ValueError("preço: modo MARKUP ou TABELA")
        return v

    @field_validator("formula")
    @classmethod
    def _f(cls, v):
        return _formula(v, "preço")


def _erros_pydantic(e: ValidationError) -> list[str]:
    out = []
    for x in e.errors():
        msg = str(x.get("msg", "")).removeprefix("Value error, ")
        local = ".".join(str(p) for p in x.get("loc", ()) if not isinstance(p, int))
        out.append(f"{local}: {msg}" if local and local not in msg else msg)
    return out


def limpar_perguntas(lista: list | None) -> list[dict]:
    try:
        itens = [Pergunta.model_validate(p) for p in (lista or [])]
    except ValidationError as e:
        raise ErroConfigurador("Pergunta com problema", detalhes=_erros_pydantic(e)) from e
    _sem_repetidos([p.codigo for p in itens], "pergunta")
    return [p.model_dump(exclude_none=True, exclude_defaults=True) | {"codigo": p.codigo, "tipo": p.tipo} for p in itens]


def limpar_componentes(lista: list | None) -> list[dict]:
    try:
        itens = [Componente.model_validate(c) for c in (lista or [])]
    except ValidationError as e:
        raise ErroConfigurador("Componente com problema", detalhes=_erros_pydantic(e)) from e
    _sem_repetidos([c.codigo for c in itens], "componente")
    return [c.model_dump(exclude_none=True, exclude_defaults=True) | {"codigo": c.codigo, "tipo": c.tipo} for c in itens]


def limpar_preco(p: dict | None) -> dict | None:
    if not p:
        return None
    try:
        return Preco.model_validate(p).model_dump(exclude_none=True) or None
    except ValidationError as e:
        raise ErroConfigurador("Preço com problema", detalhes=_erros_pydantic(e)) from e


def _sem_repetidos(codigos: list[str], oque: str):
    vistos, rep = set(), set()
    for c in codigos:
        (rep if c in vistos else vistos).add(c)
    if rep:
        raise ErroConfigurador(f"Código de {oque} repetido: {', '.join(sorted(rep))}")


def limpar_opcoes_acabamento(componentes: list[str], opcoes: list[dict]) -> tuple[list[str], list[dict]]:
    comps = []
    for c in componentes or []:
        c = _cod(c)
        if c not in comps:
            comps.append(c)
    if not comps:
        raise ErroConfigurador("Informe ao menos um componente do acabamento (ex.: CHAPA, FITA)")
    out, codigos = [], set()
    for o in opcoes or []:
        codigo = normalizar(o.get("codigo") or o.get("nome") or "")[:40]
        if not codigo or codigo in codigos:
            raise ErroConfigurador(f"Opção de acabamento sem código ou repetida: '{codigo}'")
        codigos.add(codigo)
        mats = {normalizar(k): str(v).strip()[:60] for k, v in (o.get("materiais") or {}).items() if v and str(v).strip()}
        estranhos = set(mats) - set(comps)
        if estranhos:
            raise ErroConfigurador(f"Opção {codigo}: componente(s) {', '.join(sorted(estranhos))} não existem no acabamento")
        info = {str(k).strip().lower(): v for k, v in (o.get("info") or {}).items() if str(k).strip()}
        out.append({"codigo": codigo, "nome": str(o.get("nome") or codigo)[:120], "referencia": (o.get("referencia") or None),
                    "materiais": mats, "info": info, "adicional": float(o.get("adicional") or 0),
                    "padrao": bool(o.get("padrao")), "ativo": o.get("ativo", True) is not False})
    if not out:
        raise ErroConfigurador("Cadastre ao menos uma opção de acabamento")
    return comps, out


# --- Herança ----------------------------------------------------------------------------------------

def config(db: Session, empresa_id: int) -> ConfigProduto:
    cfg = db.get(ConfigProduto, empresa_id)
    if cfg is None:
        cfg = ConfigProduto(empresa_id=empresa_id, constantes={})
        db.add(cfg)
        db.flush()
    return cfg


def cadeia(db: Session, no: NoProduto) -> list[NoProduto]:
    """Do topo da linha até o nó (a ordem em que a herança se aplica)."""
    lista, atual, vistos = [], no, set()
    while atual is not None:
        if atual.id in vistos:
            raise ErroConfigurador(f"Herança circular em {atual.codigo}")
        vistos.add(atual.id)
        lista.append(atual)
        atual = db.get(NoProduto, atual.pai_id) if atual.pai_id else None
    return list(reversed(lista))


def _mesclar(nos: list[NoProduto], campo: str) -> list[dict]:
    efetivo: OrderedDict[str, dict] = OrderedDict()
    for no in nos:
        for item in getattr(no, campo) or []:
            c = item["codigo"]
            if item.get("remover"):
                efetivo.pop(c, None)
            else:
                efetivo[c] = {**item, "origem": no.codigo}
    return list(efetivo.values())


def efetivo(db: Session, no: NoProduto) -> dict:
    nos = cadeia(db, no)
    preco: dict = {}
    for n in nos:
        preco.update({k: v for k, v in (n.preco or {}).items() if v is not None})
    descricao = next((n.descricao_formula for n in reversed(nos) if n.descricao_formula), None)
    return {"perguntas": _mesclar(nos, "perguntas"), "componentes": _mesclar(nos, "componentes"), "preco": preco,
            "descricao_formula": descricao, "cadeia": [n.codigo for n in nos]}


# --- Motor --------------------------------------------------------------------------------------------

def _fmt(v: float) -> str:
    return formulas.formatar(round(v, 1))


class Motor(formulas.Ambiente):
    """Uma configuração: respostas do vendedor sobre a engenharia de um modelo."""

    def __init__(self, db: Session, modelo: NoProduto, respostas: dict | None = None):
        if modelo.tipo != "MODELO":
            raise ErroConfigurador(f"{modelo.codigo} é {modelo.tipo}: só MODELO é vendido")
        self.db, self.modelo, self.empresa_id = db, modelo, modelo.empresa_id
        self.cfg = config(db, modelo.empresa_id)
        self.empresa = db.get(Empresa, modelo.empresa_id)
        self.const = {normalizar(k): v for k, v in (self.cfg.constantes or {}).items()}
        self.acab = {a.codigo: a for a in db.scalars(select(Acabamento).where(Acabamento.empresa_id == self.empresa_id))}
        self.nos = {n.codigo: n for n in db.scalars(select(NoProduto).where(NoProduto.empresa_id == self.empresa_id))}
        self.materiais = {m.codigo: m for m in db.scalars(select(Material).where(Material.empresa_id == self.empresa_id))}
        self._ef: dict[str, dict] = {}
        self.ef = self._efetivo(modelo)
        self.perguntas: OrderedDict[str, dict] = OrderedDict((p["codigo"], p) for p in self.ef["perguntas"])
        self._perguntas_de_subconjuntos(self.ef["componentes"], [modelo.codigo])
        self.respostas = {normalizar(k): v for k, v in (respostas or {}).items()}
        self._valores: dict[str, object] = {}
        self._vis: dict[str, bool] = {}
        self._calc: set[str] = set()
        self.local: list[dict] = []
        self.erros: dict[str, str] = {}       # erro de resposta do vendedor, por pergunta
        self.pendencias: list[str] = []       # erro de engenharia (regra, material, subconjunto)
        self.subs_usados: set[str] = set()

    # Biblioteca
    def _efetivo(self, no: NoProduto) -> dict:
        if no.codigo not in self._ef:
            self._ef[no.codigo] = efetivo(self.db, no)
        return self._ef[no.codigo]

    def _perguntas_de_subconjuntos(self, comps: list[dict], pilha: list[str]):
        for c in comps:
            if c.get("tipo") != "SUBCONJUNTO":
                continue
            sub = self.nos.get(c.get("subconjunto"))
            if sub is None or sub.codigo in pilha or len(pilha) > NIVEIS_MAX:
                continue
            ef = self._efetivo(sub)
            for p in ef["perguntas"]:
                self.perguntas.setdefault(p["codigo"], p)  # a pergunta do modelo vale sobre a do subconjunto
            self._perguntas_de_subconjuntos(ef["componentes"], pilha + [sub.codigo])

    def pendencia(self, texto: str):
        if texto not in self.pendencias:
            self.pendencias.append(texto)

    # Ambiente das fórmulas
    def variavel(self, nome: str):
        for frame in reversed(self.local):
            if nome in frame:
                return frame[nome]
        if nome in self.perguntas:
            return self.valor(nome)
        if nome in ALIAS_MEDIDAS and ALIAS_MEDIDAS[nome] in self.perguntas:
            return self.valor(ALIAS_MEDIDAS[nome])
        raise ErroFormula(f"'{nome}' não é pergunta nem medida deste produto")

    def constante(self, nome: str):
        if nome not in self.const:
            raise ErroFormula(f"constante %{nome}% não cadastrada (Configurador → Constantes)")
        return float(self.const[nome])

    def _pergunta_acabamento(self, nome: str) -> dict | None:
        p = self.perguntas.get(nome)
        if p and p["tipo"] == "ACABAMENTO":
            return p
        return next((q for q in self.perguntas.values() if q["tipo"] == "ACABAMENTO" and q.get("acabamento") == nome), None)

    def _opcao_acabamento(self, p: dict) -> dict | None:
        escolhido = self.valor(p["codigo"])
        acab = self.acab.get(p.get("acabamento"))
        if escolhido is None or acab is None:
            return None
        return next((o for o in acab.opcoes if o["codigo"] == escolhido), None)

    def info(self, acabamento: str, campo: str):
        p = self._pergunta_acabamento(acabamento)
        if p is None:
            raise ErroFormula(f"@{acabamento}: não há pergunta de acabamento com esse código")
        op = self._opcao_acabamento(p)
        if op is None:
            return None
        if campo in ("nome", "codigo", "referencia"):
            return op.get(campo)
        if campo in op.get("info", {}):
            return op["info"][campo]
        if campo.upper() in op.get("materiais", {}):
            return op["materiais"][campo.upper()]
        return None

    def _av(self, texto: str | None, onde: str, padrao=None):
        if texto is None or str(texto).strip() == "":
            return padrao
        try:
            return formulas.avaliar(texto, self)
        except ErroFormula as e:
            self.pendencia(f"{onde}: {e}")
            return padrao

    def _num(self, texto, onde: str, padrao: float | None = None) -> float | None:
        v = self._av(texto, onde, padrao)
        if v is None:
            return padrao
        try:
            return float(v) if not isinstance(v, str) else float(v.replace(",", "."))
        except ValueError:
            self.pendencia(f"{onde}: '{v}' não é número")
            return padrao

    # Perguntas
    def visivel(self, codigo: str) -> bool:
        p = self.perguntas[codigo]
        if not p.get("exibir_se"):
            return True
        if codigo not in self._vis:
            chave = f"vis:{codigo}"
            if chave in self._calc:
                self.pendencia(f"pergunta {codigo}: 'exibir se' depende dela mesma")
                return True
            self._calc.add(chave)
            try:
                self._vis[codigo] = verdadeiro(self._av(p["exibir_se"], f"pergunta {codigo} (exibir se)", True))
            finally:
                self._calc.discard(chave)
        return self._vis[codigo]

    def valor(self, codigo: str):
        if codigo in self._valores:
            return self._valores[codigo]
        if codigo in self._calc:
            raise ErroFormula(f"fórmula circular na pergunta {codigo}")
        self._calc.add(codigo)
        try:
            v = self._calcular(self.perguntas[codigo])
        finally:
            self._calc.discard(codigo)
        self._valores[codigo] = v
        return v

    def _calcular(self, p: dict):
        c = p["codigo"]
        if not self.visivel(c):
            return None
        if p.get("sombra"):
            return self._coagir(p, self._av(p["formula"], f"pergunta {c}"), calculado=True)
        r = self.respostas.get(c)
        if r is not None and str(r).strip() != "":
            return self._coagir(p, r)
        if p.get("formula"):
            return self._coagir(p, self._av(p["formula"], f"pergunta {c}"), calculado=True)
        if p.get("padrao") not in (None, ""):
            return self._coagir(p, p["padrao"], calculado=True)
        if p["tipo"] in ("ESCOLHA", "ACABAMENTO"):
            padrao = next((o for o in self._todas_opcoes(p) if o.get("padrao")), None)
            return padrao["codigo"] if padrao else None
        if p["tipo"] == "SIM_NAO":
            return False
        return None

    def _coagir(self, p: dict, v, calculado: bool = False):
        if v is None:
            return None
        t = p["tipo"]
        if t == "NUMERO":
            try:
                return float(v) if not isinstance(v, str) else float(v.strip().replace(".", "").replace(",", ".")
                                                                   if "," in v else v.strip())
            except ValueError:
                if not calculado:
                    self.erros[p["codigo"]] = "informe um número"
                return None
        if t == "SIM_NAO":
            return verdadeiro(v)
        if t in ("ESCOLHA", "ACABAMENTO"):
            alvo = normalizar(v)
            for o in self._todas_opcoes(p):
                if o["codigo"] == alvo or normalizar(o["nome"]) == alvo:
                    return o["codigo"]
            return alvo
        return str(v).strip()[:200]

    def _todas_opcoes(self, p: dict) -> list[dict]:
        if p["tipo"] == "ESCOLHA":
            return p.get("opcoes") or []
        if p["tipo"] == "ACABAMENTO":
            acab = self.acab.get(p.get("acabamento"))
            if acab is None:
                self.pendencia(f"pergunta {p['codigo']}: acabamento {p.get('acabamento')} não cadastrado")
                return []
            ops = [o for o in acab.opcoes if o.get("ativo", True)]
            if p.get("liberadas") is not None:
                ops = [o for o in ops if o["codigo"] in p["liberadas"]]
            return ops
        return []

    def disponiveis(self, p: dict) -> list[dict]:
        bloqueadas = set()
        for b in p.get("bloqueios") or []:
            if verdadeiro(self._av(b["se"], f"pergunta {p['codigo']} (bloqueio)", False)):
                bloqueadas.update(b["opcoes"])
        return [o for o in self._todas_opcoes(p) if o["codigo"] not in bloqueadas]

    def validar(self) -> dict[str, str]:
        for c, p in self.perguntas.items():
            v = self.valor(c)
            if c in self.erros or not self.visivel(c):
                continue
            if p.get("sombra"):
                pass
            elif v is None or v == "":
                if p.get("obrigatoria", True) and p["tipo"] != "SIM_NAO":
                    self.erros[c] = "responda esta pergunta"
                continue
            elif p["tipo"] == "NUMERO":
                if p.get("minimo") is not None and v < p["minimo"]:
                    self.erros[c] = f"mínimo {_fmt(p['minimo'])} {p.get('unidade') or ''}".strip()
                elif p.get("maximo") is not None and v > p["maximo"]:
                    self.erros[c] = f"máximo {_fmt(p['maximo'])} {p.get('unidade') or ''}".strip()
                elif p.get("somente_propostos") and p.get("propostos") and not any(abs(v - x) < 1e-6 for x in p["propostos"]):
                    self.erros[c] = "use uma das medidas do catálogo: " + ", ".join(_fmt(x) for x in p["propostos"])
            elif p["tipo"] in ("ESCOLHA", "ACABAMENTO"):
                if v not in {o["codigo"] for o in self.disponiveis(p)}:
                    self.erros[c] = f"opção {v} não está disponível nesta configuração"
            if c in self.erros:
                continue
            for regra in p.get("validacoes") or []:
                ok = self._av(regra["regra"], f"pergunta {c} (validação)", True)
                if not verdadeiro(ok):
                    self.erros[c] = regra["mensagem"]
                    break
        return self.erros

    def estado(self) -> list[dict]:
        out = []
        for c, p in self.perguntas.items():
            vis = self.visivel(c)
            item = {"codigo": c, "rotulo": p.get("rotulo") or c, "tipo": p["tipo"], "unidade": p.get("unidade"),
                    "visivel": vis, "valor": self.valor(c), "sombra": bool(p.get("sombra")),
                    "obrigatoria": p.get("obrigatoria", True), "erro": self.erros.get(c), "origem": p.get("origem")}
            for k in ("minimo", "maximo", "propostos", "somente_propostos"):
                if p.get(k) is not None:
                    item[k] = p[k]
            if p["tipo"] in ("ESCOLHA", "ACABAMENTO"):
                item["opcoes"] = [{"codigo": o["codigo"], "nome": o["nome"], "adicional": o.get("adicional", 0)}
                                  for o in (self.disponiveis(p) if vis else [])]
            out.append(item)
        return out

    def respostas_normalizadas(self) -> dict:
        out = {}
        for c, p in self.perguntas.items():
            if p.get("sombra") or not self.visivel(c):
                continue
            v = self.valor(c)
            if v is None:
                continue
            out[c] = round(v, 4) if isinstance(v, float) else v
        return out

    # Explosão
    def _material(self, ref: str | None, onde: str) -> str | None:
        if not ref:
            return None
        if ref.startswith("@"):
            m = _REF_ACAB.match(ref)
            p = self._pergunta_acabamento(m.group(1)) if m else None
            if p is None:
                self.pendencia(f"{onde}: {ref} — não há pergunta de acabamento {m.group(1) if m else ref}")
                return None
            op = self._opcao_acabamento(p)
            if op is None:
                if self.visivel(p["codigo"]):
                    self.pendencia(f"{onde}: escolha {p.get('rotulo') or p['codigo']}")
                else:
                    self.pendencia(f"{onde}: usa o acabamento {p['codigo']}, que está oculto nesta configuração")
                return None
            codigo = op.get("materiais", {}).get(m.group(2))
            if not codigo:
                acab = self.acab[p["acabamento"]]
                self.pendencia(f"{onde}: o acabamento {acab.nome} / {op['nome']} não define o material de {m.group(2)}")
                return None
        elif ref.startswith("="):
            v = self._av(ref[1:], f"{onde} (material)")
            codigo = str(v).strip() if v not in (None, "") else None
            if codigo is None:
                return None
        else:
            codigo = ref
        if codigo not in self.materiais:
            self.pendencia(f"{onde}: material '{codigo}' sem cadastro")
        return codigo

    def explodir(self) -> dict:
        w = self._num_pergunta("LARGURA")
        h = self._num_pergunta("ALTURA")
        d = self._num_pergunta("PROFUNDIDADE")
        self.modulo = {"codigo": self.modelo.codigo, "descricao": self.descricao(), "largura_mm": w, "altura_mm": h,
                       "profundidade_mm": d, "pecas": [], "itens": []}
        self.arvore = self._componentes(self.ef["componentes"], (w, h, d), [], 1.0, 0, [self.modelo.codigo])
        return self.modulo

    def _num_pergunta(self, codigo: str) -> float | None:
        if codigo not in self.perguntas:
            return None
        v = self.valor(codigo)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def descricao(self) -> str:
        texto = self.ef.get("descricao_formula")
        if not texto:
            return self.modelo.nome
        try:
            return formulas.modelo_texto(texto, self)[:300] or self.modelo.nome
        except ErroFormula as e:
            self.pendencia(f"descrição do produto: {e}")
            return self.modelo.nome

    def _componentes(self, comps, dims, caminho, mult, nivel, pilha) -> list[dict]:
        w, h, d = dims
        frame = {"W": w, "H": h, "D": d, "PW": w, "PH": h, "PD": d}
        nos = []
        for c in comps:
            ref = ".".join(caminho + [c["codigo"]])
            no = {"codigo": c["codigo"], "caminho": ref, "tipo": c["tipo"], "descricao": c.get("descricao"),
                  "origem": c.get("origem"), "incluido": True}
            nos.append(no)
            self.local.append(frame)
            try:
                if c.get("se") and not verdadeiro(self._av(c["se"], f"{ref} (condição)", False)):
                    no["incluido"] = False
                    continue
                self._componente(c, no, ref, frame, caminho, mult, nivel, pilha)
            finally:
                self.local.pop()
        return nos

    def _componente(self, c, no, ref, frame, caminho, mult, nivel, pilha):
        tipo = c["tipo"]
        local = {}
        if tipo in ("PECA", "VIDRO", "PERFIL"):
            comp = self._num(c.get("comprimento"), f"{ref} (comprimento)")
            larg = self._num(c.get("largura"), f"{ref} (largura)") if tipo != "PERFIL" else None
            local = {"C": comp, "L": larg}
            if comp is None or comp <= 0 or (tipo != "PERFIL" and (larg is None or larg <= 0)):
                self.pendencia(f"{ref}: medida inválida ({_fmt(comp or 0)} × {_fmt(larg or 0)})")
                no["incluido"] = False
                return
        self.local.append(local)
        try:
            qtd = self._num(c.get("quantidade") or "1", f"{ref} (quantidade)", 1.0)
            if qtd is None or qtd <= 0:
                no["incluido"], no["quantidade"] = False, 0
                return
            total = qtd * mult
            no["quantidade"] = round(total, 4)
            try:
                descricao = formulas.modelo_texto(c.get("descricao") or c["codigo"], self)[:200]
            except ErroFormula as e:
                self.pendencia(f"{ref} (descrição): {e}")
                descricao = c["codigo"]
            no["descricao"] = descricao
            if tipo == "SUBCONJUNTO":
                self._subconjunto(c, no, ref, frame, caminho, total, nivel, pilha)
                return
            codigo = self._material(c.get("material"), ref)
            mat = self.materiais.get(codigo) if codigo else None
            no["material"] = codigo
            if tipo == "PECA":
                self._peca(c, no, ref, local, total, codigo, mat, descricao)
            else:
                self._item(c, no, ref, local, total, codigo, mat, descricao)
        finally:
            self.local.pop()

    def _peca(self, c, no, ref, local, total, codigo, mat, descricao):
        esp = self._num(c.get("espessura"), f"{ref} (espessura)") if c.get("espessura") else None
        if esp is None and mat is not None:
            esp = mat.espessura_mm
        if abs(total - round(total)) > 1e-6:
            self.pendencia(f"{ref}: quantidade de peças {_fmt(total)} não é inteira")
        fitas = {lado: self._material(r, f"{ref} (fita {lado})") for lado, r in (c.get("fitas") or {}).items()}
        peca = {"codigo": ref[:60], "descricao": descricao, "material_codigo": codigo or "?",
                "comprimento_mm": round(local["C"], 1), "largura_mm": round(local["L"], 1),
                "espessura_mm": esp, "quantidade": max(1, round(total)), "veio": bool(c.get("veio")),
                "fita_c1": fitas.get("c1"), "fita_c2": fitas.get("c2"), "fita_l1": fitas.get("l1"), "fita_l2": fitas.get("l2"),
                "operacoes": c.get("operacoes"), "programa_usinagem": c.get("usinagem")}
        self.modulo["pecas"].append(peca)
        no["medidas"] = f"{_fmt(local['C'])} × {_fmt(local['L'])}" + (f" × {_fmt(esp)}" if esp else "")

    def _item(self, c, no, ref, local, total, codigo, mat, descricao):
        tipo = c["tipo"]
        unidade = (mat.unidade if mat else None) or {"PERFIL": "M", "VIDRO": "M2"}.get(tipo, "UN")
        detalhe = None
        cortes = None
        if tipo == "PERFIL":
            metros = (local["C"] + self.cfg.serra_perfil_mm) / 1000 * total * (1 + self.cfg.perda_perfil_pct / 100)
            if unidade.upper() in ("M", "ML") or not (mat and mat.comprimento_mm):
                qtd = metros
            else:  # barra: fração da barra pelo comprimento cadastrado (o aproveitamento fica para o plano de corte)
                qtd = metros / (mat.comprimento_mm / 1000)
            detalhe = f"{_fmt(total)} × {_fmt(local['C'])} mm"
            cortes = [{"comprimento_mm": round(local["C"], 1), "quantidade": round(total, 4)}]
            no["medidas"] = f"{_fmt(local['C'])} mm"
        elif tipo == "VIDRO":
            area = local["C"] * local["L"] / 1e6 * total
            qtd = area if unidade.upper() == "M2" else total
            detalhe = f"{_fmt(total)} × {_fmt(local['C'])} × {_fmt(local['L'])} mm"
            no["medidas"] = f"{_fmt(local['C'])} × {_fmt(local['L'])}"
        else:
            qtd = total
        item = {"material_codigo": codigo or "?", "descricao": (f"{descricao} · {detalhe}" if detalhe else descricao)[:200],
                "quantidade": round(qtd, 4), "unidade": unidade, "tipo": tipo, "componente": ref}
        if cortes:
            item["cortes"] = cortes
        self.modulo["itens"].append(item)

    def _subconjunto(self, c, no, ref, frame, caminho, total, nivel, pilha):
        sub = self.nos.get(c.get("subconjunto"))
        if sub is None or not sub.ativo:
            self.pendencia(f"{ref}: subconjunto {c.get('subconjunto')} não cadastrado ou inativo")
            no["incluido"] = False
            return
        if sub.codigo in pilha or nivel >= NIVEIS_MAX:
            self.pendencia(f"{ref}: subconjunto {sub.codigo} dentro dele mesmo (ou mais de {NIVEIS_MAX} níveis)")
            no["incluido"] = False
            return
        self.subs_usados.add(sub.codigo)
        w2 = self._num(c.get("largura"), f"{ref} (largura)", frame["W"])
        h2 = self._num(c.get("altura"), f"{ref} (altura)", frame["H"])
        d2 = self._num(c.get("profundidade"), f"{ref} (profundidade)", frame["D"])
        no["medidas"] = " × ".join(_fmt(x) for x in (w2, h2, d2) if x)
        no["subconjunto"] = sub.codigo
        no["filhos"] = self._componentes(self._efetivo(sub)["componentes"], (w2, h2, d2), caminho + [c["codigo"]],
                                         total, nivel + 1, pilha + [sub.codigo])

    # Custo e preço
    def custo(self) -> dict:
        perda_chapa = 1 + (self.empresa.perda_chapa_pct or 0) / 100
        perda_fita = 1 + (self.empresa.perda_fita_pct or 0) / 100
        linhas: dict[str, dict] = {}

        def somar(codigo, quantidade, unidade, custo_unit):
            mat = self.materiais.get(codigo)
            ln = linhas.setdefault(codigo, {"material_codigo": codigo, "descricao": mat.descricao if mat else "(sem cadastro)",
                                            "unidade": unidade, "quantidade": 0.0, "custo": 0.0})
            ln["quantidade"] += quantidade
            ln["custo"] += quantidade * custo_unit

        for pc in self.modulo["pecas"]:
            mat = self.materiais.get(pc["material_codigo"])
            area = pc["comprimento_mm"] * pc["largura_mm"] / 1e6 * pc["quantidade"] * perda_chapa
            custo_m2 = 0.0
            if mat:
                if mat.unidade.upper() != "M2" and mat.comprimento_mm and mat.largura_mm:
                    custo_m2 = mat.custo_unitario / (mat.comprimento_mm * mat.largura_mm / 1e6)
                else:
                    custo_m2 = mat.custo_unitario
            somar(pc["material_codigo"], area, "M2", custo_m2)
            for lado, medida in (("fita_c1", pc["comprimento_mm"]), ("fita_c2", pc["comprimento_mm"]),
                                 ("fita_l1", pc["largura_mm"]), ("fita_l2", pc["largura_mm"])):
                if pc.get(lado):
                    fm = self.materiais.get(pc[lado])
                    somar(pc[lado], medida / 1000 * pc["quantidade"] * perda_fita, "M", fm.custo_unitario if fm else 0.0)
        for it in self.modulo["itens"]:
            mat = self.materiais.get(it["material_codigo"])
            somar(it["material_codigo"], it["quantidade"], it["unidade"], mat.custo_unitario if mat else 0.0)

        from .custos import mao_de_obra_pecas
        mo = mao_de_obra_pecas(self.db, self.empresa_id, self.modelo.codigo, self.modulo["descricao"], self.modulo["pecas"])
        consumo = [{**ln, "quantidade": round(ln["quantidade"], 4), "custo": round(ln["custo"], 2)}
                   for ln in sorted(linhas.values(), key=lambda x: x["material_codigo"])]
        material = round(sum(ln["custo"] for ln in consumo), 2)
        m2 = sum(pc["comprimento_mm"] * pc["largura_mm"] / 1e6 * pc["quantidade"] for pc in self.modulo["pecas"])
        return {"consumo": consumo, "material": material, "mao_de_obra": mo["total"], "horas": mo["horas"],
                "por_setor": mo["por_setor"], "total": round(material + mo["total"], 2), "m2_chapa": round(m2, 4),
                "pecas": sum(pc["quantidade"] for pc in self.modulo["pecas"])}

    def _markup(self) -> tuple[float, str]:
        p = self.ef["preco"]
        if p.get("markup"):
            return float(p["markup"]), f"markup do produto ({self.ef['cadeia'][-1] if self.ef['cadeia'] else ''})"
        from . import controladoria, markup
        cen = controladoria.cenario_principal(self.db, self.empresa_id)
        if cen is not None:
            try:
                return float(markup.calcular(cen.premissas)["markup"]["markup_final"]), f"cenário principal ({cen.nome})"
            except Exception:  # premissas inválidas não derrubam a venda: cai no padrão
                pass
        return float(self.cfg.markup_padrao or 2.0), "markup padrão do configurador"

    def preco(self, custo: dict) -> dict:
        p = self.ef["preco"]
        adicionais = []
        for c, perg in self.perguntas.items():
            if perg["tipo"] not in ("ESCOLHA", "ACABAMENTO") or not self.visivel(c):
                continue
            v = self.valor(c)
            op = next((o for o in self._todas_opcoes(perg) if o["codigo"] == v), None)
            if op and op.get("adicional"):
                adicionais.append({"pergunta": c, "opcao": op["nome"], "valor": float(op["adicional"])})
        soma_adic = sum(a["valor"] for a in adicionais)
        if (p.get("modo") or "MARKUP") == "TABELA":
            self.local.append({"CUSTO": custo["total"], "CUSTO_MATERIAL": custo["material"]})
            try:
                base = self._num(p.get("formula"), "fórmula de preço", 0.0) or 0.0
            finally:
                self.local.pop()
            mk, origem = None, "preço de tabela (fórmula do produto)"
        else:
            mk, origem = self._markup()
            base = custo["total"] * mk
        return {"modo": p.get("modo") or "MARKUP", "markup": mk, "origem": origem, "base": round(base, 2),
                "adicionais": adicionais, "unitario": round(base + soma_adic, 2)}

    # Assinatura: mesma resposta + mesma engenharia = mesmo código
    def assinatura(self) -> str:
        acabs = sorted({p.get("acabamento") for p in self.perguntas.values() if p.get("acabamento")})
        eng = {"modelo": self.ef, "subs": {s: self._ef[s] for s in sorted(self.subs_usados)},
               "acab": {a: self.acab[a].opcoes for a in acabs if a in self.acab}, "const": self.const,
               "perfil": [self.cfg.perda_perfil_pct, self.cfg.serra_perfil_mm]}
        bruto = json.dumps({"r": self.respostas_normalizadas(), "e": eng}, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(bruto.encode()).hexdigest()

    def resultado(self, quantidade: int = 1) -> dict:
        self.validar()
        modulo = self.explodir()
        custo = self.custo()
        preco = self.preco(custo)
        existente = self.db.scalar(select(ConfiguracaoProduto).where(
            ConfiguracaoProduto.empresa_id == self.empresa_id, ConfiguracaoProduto.modelo_id == self.modelo.id,
            ConfiguracaoProduto.assinatura == self.assinatura()))
        return {"modelo": {"id": self.modelo.id, "codigo": self.modelo.codigo, "nome": self.modelo.nome,
                           "heranca": self.ef["cadeia"]},
                "perguntas": self.estado(), "erros": dict(self.erros), "pendencias": list(self.pendencias),
                "valido": not self.erros and not self.pendencias, "descricao": modulo["descricao"],
                "codigo_existente": existente.codigo if existente else None, "respostas": self.respostas_normalizadas(),
                "modulo": modulo, "arvore": self.arvore, "custo": custo,
                "preco": {**preco, "quantidade": quantidade, "total": round(preco["unitario"] * quantidade, 2)}}


# --- Biblioteca: leitura ------------------------------------------------------------------------------

def carregar_no(db: Session, empresa_id: int, no_id: int) -> NoProduto:
    no = db.get(NoProduto, no_id)
    if no is None or no.empresa_id != empresa_id:
        raise ErroConfigurador("Produto não encontrado", 404)
    return no


def no_out(no: NoProduto, completo: bool = False) -> dict:
    d = {"id": no.id, "pai_id": no.pai_id, "tipo": no.tipo, "codigo": no.codigo, "nome": no.nome, "ordem": no.ordem,
         "ativo": no.ativo, "perguntas": len(no.perguntas or []), "componentes": len(no.componentes or []),
         "atualizado_em": no.atualizado_em, "atualizado_por": no.atualizado_por}
    if completo:
        d.update({"perguntas": no.perguntas or [], "componentes": no.componentes or [], "preco": no.preco,
                  "descricao_formula": no.descricao_formula, "observacao": no.observacao})
    return d


def acabamento_out(a: Acabamento) -> dict:
    return {"id": a.id, "codigo": a.codigo, "nome": a.nome, "componentes": a.componentes, "opcoes": a.opcoes}


def modelos_a_venda(db: Session, empresa_id: int) -> list[dict]:
    """Para o vendedor: modelos ativos com o caminho na linha (Cozinha › Balcões)."""
    nos = {n.id: n for n in db.scalars(select(NoProduto).where(NoProduto.empresa_id == empresa_id))}
    out = []
    for n in nos.values():
        if n.tipo != "MODELO" or not n.ativo:
            continue
        caminho, atual, guarda = [], nos.get(n.pai_id), 0
        while atual is not None and guarda < 20:
            if not atual.ativo:
                break
            caminho.append(atual.nome)
            atual, guarda = nos.get(atual.pai_id), guarda + 1
        else:
            out.append({"id": n.id, "codigo": n.codigo, "nome": n.nome, "linha": " › ".join(reversed(caminho)), "ordem": n.ordem})
    return sorted(out, key=lambda m: (m["linha"], m["ordem"], m["nome"]))


# --- Configuração confirmada (código reaproveitável) -------------------------------------------------

def simular(db: Session, modelo: NoProduto, respostas: dict | None, quantidade: int = 1) -> dict:
    return Motor(db, modelo, respostas).resultado(quantidade)


def confirmar(db: Session, modelo: NoProduto, respostas: dict | None, usuario: str | None) -> tuple[ConfiguracaoProduto, dict]:
    """Valida e grava (ou reaproveita) a configuração. Erro de resposta ou pendência de engenharia barra."""
    motor = Motor(db, modelo, respostas)
    r = motor.resultado()
    if r["erros"]:
        rot = {p["codigo"]: p["rotulo"] for p in r["perguntas"]}
        raise ErroConfigurador(f"{modelo.nome}: confira as respostas", 422,
                               [f"{rot.get(c, c)}: {m}" for c, m in r["erros"].items()])
    if r["pendencias"]:
        raise ErroConfigurador(f"{modelo.nome} tem pendência de engenharia (avise a engenharia de produto)", 422,
                               r["pendencias"])
    assinatura = motor.assinatura()
    existente = db.scalar(select(ConfiguracaoProduto).where(
        ConfiguracaoProduto.empresa_id == modelo.empresa_id, ConfiguracaoProduto.modelo_id == modelo.id,
        ConfiguracaoProduto.assinatura == assinatura))
    if existente:
        return existente, r
    seq = (db.scalar(select(func.max(ConfiguracaoProduto.sequencial)).where(
        ConfiguracaoProduto.empresa_id == modelo.empresa_id, ConfiguracaoProduto.modelo_id == modelo.id)) or 0) + 1
    codigo = f"{modelo.codigo}.{seq:04d}"
    modulo = {**r["modulo"], "codigo": codigo}
    custo = {k: r["custo"][k] for k in ("material", "mao_de_obra", "horas", "total", "m2_chapa", "pecas")}
    custo["preco_unitario"], custo["markup"], custo["origem_preco"] = r["preco"]["unitario"], r["preco"]["markup"], r["preco"]["origem"]
    cfg = ConfiguracaoProduto(empresa_id=modelo.empresa_id, modelo_id=modelo.id, sequencial=seq, codigo=codigo,
                              assinatura=assinatura, respostas=r["respostas"], descricao=r["descricao"][:300],
                              modulo=modulo, custo=custo, criado_por=usuario)
    db.add(cfg)
    db.flush()
    return cfg, r


def preparar_itens(db: Session, empresa_id: int, itens: list[dict], usuario: str | None) -> list[dict]:
    """Itens da venda: cada um vira configuração gravada, com preço e custo do momento (o vendido fica congelado)."""
    if not itens:
        raise ErroConfigurador("Configure ao menos um produto")
    if len(itens) > 300:
        raise ErroConfigurador("Até 300 produtos configurados por versão")
    out, erros = [], []
    for i, it in enumerate(itens, start=1):
        try:
            modelo = carregar_no(db, empresa_id, int(it["modelo_id"]))
            qtd = int(it.get("quantidade") or 1)
            if not 1 <= qtd <= 999:
                raise ErroConfigurador("quantidade entre 1 e 999")
            cfg, r = confirmar(db, modelo, it.get("respostas") or {}, usuario)
        except ErroConfigurador as e:
            erros.append(f"Item {i}: {e}" + (f" — {'; '.join(e.detalhes)}" if e.detalhes else ""))
            continue
        out.append({"configuracao_id": cfg.id, "codigo": cfg.codigo, "modelo_id": modelo.id, "modelo_codigo": modelo.codigo,
                    "descricao": cfg.descricao, "respostas": cfg.respostas, "quantidade": qtd,
                    "ambiente": (str(it.get("ambiente") or "").strip() or "Produtos configurados")[:120],
                    "preco_unitario": cfg.custo["preco_unitario"], "custo_material": cfg.custo["material"],
                    "mao_de_obra": cfg.custo["mao_de_obra"], "horas": cfg.custo["horas"], "m2": cfg.custo["m2_chapa"],
                    "pecas": cfg.custo["pecas"]})
    if erros:
        raise ErroConfigurador("Há produtos configurados com problema", 422, erros)
    return out


def resumo_itens(itens: list[dict], cliente: str | None) -> dict:
    """Mesmo formato do resumo do XML do Promob (o comercial negocia igual)."""
    ambientes: OrderedDict[str, dict] = OrderedDict()
    modulos, preco, custo, mo, horas, m2, pecas, n = [], 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0
    for it in itens:
        q = it["quantidade"]
        a = ambientes.setdefault(it["ambiente"], {"nome": it["ambiente"], "modulos": 0, "pecas": 0, "m2": 0.0})
        a["modulos"] += q
        a["pecas"] += it["pecas"] * q
        a["m2"] = round(a["m2"] + it["m2"] * q, 3)
        modulos.append({"ambiente": it["ambiente"], "codigo": it["codigo"], "descricao": it["descricao"], "quantidade": q,
                        "origem": "CONFIGURADOR"})
        preco += it["preco_unitario"] * q
        custo += it["custo_material"] * q
        mo += it["mao_de_obra"] * q
        horas += it["horas"] * q
        m2 += it["m2"] * q
        pecas += it["pecas"] * q
        n += q
    r2 = lambda v, k=2: round(v, k)  # noqa: E731
    return {"cliente": cliente, "ambientes": list(ambientes.values()), "modulos": modulos, "total_modulos": n,
            "total_pecas": int(pecas), "m2_chapa": r2(m2, 3), "valor_tabela": r2(preco), "valor_pedido": r2(custo),
            "valor_venda": r2(preco), "frete": 0.0, "montagem": 0.0, "condicao_promob": None, "mao_de_obra": r2(mo),
            "mao_de_obra_horas": r2(horas), "configurados": {"itens": len(itens), "valor": r2(preco), "custo_material": r2(custo)}}


def somar_resumos(xml: dict, conf: dict) -> dict:
    """Projeto do Promob + produtos do configurador na mesma proposta."""
    r = dict(xml)
    ambientes = {a["nome"]: dict(a) for a in xml.get("ambientes", [])}
    for a in conf["ambientes"]:
        if a["nome"] in ambientes:
            b = ambientes[a["nome"]]
            b["modulos"] += a["modulos"]
            b["pecas"] += a["pecas"]
            b["m2"] = round(b["m2"] + a["m2"], 3)
        else:
            ambientes[a["nome"]] = dict(a)
    r["ambientes"] = list(ambientes.values())
    r["modulos"] = list(xml.get("modulos", [])) + conf["modulos"]
    for k in ("total_modulos", "total_pecas"):
        r[k] = (xml.get(k) or 0) + conf[k]
    for k in ("m2_chapa", "valor_tabela", "valor_pedido", "mao_de_obra", "mao_de_obra_horas"):
        r[k] = round((xml.get(k) or 0) + conf[k], 3 if k == "m2_chapa" else 2)
    r["valor_venda"] = round((xml.get("valor_venda") or xml.get("valor_tabela") or 0) + conf["valor_venda"], 2)
    r["configurados"] = conf["configurados"]
    r["promob"] = xml  # a parte do Promob, para a próxima versão somar outros produtos sem contar duas vezes
    return r


# --- Projeto: módulos gerados pela configuração -------------------------------------------------------

def _ambiente(projeto: Projeto, nome: str) -> Ambiente:
    for a in projeto.ambientes:
        if a.nome == nome:
            return a
    a = Ambiente(nome=nome)
    projeto.ambientes.append(a)
    return a


def gerar_modulos(db: Session, projeto: Projeto, itens: list[dict]) -> int:
    """Cria no projeto os módulos congelados das configurações (peças e itens no formato do Promob)."""
    materiais = {m.codigo: m for m in db.scalars(select(Material).where(Material.empresa_id == projeto.empresa_id))}
    n = 0
    for it in itens:
        cfg = db.get(ConfiguracaoProduto, it["configuracao_id"])
        if cfg is None or cfg.empresa_id != projeto.empresa_id:
            raise ErroConfigurador(f"Configuração {it.get('codigo')} não encontrada", 404)
        m = cfg.modulo
        mod = Modulo(codigo=cfg.codigo, descricao=cfg.descricao[:200], largura_mm=m.get("largura_mm"),
                     altura_mm=m.get("altura_mm"), profundidade_mm=m.get("profundidade_mm"),
                     quantidade=int(it.get("quantidade") or 1), configuracao_id=cfg.id)
        _ambiente(projeto, it.get("ambiente") or "Produtos configurados").modulos.append(mod)
        for pc in m["pecas"]:
            mod.pecas.append(Peca(
                codigo=pc["codigo"], descricao=pc["descricao"], material=materiais.get(pc["material_codigo"]),
                material_codigo=pc["material_codigo"], comprimento_mm=pc["comprimento_mm"], largura_mm=pc["largura_mm"],
                espessura_mm=pc.get("espessura_mm"), quantidade=pc["quantidade"], veio=pc.get("veio", False),
                fita_c1=pc.get("fita_c1"), fita_c2=pc.get("fita_c2"), fita_l1=pc.get("fita_l1"), fita_l2=pc.get("fita_l2"),
                operacoes=pc.get("operacoes"), programa_usinagem=pc.get("programa_usinagem")))
        for ix in m["itens"]:
            mod.itens.append(ItemModulo(material=materiais.get(ix["material_codigo"]), material_codigo=ix["material_codigo"],
                                        descricao=ix["descricao"][:200], quantidade=ix["quantidade"], unidade=ix["unidade"][:10]))
        n += 1
    db.flush()
    return n


def preservar(projeto: Projeto) -> list[dict]:
    """Antes de reimportar o XML: guarda os módulos do configurador para devolvê-los depois."""
    return [{"configuracao_id": m.configuracao_id, "quantidade": m.quantidade, "ambiente": a.nome}
            for a in projeto.ambientes for m in a.modulos if m.configuracao_id]


def valores(db: Session, itens: list[dict]) -> tuple[float, float]:
    """Preço e custo de material congelados das configurações (× quantidade)."""
    preco = custo = 0.0
    for it in itens:
        cfg = db.get(ConfiguracaoProduto, it["configuracao_id"])
        if cfg is not None:
            q = int(it.get("quantidade") or 1)
            preco += (cfg.custo.get("preco_unitario") or 0) * q
            custo += (cfg.custo.get("material") or 0) * q
    return round(preco, 2), round(custo, 2)


# --- Acabamentos: sugestão de materiais pelo cadastro ------------------------------------------------

_TIPO_POR_COMPONENTE = (("FITA", "FITA"), ("BORDA", "FITA"), ("PERFIL", "PERFIL"), ("VIDRO", "VIDRO"),
                        ("ESPELHO", "VIDRO"), ("PUXADOR", None), ("CHAPA", "CHAPA"), ("MDF", "CHAPA"), ("MDP", "CHAPA"),
                        ("CAIXA", "CHAPA"), ("FRENTE", "CHAPA"), ("FUNDO", "CHAPA"), ("PORTA", "CHAPA"))


def _palavras(texto: str) -> set[str]:
    return {p for p in re.split(r"[^A-Z0-9]+", normalizar(texto).replace("_", " ")) if len(p) >= 2}


def sugerir(db: Session, empresa_id: int, acabamento: Acabamento) -> dict:
    """Para cada opção × componente sem material: os materiais do cadastro que mais combinam (tipo, espessura, nome).

    A engenharia confirma; ninguém digita código de matéria-prima um a um.
    """
    materiais = list(db.scalars(select(Material).where(Material.empresa_id == empresa_id)))
    out = {}
    for op in acabamento.opcoes:
        chave_op = _palavras(op["nome"]) | _palavras(op["codigo"])
        sugest = {}
        for comp in acabamento.componentes:
            if op.get("materiais", {}).get(comp):
                continue
            tipo = next((t for k, t in _TIPO_POR_COMPONENTE if k in comp), None)
            esp = re.search(r"(\d+(?:[.,]\d+)?)", comp)
            esp = float(esp.group(1).replace(",", ".")) if esp else None
            ranking = []
            for m in materiais:
                if tipo and m.tipo != tipo:
                    continue
                if esp and m.espessura_mm and abs(m.espessura_mm - esp) > 0.01:
                    continue
                nome = _palavras(m.descricao) | _palavras(m.codigo)
                comuns = chave_op & nome
                if not comuns:
                    continue
                ranking.append((len(comuns) / max(1, len(chave_op)), m))
            ranking.sort(key=lambda x: (-x[0], x[1].codigo))
            sugest[comp] = [{"codigo": m.codigo, "descricao": m.descricao, "confianca": round(s, 2)} for s, m in ranking[:3]]
        out[op["codigo"]] = sugest
    return out


# --- Setup da base: a biblioteca vai de uma fábrica para outra ---------------------------------------

CAMPOS_MATERIAL = ("codigo", "descricao", "tipo", "unidade", "espessura_mm", "comprimento_mm", "largura_mm", "custo_unitario")


def _materiais_citados(nos: list[NoProduto], acabs: list[Acabamento]) -> set[str]:
    codigos = set()
    for a in acabs:
        for o in a.opcoes:
            codigos.update(v for v in (o.get("materiais") or {}).values() if v)
    for n in nos:
        for c in n.componentes or []:
            for ref in [c.get("material"), *(c.get("fitas") or {}).values()]:
                if ref and not ref.startswith(("@", "=")):
                    codigos.add(ref)
    return codigos


def exportar(db: Session, empresa_id: int) -> dict:
    nos = list(db.scalars(select(NoProduto).where(NoProduto.empresa_id == empresa_id).order_by(NoProduto.id)))
    acabs = list(db.scalars(select(Acabamento).where(Acabamento.empresa_id == empresa_id).order_by(Acabamento.codigo)))
    por_id = {n.id: n.codigo for n in nos}
    cfg = config(db, empresa_id)
    citados = _materiais_citados(nos, acabs)
    mats = db.scalars(select(Material).where(Material.empresa_id == empresa_id, Material.codigo.in_(citados))) if citados else []
    return {
        "config": {"constantes": cfg.constantes or {}, "perda_perfil_pct": cfg.perda_perfil_pct,
                   "serra_perfil_mm": cfg.serra_perfil_mm, "markup_padrao": cfg.markup_padrao},
        "acabamentos": [{"codigo": a.codigo, "nome": a.nome, "componentes": a.componentes, "opcoes": a.opcoes} for a in acabs],
        "biblioteca": [{"codigo": n.codigo, "pai": por_id.get(n.pai_id), "tipo": n.tipo, "nome": n.nome, "ordem": n.ordem,
                        "ativo": n.ativo, "descricao_formula": n.descricao_formula, "perguntas": n.perguntas or [],
                        "componentes": n.componentes or [], "preco": n.preco, "observacao": n.observacao} for n in nos],
        "materiais": [{k: (m.tipo.value if k == "tipo" and hasattr(m.tipo, "value") else getattr(m, k)) for k in CAMPOS_MATERIAL}
                      for m in sorted(mats, key=lambda m: m.codigo)],
    }


def aplicar_setup(db: Session, empresa_id: int, dados: dict, usuario: str | None = None) -> list[str]:
    """Idempotente: casa pelo código e atualiza; nada é apagado. Materiais: só cria os que faltam."""
    from ..models import TipoMaterial

    mud: list[str] = []
    existentes_mat = set(db.scalars(select(Material.codigo).where(Material.empresa_id == empresa_id)))
    for m in dados.get("materiais") or []:
        codigo = str(m.get("codigo") or "").strip()[:60]
        if not codigo or codigo in existentes_mat:
            continue
        try:
            tipo = TipoMaterial(str(m.get("tipo") or "OUTRO").upper())
        except ValueError:
            tipo = TipoMaterial.OUTRO
        db.add(Material(empresa_id=empresa_id, codigo=codigo, descricao=str(m.get("descricao") or codigo)[:200], tipo=tipo,
                        unidade=str(m.get("unidade") or "UN")[:10], espessura_mm=m.get("espessura_mm"),
                        comprimento_mm=m.get("comprimento_mm"), largura_mm=m.get("largura_mm"),
                        custo_unitario=float(m.get("custo_unitario") or 0)))
        existentes_mat.add(codigo)
        mud.append(f"Novo material {codigo} · {m.get('descricao') or ''}".strip(" ·"))
    if dados.get("config"):
        c = config(db, empresa_id)
        novo = dados["config"]
        if novo.get("constantes") is not None:
            const = {normalizar(k): float(v) for k, v in novo["constantes"].items()}
            if const != (c.constantes or {}):
                mud.append(f"Constantes: {', '.join(f'{k}={formulas.formatar(v)}' for k, v in sorted(const.items()))}")
                c.constantes = const
        for k in ("perda_perfil_pct", "serra_perfil_mm", "markup_padrao"):
            if novo.get(k) is not None and float(novo[k]) != getattr(c, k):
                mud.append(f"{k}: {formulas.formatar(getattr(c, k))} → {formulas.formatar(float(novo[k]))}")
                setattr(c, k, float(novo[k]))
    acabs = {a.codigo: a for a in db.scalars(select(Acabamento).where(Acabamento.empresa_id == empresa_id))}
    for a in dados.get("acabamentos") or []:
        codigo = _cod(a.get("codigo") or "")
        comps, opcoes = limpar_opcoes_acabamento(a.get("componentes") or [], a.get("opcoes") or [])
        atual = acabs.get(codigo)
        if atual is None:
            atual = Acabamento(empresa_id=empresa_id, codigo=codigo, nome=str(a.get("nome") or codigo)[:160],
                               componentes=comps, opcoes=opcoes)
            db.add(atual)
            acabs[codigo] = atual
            mud.append(f"Novo acabamento {codigo} · {atual.nome} ({len(opcoes)} opções)")
        elif (atual.componentes, atual.opcoes, atual.nome) != (comps, opcoes, a.get("nome") or atual.nome):
            atual.componentes, atual.opcoes, atual.nome = comps, opcoes, str(a.get("nome") or atual.nome)[:160]
            mud.append(f"Acabamento {codigo} atualizado ({len(opcoes)} opções)")
    db.flush()
    nos = {n.codigo: n for n in db.scalars(select(NoProduto).where(NoProduto.empresa_id == empresa_id))}
    pendentes = list(dados.get("biblioteca") or [])
    codigos = [_cod(n.get("codigo") or "") for n in pendentes]
    _sem_repetidos(codigos, "item da biblioteca")
    feitos: set[str] = set()
    for _ in range(len(pendentes) + 1):  # pais antes dos filhos, em qualquer ordem no arquivo
        restantes = []
        for n in pendentes:
            codigo = _cod(n["codigo"])
            pai = _cod(n["pai"]) if n.get("pai") else None
            if pai and pai not in feitos and pai in codigos:
                restantes.append(n)
                continue
            if pai and pai not in nos:
                raise ErroConfigurador(f"Biblioteca: {codigo} está dentro de {pai}, que não existe")
            tipo = str(n.get("tipo") or "MODELO").upper()
            if tipo not in TIPOS_NO:
                raise ErroConfigurador(f"Biblioteca: tipo {tipo} inválido em {codigo}")
            try:
                campos = {"pai_id": nos[pai].id if pai else None, "tipo": tipo, "nome": str(n.get("nome") or codigo)[:160],
                          "ordem": int(n.get("ordem") or 0), "ativo": n.get("ativo", True) is not False,
                          "descricao_formula": n.get("descricao_formula") or None,
                          "perguntas": limpar_perguntas(n.get("perguntas")), "componentes": limpar_componentes(n.get("componentes")),
                          "preco": limpar_preco(n.get("preco")), "observacao": n.get("observacao")}
            except ErroConfigurador as e:
                raise ErroConfigurador(f"Biblioteca, {codigo}: {e}" + (f" — {'; '.join(e.detalhes)}" if e.detalhes else ""))
            atual = nos.get(codigo)
            if atual is None:
                atual = NoProduto(empresa_id=empresa_id, codigo=codigo, atualizado_por=usuario or "Setup da base", **campos)
                db.add(atual)
                db.flush()
                nos[codigo] = atual
                mud.append(f"Novo {tipo.lower()} {codigo} · {campos['nome']}")
            else:
                if any(getattr(atual, k) != v for k, v in campos.items()):
                    for k, v in campos.items():
                        setattr(atual, k, v)
                    atual.atualizado_por = usuario or "Setup da base"
                    mud.append(f"{tipo.title()} {codigo} atualizado")
            feitos.add(codigo)
        pendentes = restantes
        if not pendentes:
            break
    if pendentes:
        raise ErroConfigurador(f"Biblioteca com herança circular: {', '.join(_cod(n['codigo']) for n in pendentes)}")
    db.flush()
    return mud
