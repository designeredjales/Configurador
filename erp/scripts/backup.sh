#!/usr/bin/env bash
# Backup do banco e dos arquivos (renders das propostas) do ERP. Roda no serviço "backup" do docker-compose:
#   - um backup ao subir e depois todo dia na hora BACKUP_HORA (fuso TZ);
#   - guarda BACKUP_DIAS dias na pasta /backups (volume "backups");
#   - com RCLONE_DESTINO definido (ex.: nuvem:erp-backups), envia cada arquivo para a nuvem.
# Backup manual: docker compose exec backup bash /scripts/backup.sh agora
set -euo pipefail
PASTA=${BACKUP_PASTA:-/backups}
DIAS=${BACKUP_DIAS:-14}
HORA=${BACKUP_HORA:-03}
mkdir -p "$PASTA"

if [ -n "${RCLONE_DESTINO:-}" ] && ! command -v rclone >/dev/null; then
  echo "instalando rclone para a cópia na nuvem..."
  apt-get update -qq && apt-get install -y -qq rclone >/dev/null
fi

fazer_backup() {
  local arq="$PASTA/erp_$(date +%Y%m%d_%H%M).dump"
  pg_dump -Fc --no-owner -f "$arq.parcial"     # PGHOST, PGUSER, PGDATABASE e PGPASSWORD vêm do ambiente
  mv "$arq.parcial" "$arq"                       # só vira .dump quando o arquivo está completo
  echo "$(date '+%F %T') backup ok: $(basename "$arq") ($(du -h "$arq" | cut -f1))"
  local arqs=""
  if [ -d /arquivos ] && [ -n "$(ls -A /arquivos 2>/dev/null)" ]; then
    arqs="$PASTA/erp_arquivos_$(date +%Y%m%d_%H%M).tar.gz"
    tar -czf "$arqs.parcial" -C /arquivos . && mv "$arqs.parcial" "$arqs"
    echo "$(date '+%F %T') arquivos ok: $(basename "$arqs") ($(du -h "$arqs" | cut -f1))"
  fi
  find "$PASTA" \( -name 'erp_*.dump' -o -name 'erp_arquivos_*.tar.gz' \) -mtime +"$DIAS" -print -delete | sed 's/^/removido (antigo): /'
  if [ -n "${RCLONE_DESTINO:-}" ]; then
    rclone copy "$arq" "$RCLONE_DESTINO" && echo "cópia na nuvem ok: $RCLONE_DESTINO"
    [ -n "$arqs" ] && rclone copy "$arqs" "$RCLONE_DESTINO" && echo "arquivos na nuvem ok"
  fi
}

if [ "${1:-}" = "agora" ]; then fazer_backup; exit 0; fi

fazer_backup || echo "ATENÇÃO: backup inicial falhou"
while true; do
  agora=$(date +%s)
  alvo=$(date -d "today ${HORA}:00" +%s)
  [ "$alvo" -le "$agora" ] && alvo=$(date -d "tomorrow ${HORA}:00" +%s)
  sleep $((alvo - agora))
  fazer_backup || echo "ATENÇÃO: backup falhou em $(date '+%F %T')"
done
