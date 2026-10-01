#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/xgl34222220-ops/guizang.git"
APP_DIR="${APP_DIR:-/opt/guizang}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found. Installing Docker..."
  curl -fsSL https://get.docker.com | sh
fi

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  mkdir -p "$(dirname "$APP_DIR")"
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

if [ ! -f .env ]; then
  OWNER_TOKEN="$(openssl rand -hex 32)"
  MUSE_TOKEN="$(openssl rand -hex 32)"
  DOTS_TOKEN="$(openssl rand -hex 32)"
  cat > .env <<EOF
OWNER_TOKEN=$OWNER_TOKEN
MUSE_TOKEN=$MUSE_TOKEN
DOTS_TOKEN=$DOTS_TOKEN
BASE_URL=
PORT=3000
EOF
  chmod 600 .env
fi

docker compose up -d --build

echo
echo "Guizang Room is running on port 3000."
echo "Open: http://SERVER_IP:3000"
echo
echo "Tokens are stored in: $APP_DIR/.env"
echo "Run: docker compose logs guizang | tail -n 30"
