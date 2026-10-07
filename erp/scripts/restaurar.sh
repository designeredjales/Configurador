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
