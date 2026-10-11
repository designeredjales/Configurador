#!/usr/bin/env bash
# Instala o ERP Moveleiro numa VPS Ubuntu 22.04/24.04 limpa, com HTTPS automático.
#
#   curl -fsSL https://raw.githubusercontent.com/designeredjales/Configurador/<ramo>/erp/scripts/provisionar.sh -o provisionar.sh
#   sudo DOMINIO=erp.suaempresa.com.br EMAIL=ti@suaempresa.com.br bash provisionar.sh
#
# Variáveis (as obrigatórias são perguntadas se faltarem):
#   DOMINIO   endereço do ERP (o DNS tipo A precisa apontar para o IP desta VPS)
#   EMAIL     e-mail para os avisos do certificado HTTPS
#   REPO      repositório (padrão: https://github.com/designeredjales/Configurador.git)
#   RAMO      ramo a implantar (padrão: main)
#   GIT_TOKEN token de leitura do GitHub, só se o repositório for privado (não fica gravado)
#   PASTA     onde instalar (padrão: /opt/erp-moveleiro)
#
# O que faz: atualiza o sistema, liga atualizações de segurança automáticas, firewall (SSH, 80, 443),
# fail2ban, swap em máquinas pequenas, instala o Docker, baixa o ERP, gera os segredos do .env,
# sobe banco + ERP + backup + Caddy (HTTPS) e confere se o sistema respondeu.
# Pode ser rodado de novo: o que já existe é mantido (o .env nunca é sobrescrito).
set -euo pipefail

REPO=${REPO:-https://github.com/designeredjales/Configurador.git}
RAMO=${RAMO:-main}
PASTA=${PASTA:-/opt/erp-moveleiro}
ok() { printf '\033[32m✔\033[0m %s\n' "$*"; }
aviso() { printf '\033[33m!\033[0m %s\n' "$*"; }
falha() { printf '\033[31m✘ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || falha "Rode como root: sudo bash provisionar.sh"
. /etc/os-release 2>/dev/null || true
[ "${ID:-}" = "ubuntu" ] || aviso "Testado em Ubuntu 22.04/24.04; este sistema é ${PRETTY_NAME:-desconhecido}"

[ -n "${DOMINIO:-}" ] || read -r -p "Domínio do ERP (ex.: erp.suaempresa.com.br): " DOMINIO
[ -n "${EMAIL:-}" ] || read -r -p "E-mail para os avisos do certificado: " EMAIL
[[ "$DOMINIO" =~ ^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || falha "Domínio inválido: $DOMINIO"
[[ "$EMAIL" == *@*.* ]] || falha "E-mail inválido: $EMAIL"

echo "== 1/7 Sistema e segurança"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get -y -qq -o Dpkg::Options::=--force-confold upgrade >/dev/null
apt-get install -y -qq ca-certificates curl git ufw fail2ban unattended-upgrades openssl dnsutils >/dev/null
dpkg-reconfigure -f noninteractive unattended-upgrades >/dev/null 2>&1 || true
systemctl enable --now fail2ban >/dev/null 2>&1 || true
ok "pacotes, atualizações automáticas e fail2ban"

ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null
ufw --force enable >/dev/null
ok "firewall: só SSH, 80 e 443 abertos"

MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "$MEM_MB" -lt 3500 ] && ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "swap de 2 GB (máquina com ${MEM_MB} MB de RAM)"
fi
timedatectl set-timezone America/Sao_Paulo 2>/dev/null || true

echo "== 2/7 Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh >/dev/null
fi
systemctl enable --now docker >/dev/null
docker compose version >/dev/null || falha "Docker Compose não ficou disponível"
ok "$(docker --version)"

echo "== 3/7 Código do ERP"
URL_CLONE="$REPO"
if [ -n "${GIT_TOKEN:-}" ]; then URL_CLONE="${REPO/https:\/\//https://x-access-token:${GIT_TOKEN}@}"; fi
if [ -d "$PASTA/.git" ]; then
  git -C "$PASTA" fetch -q origin "$RAMO" && git -C "$PASTA" checkout -q "$RAMO" && git -C "$PASTA" pull -q --ff-only origin "$RAMO"
else
  git clone -q --branch "$RAMO" "$URL_CLONE" "$PASTA" || falha "Não consegui clonar $REPO (ramo $RAMO). Repositório privado? Informe GIT_TOKEN."
fi
git -C "$PASTA" remote set-url origin "$REPO"   # o token não fica gravado no servidor
ERP="$PASTA/erp"
cd "$ERP"
ok "código em $ERP ($(git rev-parse --short HEAD))"

echo "== 4/7 Configuração (.env)"
if [ ! -f .env ]; then
  cp .env.exemplo .env
  chmod 600 .env
  definir() { if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi; }
  definir POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  definir ERP_SECRET "$(openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-64)"
  definir ERP_URL_PUBLICA "https://$DOMINIO"
  definir ERP_DOMINIO "$DOMINIO"
  definir ACME_EMAIL "$EMAIL"
  definir ERP_BIND 127.0.0.1
  definir COMPOSE_FILE docker-compose.yml:docker-compose.vps.yml
  definir COMPOSE_PROJECT_NAME erp
  ok ".env criado com senha do banco e segredo gerados (guarde uma cópia fora do servidor)"
else
  ok ".env já existe: mantido"
fi
sed -i "s|^APP_VERSAO=.*|APP_VERSAO=$(git rev-parse --short HEAD)|" .env

echo "== 5/7 DNS"
IP_PUBLICO=$(curl -fsS4 https://api.ipify.org 2>/dev/null || true)
IP_DNS=$(dig +short A "$DOMINIO" | tail -1)
if [ -n "$IP_PUBLICO" ] && [ "$IP_DNS" = "$IP_PUBLICO" ]; then
  ok "$DOMINIO aponta para esta VPS ($IP_PUBLICO)"
else
  aviso "$DOMINIO aponta para '${IP_DNS:-nada}', esta VPS é '${IP_PUBLICO:-?}'. Crie o registro A no DNS; o certificado sai assim que apontar."
fi

echo "== 6/7 Subindo banco, ERP, backup e HTTPS"
docker compose build -q
docker compose up -d
ok "contêineres no ar: $(docker compose ps --services --status running | tr '\n' ' ')"

echo "== 7/7 Conferência"
for i in $(seq 1 60); do
  if docker compose exec -T erp python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/saude',timeout=3)" 2>/dev/null; then
    ok "ERP respondendo (migrações aplicadas)"; break
  fi
  [ "$i" -eq 60 ] && falha "ERP não respondeu em 3 minutos. Veja: cd $ERP && docker compose logs erp"
  sleep 3
done
if curl -fsS -m 10 "https://$DOMINIO/api/saude" >/dev/null 2>&1; then
  ok "HTTPS funcionando: https://$DOMINIO"
else
  aviso "HTTPS ainda não respondeu (DNS ou emissão do certificado em andamento). Confira em alguns minutos: bash scripts/verificar.sh"
fi

cat <<FIM

ERP Moveleiro instalado em $ERP
  Acesse:      https://$DOMINIO  (o primeiro cadastro cria a empresa e o administrador)
  Conferir:    cd $ERP && bash scripts/verificar.sh
  Atualizar:   cd $ERP && bash scripts/atualizar.sh
  Backup já:   cd $ERP && docker compose exec backup bash /scripts/backup.sh agora
  Logs:        cd $ERP && docker compose logs -f erp

Próximos passos: copie o .env para um cofre de senhas, configure RCLONE_DESTINO (cópia do backup na nuvem)
e um monitor externo apontando para https://$DOMINIO/api/saude.
FIM
