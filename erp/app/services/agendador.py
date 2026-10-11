"""Agendador interno: consolidação financeira diária de cada empresa, no horário do setup da base.

Roda numa thread do próprio servidor (ERP_AGENDADOR=0 desliga). Com várias instâncias, a chave
única da execução (uma AGENDADA por empresa e dia) impede que a consolidação rode em dobro.
Alternativa por cron: `python -m app.consolidar` (todas as empresas, uma vez).
"""
import logging
import os
import threading
from datetime import datetime

from sqlalchemy import select

from ..db import SessionLocal
from ..models import ConfigFinanceira, Empresa
from . import controladoria

log = logging.getLogger("erp.agendador")
INTERVALO_S = int(os.getenv("ERP_AGENDADOR_INTERVALO", "300"))
_parar = threading.Event()
_thread: threading.Thread | None = None


def rodar_pendentes(agora: datetime | None = None) -> list[dict]:
    """Consolida as empresas cuja hora agendada já passou hoje e que ainda não rodaram."""
    agora = agora or datetime.now()
    feitas = []
    with SessionLocal() as db:
        ids = list(db.scalars(select(Empresa.id)))
    for empresa_id in ids:
        with SessionLocal() as db:
            try:
                cfg = db.get(ConfigFinanceira, empresa_id) or controladoria.config(db, empresa_id)
                if not cfg.consolidacao_ativa or agora.hour < (cfg.consolidacao_hora or 0):
                    db.commit()
                    continue
                ex = controladoria.consolidar(db, empresa_id, origem="AGENDADA", usuario="Agendador", hoje=agora.date())
                db.commit()
                if ex is not None:
                    feitas.append({"empresa_id": empresa_id, "execucao_id": ex.id})
            except Exception:  # uma empresa com problema não para as outras
                db.rollback()
                log.exception("Falha na consolidação agendada da empresa %s", empresa_id)
    return feitas


def _laco() -> None:
    while not _parar.wait(INTERVALO_S):
        try:
            rodar_pendentes()
        except Exception:
            log.exception("Falha no agendador")


def iniciar() -> None:
    global _thread
    if os.getenv("ERP_AGENDADOR", "1") == "0" or (_thread and _thread.is_alive()):
        return
    _parar.clear()
    _thread = threading.Thread(target=_laco, name="agendador-consolidacao", daemon=True)
    _thread.start()


def parar() -> None:
    _parar.set()
