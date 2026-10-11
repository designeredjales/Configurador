"""Modelo de dados do ERP Moveleiro (núcleo Engenharia + PCP).

Toda entidade de negócio carrega `empresa_id`: o banco é multiempresa (SaaS)
desde o primeiro dia.
"""
from datetime import date, datetime
from enum import Enum

from sqlalchemy import JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    PERFIL = "PERFIL"  # perfil de alumínio, puxador linear: consumo em metro ou barra
    VIDRO = "VIDRO"
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
    VENDEDOR = "VENDEDOR"      # funil, negociação e proposta
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
    SOB_DEMANDA = "SOB_DEMANDA"  # só peças cuja separação pede este setor (tupia, tamburato...)


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
    # Expedição: quantos módulos diferentes cabem numa caixa master antes de sugerir outra caixa
    caixa_max_modulos: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    # Importação do Promob: código sem de-para e sem cadastro vira material novo (True) ou pendência (False)
    promob_cria_materiais: Mapped[bool] = mapped_column(default=True, server_default="1")

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
    # Sem conferência: o setor não é bipado; a etapa fecha sozinha quando a peça passa no setor seguinte
    exige_apontamento: Mapped[bool] = mapped_column(default=True, server_default="1")
    # Capacidade e custo-hora: custo mensal (folha + encargos + rateio) ÷ horas produtivas do mês
    pessoas: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    horas_dia: Mapped[float] = mapped_column(Float, default=8.8, server_default="8.8")
    eficiencia_pct: Mapped[float] = mapped_column(Float, default=85.0, server_default="85")
    custo_mensal: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # Tempo padrão por peça que passa no setor: fixo + proporcional à área
    minutos_peca: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    minutos_m2: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")

    @property
    def capacidade_h_dia(self) -> float:
        """Horas produtivas por dia: pessoas × horas do turno × eficiência."""
        return round((self.pessoas or 0) * (self.horas_dia or 0) * (self.eficiencia_pct or 0) / 100, 2)

    def custo_hora_para(self, dias_uteis: int) -> float:
        cap = self.capacidade_h_dia * (dias_uteis or 0)
        return round((self.custo_mensal or 0) / cap, 2) if cap else 0.0

    @property
    def custo_hora(self) -> float:
        return self.custo_hora_para(getattr(self, "dias_uteis", None) or 22)

    def minutos(self, area_m2: float) -> float:
        """Tempo padrão de uma peça neste setor."""
        return (self.minutos_peca or 0) + (self.minutos_m2 or 0) * area_m2


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
    # Venda: o que foi vendido fica congelado para a auditoria contra o executivo de produção
    oportunidade_id: Mapped[int | None] = mapped_column(Integer)
    venda_resumo: Mapped[dict | None] = mapped_column(JSON)
    auditoria_ciente_por: Mapped[str | None] = mapped_column(String(120))
    auditoria_ciente_em: Mapped[datetime | None] = mapped_column(DateTime)

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
    # Produto do configurador: a configuração gerada (o XML do Promob não apaga este módulo ao reimportar)
    configuracao_id: Mapped[int | None] = mapped_column(ForeignKey("configuracoes_produto.id"))

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
    # Separação (tupia, tamburato, transformação...): vem das regras ou do PCP (manual não é sobrescrita)
    separacao: Mapped[str | None] = mapped_column(String(20))
    separacao_manual: Mapped[bool] = mapped_column(default=False, server_default="0")

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


class LoteProducao(Base):
    """Vários projetos liberados produzidos juntos: um plano de corte e uma sequência de etiquetas."""
    __tablename__ = "lotes_producao"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    descricao: Mapped[str] = mapped_column(String(120))
    data_entrega: Mapped[date | None] = mapped_column(Date)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    criado_por: Mapped[str | None] = mapped_column(String(120))

    ops: Mapped[list["OrdemProducao"]] = relationship(back_populates="lote", order_by="OrdemProducao.numero")


