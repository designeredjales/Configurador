"""Linguagem de fórmulas do configurador de produtos.

Aceita a sintaxe do Promob Catalog e a do configurador da Focco, para a engenharia escrever como já sabe:

    $PW$ - 32                         medida de quem contém o componente (Catalog: $PW$ $PH$ $PD$, $W$ $H$ $D$)
    [LARGURA] - 32                    resposta de uma pergunta (Focco: [VARIAVEL]; também $LARGURA$ ou LARGURA)
    [PROFUNDIDADE] * %TAXACOLA%       constante cadastrada (Focco: %CONSTANTE%)
    @CORPO.espessura                  informação do acabamento escolhido (Catalog: @CORPO(espessura)@)
    ($PH$ <= 700) ? 2 : 3             condicional (também se(cond; sim; não) e faixa(x, 700, 2, 1300, 3, 4))
    [OPCAO FRENTE] = "SEM FRENTE"     igualdade da Focco (= ou ==), AND/OR/NOT ou && || !

Regras em várias linhas (Focco): cada linha `condição >> valor` vale quando a condição é verdadeira; a primeira
que valer decide. Uma linha sem `>>` é o valor padrão. Tudo depois de `;` na linha é comentário.

O avaliador não executa código: só números, textos, variáveis, operadores e as funções da lista abaixo.
"""
import math
import re
import unicodedata
from functools import lru_cache


class ErroFormula(ValueError):
    pass


