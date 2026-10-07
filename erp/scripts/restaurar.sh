#!/usr/bin/env bash
# Restaura um backup no banco do ERP. APAGA os dados atuais e põe os do arquivo no lugar.
#   docker compose stop erp
#   docker compose exec backup bash /scripts/restaurar.sh erp_20261007_0300.dump
#   docker compose start erp
set -euo pipefail
PASTA=${BACKUP_PASTA:-/backups}
ARQ=${1:?informe o arquivo, ex.: erp_20261007_0300.dump (lista: ls /backups)}
[ -f "$ARQ" ] || ARQ="$PASTA/$ARQ"
[ -f "$ARQ" ] || { echo "arquivo não encontrado: $ARQ"; exit 1; }
if [ "${2:-}" != "--sim" ]; then
  read -r -p "Isto substitui TODOS os dados atuais pelos de $(basename "$ARQ"). Digite RESTAURAR para continuar: " ok
  [ "$ok" = "RESTAURAR" ] || { echo "cancelado"; exit 1; }
fi
pg_restore --clean --if-exists --no-owner -d "$PGDATABASE" "$ARQ"
echo "restaurado: $(basename "$ARQ")"
# Renders das propostas: o pacote do mesmo horário volta para o volume de arquivos (montado com escrita só aqui)
PACOTE="${ARQ/erp_/erp_arquivos_}"; PACOTE="${PACOTE%.dump}.tar.gz"
if [ -f "$PACOTE" ] && [ -w /arquivos ]; then
  tar -xzf "$PACOTE" -C /arquivos && echo "arquivos restaurados: $(basename "$PACOTE")"
elif [ -f "$PACOTE" ]; then
  echo "Renders do mesmo horário: $(basename "$PACOTE"). Para restaurá-los, no servidor (pasta do ERP):"
  echo "  docker run --rm -v erp_arquivos:/arquivos -v erp_backups:/backups:ro postgres:16 tar -xzf /backups/$(basename "$PACOTE") -C /arquivos"
fi