class OrdemProducao(Base):
    __tablename__ = "ordens_producao"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    lote_id: Mapped[int | None] = mapped_column(ForeignKey("lotes_producao.id"), index=True)
    status: Mapped[StatusOP] = mapped_column(String(20), default=StatusOP.ABERTA)
    prioridade: Mapped[int] = mapped_column(Integer, default=3)
    data_entrega: Mapped[date | None] = mapped_column(Date)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_cancelamento: Mapped[str | None] = mapped_column(String(200))

    projeto: Mapped[Projeto] = relationship()
    lote: Mapped[LoteProducao | None] = relationship(back_populates="ops")
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
    # Controladoria: centro de custo, conta do DRE gerencial (vazio = pela categoria) e aprovação da despesa
    centro_custo_id: Mapped[int | None] = mapped_column(ForeignKey("centros_custo.id"), index=True)
    conta: Mapped[str | None] = mapped_column(String(30))
    aprovacao: Mapped[str] = mapped_column(String(10), default="LIVRE", server_default="LIVRE")
    aprovacao_motivo: Mapped[str | None] = mapped_column(String(300))
    aprovado_por: Mapped[str | None] = mapped_column(String(120))

    projeto: Mapped[Projeto | None] = relationship()
    fornecedor: Mapped[Fornecedor | None] = relationship()
    cliente: Mapped[Cliente | None] = relationship()
    centro_custo: Mapped["CentroCusto | None"] = relationship()


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


class CaixaMaster(Base):
    """Volume da expedição: peças de um único projeto (cliente) e ambiente, com etiqueta própria."""
    __tablename__ = "caixas_master"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    codigo_barras: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    projeto_id: Mapped[int] = mapped_column(ForeignKey("projetos.id"), index=True)
    ambiente_id: Mapped[int] = mapped_column(ForeignKey("ambientes.id"))
    status: Mapped[str] = mapped_column(String(10), default="ABERTA")  # ABERTA, FECHADA, EXPEDIDA
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    criado_por: Mapped[str | None] = mapped_column(String(120))
    fechada_em: Mapped[datetime | None] = mapped_column(DateTime)
    expedida_em: Mapped[datetime | None] = mapped_column(DateTime)

    projeto: Mapped[Projeto] = relationship()
    ambiente: Mapped[Ambiente] = relationship()
    itens: Mapped[list["ItemCaixa"]] = relationship(
        back_populates="caixa", cascade="all, delete-orphan", order_by="ItemCaixa.id"
    )


class ItemCaixa(Base):
    __tablename__ = "itens_caixa"

    id: Mapped[int] = mapped_column(primary_key=True)
    caixa_id: Mapped[int] = mapped_column(ForeignKey("caixas_master.id"), index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades_peca.id"), unique=True)
    adicionado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    usuario_nome: Mapped[str | None] = mapped_column(String(120))

    caixa: Mapped[CaixaMaster] = relationship(back_populates="itens")
    unidade: Mapped[UnidadePeca] = relationship()


class ClasseSeparacao(Base):
    """Peças que seguem caminho próprio na fábrica e precisam ser separadas no apontamento."""
    __tablename__ = "classes_separacao"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(20))
    nome: Mapped[str] = mapped_column(String(60))
    # Palavras procuradas na descrição/código da peça, no módulo e nas operações do Promob (vírgula)
    palavras_chave: Mapped[str] = mapped_column(String(400), default="")
    centro_codigo: Mapped[str | None] = mapped_column(String(20))  # setor extra no roteiro
    vai_para_caixa: Mapped[bool] = mapped_column(default=True)  # False: vira outra peça, não é expedida sozinha
    ativo: Mapped[bool] = mapped_column(default=True)


