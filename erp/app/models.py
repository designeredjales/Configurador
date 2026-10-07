"""Modelo de dados do ERP Moveleiro (núcleo Engenharia + PCP).

Toda entidade de negócio carrega `empresa_id`: o banco é multiempresa (SaaS)
desde o primeiro dia.
"""
from datetime import date, datetime
from enum import Enum

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


OPERACOES_USINAGEM = {"FURAR", "RASGO", "USINAR", "USINAGEM", "FRESAR", "CNC"}


def agora() -> datetime:
    return datetime.now()


class TipoMaterial(str, Enum):
    CHAPA = "CHAPA"
    FITA = "FITA"
    FERRAGEM = "FERRAGEM"
    ACESSORIO = "ACESSORIO"
    OUTRO = "OUTRO"


class StatusProjeto(str, Enum):
    ORCAMENTO = "ORCAMENTO"
    APROVADO = "APROVADO"
    ENGENHARIA = "ENGENHARIA"
    LIBERADO = "LIBERADO"
    PRODUCAO = "PRODUCAO"
    CONCLUIDO = "CONCLUIDO"   # produção concluída
    ENTREGUE = "ENTREGUE"     # montado e entregue ao cliente
    CANCELADO = "CANCELADO"


class StatusOP(str, Enum):
    ABERTA = "ABERTA"
    EM_PRODUCAO = "EM_PRODUCAO"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


class Perfil(str, Enum):
    ADMIN = "ADMIN"            # tudo, inclusive usuários
    GESTOR = "GESTOR"          # engenharia + PCP + cadastros
    ENGENHARIA = "ENGENHARIA"  # projetos, importação, liberação, materiais
    PCP = "PCP"                # ordens de produção, centros, apontamento
    COMPRAS = "COMPRAS"        # fornecedores, pedidos, recebimento, estoque
    FINANCEIRO = "FINANCEIRO"  # contratos, contas a pagar e receber, DRE
    MONTAGEM = "MONTAGEM"      # agenda de montagem, checklist de entrega, assistência
    OPERADOR = "OPERADOR"      # apontamento e consulta


class StatusPedido(str, Enum):
    RASCUNHO = "RASCUNHO"
    ENVIADO = "ENVIADO"
    PARCIAL = "PARCIAL"
    RECEBIDO = "RECEBIDO"
    CANCELADO = "CANCELADO"


class OrigemMovimento(str, Enum):
    RECEBIMENTO = "RECEBIMENTO"
    CONSUMO = "CONSUMO"        # baixa da reserva quando o projeto conclui
    INVENTARIO = "INVENTARIO"  # ajuste de contagem física
    REFUGO = "REFUGO"          # material perdido em peça refugada


class TipoLancamento(str, Enum):
    RECEBER = "RECEBER"
    PAGAR = "PAGAR"


class Categoria(str, Enum):
    VENDA = "VENDA"
    MATERIAL = "MATERIAL"
    MAO_DE_OBRA = "MAO_DE_OBRA"
    FRETE = "FRETE"
    MONTAGEM = "MONTAGEM"
    COMISSAO = "COMISSAO"
    IMPOSTO = "IMPOSTO"
    DESPESA_FIXA = "DESPESA_FIXA"
    ASSISTENCIA = "ASSISTENCIA"
    OUTROS = "OUTROS"


class StatusMontagem(str, Enum):
    AGENDADA = "AGENDADA"
    EM_ANDAMENTO = "EM_ANDAMENTO"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


class TipoChamado(str, Enum):
    GARANTIA = "GARANTIA"
    AJUSTE = "AJUSTE"
    DANO = "DANO"
    PECA_FALTANTE = "PECA_FALTANTE"
    OUTRO = "OUTRO"


class CausaChamado(str, Enum):
    """Causa raiz. As internas (todas menos CLIENTE) contam como retrabalho."""
    PRODUCAO = "PRODUCAO"
    PROJETO = "PROJETO"
    MONTAGEM = "MONTAGEM"
    MATERIAL = "MATERIAL"
    CLIENTE = "CLIENTE"


class StatusChamado(str, Enum):
    ABERTO = "ABERTO"
    AGENDADO = "AGENDADO"
    RESOLVIDO = "RESOLVIDO"


