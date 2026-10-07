from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import RegraCentro, StatusOP, StatusProjeto, TipoMaterial


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


# --- PCP ---------------------------------------------------------------------

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
    operador: str | None = None


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