class Carrinho(Base):
    """Carrinho físico da fábrica (reutilizável), com etiqueta própria."""
    __tablename__ = "carrinhos"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    codigo_barras: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    ativo: Mapped[bool] = mapped_column(default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    itens: Mapped[list["ItemCarrinho"]] = relationship(
        back_populates="carrinho", cascade="all, delete-orphan", order_by="ItemCarrinho.id"
    )


class ItemCarrinho(Base):
    __tablename__ = "itens_carrinho"

    id: Mapped[int] = mapped_column(primary_key=True)
    carrinho_id: Mapped[int] = mapped_column(ForeignKey("carrinhos.id"), index=True)
    unidade_id: Mapped[int] = mapped_column(ForeignKey("unidades_peca.id"), unique=True)
    centro_codigo: Mapped[str] = mapped_column(String(20))  # setor em que a peça entrou no carrinho
    adicionado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    usuario_nome: Mapped[str | None] = mapped_column(String(120))

    carrinho: Mapped[Carrinho] = relationship(back_populates="itens")
    unidade: Mapped[UnidadePeca] = relationship()


class RegistroAuditoria(Base):
    """Quem alterou o quê: uma linha por requisição que muda dados (gravada pelo middleware)."""
    __tablename__ = "auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int | None] = mapped_column(ForeignKey("empresas.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer)
    usuario_nome: Mapped[str | None] = mapped_column(String(120))
    quando: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    metodo: Mapped[str] = mapped_column(String(8))
    rota: Mapped[str] = mapped_column(String(200))
    acao: Mapped[str] = mapped_column(String(160))
    entidade_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str | None] = mapped_column(String(64))
    detalhes: Mapped[dict | None] = mapped_column(JSON)


class RegistroErro(Base):
    """Erro inesperado no servidor, com código para o suporte localizar."""
    __tablename__ = "erros_sistema"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    empresa_id: Mapped[int | None] = mapped_column(Integer, index=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer)
    quando: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)
    metodo: Mapped[str] = mapped_column(String(8))
    rota: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(120))
    mensagem: Mapped[str] = mapped_column(String(500))
    rastreio: Mapped[str] = mapped_column(String(8000))


# --- Comercial: funil, negociação e proposta -----------------------------------------

class ConfigComercial(Base):
    """Política comercial da empresa (uma linha por empresa), editada pelo administrador."""
    __tablename__ = "config_comercial"

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), primary_key=True)
    desconto_max_vendedor: Mapped[float] = mapped_column(Float, default=5.0)
    desconto_max_gerente: Mapped[float] = mapped_column(Float, default=12.0)
    margem_minima: Mapped[float] = mapped_column(Float, default=20.0)
    comissao_vendedor_pct: Mapped[float] = mapped_column(Float, default=3.0)
    limite_divergencia_pct: Mapped[float] = mapped_column(Float, default=3.0)
    validade_proposta_dias: Mapped[int] = mapped_column(Integer, default=15)
    etapas: Mapped[list | None] = mapped_column(JSON)
    condicoes: Mapped[list | None] = mapped_column(JSON)  # [{"nome", "parcelas", "ajuste_pct"}]
    # Promob Prices: o token nunca sai pela API
    prices_token: Mapped[str | None] = mapped_column(String(2000))
    prices_tabela: Mapped[str | None] = mapped_column(String(200))
    prices_sincronizado_em: Mapped[datetime | None] = mapped_column(DateTime)
    # Setup da integração por base: endereço da API, tabela escolhida (vazio = a ativa) e colunas do CSV
    prices_url: Mapped[str | None] = mapped_column(String(300))
    prices_tabela_preferida: Mapped[str | None] = mapped_column(String(200))
    prices_colunas: Mapped[dict | None] = mapped_column(JSON)  # {"sku": "...", "descricao": "...", "preco": "..."}


class Parceiro(Base):
    """Arquiteto, designer ou loja que indica obras e recebe RT."""
    __tablename__ = "parceiros"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(160))
    tipo: Mapped[str] = mapped_column(String(20), default="ARQUITETO")
    documento: Mapped[str | None] = mapped_column(String(20))
    telefone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(160))
    rt_pct: Mapped[float] = mapped_column(Float, default=0.0)
    ativo: Mapped[bool] = mapped_column(default=True)


