#!/usr/bin/env bash
# Atualiza o ERP na VPS com segurança: backup antes, nova versão, conferência e volta automática se falhar.
#   cd /opt/erp-moveleiro/erp && bash scripts/atualizar.sh            (ramo atual)
#   RAMO=main bash scripts/atualizar.sh                               (outro ramo)
# - Se o build da versão nova falhar, nada muda: o sistema segue na versão atual.
# - Se a versão nova não responder em 3 minutos, o código e a imagem anteriores voltam a rodar.
# As migrações do banco não são desfeitas sozinhas: se a volta acontecer depois de uma migração,
# restaure o backup feito no passo 1 (o nome aparece na tela) com scripts/restaurar.sh.
# ERP_BUILD troca o comando de build (ex.: build feito em outra máquina); ERP_ESPERA, as tentativas de 3 s.
set -euo pipefail
cd "$(dirname "$0")/.."
ok() { printf '\033[32m✔\033[0m %s\n' "$*"; }
aviso() { printf '\033[33m!\033[0m %s\n' "$*"; }

RAMO=${RAMO:-$(git rev-parse --abbrev-ref HEAD)}
ANTERIOR=$(git rev-parse --short HEAD)
[ -f .env ] || { echo "Falta o .env (rode scripts/provisionar.sh primeiro)"; exit 1; }

responde() {
  for _ in $(seq 1 "${ERP_ESPERA:-60}"); do
    docker compose exec -T erp python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/saude',timeout=3)" 2>/dev/null && return 0
    sleep 3
  done
  return 1
}
versao() { sed -i "s|^APP_VERSAO=.*|APP_VERSAO=$1|" .env; export APP_VERSAO="$1"; }
codigo_anterior() { git checkout -q -B "$RAMO" "$ANTERIOR"; versao "$ANTERIOR"; }  # o próximo pull avança de novo
construir() { if [ -n "${ERP_BUILD:-}" ]; then bash -c "$ERP_BUILD"; else docker compose build -q erp; fi; }

echo "== 1/4 Backup antes de atualizar"
docker compose exec -T backup bash /scripts/backup.sh agora
ok "backup feito (versão atual $ANTERIOR)"

echo "== 2/4 Baixando a versão nova ($RAMO)"
git fetch -q origin "$RAMO"
git checkout -q "$RAMO"
git pull -q --ff-only origin "$RAMO"
NOVA=$(git rev-parse --short HEAD)
if [ "$NOVA" = "$ANTERIOR" ]; then ok "já está na versão mais nova ($NOVA)"; exit 0; fi
git log --oneline "$ANTERIOR..$NOVA" | head -20

echo "== 3/4 Construindo e subindo $NOVA"
versao "$NOVA"
if ! construir; then
  codigo_anterior
  aviso "o build de $NOVA falhou: nada foi alterado, o sistema segue na versão $ANTERIOR"
  exit 1
fi
docker compose up -d

echo "== 4/4 Conferindo"
if responde; then
  ok "versão $NOVA no ar"
  docker image prune -f >/dev/null 2>&1 || true
  # guarda só as 3 imagens mais recentes do ERP (para voltar de versão sem rebuild)
  docker images erp-moveleiro --format '{{.Tag}}' | tail -n +4 | xargs -r -I{} docker rmi -f "erp-moveleiro:{}" >/dev/null 2>&1 || true
else
  aviso "a versão $NOVA não respondeu: voltando para $ANTERIOR"
  docker compose logs --tail 40 erp || true
  codigo_anterior
  docker compose up -d
  if responde; then
    aviso "de volta na versão $ANTERIOR. Se a versão $NOVA trouxe migração, restaure o backup do passo 1."
  else
    echo "A versão anterior também não respondeu. Veja: docker compose logs erp" >&2
  fi
  exit 1
fi
