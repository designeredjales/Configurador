"""Auditoria (quem alterou o quê) e saúde do sistema (versão, banco, backup, erros)."""
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from .. import observabilidade
from ..db import engine, get_db
from ..deps import ADMIN, empresa_atual
from ..models import Empresa, RegistroAuditoria, RegistroErro

router = APIRouter(prefix="/api", tags=["sistema"])
INICIO = time.time()


@router.get("/auditoria", dependencies=[Depends(ADMIN)])
def auditoria(de: date | None = None, ate: date | None = None, usuario: str | None = None, busca: str | None = None,
              limite: int = 300, emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    consulta = select(RegistroAuditoria).where(RegistroAuditoria.empresa_id == emp.id)
    if de:
        consulta = consulta.where(RegistroAuditoria.quando >= datetime.combine(de, datetime.min.time()))
    if ate:
        consulta = consulta.where(RegistroAuditoria.quando < datetime.combine(ate + timedelta(days=1), datetime.min.time()))
    if usuario:
        consulta = consulta.where(RegistroAuditoria.usuario_nome == usuario)
    if busca:
        termo = f"%{busca.strip()}%"
        consulta = consulta.where(or_(RegistroAuditoria.acao.ilike(termo), RegistroAuditoria.rota.ilike(termo),
                                      RegistroAuditoria.entidade_id.ilike(termo)))
    linhas = db.scalars(consulta.order_by(RegistroAuditoria.quando.desc(), RegistroAuditoria.id.desc())
                        .limit(max(1, min(limite, 1000))))
    usuarios = sorted(n for n in db.scalars(select(RegistroAuditoria.usuario_nome).where(
        RegistroAuditoria.empresa_id == emp.id, RegistroAuditoria.usuario_nome.is_not(None)).distinct()))
    return {"usuarios": usuarios, "registros": [{
        "id": r.id, "quando": r.quando, "usuario": r.usuario_nome, "acao": r.acao, "rota": r.rota, "metodo": r.metodo,
        "entidade_id": r.entidade_id, "status": r.status, "resultado": "ok" if r.status < 400 else "recusado" if r.status < 500 else "erro",
        "ip": r.ip, "detalhes": r.detalhes} for r in linhas]}


def ultimo_backup() -> dict:
    """Lê a pasta de backups (montada no contêiner do ERP pelo docker-compose)."""
    pasta = Path(os.getenv("ERP_PASTA_BACKUP", "/backups"))
    if not pasta.is_dir():
        return {"configurado": False, "mensagem": "Pasta de backups não encontrada neste servidor"}
    arquivos = sorted(pasta.glob("erp_*.dump"), key=lambda p: p.stat().st_mtime)
    if not arquivos:
        return {"configurado": True, "arquivo": None, "alerta": True, "mensagem": "Nenhum backup gerado ainda"}
    a = arquivos[-1]
    idade = (time.time() - a.stat().st_mtime) / 3600
    return {"configurado": True, "arquivo": a.name, "quando": datetime.fromtimestamp(a.stat().st_mtime),
            "idade_horas": round(idade, 1), "tamanho_mb": round(a.stat().st_size / 1e6, 2), "quantidade": len(arquivos),
            "alerta": idade > 26, "mensagem": "Último backup tem mais de 26 horas" if idade > 26 else "Em dia"}


@router.get("/sistema", dependencies=[Depends(ADMIN)])
def sistema(emp: Empresa = Depends(empresa_atual), db: Session = Depends(get_db)):
    try:
        migracao = db.execute(text("select version_num from alembic_version")).scalar()
    except Exception:
        db.rollback()
        migracao = None
    desde = datetime.now() - timedelta(hours=24)
    erros = list(db.scalars(select(RegistroErro).where(RegistroErro.empresa_id == emp.id)
                            .order_by(RegistroErro.quando.desc()).limit(20)))
    return {
        "versao": os.getenv("APP_VERSAO", "desenvolvimento"),
        "ambiente": os.getenv("ERP_AMBIENTE", "producao" if os.getenv("ERP_CRIAR_TABELAS") == "0" else "desenvolvimento"),
        "banco": engine.dialect.name, "migracao": migracao or "sem Alembic",
        "no_ar_desde": datetime.fromtimestamp(INICIO), "sentry": observabilidade.SENTRY_ATIVO,
        "backup": ultimo_backup(),
        "erros_24h": db.scalar(select(func.count()).select_from(RegistroErro).where(
            RegistroErro.empresa_id == emp.id, RegistroErro.quando >= desde)),
        "alteracoes_24h": db.scalar(select(func.count()).select_from(RegistroAuditoria).where(
            RegistroAuditoria.empresa_id == emp.id, RegistroAuditoria.quando >= desde)),
        "erros": [{"codigo": e.id, "quando": e.quando, "rota": e.rota, "metodo": e.metodo, "tipo": e.tipo,
                   "mensagem": e.mensagem} for e in erros],
    }
