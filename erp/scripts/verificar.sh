#!/usr/bin/env bash
# Confere a saúde da instalação na VPS: contêineres, ERP, HTTPS e certificado, último backup, disco e memória.
#   cd /opt/erp-moveleiro/erp && bash scripts/verificar.sh
set -uo pipefail
cd "$(dirname "$0")/.."
ok() { printf '\033[32m✔\033[0m %s\n' "$*"; }
aviso() { printf '\033[33m!\033[0m %s\n' "$*"; PROBLEMAS=$((PROBLEMAS + 1)); }
PROBLEMAS=0
DOMINIO=$(grep -E '^ERP_DOMINIO=' .env 2>/dev/null | cut -d= -f2-)

for s in banco erp backup caddy; do
  estado=$(docker compose ps --format '{{.Service}} {{.State}} {{.Health}}' 2>/dev/null | awk -v s="$s" '$1==s {print $2, $3}')
  case "$estado" in
    running*unhealthy*) aviso "$s rodando, mas com falha de saúde" ;;
    running*) ok "$s: $estado" ;;
    "") [ "$s" = "caddy" ] && [ -z "$DOMINIO" ] || aviso "$s não está rodando" ;;
    *) aviso "$s: $estado" ;;
  esac
done

if docker compose exec -T erp python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/saude',timeout=3)" 2>/dev/null; then
  ok "ERP responde internamente (versão $(grep -E '^APP_VERSAO=' .env | cut -d= -f2-))"
else
  aviso "ERP não responde internamente: docker compose logs erp"
fi

if [ -n "$DOMINIO" ]; then
  if curl -fs -m 10 "https://$DOMINIO/api/saude" >/dev/null 2>&1; then
    validade=$(echo | openssl s_client -servername "$DOMINIO" -connect "$DOMINIO:443" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
    ok "HTTPS ok em https://$DOMINIO (certificado até ${validade:-?}, renovação automática)"
  else
    aviso "https://$DOMINIO não responde (DNS, firewall ou certificado): docker compose logs caddy"
  fi
fi

ultimo=$(docker compose exec -T backup sh -c 'ls -t /backups/erp_*.dump 2>/dev/null | head -1' 2>/dev/null | tr -d '\r')
if [ -n "$ultimo" ]; then
  idade_h=$(docker compose exec -T backup sh -c "echo \$(( (\$(date +%s) - \$(stat -c %Y $ultimo)) / 3600 ))" 2>/dev/null | tr -d '\r')
  if [ "${idade_h:-99}" -le 26 ]; then ok "último backup: $(basename "$ultimo") (há ${idade_h} h)"; else aviso "último backup tem ${idade_h} h: confira o serviço backup"; fi
else
  aviso "nenhum backup encontrado em /backups"
fi
grep -qE '^RCLONE_DESTINO=.+' .env 2>/dev/null && ok "cópia do backup na nuvem configurada" || aviso "backup só no servidor: configure RCLONE_DESTINO no .env"

uso=$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')
[ "$uso" -lt 80 ] && ok "disco: ${uso}% usado" || aviso "disco com ${uso}% usado"
livre=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
[ "$livre" -gt 300 ] && ok "memória livre: ${livre} MB" || aviso "pouca memória livre: ${livre} MB"

if [ "$PROBLEMAS" -eq 0 ]; then ok "tudo certo"; else echo "$PROBLEMAS ponto(s) para olhar"; exit 1; fi
