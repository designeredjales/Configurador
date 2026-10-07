from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import (
    CausaChamado,
    Categoria,
    Perfil,
    RegraCentro,
    StatusChamado,
    StatusMontagem,
    StatusOP,
    StatusProjeto,
    TipoChamado,
    TipoLancamento,
    TipoMaterial,
)
from .security import SENHA_MINIMA


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Empresa -----------------------------------------------------------------

class EmpresaIn(Schema):
    nome: str
    cnpj: str | None = None
    perda_chapa_pct: float = Field(15.0, ge=0, le=100)
    perda_fita_pct: float = Field(10.0, ge=0, le=100)
    chapa_comprimento_mm: float = Field(2750.0, gt=0)
    chapa_largura_mm: float = Field(1850.0, gt=0)
    serra_mm: float = Field(4.0, ge=0)
    refilo_mm: float = Field(10.0, ge=0)
    imposto_venda_pct: float = Field(0.0, ge=0, le=100)
    garantia_meses: int = Field(12, ge=0, le=120)
    caixa_max_modulos: int = Field(3, ge=1, le=50)


class EmpresaOut(EmpresaIn):
    id: int
    uf: str | None = None
    inscricao_estadual: str | None = None
    ncm_padrao: str = "94034000"
    cfop_interno: str = "5101"
    cfop_interestadual: str = "6101"
    csosn_padrao: str = "102"
    fiscal_ambiente: str = "homologacao"
    fiscal_token_configurado: bool = False  # o token em si nunca é devolvido


class EmpresaAtualizar(Schema):
    """Atualização parcial: só os campos enviados mudam."""
    nome: str | None = Field(None, min_length=2)
    cnpj: str | None = None
    perda_chapa_pct: float | None = Field(None, ge=0, le=100)
    perda_fita_pct: float | None = Field(None, ge=0, le=100)
    chapa_comprimento_mm: float | None = Field(None, gt=0)
    chapa_largura_mm: float | None = Field(None, gt=0)
    serra_mm: float | None = Field(None, ge=0)
    refilo_mm: float | None = Field(None, ge=0)
    imposto_venda_pct: float | None = Field(None, ge=0, le=100)
    garantia_meses: int | None = Field(None, ge=0, le=120)
    caixa_max_modulos: int | None = Field(None, ge=1, le=50)
    uf: str | None = Field(None, min_length=2, max_length=2)
    inscricao_estadual: str | None = None
    ncm_padrao: str | None = Field(None, pattern=r"^\d{4}\.?\d{2}\.?\d{2}$")
    cfop_interno: str | None = Field(None, pattern=r"^\d{4}$")
    cfop_interestadual: str | None = Field(None, pattern=r"^\d{4}$")
    csosn_padrao: str | None = Field(None, pattern=r"^\d{3}$")
    fiscal_ambiente: Literal["homologacao", "producao"] | None = None
    fiscal_token: str | None = None


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


class EsqueciIn(Schema):
    email: str


class RedefinirIn(Schema):
    token: str = Field(min_length=20)
    senha: str

    _senha = field_validator("senha")(_validar_senha)


class TrocarSenhaIn(Schema):
    senha_atual: str
    senha_nova: str

    _senha = field_validator("senha_nova")(_validar_senha)


class UsuarioIn(Schema):
    nome: str = Field(min_length=2)
    email: str
    senha: str
    perfil: Perfil
    funcoes: list[str] | None = None  # None = padrão do perfil

    _senha = field_validator("senha")(_validar_senha)
    _email = field_validator("email")(_validar_email)


class UsuarioAtualizar(Schema):
    nome: str | None = None
    perfil: Perfil | None = None
    ativo: bool | None = None
    senha: str | None = None
    funcoes: list[str] | None = None  # enviar null volta ao padrão do perfil

    _senha = field_validator("senha")(_validar_senha)


class UsuarioOut(Schema):
    id: int
    nome: str
    email: str
    perfil: Perfil
    ativo: bool
    ultimo_acesso: datetime | None
    funcoes_efetivas: list[str]
    funcoes_personalizadas: bool


class FuncaoOut(Schema):
    codigo: str
    modulo: str
    nome: str
    descricao: str


class CatalogoFuncoes(Schema):
    funcoes: list[FuncaoOut]
    padrao_por_perfil: dict[str, list[str]]


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
    logradouro: str | None = None
    numero: str | None = None
    complemento: str | None = None
    bairro: str | None = None
    cidade: str | None = None
    uf: str | None = Field(None, max_length=2)
    cep: str | None = None


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