class Oportunidade(Base):
    """Uma negociação no funil: do primeiro contato ao contrato (ou à perda)."""
    __tablename__ = "oportunidades"
    __table_args__ = (UniqueConstraint("empresa_id", "numero"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    titulo: Mapped[str] = mapped_column(String(160))
    cliente_nome: Mapped[str] = mapped_column(String(160))
    telefone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(160))
    etapa: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10), default="ABERTA")  # ABERTA, GANHA, PERDIDA
    origem: Mapped[str | None] = mapped_column(String(60))
    parceiro_id: Mapped[int | None] = mapped_column(ForeignKey("parceiros.id"))
    vendedor_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    valor_estimado: Mapped[float | None] = mapped_column(Float)
    link_3d: Mapped[str | None] = mapped_column(String(400))
    link_2020: Mapped[str | None] = mapped_column(String(400))
    token_2020: Mapped[str | None] = mapped_column(String(400))
    proxima_acao: Mapped[str | None] = mapped_column(String(200))
    proxima_acao_em: Mapped[date | None] = mapped_column(Date)
    motivo_perda: Mapped[str | None] = mapped_column(String(200))
    projeto_id: Mapped[int | None] = mapped_column(ForeignKey("projetos.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    fechado_em: Mapped[datetime | None] = mapped_column(DateTime)

    parceiro: Mapped[Parceiro | None] = relationship()
    vendedor: Mapped["Usuario | None"] = relationship()
    versoes: Mapped[list["VersaoProposta"]] = relationship(
        back_populates="oportunidade", cascade="all, delete-orphan", order_by="VersaoProposta.numero"
    )
    imagens: Mapped[list["ImagemProposta"]] = relationship(
        back_populates="oportunidade", cascade="all, delete-orphan", order_by="ImagemProposta.id"
    )


class VersaoProposta(Base):
    """Cada XML enviado vira uma versão: resumo do projeto, negociação, aprovação e proposta ao cliente."""
    __tablename__ = "versoes_proposta"

    id: Mapped[int] = mapped_column(primary_key=True)
    oportunidade_id: Mapped[int] = mapped_column(ForeignKey("oportunidades.id"), index=True)
    numero: Mapped[int] = mapped_column(Integer)
    arquivo: Mapped[str] = mapped_column(String(200))
    xml: Mapped[str] = mapped_column(Text)
    resumo: Mapped[dict] = mapped_column(JSON)
    desconto_pct: Mapped[float] = mapped_column(Float, default=0.0)
    condicao: Mapped[str | None] = mapped_column(String(60))
    calculo: Mapped[dict | None] = mapped_column(JSON)
    # Produtos do configurador vendidos nesta versão (sozinhos ou somados ao XML do Promob)
    itens_config: Mapped[list | None] = mapped_column(JSON)
    aprovacao: Mapped[str] = mapped_column(String(12), default="LIVRE")  # LIVRE, PENDENTE, APROVADA, RECUSADA
    aprovacao_motivo: Mapped[str | None] = mapped_column(String(300))
    aprovado_por: Mapped[str | None] = mapped_column(String(120))
    token_publico: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    proposta_validade: Mapped[date | None] = mapped_column(Date)
    aceite_em: Mapped[datetime | None] = mapped_column(DateTime)
    aceite_nome: Mapped[str | None] = mapped_column(String(160))
    aceite_ip: Mapped[str | None] = mapped_column(String(64))
    criado_por: Mapped[str | None] = mapped_column(String(120))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    oportunidade: Mapped[Oportunidade] = relationship(back_populates="versoes")


class ImagemProposta(Base):
    __tablename__ = "imagens_proposta"

    id: Mapped[int] = mapped_column(primary_key=True)
    oportunidade_id: Mapped[int] = mapped_column(ForeignKey("oportunidades.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(40))
    caminho: Mapped[str] = mapped_column(String(300))
    legenda: Mapped[str | None] = mapped_column(String(160))

    oportunidade: Mapped[Oportunidade] = relationship(back_populates="imagens")


class PrecoPromob(Base):
    """Tabela de preços vigente, sincronizada do Promob Prices."""
    __tablename__ = "precos_promob"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80), index=True)
    descricao: Mapped[str] = mapped_column(String(300), default="")
    preco: Mapped[float] = mapped_column(Float)


class ConfigGestao(Base):
    """Gestão à vista: metas do mês, limites de WIP do kanban e calendário da fábrica (uma linha por empresa)."""
    __tablename__ = "config_gestao"

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), primary_key=True)
    metas: Mapped[dict | None] = mapped_column(JSON)
    limites_wip: Mapped[dict | None] = mapped_column(JSON)
    dias_uteis_mes: Mapped[int] = mapped_column(Integer, default=22)
    horas_turno: Mapped[float] = mapped_column(Float, default=8.8)
    # Tambor-pulmão-corda: dias de proteção antes da restrição e setor fixado como tambor (vazio = calculado)
    pulmao_dias: Mapped[float] = mapped_column(Float, default=2.0, server_default="2")
    tambor_codigo: Mapped[str | None] = mapped_column(String(20))