class RegraCentro(str, Enum):
    """Quando uma peça passa pelo centro de trabalho."""
    TODAS = "TODAS"
    COM_FITA = "COM_FITA"
    COM_USINAGEM = "COM_USINAGEM"


class Empresa(Base):
    __tablename__ = "empresas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(200))
    cnpj: Mapped[str | None] = mapped_column(String(20))
    perda_chapa_pct: Mapped[float] = mapped_column(Float, default=15.0)
    perda_fita_pct: Mapped[float] = mapped_column(Float, default=10.0)
    # Padrões da seccionadora para o plano de corte
    chapa_comprimento_mm: Mapped[float] = mapped_column(Float, default=2750.0)
    chapa_largura_mm: Mapped[float] = mapped_column(Float, default=1850.0)
    serra_mm: Mapped[float] = mapped_column(Float, default=4.0)
    refilo_mm: Mapped[float] = mapped_column(Float, default=10.0)
    # Imposto sobre a venda (ex.: alíquota do Simples) usado no DRE por obra
    imposto_venda_pct: Mapped[float] = mapped_column(Float, default=0.0)
    garantia_meses: Mapped[int] = mapped_column(Integer, default=12)
    # Fiscal (NF-e por emissor integrado). O token nunca sai pela API.
    uf: Mapped[str | None] = mapped_column(String(2))
    inscricao_estadual: Mapped[str | None] = mapped_column(String(20))
    ncm_padrao: Mapped[str] = mapped_column(String(10), default="94034000")
    cfop_interno: Mapped[str] = mapped_column(String(4), default="5101")
    cfop_interestadual: Mapped[str] = mapped_column(String(4), default="6101")
    csosn_padrao: Mapped[str] = mapped_column(String(3), default="102")
    fiscal_ambiente: Mapped[str] = mapped_column(String(12), default="homologacao")
    fiscal_token: Mapped[str | None] = mapped_column(String(200))

    @property
    def fiscal_token_configurado(self) -> bool:
        return bool(self.fiscal_token)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(200))
    perfil: Mapped[Perfil] = mapped_column(String(20))
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(DateTime)
    # Vai dentro do token: trocar a senha incrementa e derruba todas as sessões antigas
    versao_sessao: Mapped[int] = mapped_column(Integer, default=1)
    # Funções personalizadas pelo administrador; None = padrão do perfil (ver app/funcoes.py)
    funcoes: Mapped[list[str] | None] = mapped_column(JSON)

    @property
    def funcoes_efetivas(self) -> list[str]:
        from .funcoes import efetivas
        return sorted(efetivas(self))

    @property
    def funcoes_personalizadas(self) -> bool:
        return self.funcoes is not None and self.perfil != Perfil.ADMIN

    empresa: Mapped[Empresa] = relationship()


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    documento: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    cidade: Mapped[str | None] = mapped_column(String(100))
    logradouro: Mapped[str | None] = mapped_column(String(200))
    numero: Mapped[str | None] = mapped_column(String(20))
    complemento: Mapped[str | None] = mapped_column(String(100))
    bairro: Mapped[str | None] = mapped_column(String(100))
    uf: Mapped[str | None] = mapped_column(String(2))
    cep: Mapped[str | None] = mapped_column(String(9))


class Fornecedor(Base):
    __tablename__ = "fornecedores"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    documento: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    prazo_dias: Mapped[int] = mapped_column(Integer, default=7)
    prazo_pagamento_dias: Mapped[int] = mapped_column(Integer, default=30)


class Material(Base):
    __tablename__ = "materiais"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[TipoMaterial] = mapped_column(String(20))
    unidade: Mapped[str] = mapped_column(String(10), default="UN")
    espessura_mm: Mapped[float | None] = mapped_column(Float)
    comprimento_mm: Mapped[float | None] = mapped_column(Float)
    largura_mm: Mapped[float | None] = mapped_column(Float)
    custo_unitario: Mapped[float] = mapped_column(Float, default=0.0)
    estoque_minimo: Mapped[float] = mapped_column(Float, default=0.0)
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"))


class CentroTrabalho(Base):
    __tablename__ = "centros_trabalho"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(20))
    nome: Mapped[str] = mapped_column(String(100))
    sequencia: Mapped[int] = mapped_column(Integer)
    regra: Mapped[RegraCentro] = mapped_column(String(20), default=RegraCentro.TODAS)
    ativo: Mapped[bool] = mapped_column(default=True)