class ProjetoAtualizar(Schema):
    nome: str | None = Field(None, min_length=2)
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
    valor_tabela: float | None = None
    valor_pedido: float | None = None
    valor_venda: float | None = None
    frete_orcado: float | None = None
    montagem_orcada: float | None = None
    condicao_pagamento: str | None = None
    parcelas_sugeridas: int | None = None
    entrada_sugerida: bool | None = None
    contrato_em: date | None = None
    liberado_em: datetime | None = None
    producao_concluida_em: datetime | None = None
    entregue_em: datetime | None = None


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
    prazo_pagamento_dias: int = Field(30, ge=0)


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


# --- Financeiro -----------------------------------------------------------------

class ContratoIn(Schema):
    valor_venda: float = Field(gt=0)
    parcelas: int = Field(ge=1, le=120)
    primeiro_vencimento: date


class LancamentoIn(Schema):
    tipo: TipoLancamento
    categoria: Categoria
    descricao: str = Field(min_length=2)
    valor: float = Field(gt=0)
    vencimento: date
    projeto_id: int | None = None
    fornecedor_id: int | None = None


class LancamentoOut(Schema):
    id: int
    tipo: TipoLancamento
    categoria: Categoria
    descricao: str
    valor: float
    vencimento: date
    pago_em: date | None
    valor_pago: float | None
    projeto_id: int | None
    projeto_codigo: str | None
    pedido_id: int | None
    fornecedor_nome: str | None
    cliente_nome: str | None
    situacao: str


class BaixaIn(Schema):
    data: date
    valor: float | None = Field(None, gt=0)


class DREObra(Schema):
    projeto_id: int
    codigo: str
    status: StatusProjeto
    receita: float
    impostos: float
    imposto_pct: float
    receita_liquida: float
    material: float
    material_base: str
    material_refugo: float = 0.0
    custos_diretos: dict[str, float]
    total_custos_diretos: float
    margem_contribuicao: float
    margem_pct: float
    orcado_frete: float | None
    orcado_montagem: float | None
    recebido: float
    a_receber: float
    contrato_em: date | None


class MesFluxo(Schema):
    mes: str
    receber_previsto: float
    pagar_previsto: float
    recebido: float
    pago: float
    saldo_mes: float
    saldo_acumulado: float


class FluxoCaixa(Schema):
    meses: list[MesFluxo]
    vencido_receber: float
    vencido_pagar: float


# --- NF-e ------------------------------------------------------------------------

class EmitirNotaIn(Schema):
    valor: float | None = Field(None, gt=0)
    descricao: str | None = Field(None, max_length=120)


class NotaOut(Schema):
    id: int
    projeto_id: int
    ref: str
    ambiente: str
    valor: float
    status: str
    numero: str | None
    serie: str | None
    chave: str | None
    url_danfe: str | None
    url_xml: str | None
    mensagem: str | None
    criado_em: datetime
    atualizado_em: datetime


# --- Conciliação bancária -------------------------------------------------------

class SugestaoConciliacao(Schema):
    lancamento_id: int
    descricao: str
    vencimento: date
    valor: float


class MovimentoBancarioOut(Schema):
    id: int
    data: date
    valor: float
    descricao: str
    situacao: str  # PENDENTE, CONCILIADO, IGNORADO
    lancamento_id: int | None
    lancamento_descricao: str | None
    sugestoes: list[SugestaoConciliacao]


class ConciliarIn(Schema):
    lancamento_id: int


class LancarMovimentoIn(Schema):
    categoria: Categoria
    descricao: str | None = None
    projeto_id: int | None = None


# --- Montagem e pós-obra --------------------------------------------------------

class MontagemIn(Schema):
    projeto_id: int
    data_inicio: date
    data_fim: date
    equipe: str = Field(min_length=2)
    endereco: str | None = None
    observacao: str | None = None


class ItemChecklistOut(Schema):
    id: int
    descricao: str
    ok: bool
    observacao: str | None
    conferido_por: str | None


class MontagemOut(Schema):
    id: int
    projeto_id: int
    projeto_codigo: str
    projeto_nome: str
    data_inicio: date
    data_fim: date
    equipe: str
    endereco: str | None
    observacao: str | None
    status: StatusMontagem
    producao_concluida: bool
    iniciada_em: datetime | None
    concluida_em: datetime | None
    recebido_por: str | None
    itens: list[ItemChecklistOut]


class ConferenciaIn(Schema):
    ok: bool
    observacao: str | None = None


class ConclusaoMontagemIn(Schema):
    recebido_por: str


class ChamadoIn(Schema):
    projeto_id: int
    tipo: TipoChamado
    descricao: str = Field(min_length=3)


class ChamadoAtualizar(Schema):
    agendado_para: date | None = None


class ResolucaoIn(Schema):
    causa: CausaChamado
    solucao: str
    custo: float = Field(0.0, ge=0)


