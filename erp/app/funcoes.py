"""Catálogo de funções do ERP e o modelo padrão de cada perfil.

O perfil é só o ponto de partida: o administrador pode marcar ou desmarcar
funções por usuário (Usuario.funcoes). O perfil ADMIN tem sempre todas, para
a empresa nunca ficar sem quem administre.
"""
from .models import Perfil

# código: (módulo, nome, o que libera)
CATALOGO: dict[str, tuple[str, str, str]] = {
    "indicadores": ("Gestão", "Indicadores do dono", "Painel de vendas, margem, prazos, gargalo e retrabalho"),
    "projetos": ("Engenharia", "Projetos e engenharia", "Importar XML do Promob, editar projeto, liberar para a fábrica"),
    "materiais": ("Engenharia", "Cadastro de materiais", "Criar e editar materiais, custos e estoque mínimo"),
    "clientes": ("Comercial", "Cadastro de clientes", "Criar e editar clientes e endereço fiscal"),
    "pcp": ("Produção", "Ordens de produção", "Gerar e cancelar OP, cadastrar centros de trabalho"),
    "apontamento": ("Produção", "Apontamento", "Dar baixa nas peças pelo código de barras"),
    "estorno": ("Produção", "Estornar apontamento", "Desfazer a última baixa de uma peça, com motivo"),
    "refugo": ("Produção", "Refugo e reposição", "Registrar peça perdida e gerar a peça de reposição"),
    "montagem": ("Obra", "Montagem", "Agendar montagem, conferir checklist, entregar a obra"),
    "assistencia": ("Obra", "Assistência técnica", "Abrir, agendar e resolver chamados de pós-obra"),
    "estoque": ("Suprimentos", "Estoque e inventário", "Ajustar saldo por contagem física"),
    "compras": ("Suprimentos", "Compras", "Fornecedores, pedidos de compra e recebimento"),
    "financeiro": ("Financeiro", "Financeiro", "Contratos, contas a pagar e receber, fluxo de caixa, DRE"),
    "fiscal": ("Financeiro", "NF-e", "Emitir e consultar nota fiscal"),
    "conciliacao": ("Financeiro", "Conciliação bancária", "Importar extrato OFX e conciliar movimentos"),
    "usuarios": ("Administração", "Usuários e configurações", "Gerenciar equipe, funções e configurações da empresa"),
}

TODAS = frozenset(CATALOGO)

PADRAO_PERFIL: dict[Perfil, frozenset[str]] = {
    Perfil.ADMIN: TODAS,
    Perfil.GESTOR: TODAS - {"usuarios"},
    Perfil.ENGENHARIA: frozenset({"projetos", "materiais", "clientes"}),
    Perfil.PCP: frozenset({"pcp", "apontamento", "estorno", "refugo", "montagem", "assistencia"}),
    Perfil.COMPRAS: frozenset({"compras", "estoque", "materiais"}),
    Perfil.FINANCEIRO: frozenset({"financeiro", "fiscal", "conciliacao", "clientes"}),
    Perfil.MONTAGEM: frozenset({"montagem", "assistencia"}),
    Perfil.OPERADOR: frozenset({"apontamento"}),
}


def efetivas(usuario) -> frozenset[str]:
    """Funções que o usuário opera agora: as personalizadas ou o padrão do perfil."""
    if usuario.perfil == Perfil.ADMIN:
        return TODAS
    if usuario.funcoes is not None:
        return frozenset(f for f in usuario.funcoes if f in CATALOGO)
    return PADRAO_PERFIL.get(Perfil(usuario.perfil), frozenset())
