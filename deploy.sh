#!/bin/bash
# Usage: bash deploy.sh TON_GITHUB_TOKEN TON_TELEGRAM_TOKEN TON_ANTHROPIC_KEY
set -e

GITHUB_TOKEN="$1"
TELEGRAM_TOKEN="$2"
ANTHROPIC_KEY="${3:-}"

if [ -z "$GITHUB_TOKEN" ] || [ -z "$TELEGRAM_TOKEN" ]; then
    echo "❌ Usage: bash deploy.sh GITHUB_TOKEN TELEGRAM_TOKEN [ANTHROPIC_KEY]"
    exit 1
fi

REPO_URL="https://${GITHUB_TOKEN}@github.com/Ch4Trd/desktop-tutorial.git"
BRANCH="claude/news-aggregator-tool-80E6B"
SERVICE_NAME="tradinglive"
INSTALL_DIR="$(pwd)/desktop-tutorial/tradingLIVE"
CURRENT_USER="$(whoami)"

echo "📦 Clonage du dépôt..."
if [ -d "desktop-tutorial" ]; then
    cd desktop-tutorial
    git pull
    cd ..
else
    git clone "$REPO_URL"
fi

cd desktop-tutorial
git checkout "$BRANCH"
cd tradingLIVE

echo "🐍 Création du venv et installation des dépendances..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "⚙️  Création du fichier .env..."
cat > .env <<EOF
TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
ANTHROPIC_API_KEY=${ANTHROPIC_KEY}
EOF

echo "🔧 Création du service systemd..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=tradingLIVE Telegram Bot
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python ${INSTALL_DIR}/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "🚀 Activation et démarrage du service..."
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl restart ${SERVICE_NAME}

sleep 3
echo ""
echo "✅ Déploiement terminé !"
echo ""
sudo systemctl status ${SERVICE_NAME} --no-pager
echo ""
echo "📋 Commandes utiles :"
echo "  Logs en direct  : journalctl -u ${SERVICE_NAME} -f"
echo "  Redémarrer      : sudo systemctl restart ${SERVICE_NAME}"
echo "  Arrêter         : sudo systemctl stop ${SERVICE_NAME}"
echo "  Statut          : sudo systemctl status ${SERVICE_NAME}"