class ChamadoOut(Schema):
    id: int
    numero: int
    projeto_id: int
    projeto_codigo: str
    projeto_nome: str
    tipo: TipoChamado
    descricao: str
    status: StatusChamado
    aberto_em: datetime
    agendado_para: date | None
    causa: CausaChamado | None
    solucao: str | None
    custo: float
    resolvido_em: datetime | None
    em_garantia: bool
    retrabalho: bool


# --- Controle de produção ---------------------------------------------------------

class OcorrenciaIn(Schema):
    codigo_barras: str
    centro_codigo: str
    motivo: str


class OcorrenciaOut(Schema):
    id: int
    tipo: str
    op_id: int
    op_numero: int
    projeto_codigo: str
    codigo_barras: str
    peca: str
    centro_codigo: str
    motivo: str
    custo_material: float
    nova_etiqueta: str | None
    usuario: str | None
    criado_em: datetime


class PecaConsulta(Schema):
    codigo_barras: str
    op_id: int
    op_numero: int
    lote_numero: int | None = None
    caixa_numero: int | None = None
    op_status: str = ""
    projeto_codigo: str
    ambiente: str
    modulo: str
    modulo_descricao: str = ""
    peca: str
    material_codigo: str
    medidas: str
    situacao: str
    proxima_etapa: str | None
    ultima_etapa: str | None
    ultima_baixa_em: datetime | None
    ultimo_operador: str | None
    reposicao: bool


class ConsultaPecas(Schema):
    total: int
    por_situacao: dict[str, int]
    pecas: list[PecaConsulta]


class BaixaOut(Schema):
    quando: datetime
    centro_codigo: str
    operador: str | None
    codigo_barras: str
    peca: str
    op_numero: int


class HistoricoBaixas(Schema):
    total: int
    por_operador: dict[str, int]
    por_centro: dict[str, int]
    baixas: list[BaixaOut]


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
    op_numero: int | None = None
    titulo: str = ""
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
    status: str = "ATIVA"
    reposicao: bool = False
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
    lote_id: int | None = None
    lote_numero: int | None = None
    motivo_cancelamento: str | None = None
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


# --- Lotes de produção ---------------------------------------------------------

class LoteIn(Schema):
    descricao: str = Field(min_length=2, max_length=120)
    projeto_ids: list[int] = Field(min_length=1)
    prioridade: int = Field(3, ge=1, le=5)
    data_entrega: date | None = None


class LoteAdicionar(Schema):
    projeto_ids: list[int] = Field(min_length=1)


class LoteProjeto(Schema):
    projeto_id: int
    codigo: str
    nome: str
    cliente: str | None
    op_id: int
    op_numero: int
    op_status: str
    pecas: int
    progresso_pct: float


class LoteOut(Schema):
    id: int
    numero: int
    descricao: str
    status: str
    data_entrega: date | None
    criado_em: datetime
    criado_por: str | None
    total_pecas: int
    etapas_total: int
    etapas_concluidas: int
    progresso_pct: float
    projetos: list[LoteProjeto]


# --- Expedição (caixa master) ----------------------------------------------------

class ItemCaixaOut(Schema):
    codigo_barras: str
    peca: str
    modulo: str
    modulo_descricao: str
    medidas: str
    adicionado_em: datetime
    usuario: str | None


class CaixaOut(Schema):
    id: int
    numero: int
    codigo_barras: str
    projeto_id: int
    projeto_codigo: str
    projeto_nome: str
    cliente: str | None
    ambiente: str
    status: str
    volume: int
    volumes_projeto: int
    modulos: list[str]
    total_itens: int
    itens: list[ItemCaixaOut]
    criado_em: datetime
    criado_por: str | None
    fechada_em: datetime | None
    expedida_em: datetime | None


class BipeCaixaIn(Schema):
    codigo_barras: str = Field(min_length=1, max_length=40)
    caixa_id: int | None = None
    nova_caixa: bool = False


class BipeCaixaOut(Schema):
    acao: str  # ADICIONADA ou CAIXA_SELECIONADA
    mensagem: str
    caixa: CaixaOut
    embalagem_apontada: bool = False
    projeto_embaladas: int = 0
    projeto_total: int = 0


class CarregarIn(Schema):
    codigo_barras: str = Field(min_length=1, max_length=40)


class PendenteExpedicao(Schema):
    codigo_barras: str
    ambiente: str
    modulo: str
    peca: str
    situacao: str
    proxima_etapa: str | None


class ExpedicaoProjeto(Schema):
    projeto_id: int
    codigo: str
    nome: str
    total_pecas: int
    embaladas: int
    em_caixas_fechadas: int
    expedidas: int
    pronto_para_expedir: bool
    pendentes: list[PendenteExpedicao]
    caixas: list[CaixaOut]
