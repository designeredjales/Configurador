"""Montagem (agenda, checklist, entrega) e assistência técnica com causa raiz."""
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CHECKLIST_PADRAO,
    CausaChamado,
    Categoria,
    Chamado,
    Empresa,
    ItemChecklist,
    Lancamento,
    Montagem,
    Projeto,
    StatusChamado,
    StatusMontagem,
    StatusProjeto,
    TipoLancamento,
    Usuario,
)
from .financeiro import _soma_meses

CAUSAS_INTERNAS = {CausaChamado.PRODUCAO, CausaChamado.PROJETO, CausaChamado.MONTAGEM, CausaChamado.MATERIAL}
PODE_AGENDAR = (StatusProjeto.LIBERADO, StatusProjeto.PRODUCAO, StatusProjeto.CONCLUIDO)


class ErroPosObra(ValueError):
    def __init__(self, mensagem: str, status: int = 409):
        super().__init__(mensagem)
        self.status = status


def agendar(db: Session, projeto: Projeto, inicio: date, fim: date, equipe: str,
            endereco: str | None, observacao: str | None) -> Montagem:
    if projeto.status not in PODE_AGENDAR:
        raise ErroPosObra(f"Projeto {projeto.status}: a montagem é agendada a partir da liberação para a fábrica")
    if fim < inicio:
        raise ErroPosObra("A data final não pode ser anterior à inicial.", 422)
    ativa = db.scalar(select(Montagem).where(
        Montagem.projeto_id == projeto.id,
        Montagem.status.in_([StatusMontagem.AGENDADA, StatusMontagem.EM_ANDAMENTO])))
    if ativa:
        raise ErroPosObra(f"O projeto já tem montagem {ativa.status.lower()} para {ativa.data_inicio:%d/%m/%Y}")
    m = Montagem(empresa_id=projeto.empresa_id, projeto=projeto, data_inicio=inicio, data_fim=fim,
                 equipe=equipe.strip(), endereco=endereco, observacao=observacao)
    m.itens = [ItemChecklist(descricao=d) for d in CHECKLIST_PADRAO]
    db.add(m)
    db.flush()
    return m


def iniciar(m: Montagem) -> None:
    if m.status != StatusMontagem.AGENDADA:
        raise ErroPosObra(f"Montagem está {m.status}")
    if m.projeto.status != StatusProjeto.CONCLUIDO:
        raise ErroPosObra("A produção do projeto ainda não foi concluída: não envie a equipe com móvel incompleto")
    m.status = StatusMontagem.EM_ANDAMENTO
    m.iniciada_em = datetime.now()


def conferir(m: Montagem, item_id: int, ok: bool, observacao: str | None, usuario: Usuario) -> ItemChecklist:
    if m.status != StatusMontagem.EM_ANDAMENTO:
        raise ErroPosObra("O checklist é conferido durante a montagem (inicie a montagem primeiro)")
    item = next((i for i in m.itens if i.id == item_id), None)
    if item is None:
        raise ErroPosObra("Item não pertence a esta montagem", 404)
    item.ok, item.observacao, item.conferido_por = ok, observacao, usuario.nome
    return item


def concluir(m: Montagem, recebido_por: str) -> None:
    if m.status != StatusMontagem.EM_ANDAMENTO:
        raise ErroPosObra(f"Montagem está {m.status}")
    pendentes = [i.descricao for i in m.itens if not i.ok]
    if pendentes:
        raise ErroPosObra("Checklist com pendências: " + "; ".join(pendentes), 422)
    if not recebido_por.strip():
        raise ErroPosObra("Informe o nome de quem recebeu a obra.", 422)
    m.status = StatusMontagem.CONCLUIDA
    m.concluida_em = datetime.now()
    m.recebido_por = recebido_por.strip()
    m.projeto.status = StatusProjeto.ENTREGUE
    m.projeto.entregue_em = m.concluida_em


def cancelar(m: Montagem) -> None:
    if m.status not in (StatusMontagem.AGENDADA, StatusMontagem.EM_ANDAMENTO):
        raise ErroPosObra(f"Montagem {m.status} não pode ser cancelada")
    m.status = StatusMontagem.CANCELADA


def abrir_chamado(db: Session, projeto: Projeto, tipo, descricao: str, usuario: Usuario) -> Chamado:
    if projeto.status not in (StatusProjeto.ENTREGUE, StatusProjeto.CONCLUIDO):
        raise ErroPosObra("Assistência técnica é aberta para projeto entregue (ou com produção concluída)")
    empresa = db.get(Empresa, projeto.empresa_id)
    em_garantia = True
    if projeto.entregue_em:
        limite = _soma_meses(projeto.entregue_em.date(), empresa.garantia_meses)
        em_garantia = date.today() <= limite
    ultimo = db.scalar(select(func.max(Chamado.numero)).where(Chamado.empresa_id == projeto.empresa_id)) or 0
    c = Chamado(empresa_id=projeto.empresa_id, numero=ultimo + 1, projeto=projeto, tipo=tipo,
                descricao=descricao.strip(), em_garantia=em_garantia, usuario_id=usuario.id)
    db.add(c)
    db.flush()
    return c


def resolver(db: Session, c: Chamado, causa: CausaChamado, solucao: str, custo: float,
             usuario: Usuario) -> None:
    if c.status == StatusChamado.RESOLVIDO:
        raise ErroPosObra(f"Chamado {c.numero} já resolvido")
    if not solucao.strip():
        raise ErroPosObra("Descreva a solução aplicada.", 422)
    c.causa, c.solucao, c.custo = causa, solucao.strip(), round(custo, 2)
    c.status = StatusChamado.RESOLVIDO
    c.resolvido_em = datetime.now()
    if c.custo > 0:
        # O custo da assistência entra no DRE da obra
        db.add(Lancamento(
            empresa_id=c.empresa_id, tipo=TipoLancamento.PAGAR, categoria=Categoria.ASSISTENCIA,
            descricao=f"Assistência {c.numero} · {c.projeto.codigo} ({causa.value.lower()})", valor=c.custo,
            vencimento=date.today(), projeto_id=c.projeto_id, usuario_id=usuario.id,
        ))
    db.flush()
