"""Modelo de dados do ERP Moveleiro (núcleo Engenharia + PCP).

Toda entidade de negócio carrega `empresa_id`: o banco é multiempresa (SaaS)
desde o primeiro dia.
"""
from datetime import date, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
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
    CONCLUIDO = "CONCLUIDO"
    CANCELADO = "CANCELADO"


class StatusOP(str, Enum):
    ABERTA = "ABERTA"
    EM_PRODUCAO = "EM_PRODUCAO"
    CONCLUIDA = "CONCLUIDA"
    CANCELADA = "CANCELADA"


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
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    documento: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(200))
    cidade: Mapped[str | None] = mapped_column(String(100))


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

    unidade: Mapped[UnidadePeca] = relationship(back_populates="etapas")
    centro: Mapped[CentroTrabalho] = relationship()
