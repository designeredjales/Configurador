#!/bin/sh
set -e
# Aplica as migrações pendentes antes de subir a aplicação
alembic upgrade head
# Um processo: o limite de tentativas de login fica em memória (ver README)
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
