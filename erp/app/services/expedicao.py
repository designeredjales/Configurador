"""Expedição por caixa master.

Regra de ouro: uma caixa leva peças de um único projeto (cliente) e de um único
ambiente. O leitor recusa peça de outro cliente; peça do mesmo cliente mas de
outro ambiente, ou que espalharia a caixa por módulos demais, gera a sugestão de
abrir outra caixa ou separar a peça para bipar depois.
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import CaixaMaster, Empresa, ItemCaixa, OrdemProducao, Projeto, StatusOP, UnidadePeca, Usuario
from . import pcp
from .producao import situacao

CENTRO_EMBALAGEM = "EMBALAGEM"


class ErroExpedicao(Exception):
    def __init__(self, mensagem: str, tipo: str, status: int = 409, sugestao: str | None = None, caixa_id: int | None = None):
        super().__init__(mensagem)
        self.status, self.tipo, self.sugestao, self.caixa_id = status, tipo, sugestao, caixa_id

    @property
    def detail(self) -> dict:
        return {"mensagem": str(self), "tipo": self.tipo, "sugestao": self.sugestao, "caixa_id": self.caixa_id}


def eh_codigo_caixa(codigo: str) -> bool:
    return len(codigo) == 12 and codigo.startswith("99") and codigo.isdigit()


def _cliente(p: Projeto) -> str:
    return p.cliente.nome if p.cliente else p.nome


def caixa_do_item(db: Session, unidade_id: int) -> CaixaMaster | None:
    item = db.scalar(select(ItemCaixa).where(ItemCaixa.unidade_id == unidade_id))
    return item.caixa if item else None


def nova_caixa(db: Session, empresa_id: int, unidade: UnidadePeca, usuario: Usuario) -> CaixaMaster:
    numero = (db.scalar(select(func.max(CaixaMaster.numero)).where(CaixaMaster.empresa_id == empresa_id)) or 0) + 1
    caixa = CaixaMaster(empresa_id=empresa_id, numero=numero, codigo_barras=f"99{empresa_id:03d}{numero:07d}",
                        projeto_id=unidade.op.projeto_id, ambiente_id=unidade.peca.modulo.ambiente_id,
                        criado_por=usuario.nome)
    db.add(caixa)
    db.flush()
    return caixa


def carregar_caixa(db: Session, empresa_id: int, caixa_id: int) -> CaixaMaster:
    caixa = db.get(CaixaMaster, caixa_id)
    if caixa is None or caixa.empresa_id != empresa_id:
        raise ErroExpedicao("Caixa master não encontrada", "NAO_ENCONTRADA", 404)
    return caixa


def _caixa_por_codigo(db: Session, empresa_id: int, codigo: str) -> CaixaMaster:
    caixa = db.scalar(select(CaixaMaster).where(CaixaMaster.codigo_barras == codigo, CaixaMaster.empresa_id == empresa_id))
    if caixa is None:
        raise ErroExpedicao(f"Caixa {codigo} não encontrada", "NAO_ENCONTRADA", 404)
    return caixa


def bipar(db: Session, emp: Empresa, usuario: Usuario, codigo: str, caixa_id: int | None = None,
          nova: bool = False) -> dict:
    codigo = codigo.strip()
    if eh_codigo_caixa(codigo):  # bipou a etiqueta de uma caixa: ela passa a ser a caixa ativa
        caixa = _caixa_por_codigo(db, emp.id, codigo)
        if caixa.status != "ABERTA":
            raise ErroExpedicao(f"Caixa {caixa.numero} está {caixa.status}. Reabra a caixa para continuar embalando.",
                                "CAIXA_FECHADA", caixa_id=caixa.id)
        return {"acao": "CAIXA_SELECIONADA", "mensagem": f"Caixa {caixa.numero} selecionada.", "caixa": caixa}

    unidade = db.scalar(select(UnidadePeca).join(OrdemProducao).where(
        UnidadePeca.codigo_barras == codigo, OrdemProducao.empresa_id == emp.id))
    if unidade is None:
        raise ErroExpedicao(f"Etiqueta {codigo} não encontrada", "NAO_ENCONTRADA", 404)
    if not unidade.ativa:
        raise ErroExpedicao(f"Peça {codigo} foi refugada: embale a peça de reposição", "REFUGADA")
    if unidade.op.status == StatusOP.CANCELADA:
        raise ErroExpedicao(f"OP {unidade.op.numero} cancelada", "OP_CANCELADA")
    ja = caixa_do_item(db, unidade.id)
    if ja is not None:
        raise ErroExpedicao(f"{unidade.peca.descricao} já está na caixa {ja.numero}", "JA_EMBALADA", caixa_id=ja.id)

    from . import separacao
    classe = separacao.mapa(db, emp.id).get(unidade.peca.separacao)
    if classe is not None and not classe.vai_para_caixa:
        raise ErroExpedicao(f"{unidade.peca.descricao} é de {classe.nome.upper()}: vira outra peça e não vai para caixa master",
                            "SEPARACAO", sugestao="SEPARAR")
    pendentes = [e for e in unidade.etapas if not e.concluida_em]
    embalagem = next((e for e in pendentes if e.centro.codigo == CENTRO_EMBALAGEM), None)
    faltam = [e for e in pendentes if e is not embalagem and e.centro.exige_apontamento]
    if faltam:
        raise ErroExpedicao(f"{unidade.peca.descricao} ainda não está pronta: falta {faltam[0].centro.codigo}",
                            "PRODUCAO_PENDENTE", sugestao="SEPARAR")
    falta_so_embalagem = embalagem is not None

    projeto, modulo = unidade.op.projeto, unidade.peca.modulo
    if nova or caixa_id is None:
        caixa = None
    else:
        caixa = carregar_caixa(db, emp.id, caixa_id)
        if caixa.status != "ABERTA":
            raise ErroExpedicao(f"Caixa {caixa.numero} está {caixa.status}. Reabra ou abra uma caixa nova.",
                                "CAIXA_FECHADA", sugestao="NOVA_CAIXA", caixa_id=caixa.id)
        if caixa.projeto_id != projeto.id:
            if caixa.projeto.cliente_id and caixa.projeto.cliente_id == projeto.cliente_id:
                raise ErroExpedicao(
                    f"PEÇA DE OUTRA OBRA. Mesmo cliente ({_cliente(projeto)}), mas a caixa {caixa.numero} é da obra "
                    f"{caixa.projeto.codigo} e a peça é da {projeto.codigo}: entregas separadas, caixas separadas.",
                    "OUTRA_OBRA", sugestao="SEPARAR", caixa_id=caixa.id)
            raise ErroExpedicao(
                f"PEÇA DE OUTRO CLIENTE. A caixa {caixa.numero} é de {_cliente(caixa.projeto)} ({caixa.projeto.codigo}); "
                f"esta peça é de {_cliente(projeto)} ({projeto.codigo}). Separe a peça.",
                "CLIENTE_DIFERENTE", sugestao="SEPARAR", caixa_id=caixa.id)
        if caixa.ambiente_id != modulo.ambiente_id:
            raise ErroExpedicao(
                f"Mesmo cliente, outro ambiente: a caixa {caixa.numero} é de {caixa.ambiente.nome} e a peça é de "
                f"{modulo.ambiente.nome}. Abra outra caixa master ou separe a peça para bipar depois.",
                "MODULO_DISTINTO", sugestao="NOVA_CAIXA", caixa_id=caixa.id)
        modulos = {i.unidade.peca.modulo_id for i in caixa.itens}
        if modulo.id not in modulos and len(modulos) >= emp.caixa_max_modulos:
            raise ErroExpedicao(
                f"A caixa {caixa.numero} já tem {len(modulos)} módulos e o limite é {emp.caixa_max_modulos}. "
                f"{modulo.codigo} ({modulo.descricao}) vai melhor em outra caixa master, ou separe para bipar depois.",
                "MODULO_DISTINTO", sugestao="NOVA_CAIXA", caixa_id=caixa.id)

    apontou = False
    if falta_so_embalagem:  # embalar é a baixa do setor de embalagem
        pcp.apontar(db, emp.id, codigo, CENTRO_EMBALAGEM, usuario)
        apontou = True
    if caixa is None:
        caixa = nova_caixa(db, emp.id, unidade, usuario)
    from .carrinhos import tirar_de_carrinho
    tirar_de_carrinho(db, unidade.id)  # foi para a caixa: saiu do carrinho
    db.add(ItemCaixa(caixa=caixa, unidade=unidade, usuario_nome=usuario.nome))
    db.flush()
    db.refresh(caixa)
    embaladas, total = progresso_projeto(db, projeto.id)
    return {"acao": "ADICIONADA", "caixa": caixa, "embalagem_apontada": apontou,
            "mensagem": f"{unidade.peca.descricao} ({modulo.codigo}) na caixa {caixa.numero}.",
            "projeto_embaladas": embaladas, "projeto_total": total}


def _unidades_projeto(db: Session, projeto_id: int) -> list[UnidadePeca]:
    return [u for u in db.scalars(select(UnidadePeca).join(OrdemProducao).where(
        OrdemProducao.projeto_id == projeto_id, OrdemProducao.status != StatusOP.CANCELADA)) if u.ativa]


def progresso_projeto(db: Session, projeto_id: int) -> tuple[int, int]:
    unidades = _unidades_projeto(db, projeto_id)
    ids = {u.id for u in unidades}
    embaladas = db.scalar(select(func.count()).select_from(ItemCaixa).where(ItemCaixa.unidade_id.in_(ids))) if ids else 0
    return embaladas, len(unidades)


def remover(db: Session, caixa: CaixaMaster, codigo: str) -> CaixaMaster:
    if caixa.status != "ABERTA":
        raise ErroExpedicao(f"Caixa {caixa.numero} está {caixa.status}: reabra para remover peças", "CAIXA_FECHADA")
    item = next((i for i in caixa.itens if i.unidade.codigo_barras == codigo.strip()), None)
    if item is None:
        raise ErroExpedicao(f"Etiqueta {codigo} não está na caixa {caixa.numero}", "NAO_ENCONTRADA", 404)
    caixa.itens.remove(item)
    db.flush()
    return caixa


def fechar(db: Session, caixa: CaixaMaster) -> CaixaMaster:
    if caixa.status != "ABERTA":
        raise ErroExpedicao(f"Caixa {caixa.numero} já está {caixa.status}", "CAIXA_FECHADA")
    if not caixa.itens:
        raise ErroExpedicao("Caixa vazia: bipe ao menos uma peça antes de fechar", "CAIXA_VAZIA", 422)
    caixa.status, caixa.fechada_em = "FECHADA", datetime.now()
    db.flush()
    return caixa


def reabrir(db: Session, caixa: CaixaMaster) -> CaixaMaster:
    if caixa.status != "FECHADA":
        raise ErroExpedicao(f"Só caixa FECHADA pode ser reaberta (esta está {caixa.status})", "STATUS")
    caixa.status, caixa.fechada_em = "ABERTA", None
    db.flush()
    return caixa


def carregar(db: Session, emp: Empresa, codigo: str) -> CaixaMaster:
    """Conferência de carregamento: bipa a etiqueta da caixa ao subir no caminhão."""
    codigo = codigo.strip()
    if not eh_codigo_caixa(codigo):
        raise ErroExpedicao("No carregamento bipe a etiqueta da caixa master, não a da peça", "NAO_E_CAIXA", 422)
    caixa = _caixa_por_codigo(db, emp.id, codigo)
    if caixa.status == "EXPEDIDA":
        raise ErroExpedicao(f"Caixa {caixa.numero} já foi carregada em {caixa.expedida_em:%d/%m %H:%M}", "JA_EXPEDIDA")
    if caixa.status != "FECHADA":
        raise ErroExpedicao(f"Caixa {caixa.numero} ainda está aberta: feche e etiquete antes de carregar", "CAIXA_ABERTA")
    caixa.status, caixa.expedida_em = "EXPEDIDA", datetime.now()
    db.flush()
    return caixa


def caixa_out(db: Session, caixa: CaixaMaster) -> dict:
    volumes = list(db.scalars(select(CaixaMaster.id).where(CaixaMaster.projeto_id == caixa.projeto_id)
                              .order_by(CaixaMaster.numero)))
    modulos = []
    for i in caixa.itens:
        m = i.unidade.peca.modulo.codigo
        if m not in modulos:
            modulos.append(m)
    p = caixa.projeto
    return {
        "id": caixa.id, "numero": caixa.numero, "codigo_barras": caixa.codigo_barras, "projeto_id": p.id,
        "projeto_codigo": p.codigo, "projeto_nome": p.nome, "cliente": p.cliente.nome if p.cliente else None,
        "ambiente": caixa.ambiente.nome, "status": caixa.status,
        "volume": volumes.index(caixa.id) + 1, "volumes_projeto": len(volumes),
        "modulos": modulos, "total_itens": len(caixa.itens),
        "itens": [{
            "codigo_barras": i.unidade.codigo_barras, "peca": i.unidade.peca.descricao,
            "modulo": i.unidade.peca.modulo.codigo, "modulo_descricao": i.unidade.peca.modulo.descricao,
            "medidas": f"{i.unidade.peca.comprimento_mm:g} × {i.unidade.peca.largura_mm:g} × {(i.unidade.peca.espessura_mm or 0):g}",
            "adicionado_em": i.adicionado_em, "usuario": i.usuario_nome,
        } for i in caixa.itens],
        "criado_em": caixa.criado_em, "criado_por": caixa.criado_por,
        "fechada_em": caixa.fechada_em, "expedida_em": caixa.expedida_em,
    }


def resumo_projeto(db: Session, projeto: Projeto) -> dict:
    unidades = _unidades_projeto(db, projeto.id)
    caixas = list(db.scalars(select(CaixaMaster).where(CaixaMaster.projeto_id == projeto.id).order_by(CaixaMaster.numero)))
    status_da = {i.unidade_id: c.status for c in caixas for i in c.itens}
    pendentes = []
    for u in unidades:
        if u.id in status_da:
            continue
        prox = next((e for e in u.etapas if not e.concluida_em), None)
        pendentes.append({"codigo_barras": u.codigo_barras, "ambiente": u.peca.modulo.ambiente.nome,
                          "modulo": u.peca.modulo.codigo, "peca": u.peca.descricao, "situacao": situacao(u),
                          "proxima_etapa": prox.centro.codigo if prox else None})
    em = [status_da.get(u.id) for u in unidades]
    return {
        "projeto_id": projeto.id, "codigo": projeto.codigo, "nome": projeto.nome, "total_pecas": len(unidades),
        "embaladas": sum(1 for s in em if s), "em_caixas_fechadas": sum(1 for s in em if s in ("FECHADA", "EXPEDIDA")),
        "expedidas": sum(1 for s in em if s == "EXPEDIDA"),
        "pronto_para_expedir": bool(unidades) and not pendentes and all(c.status != "ABERTA" for c in caixas),
        "pendentes": pendentes, "caixas": [caixa_out(db, c) for c in caixas],
    }