class DeParaMaterial(Base):
    """Código do Promob → material do estoque (com fator de conversão de quantidade)."""
    __tablename__ = "depara_materiais"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo_promob"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    codigo_promob: Mapped[str] = mapped_column(String(60))
    material_id: Mapped[int] = mapped_column(ForeignKey("materiais.id"))
    fator: Mapped[float] = mapped_column(Float, default=1.0)  # 1 unidade do Promob = fator unidades do estoque
    observacao: Mapped[str | None] = mapped_column(String(200))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    material: Mapped[Material] = relationship()


# --- Controladoria: centros de custo, verbas, planejamento e consolidação -------------------------

class CentroCusto(Base):
    __tablename__ = "centros_custo"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(20))
    nome: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(20), default="ADMINISTRATIVO")  # PRODUTIVO, ADMINISTRATIVO, COMERCIAL, ESTRUTURA
    responsavel_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    setor_codigo: Mapped[str | None] = mapped_column(String(20))  # setor da fábrica (custo-hora)
    ativo: Mapped[bool] = mapped_column(default=True)

    responsavel: Mapped[Usuario | None] = relationship()


class VerbaCentro(Base):
    """Orçamento (verba) de um centro de custo por mês e conta do DRE gerencial."""
    __tablename__ = "verbas_centro"
    __table_args__ = (UniqueConstraint("empresa_id", "centro_custo_id", "ano", "mes", "conta"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    centro_custo_id: Mapped[int] = mapped_column(ForeignKey("centros_custo.id"), index=True)
    ano: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    conta: Mapped[str] = mapped_column(String(30))
    valor: Mapped[float] = mapped_column(Float, default=0.0)


class ConfigFinanceira(Base):
    """Regras da controladoria por empresa: alçadas, centros padrão e agenda de consolidação."""
    __tablename__ = "config_financeira"

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), primary_key=True)
    alcada_valor: Mapped[float | None] = mapped_column(Float)  # despesa acima disso sempre pede aprovação
    exige_centro: Mapped[bool] = mapped_column(default=False)
    bloqueia_sem_verba: Mapped[bool] = mapped_column(default=False)
    centros_padrao: Mapped[dict | None] = mapped_column(JSON)  # {conta: centro_custo_id}
    consolidacao_ativa: Mapped[bool] = mapped_column(default=True)
    consolidacao_hora: Mapped[int] = mapped_column(Integer, default=6)
    consolidacao_meses: Mapped[int] = mapped_column(Integer, default=2)  # mês atual e anteriores


class CenarioPlanejamento(Base):
    """Premissas do ponto de equilíbrio, meta e markup (modelo de planejamento da consultoria)."""
    __tablename__ = "cenarios_planejamento"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    premissas: Mapped[dict] = mapped_column(JSON)
    principal: Mapped[bool] = mapped_column(default=False)
    criado_por: Mapped[str | None] = mapped_column(String(120))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)


