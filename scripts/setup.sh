#!/bin/bash
set -e

echo '=== WindSurf + Notion2API + Hermes Setup ==='

# 1. Install WindsurfAPI
if [ ! -d /opt/WindsurfAPI ]; then
  echo '[1/4] Cloning WindsurfAPI...'
  git clone https://github.com/dwgx/WindsurfAPI.git /opt/WindsurfAPI
else
  echo '[1/4] WindsurfAPI already exists, pulling latest...'
  cd /opt/WindsurfAPI && git pull
fi

# 2. Install Language Server
if [ ! -f /opt/windsurf/language_server_linux_x64 ]; then
  echo '[2/4] Installing Language Server...'
  cd /opt/WindsurfAPI && bash install-ls.sh
else
  echo '[2/4] Language Server already installed'
fi

# 3. Setup WindsurfAPI .env
if [ ! -f /opt/WindsurfAPI/.env ]; then
  echo '[3/4] Creating WindsurfAPI .env...'
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  cp "$SCRIPT_DIR/../config/windsurf-api.env.example" /opt/WindsurfAPI/.env
  echo '  ⚠️  Edit /opt/WindsurfAPI/.env to set API_KEY and DASHBOARD_PASSWORD'
else
  echo '[3/4] WindsurfAPI .env exists'
fi

# 4. Install systemd services
echo '[4/4] Installing systemd services...'
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/../config/windsurf-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable windsurf-api
systemctl start windsurf-api || true

echo ''
echo '=== Setup complete ==='
echo 'Next steps:'
echo '  1. Edit /opt/WindsurfAPI/.env (set API_KEY, DASHBOARD_PASSWORD)'
echo '  2. Add Windsurf account: bash scripts/add-windsurf-account.sh <token>'
echo '  3. Copy hermes config:   cp config/hermes-config.yaml ~/.hermes/config.yaml'
echo '  4. Restart hermes:       systemctl restart hermes-gateway'
