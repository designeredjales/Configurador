from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import Perfil, RegraCentro, StatusOP, StatusProjeto, TipoMaterial
from .security import SENHA_MINIMA


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Empresa -----------------------------------------------------------------

class EmpresaIn(Schema):
    nome: str
    cnpj: str | None = None
    perda_chapa_pct: float = 15.0
    perda_fita_pct: float = 10.0


class EmpresaOut(EmpresaIn):
    id: int


# --- Acesso -------------------------------------------------------------------

def _validar_senha(senha: str | None) -> str | None:
    if senha is not None and len(senha) < SENHA_MINIMA:
        raise ValueError(f"A senha precisa ter pelo menos {SENHA_MINIMA} caracteres.")
    return senha


def _validar_email(email: str) -> str:
    email = email.strip()
    if "@" not in email or "." not in email.split("@")[-1] or " " in email:
        raise ValueError("E-mail inválido.")
    return email


class RegistroIn(Schema):
    empresa: str = Field(min_length=2)
    cnpj: str | None = None
    nome: str = Field(min_length=2)
    email: str
    senha: str

    _senha = field_validator("senha")(_validar_senha)
    _email = field_validator("email")(_validar_email)


class LoginIn(Schema):
    email: str
    senha: str


class UsuarioIn(Schema):
    nome: str = Field(min_length=2)
    email: str
    senha: str
    perfil: Perfil

    _senha = field_validator("senha")(_validar_senha)
    _email = field_validator("email")(_validar_email)


class UsuarioAtualizar(Schema):
    nome: str | None = None
    perfil: Perfil | None = None
    ativo: bool | None = None
    senha: str | None = None

    _senha = field_validator("senha")(_validar_senha)


class UsuarioOut(Schema):
    id: int
    nome: str
    email: str
    perfil: Perfil
    ativo: bool
    ultimo_acesso: datetime | None


class EmpresaResumo(Schema):
    id: int
    nome: str


class Sessao(Schema):
    token: str
    usuario: UsuarioOut
    empresa: EmpresaResumo


# --- Cadastros ---------------------------------------------------------------

class ClienteIn(Schema):
    nome: str
    documento: str | None = None
    telefone: str | None = None
    email: str | None = None
    cidade: str | None = None


class ClienteOut(ClienteIn):
    id: int


class MaterialIn(Schema):
    codigo: str
    descricao: str
    tipo: TipoMaterial
    unidade: str = "UN"
    espessura_mm: float | None = None
    comprimento_mm: float | None = None
    largura_mm: float | None = None
    custo_unitario: float = 0.0
    estoque_minimo: float = 0.0
    fornecedor_id: int | None = None


class MaterialOut(MaterialIn):
    id: int


class CentroIn(Schema):
    codigo: str
    nome: str
    sequencia: int
    regra: RegraCentro = RegraCentro.TODAS
    ativo: bool = True


class CentroOut(CentroIn):
    id: int


# --- Engenharia --------------------------------------------------------------

class PecaOut(Schema):
    id: int
    codigo: str
    descricao: str
    material_codigo: str
    material_id: int | None
    comprimento_mm: float
    largura_mm: float
    espessura_mm: float | None
    quantidade: int
    veio: bool
    fita_c1: str | None
    fita_c2: str | None
    fita_l1: str | None
    fita_l2: str | None
    fita_codigo: str | None
    fita_metros: float | None
    programa_usinagem: str | None
    operacoes: str | None


class ItemModuloOut(Schema):
    id: int
    material_codigo: str
    material_id: int | None
    descricao: str
    quantidade: float
    unidade: str


class ModuloOut(Schema):
    id: int
    codigo: str
    descricao: str
    largura_mm: float | None
    altura_mm: float | None
    profundidade_mm: float | None
    quantidade: int
    pecas: list[PecaOut]
    itens: list[ItemModuloOut]


class AmbienteOut(Schema):
    id: int
    nome: str
    modulos: list[ModuloOut]


class ProjetoIn(Schema):
    codigo: str
    nome: str
    cliente_id: int | None = None
    data_entrega: date | None = None


class ProjetoResumo(Schema):
    id: int
    codigo: str
    nome: str
    cliente_id: int | None
    status: StatusProjeto
    origem: str
    data_entrega: date | None
    criado_em: datetime


class ProjetoOut(ProjetoResumo):
    ambientes: list[AmbienteOut]


class ResultadoImportacao(Schema):
    projeto_id: int
    origem: str = "CSV"
    cliente: str | None = None
    materiais_criados: list[str] = []
    ambientes: int
    modulos: int
    pecas: int
    itens: int
    avisos: list[str]