class ConsolidacaoDRE(Base):
    """Valor consolidado de uma conta do DRE gerencial no mês (por regime, centro e fonte)."""
    __tablename__ = "consolidacao_dre"

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    ano: Mapped[int] = mapped_column(Integer, index=True)
    mes: Mapped[int] = mapped_column(Integer)
    regime: Mapped[str] = mapped_column(String(12))  # COMPETENCIA (operacional) ou CAIXA (bancário)
    centro_custo_id: Mapped[int | None] = mapped_column(ForeignKey("centros_custo.id"))
    conta: Mapped[str] = mapped_column(String(30))
    valor: Mapped[float] = mapped_column(Float)
    fonte: Mapped[str] = mapped_column(String(10), default="ERP")  # ERP ou HISTORICO (importado)
    gerado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class ExecucaoConsolidacao(Base):
    __tablename__ = "execucoes_consolidacao"
    __table_args__ = (UniqueConstraint("empresa_id", "chave"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    chave: Mapped[str] = mapped_column(String(40))  # AGENDADA-AAAA-MM-DD (uma por dia) ou MANUAL-<instante>
    origem: Mapped[str] = mapped_column(String(10))
    iniciado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(10), default="RODANDO")
    usuario: Mapped[str | None] = mapped_column(String(120))
    resumo: Mapped[dict | None] = mapped_column(JSON)


# --- Configurador de produtos (engenharia programa, o comercial escolhe na venda) ---------------------

class NoProduto(Base):
    """Biblioteca de produtos configuráveis, com herança como no Promob Catalog.

    GRUPO (linha de modulação, grupo, subgrupo) guarda o que vale para tudo abaixo dele; MODELO é o produto que
    o vendedor configura; SUBCONJUNTO é um conjunto reutilizável (REF de agregados), como a porta de alumínio
    com vidro. Perguntas e componentes do filho com o mesmo código substituem os herdados.
    """
    __tablename__ = "produtos_nos"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    pai_id: Mapped[int | None] = mapped_column(ForeignKey("produtos_nos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(12))  # GRUPO, MODELO, SUBCONJUNTO
    codigo: Mapped[str] = mapped_column(String(40))
    nome: Mapped[str] = mapped_column(String(160))
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    ativo: Mapped[bool] = mapped_column(default=True)
    descricao_formula: Mapped[str | None] = mapped_column(String(400))
    perguntas: Mapped[list | None] = mapped_column(JSON)
    componentes: Mapped[list | None] = mapped_column(JSON)
    preco: Mapped[dict | None] = mapped_column(JSON)  # {"modo": "MARKUP"|"TABELA", "markup": 2.1, "formula": "..."}
    observacao: Mapped[str | None] = mapped_column(String(400))
    atualizado_por: Mapped[str | None] = mapped_column(String(120))
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)


class Acabamento(Base):
    """Modelo de acabamento (Catalog: modelo definição): componentes e as opções (modelos tipo) com o material de cada um."""
    __tablename__ = "acabamentos"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(40))
    nome: Mapped[str] = mapped_column(String(160))
    componentes: Mapped[list] = mapped_column(JSON)  # ["CHAPA", "FITA"]
    # [{"codigo", "nome", "referencia", "materiais": {"CHAPA": "MDP15-BR"}, "info": {"espessura": 15}, "adicional": 0, "ativo": true}]
    opcoes: Mapped[list] = mapped_column(JSON)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)


class ConfigProduto(Base):
    """Parâmetros do configurador da base: constantes das regras, perdas de perfil e markup padrão."""
    __tablename__ = "config_produto"

    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), primary_key=True)
    constantes: Mapped[dict | None] = mapped_column(JSON)  # {"TAXACOLA": 0.012}
    perda_perfil_pct: Mapped[float] = mapped_column(Float, default=3.0)
    serra_perfil_mm: Mapped[float] = mapped_column(Float, default=4.0)
    markup_padrao: Mapped[float] = mapped_column(Float, default=2.0)


class ConfiguracaoProduto(Base):
    """Configuração já gerada (Focco: BL101.0001). A mesma resposta com a mesma engenharia reaproveita o código."""
    __tablename__ = "configuracoes_produto"
    __table_args__ = (UniqueConstraint("empresa_id", "codigo"), UniqueConstraint("empresa_id", "modelo_id", "assinatura"))

    id: Mapped[int] = mapped_column(primary_key=True)
    empresa_id: Mapped[int] = mapped_column(ForeignKey("empresas.id"), index=True)
    modelo_id: Mapped[int] = mapped_column(ForeignKey("produtos_nos.id"), index=True)
    sequencial: Mapped[int] = mapped_column(Integer)
    codigo: Mapped[str] = mapped_column(String(60))
    assinatura: Mapped[str] = mapped_column(String(64))
    respostas: Mapped[dict] = mapped_column(JSON)
    descricao: Mapped[str] = mapped_column(String(300))
    modulo: Mapped[dict] = mapped_column(JSON)  # estrutura congelada: medidas, peças e itens
    custo: Mapped[dict] = mapped_column(JSON)
    criado_por: Mapped[str | None] = mapped_column(String(120))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
