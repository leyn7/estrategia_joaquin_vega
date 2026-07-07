#!/bin/bash
# Despliegue del bot MDT. Uso:
#   ./deploy.sh [usuario@ip]        (default: bot-vps)
# Idempotente: la primera vez instala todo; las siguientes solo actualiza código.
set -euo pipefail

DEST="${1:-bot-vps}"
APP=/opt/mdt_bot

echo "[1/5] Sistema base (python) y usuario de servicio..."
ssh "$DEST" "apt-get update -qq && apt-get install -y -qq python3-venv >/dev/null
             id -u bot &>/dev/null || useradd -r -s /usr/sbin/nologin bot
             mkdir -p $APP/logs"

echo "[2/5] Subiendo código (solo módulos mdt_*, sin backtests ni caché)..."
tar -czf - --exclude __pycache__ mdt_*.py requirements.txt | ssh "$DEST" "tar -xzf - -C $APP"

echo "[3/5] Entorno Python..."
ssh "$DEST" "cd $APP && [ -d venv ] || python3 -m venv venv
             venv/bin/pip install -q -r requirements.txt
             [ -f .env ] || true
             chown -R bot:bot $APP"

echo "[4/5] Servicio systemd y .env..."
scp -q deploy/mdt-bot.service "$DEST:/etc/systemd/system/"
scp -q deploy/env.example "$DEST:$APP/env.example"
ssh "$DEST" "[ -f $APP/.env ] || cp $APP/env.example $APP/.env
             chown bot:bot $APP/.env $APP/env.example
             systemctl daemon-reload && systemctl enable mdt-bot >/dev/null"

echo "[5/5] (Re)arrancando..."
ssh "$DEST" "systemctl restart mdt-bot && sleep 3 && systemctl --no-pager -l status mdt-bot | head -12"

echo
echo "Listo. Logs en vivo:  ssh $DEST 'tail -f $APP/logs/bot.log'"
echo "Si es la primera vez: crear $APP/.env con el token (ver deploy/env.example)"
