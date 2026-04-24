"""
i18n.py – Traductions FR / EN / ES pour tradingLIVE.
"""

SUPPORTED = ("fr", "en", "es")
DEFAULT   = "fr"

STRINGS: dict[str, dict[str, str]] = {

    # ── /lang ─────────────────────────────────────────────────────────────────
    "lang_set": {
        "fr": "✅ Langue définie sur <b>Français</b>.",
        "en": "✅ Language set to <b>English</b>.",
        "es": "✅ Idioma configurado en <b>Español</b>.",
    },
    "lang_usage": {
        "fr": "❓ Usage : /lang fr | en | es",
        "en": "❓ Usage: /lang fr | en | es",
        "es": "❓ Uso: /lang fr | en | es",
    },
    "lang_invalid": {
        "fr": "❌ Langue non supportée. Choix : <code>fr</code>, <code>en</code>, <code>es</code>",
        "en": "❌ Unsupported language. Choices: <code>fr</code>, <code>en</code>, <code>es</code>",
        "es": "❌ Idioma no compatible. Opciones: <code>fr</code>, <code>en</code>, <code>es</code>",
    },

    # ── /start ────────────────────────────────────────────────────────────────
    "start": {
        "fr": (
            "👋 <b>Bienvenue sur tradingLIVE!</b>\n\n"
            "📊 Terminal de trading IA en temps réel — Forex, Indices, Macro.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📈 <b>Marché</b>\n"
            "🔹 /price       – Prix temps réel\n"
            "🔹 /deep        – Analyse profonde IA\n"
            "🔹 /confluence  – Score de confluence\n\n"
            "🔔 <b>Alertes</b>\n"
            "🔹 /market on   – Alertes marché haute importance\n"
            "🔹 /breaking on – Breaking news FOMC/crash\n"
            "🔹 /trump on    – Alertes Trump\n\n"
            "⚙️ <b>Système</b>\n"
            "🔹 /lang fr|en|es – Langue\n"
            "🔹 /tz America/Toronto – Fuseau horaire\n"
            "🔹 /help        – Toutes les commandes\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚡ Tapez /help pour voir toutes les commandes!"
        ),
        "en": (
            "👋 <b>Welcome to tradingLIVE!</b>\n\n"
            "📊 Real-time AI trading terminal — Forex, Indices, Macro.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📈 <b>Market</b>\n"
            "🔹 /price       – Real-time prices\n"
            "🔹 /deep        – Deep AI analysis\n"
            "🔹 /confluence  – Confluence score\n\n"
            "🔔 <b>Alerts</b>\n"
            "🔹 /market on   – High-impact market alerts\n"
            "🔹 /breaking on – Breaking news FOMC/crash\n"
            "🔹 /trump on    – Trump alerts\n\n"
            "⚙️ <b>System</b>\n"
            "🔹 /lang fr|en|es – Language\n"
            "🔹 /tz America/Toronto – Timezone\n"
            "🔹 /help        – All commands\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚡ Type /help to see all commands!"
        ),
        "es": (
            "👋 <b>¡Bienvenido a tradingLIVE!</b>\n\n"
            "📊 Terminal de trading IA en tiempo real — Forex, Índices, Macro.\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📈 <b>Mercado</b>\n"
            "🔹 /price       – Precios en tiempo real\n"
            "🔹 /deep        – Análisis profundo con IA\n"
            "🔹 /confluence  – Score de confluencia\n\n"
            "🔔 <b>Alertas</b>\n"
            "🔹 /market on   – Alertas de alto impacto\n"
            "🔹 /breaking on – Breaking news FOMC/crash\n"
            "🔹 /trump on    – Alertas Trump\n\n"
            "⚙️ <b>Sistema</b>\n"
            "🔹 /lang fr|en|es – Idioma\n"
            "🔹 /tz America/Toronto – Zona horaria\n"
            "🔹 /help        – Todos los comandos\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⚡ ¡Escribe /help para ver todos los comandos!"
        ),
    },

    # ── /help ─────────────────────────────────────────────────────────────────
    "help": {
        "fr": (
            "📊 <b>tradingLIVE – Aide complète</b>\n═══════════════════════════════\n\n"
            "<b>📈 Marché</b>\n"
            "🔹 /price            – Prix temps réel (NAS100/US500/GBP/CAD/EUR)\n"
            "🔹 /correlation      – Corrélations inter-marchés 30j\n"
            "🔹 /day              – Calendrier du jour (High+Medium)\n"
            "🔹 /week             – Calendrier économique semaine\n"
            "🔹 /deep             – Analyse profonde IA (algo + LLaMA)\n"
            "🔹 /session          – Sessions Asia/London/NY en cours\n\n"
            "<b>📐 Analyse technique</b>\n"
            "🔹 /structure        – Market structure (HH/HL/BOS/CHoCH)\n"
            "🔹 /divergence       – Divergences RSI régulières & cachées\n"
            "🔹 /confluence       – Score 0-10 + grade A-F + bias Long/Short\n"
            "🔹 /vix              – VIX — indice de peur & volatilité\n"
            "🔹 /yield-curve      – Yield curve US 3M/5Y/10Y/30Y\n"
            "🔹 /risk-calc &lt;compte&gt; &lt;risque%&gt; &lt;entrée&gt; &lt;SL&gt; [TP]\n"
            "                     – Taille de position & R:R\n\n"
            "<b>📰 News & IA</b>\n"
            "🔹 /flashnews [h]    – Flash news scorées HIGH/MEDIUM/LOW\n"
            "🔹 /us               – Dernières news américaines\n"
            "🔹 /newreport        – Rapport news US\n"
            "🔹 /ask &lt;question&gt;  – Question libre à l'IA\n\n"
            "<b>🔔 Alertes temps réel</b>\n"
            "🔹 /market on|off    – Alertes marché haute importance (polling 60s)\n"
            "🔹 /breaking on|off  – Breaking news FOMC/crash/missile (polling 90s)\n"
            "🔹 /trump on|off     – Alertes Trump tweets & déclarations\n"
            "🔹 /alert on N|off   – Alertes périodiques news toutes les Nh\n\n"
            "<b>⚙️ Système</b>\n"
            "🔹 /tz &lt;fuseau&gt;     – Fuseau horaire (ex: /tz America/Toronto)\n"
            "🔹 /lang fr|en|es    – Changer la langue\n"
            "🔹 /ping             – État du bot\n"
            "🔹 /uptime           – Temps en ligne\n\n"
            "═══════════════════════════════\n"
            "⚡ <b>tradingLIVE</b> — IA + marchés en temps réel"
        ),
        "en": (
            "📊 <b>tradingLIVE – Full Help</b>\n═══════════════════════════════\n\n"
            "<b>📈 Market</b>\n"
            "🔹 /price            – Real-time prices (NAS100/US500/GBP/CAD/EUR)\n"
            "🔹 /correlation      – 30-day cross-market correlations\n"
            "🔹 /day              – Today's calendar (High+Medium)\n"
            "🔹 /week             – Weekly economic calendar\n"
            "🔹 /deep             – Deep AI analysis (algo + LLaMA)\n"
            "🔹 /session          – Active sessions: Asia/London/NY\n\n"
            "<b>📐 Technical Analysis</b>\n"
            "🔹 /structure        – Market structure (HH/HL/BOS/CHoCH)\n"
            "🔹 /divergence       – RSI divergences — regular & hidden\n"
            "🔹 /confluence       – Score 0-10 + grade A-F + Long/Short bias\n"
            "🔹 /vix              – VIX — fear index & volatility\n"
            "🔹 /yield-curve      – US yield curve 3M/5Y/10Y/30Y\n"
            "🔹 /risk-calc &lt;account&gt; &lt;risk%&gt; &lt;entry&gt; &lt;SL&gt; [TP]\n"
            "                     – Position size & R:R ratio\n\n"
            "<b>📰 News & AI</b>\n"
            "🔹 /flashnews [h]    – Flash news scored HIGH/MEDIUM/LOW\n"
            "🔹 /us               – Latest US news\n"
            "🔹 /newreport        – US news report\n"
            "🔹 /ask &lt;question&gt;  – Ask the AI anything\n\n"
            "<b>🔔 Real-time Alerts</b>\n"
            "🔹 /market on|off    – High-impact market alerts (polling 60s)\n"
            "🔹 /breaking on|off  – Breaking news FOMC/crash/missile (polling 90s)\n"
            "🔹 /trump on|off     – Trump tweets & statements alerts\n"
            "🔹 /alert on N|off   – Periodic news alerts every Nh\n\n"
            "<b>⚙️ System</b>\n"
            "🔹 /tz &lt;timezone&gt;   – Set timezone (ex: /tz America/Toronto)\n"
            "🔹 /lang fr|en|es    – Change language\n"
            "🔹 /ping             – Bot status\n"
            "🔹 /uptime           – Uptime\n\n"
            "═══════════════════════════════\n"
            "⚡ <b>tradingLIVE</b> — AI + real-time markets"
        ),
        "es": (
            "📊 <b>tradingLIVE – Ayuda completa</b>\n═══════════════════════════════\n\n"
            "<b>📈 Mercado</b>\n"
            "🔹 /price            – Precios en tiempo real (NAS100/US500/GBP/CAD/EUR)\n"
            "🔹 /correlation      – Correlaciones entre mercados (30 días)\n"
            "🔹 /day              – Calendario del día (High+Medium)\n"
            "🔹 /week             – Calendario económico semanal\n"
            "🔹 /deep             – Análisis profundo con IA (algo + LLaMA)\n"
            "🔹 /session          – Sesiones activas: Asia/Londres/NY\n\n"
            "<b>📐 Análisis técnico</b>\n"
            "🔹 /structure        – Estructura de mercado (HH/HL/BOS/CHoCH)\n"
            "🔹 /divergence       – Divergencias RSI regulares y ocultas\n"
            "🔹 /confluence       – Score 0-10 + grado A-F + sesgo Long/Short\n"
            "🔹 /vix              – VIX — índice de miedo y volatilidad\n"
            "🔹 /yield-curve      – Curva de rendimientos US 3M/5Y/10Y/30Y\n"
            "🔹 /risk-calc &lt;cuenta&gt; &lt;riesgo%&gt; &lt;entrada&gt; &lt;SL&gt; [TP]\n"
            "                     – Tamaño de posición y R:R\n\n"
            "<b>📰 Noticias & IA</b>\n"
            "🔹 /flashnews [h]    – Flash news con score HIGH/MEDIUM/LOW\n"
            "🔹 /us               – Últimas noticias de EE.UU.\n"
            "🔹 /newreport        – Informe de noticias US\n"
            "🔹 /ask &lt;pregunta&gt;  – Pregunta libre a la IA\n\n"
            "<b>🔔 Alertas en tiempo real</b>\n"
            "🔹 /market on|off    – Alertas de alto impacto (polling 60s)\n"
            "🔹 /breaking on|off  – Breaking news FOMC/crash/misil (polling 90s)\n"
            "🔹 /trump on|off     – Alertas Trump tweets y declaraciones\n"
            "🔹 /alert on N|off   – Alertas periódicas de noticias cada Nh\n\n"
            "<b>⚙️ Sistema</b>\n"
            "🔹 /tz &lt;zona&gt;       – Zona horaria (ej: /tz America/Toronto)\n"
            "🔹 /lang fr|en|es    – Cambiar idioma\n"
            "🔹 /ping             – Estado del bot\n"
            "🔹 /uptime           – Tiempo en línea\n\n"
            "═══════════════════════════════\n"
            "⚡ <b>tradingLIVE</b> — IA + mercados en tiempo real"
        ),
    },

    # ── loading messages ──────────────────────────────────────────────────────
    "loading_price": {
        "fr": "⏳ Récupération des prix…",
        "en": "⏳ Fetching prices…",
        "es": "⏳ Obteniendo precios…",
    },
    "loading_correlation": {
        "fr": "🔗 Calcul des corrélations 30j…",
        "en": "🔗 Computing 30-day correlations…",
        "es": "🔗 Calculando correlaciones 30 días…",
    },
    "loading_calendar": {
        "fr": "📅 Chargement du calendrier…",
        "en": "📅 Loading calendar…",
        "es": "📅 Cargando calendario…",
    },
    "loading_day": {
        "fr": "📅 Chargement des événements du jour…",
        "en": "📅 Loading today's events…",
        "es": "📅 Cargando eventos del día…",
    },
    "loading_deep": {
        "fr": "🧠 Analyse profonde en cours… (30-60s)",
        "en": "🧠 Deep analysis in progress… (30-60s)",
        "es": "🧠 Análisis profundo en curso… (30-60s)",
    },
    "loading_flash": {
        "fr": "⚡ Récupération des flash news…",
        "en": "⚡ Fetching flash news…",
        "es": "⚡ Obteniendo noticias flash…",
    },
    "loading_report": {
        "fr": "⏳ Chargement du rapport…",
        "en": "⏳ Loading report…",
        "es": "⏳ Cargando informe…",
    },
    "loading_us": {
        "fr": "🇺🇸 Chargement des news US…",
        "en": "🇺🇸 Loading US news…",
        "es": "🇺🇸 Cargando noticias de EE.UU.…",
    },
    "loading_canada": {
        "fr": "🇨🇦 Chargement des news Canada…",
        "en": "🇨🇦 Loading Canada news…",
        "es": "🇨🇦 Cargando noticias de Canadá…",
    },

    # ── errors ────────────────────────────────────────────────────────────────
    "error_no_history": {
        "fr": "❌ Impossible de récupérer les données historiques.",
        "en": "❌ Unable to fetch historical data.",
        "es": "❌ No se pueden obtener los datos históricos.",
    },
    "error_deep": {
        "fr": "❌ <b>Erreur lors de l'analyse profonde</b>\n",
        "en": "❌ <b>Error during deep analysis</b>\n",
        "es": "❌ <b>Error durante el análisis profundo</b>\n",
    },
    "unknown_cmd": {
        "fr": "❓ Commande inconnue. Tapez /help pour la liste des commandes.",
        "en": "❓ Unknown command. Type /help for the command list.",
        "es": "❓ Comando desconocido. Escribe /help para ver los comandos.",
    },

    # ── /ping ─────────────────────────────────────────────────────────────────
    "ping_wait": {
        "fr": "🏓 Pong!",
        "en": "🏓 Pong!",
        "es": "🏓 ¡Pong!",
    },
    "ping_ok": {
        "fr": "✅ <b>tradingLIVE est en ligne</b> — latence: <b>{ms}ms</b>",
        "en": "✅ <b>tradingLIVE is online</b> — latency: <b>{ms}ms</b>",
        "es": "✅ <b>tradingLIVE está en línea</b> — latencia: <b>{ms}ms</b>",
    },

    # ── /uptime ───────────────────────────────────────────────────────────────
    "uptime": {
        "fr": "⏱ <b>Uptime tradingLIVE</b>\nEn ligne depuis : <i>{since}</i>\nDurée : <b>{h}h {m}m {s}s</b>",
        "en": "⏱ <b>tradingLIVE Uptime</b>\nOnline since: <i>{since}</i>\nDuration: <b>{h}h {m}m {s}s</b>",
        "es": "⏱ <b>Uptime de tradingLIVE</b>\nEn línea desde: <i>{since}</i>\nDuración: <b>{h}h {m}m {s}s</b>",
    },

    # ── /alert ────────────────────────────────────────────────────────────────
    "alert_active": {
        "fr": "✅ Alertes actives — toutes les <b>{h}h</b>\n/alert off pour désactiver.",
        "en": "✅ Alerts active — every <b>{h}h</b>\n/alert off to disable.",
        "es": "✅ Alertas activas — cada <b>{h}h</b>\n/alert off para desactivar.",
    },
    "alert_inactive": {
        "fr": "🔕 Alertes désactivées.\n/alert on 4 pour activer (toutes les 4h).",
        "en": "🔕 Alerts disabled.\n/alert on 4 to enable (every 4h).",
        "es": "🔕 Alertas desactivadas.\n/alert on 4 para activar (cada 4h).",
    },
    "alert_off_confirm": {
        "fr": "🔕 Alertes désactivées.",
        "en": "🔕 Alerts disabled.",
        "es": "🔕 Alertas desactivadas.",
    },
    "alert_on_confirm": {
        "fr": "✅ Alertes activées — toutes les <b>{h}h</b>\n/alert off pour désactiver.",
        "en": "✅ Alerts enabled — every <b>{h}h</b>\n/alert off to disable.",
        "es": "✅ Alertas activadas — cada <b>{h}h</b>\n/alert off para desactivar.",
    },

    # ── AI language instruction ───────────────────────────────────────────────
    "ai_language": {
        "fr": "Réponds toujours en français.",
        "en": "Always respond in English.",
        "es": "Responde siempre en español.",
    },
    "ai_label": {
        "fr": "🤖 <b>ANALYSE IA (LLaMA 3.3)</b>",
        "en": "🤖 <b>AI ANALYSIS (LLaMA 3.3)</b>",
        "es": "🤖 <b>ANÁLISIS IA (LLaMA 3.3)</b>",
    },
}


def t(key: str, lang: str, **kwargs) -> str:
    """Retourne la chaîne traduite pour la clé et la langue donnée."""
    lang = lang if lang in SUPPORTED else DEFAULT
    text = STRINGS.get(key, {}).get(lang) or STRINGS.get(key, {}).get(DEFAULT, key)
    return text.format(**kwargs) if kwargs else text