class Projeto(Base):
    __tablename__ = "projetos"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    codigo: Mapped[str] = mapped_column(String(40))
    nome: Mapped[str] = mapped_column(String(200))
    status: Mapped[StatusProjeto] = mapped_column(String(20), default=StatusProjeto.ENGENHARIA)
    origem: Mapped[str] = mapped_column(String(30), default="MANUAL")
    data_entrega: Mapped[date | None] = mapped_column(Date)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    # Comercial (vem do XML do Promob e é confirmado no contrato)
    valor_tabela: Mapped[float | None] = mapped_column(Float)
    valor_pedido: Mapped[float | None] = mapped_column(Float)
    valor_venda: Mapped[float | None] = mapped_column(Float)
    frete_orcado: Mapped[float | None] = mapped_column(Float)
    montagem_orcada: Mapped[float | None] = mapped_column(Float)
    condicao_pagamento: Mapped[str | None] = mapped_column(String(120))
    parcelas_sugeridas: Mapped[int | None] = mapped_column(Integer)
    entrada_sugerida: Mapped[bool | None] = mapped_column()
    contrato_em: Mapped[date | None] = mapped_column(Date)
    # Marcos do projeto (base dos indicadores de prazo)
    liberado_em: Mapped[datetime | None] = mapped_column(DateTime)
    producao_concluida_em: Mapped[datetime | None] = mapped_column(DateTime)
    entregue_em: Mapped[datetime | None] = mapped_column(DateTime)

    cliente: Mapped[Cliente | None] = relationship()
    ambientes: Mapped[list["Ambiente"]] = relationship(
        back_populates="projeto", cascade="all, delete-orphan", order_by="Ambiente.id"
    )


class Ambiente(Base):
    __tablename__ = "ambientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))

    projeto: Mapped[Projeto] = relationship(back_populates="ambientes")
    modulos: Mapped[list["Modulo"]] = relationship(
        back_populates="ambiente", cascade="all, delete-orphan", order_by="Modulo.id"
    )


