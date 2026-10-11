"""Envio de e-mail transacional (SMTP). Sem SMTP configurado, registra no log (desenvolvimento)."""
import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("erp.email")


def enviar(para: str, assunto: str, texto: str) -> None:
    host = os.getenv("SMTP_HOST")
    if not host:
        log.warning("SMTP não configurado; e-mail para %s não enviado:\n%s\n%s", para, assunto, texto)
        return
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_REMETENTE", os.getenv("SMTP_USUARIO", "erp@localhost"))
    msg["To"], msg["Subject"] = para, assunto
    msg.set_content(texto)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORTA", "587")), timeout=20) as smtp:
        smtp.starttls()
        if os.getenv("SMTP_USUARIO"):
            smtp.login(os.getenv("SMTP_USUARIO"), os.getenv("SMTP_SENHA", ""))
        smtp.send_message(msg)