class LinhaConsumo(Schema):
    material_codigo: str
    descricao: str
    tipo: str
    unidade: str
    quantidade_liquida: float
    quantidade_com_perda: float
    quantidade_compra: float
    custo_unitario: float
    custo_total: float


class ConsumoProjeto(Schema):
    projeto_id: int
    chapas: list[LinhaConsumo]
    fitas: list[LinhaConsumo]
    itens: list[LinhaConsumo]
    custo_material_total: float
    total_pecas: int
    pendencias: list[str]


# --- Compras e estoque ------------------------------------------------------

class FornecedorIn(Schema):
    nome: str = Field(min_length=2)
    documento: str | None = None
    telefone: str | None = None
    email: str | None = None
    prazo_dias: int = Field(7, ge=0)


class FornecedorOut(FornecedorIn):
    id: int


class ItemPedidoIn(Schema):
    material_id: int
    quantidade: float = Field(gt=0)
    custo_unitario: float | None = Field(None, ge=0)


class PedidoIn(Schema):
    fornecedor_id: int
    previsao: date | None = None
    observacao: str | None = None
    itens: list[ItemPedidoIn] = Field(min_length=1)


class ItemPedidoOut(Schema):
    id: int
    material_id: int
    material_codigo: str
    descricao: str
    unidade: str
    quantidade: float
    recebido: float
    pendente: float
    custo_unitario: float


class PedidoOut(Schema):
    id: int
    numero: int
    fornecedor_id: int
    fornecedor_nome: str
    status: str
    previsao: date | None
    observacao: str | None
    criado_em: datetime
    total: float
    itens: list[ItemPedidoOut]


class RecebimentoItem(Schema):
    item_id: int
    quantidade: float


class RecebimentoIn(Schema):
    itens: list[RecebimentoItem] = Field(min_length=1)


class PosicaoEstoque(Schema):
    material_id: int
    codigo: str
    descricao: str
    tipo: str
    unidade: str
    saldo: float
    reservado: float
    em_pedido: float
    disponivel: float
    estoque_minimo: float
    sugestao_compra: float
    custo_unitario: float
    fornecedor_id: int | None


class InventarioIn(Schema):
    material_id: int
    quantidade_contada: float = Field(ge=0)
    observacao: str | None = None


class MovimentoOut(Schema):
    id: int
    material_codigo: str
    quantidade: float
    custo_unitario: float
    origem: str
    referencia: str | None
    observacao: str | None
    usuario: str | None
    criado_em: datetime


# --- PCP ---------------------------------------------------------------------

class PosicaoCorte(Schema):
    ref: str
    descricao: str
    x: float
    y: float
    comprimento: float
    largura: float
    girada: bool


class ChapaCorte(Schema):
    numero: int
    aproveitamento_pct: float
    pecas: list[PosicaoCorte]


class PlanoMaterial(Schema):
    material_codigo: str
    descricao: str
    espessura_mm: float | None
    chapa_comprimento_mm: float
    chapa_largura_mm: float
    medida_padrao: bool
    total_pecas: int
    total_chapas: int
    aproveitamento_pct: float
    chapas: list[ChapaCorte]
    nao_cabem: list[str]


class PlanoCorte(Schema):
    op_numero: int
    serra_mm: float
    refilo_mm: float
    total_chapas: int
    materiais: list[PlanoMaterial]


class GerarOPIn(Schema):
    prioridade: int = Field(3, ge=1, le=5)
    data_entrega: date | None = None


class EtapaOut(Schema):
    centro_codigo: str
    sequencia: int
    concluida_em: datetime | None
    operador: str | None


class UnidadeOut(Schema):
    codigo_barras: str
    sequencial: int
    peca_codigo: str
    peca_descricao: str
    modulo: str
    ambiente: str
    material_codigo: str
    comprimento_mm: float
    largura_mm: float
    etapas: list[EtapaOut]


class OPResumo(Schema):
    id: int
    numero: int
    projeto_id: int
    projeto_nome: str
    status: StatusOP
    prioridade: int
    data_entrega: date | None
    criada_em: datetime
    total_unidades: int
    etapas_total: int
    etapas_concluidas: int
    progresso_pct: float


class OPDetalhe(OPResumo):
    unidades: list[UnidadeOut]


class ApontamentoIn(Schema):
    codigo_barras: str
    centro_codigo: str


class ApontamentoOut(Schema):
    codigo_barras: str
    peca: str
    centro_codigo: str
    proxima_etapa: str | None
    op_numero: int
    op_status: StatusOP
    op_progresso_pct: float


class FilaCentro(Schema):
    centro_codigo: str
    centro_nome: str
    na_fila: int
    concluidas_hoje: int


class Painel(Schema):
    ops_abertas: int
    ops_em_producao: int
    ops_atrasadas: int
    centros: list[FilaCentro]
    ops: list[OPResumo]
