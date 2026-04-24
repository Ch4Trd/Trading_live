#!/bin/bash

if [ ! -f ".env" ]; then
    echo "❌ Fichier .env introuvable. Crée-le avec ton TELEGRAM_TOKEN."
    exit 1
fi

TOKEN=$(grep -E "^TELEGRAM_TOKEN=" .env | cut -d'=' -f2)
if [ -z "$TOKEN" ] || [ "$TOKEN" = "TON_TOKEN_ICI" ]; then
    echo "❌ TELEGRAM_TOKEN non configuré dans .env"
    exit 1
fi

if [ ! -f ".venv/bin/python" ]; then
    echo "⚙️  Création du venv et installation des dépendances..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip -q
    .venv/bin/pip install -r requirements.txt -q
fi

echo "🚀 Démarrage de tradingLIVE..."
.venv/bin/python main.py