def normalizar(nome: str) -> str:
    """Nome de variável sem acento, maiúsculo, espaços viram _ (COR DO CORPO → COR_DO_CORPO)."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    s = re.sub(r"\s+", "_", s.strip().upper())
    if s.startswith("D.") and len(s) > 2:  # variável proposta do Catalog: $D.CODE$
        s = s[2:]
    return {"P.W": "PW", "P.H": "PH", "P.D": "PD"}.get(s, s)


# --- Léxico ------------------------------------------------------------------------------------------

_ASPAS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
_OPS = (">>", "<=", ">=", "==", "!=", "<>", "&&", "||", "=", "<", ">", "+", "-", "*", "/", "(", ")", ",", ";", "?", ":", "!")
_PALAVRAS = {"AND": "&&", "OR": "||", "NOT": "!"}


def _tokens(texto: str) -> list[tuple[str, object, int]]:
    s = texto.translate(_ASPAS)
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and s[i + 1].isdigit()):
            m = re.match(r"\d*\.?\d+(?:[eE][-+]?\d+)?", s[i:])
            out.append(("num", float(m.group()), i))
            i += m.end()
            continue
        if c in "\"'":
            fim = s.find(c, i + 1)
            if fim < 0:
                raise ErroFormula(f"texto sem fechar aspas (posição {i + 1})")
            out.append(("txt", s[i + 1:fim], i))
            i = fim + 1
            continue
        if c in "$[%":
            fecha = {"$": "$", "[": "]", "%": "%"}[c]
            fim = s.find(fecha, i + 1)
            if fim < 0 or fim == i + 1:
                raise ErroFormula(f"'{c}' sem fechar com '{fecha}' (posição {i + 1})")
            nome = s[i + 1:fim]
            out.append(("const" if c == "%" else "var", normalizar(nome), i))
            i = fim + 1
            continue
        if c == "@":
            m = re.match(r"@([A-Za-z_][\w]*)(?:\(([\w ]+)\)@?|\.([A-Za-z_]\w*))?", s[i:])
            if m and (m.group(2) or m.group(3)):
                out.append(("info", (normalizar(m.group(1)), (m.group(2) or m.group(3)).strip().lower()), i))
                i += m.end()
                continue
            if s[i + 1:i + 2] == "(":  # @( cond ? a : b ) do Catalog é só um parêntese
                i += 1
                continue
            raise ErroFormula(f"use @ACABAMENTO.informacao (posição {i + 1})")
        if c.isalpha() or c == "_":
            m = re.match(r"[A-Za-z_][\w.]*", s[i:])
            palavra = m.group()
            if palavra.upper() in _PALAVRAS:
                out.append(("op", _PALAVRAS[palavra.upper()], i))
            elif s[i + m.end():].lstrip().startswith("("):
                out.append(("func", palavra.lower().removeprefix("math."), i))
            else:
                out.append(("var", normalizar(palavra), i))
            i += m.end()
            continue
        for op in _OPS:
            if s.startswith(op, i):
                out.append(("op", {"<>": "!=", "=": "=="}.get(op, op), i))
                i += len(op)
                break
        else:
            raise ErroFormula(f"caractere inesperado '{c}' (posição {i + 1})")
    return out


# --- Sintaxe (árvore de nós em tuplas) ---------------------------------------------------------------

class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def ver(self, *ops):
        if self.i < len(self.t) and self.t[self.i][0] == "op" and self.t[self.i][1] in ops:
            return self.t[self.i][1]
        return None

    def comer(self, op):
        if not self.ver(op):
            pos = self.t[self.i][2] + 1 if self.i < len(self.t) else "fim"
            raise ErroFormula(f"esperava '{op}' (posição {pos})")
        self.i += 1

    def tudo(self):
        no = self.ternario()
        if self.i < len(self.t):
            tipo, valor, pos = self.t[self.i]
            raise ErroFormula(f"'{valor}' inesperado (posição {pos + 1})")
        return no

    def ternario(self):
        cond = self.ou()
        if self.ver("?"):
            self.i += 1
            sim = self.ternario()
            self.comer(":")
            nao = self.ternario()
            return ("se", cond, sim, nao)
        return cond

    def ou(self):
        no = self.e()
        while self.ver("||"):
            self.i += 1
            no = ("ou", no, self.e())
        return no

    def e(self):
        no = self.comparacao()
        while self.ver("&&"):
            self.i += 1
            no = ("e", no, self.comparacao())
        return no

    def comparacao(self):
        no = self.soma()
        while (op := self.ver("==", "!=", "<", "<=", ">", ">=")):
            self.i += 1
            no = ("cmp", op, no, self.soma())
        return no

    def soma(self):
        no = self.produto()
        while (op := self.ver("+", "-")):
            self.i += 1
            no = ("arit", op, no, self.produto())
        return no

    def produto(self):
        no = self.unario()
        while (op := self.ver("*", "/")):
            self.i += 1
            no = ("arit", op, no, self.unario())
        return no

    def unario(self):
        if self.ver("-"):
            self.i += 1
            return ("neg", self.unario())
        if self.ver("+"):
            self.i += 1
            return self.unario()
        if self.ver("!"):
            self.i += 1
            return ("nao", self.unario())
        return self.primario()

    def primario(self):
        if self.i >= len(self.t):
            raise ErroFormula("fórmula termina no meio de uma expressão")
        tipo, valor, pos = self.t[self.i]
        self.i += 1
        if tipo in ("num", "txt"):
            return ("lit", valor)
        if tipo == "var":
            return ("var", valor)
        if tipo == "const":
            return ("const", valor)
        if tipo == "info":
            return ("info", *valor)
        if tipo == "func":
            if valor not in FUNCOES:
                raise ErroFormula(f"função '{valor}' não existe (posição {pos + 1})")
            self.comer("(")
            args = []
            if not self.ver(")"):
                args.append(self.ternario())
                while self.ver(",", ";"):
                    self.i += 1
                    args.append(self.ternario())
            self.comer(")")
            return ("func", valor, args)
        if tipo == "op" and valor == "(":
            no = self.ternario()
            self.comer(")")
            return no
        raise ErroFormula(f"'{valor}' inesperado (posição {pos + 1})")


def _sem_comentario(linha: str) -> str:
    """Corta a linha no primeiro ; fora de aspas e fora de parênteses (o ; separa argumentos em se(a; b; c))."""
    dentro, nivel = None, 0
    for i, c in enumerate(linha):
        if dentro:
            if c == dentro:
                dentro = None
        elif c in "\"'“”":
            dentro = '"' if c in "“”" else c
        elif c == "(":
            nivel += 1
        elif c == ")":
            nivel -= 1
        elif c == ";" and nivel <= 0:
            return linha[:i]
    return linha


@lru_cache(maxsize=4096)
def compilar(texto: str) -> tuple:
    """Lista de regras (condição ou None, expressão). Erro de sintaxe vira ErroFormula com a posição."""
    regras = []
    for linha in str(texto).splitlines():
        linha = _sem_comentario(linha).strip()
        if not linha:
            continue
        toks = _tokens(linha)
        partes, atual = [], []
        for t in toks:
            if t[0] == "op" and t[1] == ">>":
                partes.append(atual)
                atual = []
            else:
                atual.append(t)
        partes.append(atual)
        if len(partes) > 2:
            raise ErroFormula("use um só '>>' por linha (condição >> valor)")
        if any(not p for p in partes):
            raise ErroFormula("'>>' precisa de condição antes e valor depois")
        exprs = [_Parser(p).tudo() for p in partes]
        regras.append((exprs[0], exprs[1]) if len(exprs) == 2 else (None, exprs[0]))
    if not regras:
        raise ErroFormula("fórmula vazia")
    return tuple(regras)


def validar(texto: str | None) -> str | None:
    """Mensagem do erro de sintaxe, ou None se a fórmula está bem escrita (vazia também está)."""
    if texto is None or not str(texto).strip():
        return None
    try:
        compilar(str(texto))
    except ErroFormula as e:
        return str(e)
    return None


def nomes_usados(texto: str) -> set[str]:
    """Variáveis citadas na fórmula (para conferir o cadastro)."""
    out = set()

    def visitar(no):
        if not isinstance(no, tuple):
            return
        if no[0] == "var":
            out.add(no[1])
        for x in no[1:]:
            if isinstance(x, tuple):
                visitar(x)
            elif isinstance(x, list):
                for y in x:
                    visitar(y)
    for cond, expr in compilar(texto):
        visitar(cond)
        visitar(expr)
    return out


# --- Avaliação --------------------------------------------------------------------------------------

def verdadeiro(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip().upper() not in ("", "N", "NAO", "NÃO", "FALSE", "0")
    return bool(v)


def _numero(v, onde: str):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", "."))
        except ValueError:
            pass
    if v is None:
        raise ErroFormula(f"{onde}: valor vazio numa conta (pergunta sem resposta ou oculta?)")
    raise ErroFormula(f"{onde}: '{v}' não é número")


def _texto_puro(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        float(v.replace(",", "."))
        return False
    except ValueError:
        return True


def _comparar(op, a, b):
    if a is None or b is None:
        iguais = a is None and b is None
        if op == "==":
            return iguais
        if op == "!=":
            return not iguais
        return False
    na = nb = None
    try:
        na, nb = _numero(a, ""), _numero(b, "")
    except ErroFormula:
        na = nb = None
    if na is not None and nb is not None:
        a, b = na, nb
    else:
        a, b = str(a).strip().upper(), str(b).strip().upper()
    return {"==": a == b, "!=": a != b, "<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def _arred(x, casas=0):
    f = 10 ** int(casas)
    return math.floor(abs(x) * f + 0.5) / f * (1 if x >= 0 else -1)


def _faixa(x, *pares):
    """faixa(x, limite1, valor1, limite2, valor2, ..., padrão): valor da primeira faixa com x <= limite."""
    if len(pares) < 1:
        raise ErroFormula("faixa(x, limite, valor, ..., padrão)")
    padrao = pares[-1] if len(pares) % 2 else None
    for i in range(0, len(pares) - 1, 2):
        if x <= pares[i]:
            return pares[i + 1]
    return padrao


FUNCOES = {
    "round": (_arred, 1, 2), "arred": (_arred, 1, 2), "ceil": (math.ceil, 1, 1), "teto": (math.ceil, 1, 1),
    "floor": (math.floor, 1, 1), "piso": (math.floor, 1, 1), "abs": (abs, 1, 1), "sqrt": (math.sqrt, 1, 1),
    "raiz": (math.sqrt, 1, 1), "pow": (math.pow, 2, 2), "pot": (math.pow, 2, 2), "min": (min, 1, 50),
    "max": (max, 1, 50), "mod": (math.fmod, 2, 2), "sin": (math.sin, 1, 1), "cos": (math.cos, 1, 1),
    "acos": (math.acos, 1, 1), "atan": (math.atan, 1, 1), "atan2": (math.atan2, 2, 2), "exp": (math.exp, 1, 1),
    "log": (math.log, 1, 1), "faixa": (_faixa, 2, 41), "se": (None, 2, 3), "if": (None, 2, 3),
    "contem": (None, 2, 2), "texto": (None, 1, 1),
}


class Ambiente:
    """O que a fórmula enxerga. O motor do configurador sobrescreve `variavel`, `constante` e `info`."""

    def variavel(self, nome: str):
        raise ErroFormula(f"variável '{nome}' não existe")

    def constante(self, nome: str):
        raise ErroFormula(f"constante '%{nome}%' não cadastrada")

    def info(self, acabamento: str, campo: str):
        raise ErroFormula(f"acabamento '{acabamento}' não existe")


def _ev(no, amb: Ambiente):
    k = no[0]
    if k == "lit":
        return no[1]
    if k == "var":
        return amb.variavel(no[1])
    if k == "const":
        return amb.constante(no[1])
    if k == "info":
        return amb.info(no[1], no[2])
    if k == "neg":
        return -_numero(_ev(no[1], amb), "sinal de menos")
    if k == "nao":
        return not verdadeiro(_ev(no[1], amb))
    if k == "e":
        return verdadeiro(_ev(no[1], amb)) and verdadeiro(_ev(no[2], amb))
    if k == "ou":
        return verdadeiro(_ev(no[1], amb)) or verdadeiro(_ev(no[2], amb))
    if k == "se":
        return _ev(no[2], amb) if verdadeiro(_ev(no[1], amb)) else _ev(no[3], amb)
    if k == "cmp":
        return _comparar(no[1], _ev(no[2], amb), _ev(no[3], amb))
    if k == "arit":
        a, b = _ev(no[2], amb), _ev(no[3], amb)
        if no[1] == "+" and (_texto_puro(a) or _texto_puro(b)):  # "porta " + @FRENTE.nome junta os textos
            return formatar(a) + formatar(b)
        a, b = _numero(a, f"conta '{no[1]}'"), _numero(b, f"conta '{no[1]}'")
        if no[1] == "+":
            return a + b
        if no[1] == "-":
            return a - b
        if no[1] == "*":
            return a * b
        if b == 0:
            raise ErroFormula("divisão por zero")
        return a / b
    if k == "func":
        nome, args = no[1], no[2]
        f, minimo, maximo = FUNCOES[nome]
        if not minimo <= len(args) <= maximo:
            raise ErroFormula(f"{nome}() recebe de {minimo} a {maximo} valores")
        if nome in ("se", "if"):
            if verdadeiro(_ev(args[0], amb)):
                return _ev(args[1], amb)
            return _ev(args[2], amb) if len(args) > 2 else None
        vals = [_ev(a, amb) for a in args]
        if nome == "contem":
            return str(vals[1] or "").upper() in str(vals[0] or "").upper()
        if nome == "texto":
            return formatar(vals[0])
        nums = [_numero(v, f"{nome}()") for v in vals]
        try:
            return float(f(*nums))
        except (ValueError, OverflowError) as e:
            raise ErroFormula(f"{nome}(): {e}") from e
    raise ErroFormula(f"nó desconhecido {k}")


def avaliar(texto: str, amb: Ambiente):
    """Valor da fórmula. Regras com >> que não valem e nenhum padrão: None (sem valor)."""
    for cond, expr in compilar(str(texto)):
        if cond is None or verdadeiro(_ev(cond, amb)):
            return _ev(expr, amb)
    return None


def formatar(v) -> str:
    """Número no formato da descrição: 600 → '600', 0.2440 → '0,244'; texto como está; vazio some."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "SIM" if v else "NÃO"
    if isinstance(v, (int, float)):
        if float(v).is_integer():
            return str(int(v))
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    return str(v)


_CHAVES = re.compile(r"\{([^{}]+)\}")


def modelo_texto(texto: str, amb: Ambiente) -> str:
    """Monta a descrição: 'Balcão {[LARGURA]}x{[PROFUNDIDADE]} {@CORPO.nome}'. Valor vazio some sem deixar espaço duplo."""
    def troca(m):
        return formatar(avaliar(m.group(1), amb))
    s = _CHAVES.sub(troca, texto or "")
    s = re.sub(r"\s{2,}", " ", s).strip()
    return re.sub(r"\s+([,.;:)])", r"\1", s)


def erros_modelo_texto(texto: str | None) -> str | None:
    for m in _CHAVES.finditer(texto or ""):
        erro = validar(m.group(1))
        if erro:
            return f"{{{m.group(1)}}}: {erro}"
    return None