class Modulo(Base):
    __tablename__ = "modulos"

    id: Mapped[int] = mapped_column(primary_key=True)
    ambiente_id: Mapped[int] = mapped_column(ForeignKey("ambientes.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(200))
    largura_mm: Mapped[float | None] = mapped_column(Float)
    altura_mm: Mapped[float | None] = mapped_column(Float)
    profundidade_mm: Mapped[float | None] = mapped_column(Float)
    quantidade: Mapped[int] = mapped_column(Integer, default=1)

    ambiente: Mapped[Ambiente] = relationship(back_populates="modulos")
    pecas: Mapped[list["Peca"]] = relationship(
        back_populates="modulo", cascade="all, delete-orphan", order_by="Peca.id"
    )
    itens: Mapped[list["ItemModulo"]] = relationship(
        back_populates="modulo", cascade="all, delete-orphan", order_by="ItemModulo.id"
    )


class Peca(Base):
    """Peça fabricada (chapa cortada). Medidas acabadas, em mm."""
    __tablename__ = "pecas"

    id: Mapped[int] = mapped_column(primary_key=True)
    modulo_id: Mapped[int] = mapped_column(ForeignKey("modulos.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(200))
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materiais.id"))
    material_codigo: Mapped[str] = mapped_column(String(60))
    comprimento_mm: Mapped[float] = mapped_column(Float)
    largura_mm: Mapped[float] = mapped_column(Float)
    espessura_mm: Mapped[float | None] = mapped_column(Float)
    quantidade: Mapped[int] = mapped_column(Integer, default=1)
    veio: Mapped[bool] = mapped_column(default=False)
    # Fita de borda por lado (código do material de fita ou vazio)
    fita_c1: Mapped[str | None] = mapped_column(String(60))
    fita_c2: Mapped[str | None] = mapped_column(String(60))
    fita_l1: Mapped[str | None] = mapped_column(String(60))
    fita_l2: Mapped[str | None] = mapped_column(String(60))
    # Vindo do Promob: fita da peça e metragem total já calculada (sem os lados)
    fita_codigo: Mapped[str | None] = mapped_column(String(60))
    fita_metros: Mapped[float | None] = mapped_column(Float)
    programa_usinagem: Mapped[str | None] = mapped_column(String(120))
    # Operações do roteiro produtivo do Promob, separadas por vírgula (CORTE,BORDA,FURAR...)
    operacoes: Mapped[str | None] = mapped_column(String(200))

    modulo: Mapped[Modulo] = relationship(back_populates="pecas")
    material: Mapped[Material | None] = relationship()

    @property
    def lista_operacoes(self) -> list[str]:
        return [o for o in (self.operacoes or "").split(",") if o]

    @property
    def fitas(self) -> list[str]:
        return [f for f in (self.fita_c1, self.fita_c2, self.fita_l1, self.fita_l2, self.fita_codigo) if f]

    @property
    def tem_fita(self) -> bool:
        return bool(self.fitas) or "BORDA" in self.lista_operacoes

    @property
    def tem_usinagem(self) -> bool:
        return bool(self.programa_usinagem) or bool(OPERACOES_USINAGEM & set(self.lista_operacoes))


class ItemModulo(Base):
    """Ferragem/acessório comprado que vai no módulo (não passa pelo corte)."""
    __tablename__ = "itens_modulo"

    id: Mapped[int] = mapped_column(primary_key=True)
    modulo_id: Mapped[int] = mapped_column(ForeignKey("modulos.id"), index=True)
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materiais.id"))
    material_codigo: Mapped[str] = mapped_column(String(60))
    descricao: Mapped[str] = mapped_column(String(200))
    quantidade: Mapped[float] = mapped_column(Float, default=1)
    unidade: Mapped[str] = mapped_column(String(10), default="UN")

    modulo: Mapped[Modulo] = relationship(back_populates="itens")
    material: Mapped[Material | None] = relationship()


class OrdemProducao(Base):
    __tablename__ = "ordens_producao"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    status: Mapped[StatusOP] = mapped_column(String(20), default=StatusOP.ABERTA)
    prioridade: Mapped[int] = mapped_column(Integer, default=3)
    data_entrega: Mapped[date | None] = mapped_column(Date)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime)

    projeto: Mapped[Projeto] = relationship()
    unidades: Mapped[list["UnidadePeca"]] = relationship(
        back_populates="op", cascade="all, delete-orphan", order_by="UnidadePeca.id"
    )


class UnidadePeca(Base):
    """Cada peça física da OP, com etiqueta/código de barras próprio."""
    __tablename__ = "unidades_peca"

    id: Mapped[int] = mapped_column(primary_key=True)
    op_id: Mapped[int] = mapped_column(ForeignKey("ordens_producao.id"), index=True)
    peca_id: Mapped[int] = mapped_column(ForeignKey("pecas.id"))
    sequencial: Mapped[int] = mapped_column(Integer)
    codigo_barras: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(10), default="ATIVA", server_default="ATIVA")  # ATIVA ou REFUGADA
    reposicao_de_id: Mapped[int | None] = mapped_column(ForeignKey("unidades_peca.id"))

    @property
    def ativa(self) -> bool:
        return self.status != "REFUGADA"

    op: Mapped[OrdemProducao] = relationship(back_populates="unidades")
    peca: Mapped[Peca] = relationship()
    etapas: Mapped[list["EtapaUnidade"]] = relationship(
        back_populates="unidade", cascade="all, delete-orphan", order_by="EtapaUnidade.sequencia"
    )


class EtapaUnidade(Base):
    """Roteiro da peça: uma linha por centro de trabalho a percorrer."""
    __tablename__ = "etapas_unidade"

    id: Mapped[int] = mapped_column(primary_key=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades_peca.id"), index=True)
    centro_id: Mapped[int] = mapped_column(ForeignKey("centros_trabalho.id"), index=True)
    sequencia: Mapped[int] = mapped_column(Integer)
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime)
    operador: Mapped[str | None] = mapped_column(String(100))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    unidade: Mapped[UnidadePeca] = relationship(back_populates="etapas")
    centro: Mapped[CentroTrabalho] = relationship()


class PedidoCompra(Base):
    __tablename__ = "pedidos_compra"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    fornecedor_id: Mapped[int] = mapped_column(ForeignKey("fornecedores.id"))
    status: Mapped[StatusPedido] = mapped_column(String(20), default=StatusPedido.RASCUNHO)
    previsao: Mapped[date | None] = mapped_column(Date)
    observacao: Mapped[str | None] = mapped_column(String(500))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    fornecedor: Mapped[Fornecedor] = relationship()
    itens: Mapped[list["ItemPedido"]] = relationship(
        back_populates="pedido", cascade="all, delete-orphan", order_by="ItemPedido.id"
    )


class ItemPedido(Base):
    __tablename__ = "itens_pedido"

    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos_compra.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"))
    quantidade: Mapped[float] = mapped_column(Float)
    recebido: Mapped[float] = mapped_column(Float, default=0.0)
    custo_unitario: Mapped[float] = mapped_column(Float, default=0.0)

    pedido: Mapped[PedidoCompra] = relationship(back_populates="itens")
    material: Mapped[Material] = relationship()

    @property
    def pendente(self) -> float:
        return max(0.0, self.quantidade - self.recebido)


class MovimentoEstoque(Base):
    """Toda mudança de saldo. Saldo = soma das quantidades (entrada +, saída -)."""
    __tablename__ = "movimentos_estoque"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"), index=True)
    quantidade: Mapped[float] = mapped_column(Float)
    custo_unitario: Mapped[float] = mapped_column(Float, default=0.0)
    origem: Mapped[OrigemMovimento] = mapped_column(String(20))
    referencia: Mapped[str | None] = mapped_column(String(80))
    observacao: Mapped[str | None] = mapped_column(String(300))
    projeto_id: Mapped[int | None] = mapped_column(ForeignKey("projetos.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    material: Mapped[Material] = relationship()
    usuario: Mapped["Usuario | None"] = relationship()


class Reserva(Base):
    """Material comprometido com um projeto liberado, até a baixa na conclusão."""
    __tablename__ = "reservas"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"), index=True)
    quantidade: Mapped[float] = mapped_column(Float)
    baixada_em: Mapped[datetime | None] = mapped_column(DateTime)

    material: Mapped[Material] = relationship()
    projeto: Mapped[Projeto] = relationship()


class Lancamento(Base):
    """Conta a receber ou a pagar. Vinculada a projeto quando é receita ou custo da obra."""
    __tablename__ = "lancamentos"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    tipo: Mapped[TipoLancamento] = mapped_column(String(10))
    categoria: Mapped[Categoria] = mapped_column(String(20))
    descricao: Mapped[str] = mapped_column(String(200))
    valor: Mapped[float] = mapped_column(Float)
    vencimento: Mapped[date] = mapped_column(Date, index=True)
    pago_em: Mapped[date | None] = mapped_column(Date)
    valor_pago: Mapped[float | None] = mapped_column(Float)
    projeto_id: Mapped[int | None] = mapped_column(ForeignKey("projetos.id"), index=True)
    pedido_id: Mapped[int | None] = mapped_column(ForeignKey("pedidos_compra.id"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id"))
    fornecedor_id: Mapped[int | None] = mapped_column(ForeignKey("fornecedores.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    projeto: Mapped[Projeto | None] = relationship()
    fornecedor: Mapped[Fornecedor | None] = relationship()
    cliente: Mapped[Cliente | None] = relationship()


CHECKLIST_PADRAO = [
    "Módulos nivelados, alinhados e fixados",
    "Portas e frentes reguladas, sem desnível",
    "Gavetas e corrediças correndo sem atrito",
    "Ferragens, puxadores e acessórios instalados",
    "Acabamentos, fitas e tampos sem avarias",
    "Ambiente limpo e sobras recolhidas",
    "Cliente orientado sobre uso, limpeza e garantia",
]


class Montagem(Base):
    __tablename__ = "montagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    data_inicio: Mapped[date] = mapped_column(Date, index=True)
    data_fim: Mapped[date] = mapped_column(Date)
    equipe: Mapped[str] = mapped_column(String(200))
    endereco: Mapped[str | None] = mapped_column(String(300))
    observacao: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[StatusMontagem] = mapped_column(String(20), default=StatusMontagem.AGENDADA)
    iniciada_em: Mapped[datetime | None] = mapped_column(DateTime)
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime)
    recebido_por: Mapped[str | None] = mapped_column(String(120))

    projeto: Mapped[Projeto] = relationship()
    itens: Mapped[list["ItemChecklist"]] = relationship(
        back_populates="montagem", cascade="all, delete-orphan", order_by="ItemChecklist.id"
    )


class ItemChecklist(Base):
    __tablename__ = "itens_checklist"

    id: Mapped[int] = mapped_column(primary_key=True)
    montagem_id: Mapped[int] = mapped_column(ForeignKey("montagens.id"), index=True)
    descricao: Mapped[str] = mapped_column(String(200))
    ok: Mapped[bool] = mapped_column(default=False)
    observacao: Mapped[str | None] = mapped_column(String(300))
    conferido_por: Mapped[str | None] = mapped_column(String(120))

    montagem: Mapped[Montagem] = relationship(back_populates="itens")


class Chamado(Base):
    """Assistência técnica / pós-obra."""
    __tablename__ = "chamados"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    tipo: Mapped[TipoChamado] = mapped_column(String(20))
    descricao: Mapped[str] = mapped_column(String(500))
    status: Mapped[StatusChamado] = mapped_column(String(20), default=StatusChamado.ABERTO)
    aberto_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    agendado_para: Mapped[date | None] = mapped_column(Date)
    causa: Mapped[CausaChamado | None] = mapped_column(String(20))
    solucao: Mapped[str | None] = mapped_column(String(500))
    custo: Mapped[float] = mapped_column(Float, default=0.0)
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime)
    em_garantia: Mapped[bool] = mapped_column(default=False)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))

    projeto: Mapped[Projeto] = relationship()


class MovimentoBancario(Base):
    """Linha do extrato bancário (OFX). Valor positivo = entrada; negativo = saída."""
    __tablename__ = "movimentos_bancarios"
    __table_args__ = (UniqueConstraint("empresa_id", "fitid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    fitid: Mapped[str] = mapped_column(String(120))
    data: Mapped[date] = mapped_column(Date, index=True)
    valor: Mapped[float] = mapped_column(Float)
    descricao: Mapped[str] = mapped_column(String(300))
    lancamento_id: Mapped[int | None] = mapped_column(ForeignKey("lancamentos.id"))
    ignorado: Mapped[bool] = mapped_column(default=False)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    importado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    lancamento: Mapped[Lancamento | None] = relationship()


class StatusNota(str, Enum):
    PROCESSANDO = "PROCESSANDO"
    AUTORIZADA = "AUTORIZADA"
    ERRO = "ERRO"
    CANCELADA = "CANCELADA"


class NotaFiscal(Base):
    __tablename__ = "notas_fiscais"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    ref: Mapped[str] = mapped_column(String(60), unique=True)
    ambiente: Mapped[str] = mapped_column(String(12))
    valor: Mapped[float] = mapped_column(Float)
    status: Mapped[StatusNota] = mapped_column(String(15), default=StatusNota.PROCESSANDO)
    numero: Mapped[str | None] = mapped_column(String(20))
    serie: Mapped[str | None] = mapped_column(String(5))
    chave: Mapped[str | None] = mapped_column(String(60))
    url_danfe: Mapped[str | None] = mapped_column(String(400))
    url_xml: Mapped[str | None] = mapped_column(String(400))
    mensagem: Mapped[str | None] = mapped_column(String(1000))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    projeto: Mapped[Projeto] = relationship()


class RedefinicaoSenha(Base):
    """Pedido de redefinição de senha. Só o hash do token fica no banco."""
    __tablename__ = "redefinicoes_senha"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expira_em: Mapped[datetime] = mapped_column(DateTime)
    usado_em: Mapped[datetime | None] = mapped_column(DateTime)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    usuario: Mapped[Usuario] = relationship()


class Ocorrencia(Base):
    """Estorno de apontamento ou refugo de peça: quem, quando, onde e por quê."""
    __tablename__ = "ocorrencias_producao"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    op_id: Mapped[int] = mapped_column(ForeignKey("ordens_producao.id"), index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades_peca.id"))
    tipo: Mapped[str] = mapped_column(String(10))  # ESTORNO ou REFUGO
    centro_codigo: Mapped[str] = mapped_column(String(20))
    motivo: Mapped[str] = mapped_column(String(300))
    custo_material: Mapped[float] = mapped_column(Float, default=0.0)
    nova_unidade_id: Mapped[int | None] = mapped_column(ForeignKey("unidades_peca.id"))
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    usuario_nome: Mapped[str | None] = mapped_column(String(120))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)

    op: Mapped[OrdemProducao] = relationship()
    unidade: Mapped[UnidadePeca] = relationship(foreign_keys=[unidade_id])
    nova_unidade: Mapped[UnidadePeca | None] = relationship(foreign_keys=[nova_unidade_id])
