"""
ai_analyst.py – Analyse économique profonde.
IA principale : NVIDIA NIM (meta/llama-3.3-70b-instruct)
Backup        : Anthropic Claude Haiku 4.5
"""

import logging
import requests
from config import ANTHROPIC_API_KEY, NVIDIA_API_KEY

log = logging.getLogger(__name__)

NVIDIA_MODEL   = "meta/llama-3.3-70b-instruct"
NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"


# ── NVIDIA NIM (principal) ────────────────────────────────────────────────────

def _call_nvidia(system_prompt: str, user_content: str, max_tokens: int = 800) -> str | None:
    if not NVIDIA_API_KEY:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Content-Type":  "application/json",
        }
        payload = {
            "model": NVIDIA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "max_tokens":  max_tokens,
            "temperature": 0.4,
        }
        resp = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("NVIDIA API error: %s", exc)
        return None


# ── Claude (backup) ───────────────────────────────────────────────────────────

def _call_claude(system_prompt: str, user_content: str, max_tokens: int = 800) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        log.warning("Claude API error (backup): %s", exc)
        return None


# ── Dispatcher : NVIDIA → Claude → None ──────────────────────────────────────

def _call_ai(system_prompt: str, user_content: str, max_tokens: int = 800) -> str | None:
    result = _call_nvidia(system_prompt, user_content, max_tokens)
    if result:
        return result
    log.info("NVIDIA indisponible, bascule sur Claude.")
    return _call_claude(system_prompt, user_content, max_tokens)


# ── Analyse profonde de marché ────────────────────────────────────────────────

def deep_market_analysis(
    assets_data:      dict,
    calendar_summary: str,
    news_us:          list,
    news_ca:          list,
    lang:             str = "fr",
) -> str | None:
    from i18n import t as _t
    lang_instruction = _t("ai_language", lang)
    system = (
        f"You are a senior market economist and technical analyst working for an investment fund. "
        f"Your analysis must be precise, structured, and trading-oriented. "
        f"{lang_instruction} "
        f"Use real technical terms (momentum, RSI divergence, risk-on/risk-off correlation, "
        f"spread, directional bias, macro catalyst, etc.)."
    )

    price_lines = ["DONNÉES MARCHÉ (30 derniers jours) :"]
    for name, d in assets_data.items():
        if d.get("error"):
            continue
        price_lines.append(
            f"  {name}: {d['price']:.4f} | 1j:{d['change_1d']:+.2f}% | "
            f"7j:{d['change_7d']:+.2f}% | 30j:{d['change_30d']:+.2f}% | "
            f"RSI:{d['rsi']} | Tendance:{d['trend']} | "
            f"Support:{d['support']:.4f} | Résistance:{d['resistance']:.4f}"
        )

    from context_memory import get_recent_context
    ctx_block  = get_recent_context(hours=6, min_score=5, max_items=15)
    news_lines = ["DERNIÈRES NEWS US & CANADA :"]
    for a in (news_us[:8] + news_ca[:5]):
        news_lines.append(f"  - [{a.source}] {a.title}")
    if ctx_block:
        news_lines.append("")
        news_lines.append(ctx_block)

    user_content = "\n".join([
        "\n".join(price_lines),
        "",
        f"CALENDRIER ÉCONOMIQUE :\n{calendar_summary}",
        "",
        "\n".join(news_lines),
        "",
        "---",
        "Fournis une analyse complète en 6 sections :",
        "1. MACRO OVERVIEW — Contexte global, risk-on vs risk-off, sentiment dominant",
        "2. FOREX — Analyse USD, dynamiques EUR/USD GBP/USD USD/CAD USD/JPY",
        "3. INDICES & ACTIONS — NAS100, US500, NVDA : momentum, divergences, catalysts",
        "4. CORRÉLATIONS CLÉS — Relations inter-marchés détectées",
        "5. RISQUES & CATALYSTS — Événements macro à surveiller, zones de danger",
        "6. BIAIS DIRECTIONNEL — Pour chaque asset: Haussier / Baissier / Neutre + niveau clé",
        "Format: texte structuré, pas de HTML, utilise des tirets pour les listes.",
    ])

    return _call_ai(system, user_content, max_tokens=1200)


# ── Analyse des corrélations ──────────────────────────────────────────────────

def analyze_correlations(corr_matrix_str: str, assets_data: dict) -> str | None:
    system = (
        "Tu es un quant analyst spécialisé dans les corrélations inter-marchés. "
        "Explique en français, de façon pédagogique et actionnable, "
        "ce que les corrélations actuelles révèlent sur les marchés. "
        "Donne des insights concrets sur les opportunités et risques de diversification."
    )

    price_lines = ["Données prix actuels:"]
    for name, d in assets_data.items():
        if not d.get("error"):
            price_lines.append(
                f"  {name}: {d['price']:.4f} (RSI: {d['rsi']}, "
                f"1j: {d['change_1d']:+.2f}%, tendance: {d['trend']})"
            )

    user_content = (
        f"MATRICE DE CORRÉLATION 30 JOURS :\n{corr_matrix_str}\n\n"
        f"{chr(10).join(price_lines)}\n\n"
        "Analyse ces corrélations en 4 sections :\n"
        "1. CORRÉLATIONS FORTES — Paires > 0.7 ou < -0.7\n"
        "2. DIVERGENCES — Corrélations inhabituelles ou cassées\n"
        "3. DYNAMIQUES RISK-ON/RISK-OFF — Quel asset mène, lequel suit\n"
        "4. OPPORTUNITÉS — Paires à surveiller pour confirmation de signal\n"
        "Format: texte structuré, pas de HTML, utilise des tirets."
    )

    return _call_ai(system, user_content, max_tokens=600)


# ── Résumé de news ────────────────────────────────────────────────────────────

def summarize_news(articles: list) -> str | None:
    system = (
        "Tu es un analyste financier. Résume les news les plus importantes "
        "en 5 points concis en français, en te concentrant sur l'impact marché. "
        "Format: bullet points avec -, une ligne par point, pas de HTML."
    )
    content = "\n".join(f"- [{a.source}] {a.title}: {a.summary}" for a in articles[:20])
    return _call_ai(system, f"Voici les news du jour:\n{content}", max_tokens=400)


# ── Scoring d'impact pour flash news (batch) ──────────────────────────────────

def score_flash_impact(headlines: list[str]) -> list[str]:
    """
    Prend une liste de titres, retourne une liste de "HIGH"/"MEDIUM"/"LOW"
    dans le même ordre.
    """
    if not headlines:
        return []

    system = (
        "Tu es un trader institutionnel. Tu évalues l'impact de chaque headline sur les marchés financiers. "
        "Réponds UNIQUEMENT avec le format demandé, rien d'autre."
    )

    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    user_content = (
        "Classe chaque headline par impact sur les marchés financiers (forex, indices, obligations).\n"
        "FORMAT STRICT — une ligne par headline: [numéro]:[HIGH/MEDIUM/LOW]\n\n"
        "HIGH   : décisions de taux Fed/ECB/BoJ/BoC, NFP, CPI, PIB, PCE, Payrolls, ISM, "
        "hausse/baisse de taux surprise, crise géopolitique majeure, crash de marché, recession\n"
        "MEDIUM : earnings d'entreprises majeures (Apple/Tesla/NVDA), données éco secondaires, "
        "déclarations de membres de banques centrales, pétrole OPEC, chômage, ventes au détail\n"
        "LOW    : news corporate mineures, M&A petites entreprises, analyses d'analystes, "
        "upgrades/downgrades d'actions, IPO modestes, faits divers économiques\n\n"
        f"Headlines:\n{numbered}\n\n"
        "Réponse:"
    )

    raw = _call_nvidia(system, user_content, max_tokens=max(200, len(headlines) * 10 + 50))
    if raw is None:
        raw = _call_claude(system, user_content, max_tokens=max(200, len(headlines) * 10 + 50))
    if not raw:
        return ["LOW"] * len(headlines)

    results = ["LOW"] * len(headlines)
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        parts = line.split(":", 1)
        try:
            idx = int(parts[0].strip()) - 1
            level = parts[1].strip().upper()
            if 0 <= idx < len(headlines) and level in ("HIGH", "MEDIUM", "LOW"):
                results[idx] = level
        except (ValueError, IndexError):
            continue

    return results


# ── Traduction batch de titres/résumés ────────────────────────────────────────

LANG_NAME    = {"fr": "French", "en": "English", "es": "Spanish"}
LANG_LABEL   = {"fr": "french", "en": "english", "es": "spanish"}


def translate_articles(articles: list, lang: str) -> list:
    """
    Traduit in-place title + summary des articles dans la langue demandée.
    Si lang == 'en', ne fait rien (les news sont déjà en anglais).
    Retourne la liste (modifiée ou non).
    """
    if lang == "en" or not articles:
        return articles

    target = LANG_NAME.get(lang, "French")

    # Construit le payload : titres + résumés numérotés
    lines = []
    for i, a in enumerate(articles):
        lines.append(f"T{i+1}: {a.title}")
        if a.summary:
            lines.append(f"S{i+1}: {a.summary}")

    system = (
        f"You are a professional financial news translator. "
        f"Translate the following news titles and summaries to {target}. "
        f"Keep financial terms, ticker symbols, and proper nouns as-is. "
        f"Return ONLY the translations in the exact same format: "
        f"T1: ..., S1: ..., T2: ..., etc. No extra text."
    )
    user_content = "\n".join(lines)

    raw = _call_nvidia(system, user_content, max_tokens=max(400, len(articles) * 60))
    if raw is None:
        raw = _call_claude(system, user_content, max_tokens=max(400, len(articles) * 60))
    if not raw:
        return articles

    # Parse la réponse
    translations: dict[str, str] = {}
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        for prefix in ("T", "S"):
            if line.startswith(prefix) and ":" in line:
                try:
                    rest = line.split(":", 1)
                    idx  = int(rest[0][1:]) - 1
                    text = rest[1].strip()
                    if 0 <= idx < len(articles):
                        translations[f"{prefix}{idx+1}"] = text
                except (ValueError, IndexError):
                    pass

    # Applique les traductions
    import copy
    result = []
    for i, a in enumerate(articles):
        na = copy.copy(a)
        if f"T{i+1}" in translations:
            na.title = translations[f"T{i+1}"]
        if f"S{i+1}" in translations and a.summary:
            na.summary = translations[f"S{i+1}"]
        result.append(na)
    return result


# ── Traduction d'un texte court (alerte Trump/Breaking) ───────────────────────

def translate_text(text: str, lang: str) -> str:
    """Traduit un texte court dans la langue cible. Retourne l'original si échec."""
    if lang == "en" or not text.strip():
        return text
    target = LANG_NAME.get(lang, "French")
    system = (
        f"Translate the following financial news headline to {target}. "
        f"Keep proper nouns, ticker symbols, and numbers as-is. "
        f"Return ONLY the translated text, nothing else."
    )
    result = _call_nvidia(system, text, max_tokens=200)
    if not result:
        result = _call_claude(system, text, max_tokens=200)
    return result.strip() if result else text


# ── /ask — question libre à l'IA ─────────────────────────────────────────────

def ask_ai(question: str, lang: str = "fr") -> str | None:
    """Répond à une question libre sur les marchés financiers."""
    from i18n import t as _t
    from context_memory import get_recent_context
    lang_instruction = _t("ai_language", lang)
    system = (
        f"You are an expert financial analyst and economist with deep knowledge of "
        f"forex, stock markets, macroeconomics, trading strategies, and financial news. "
        f"{lang_instruction} "
        f"Be concise, precise, and actionable. No HTML formatting, use plain text. "
        f"If the user asks about recent news or events, use the context provided."
    )
    ctx_block = get_recent_context(hours=6, min_score=5, max_items=20)
    user_msg  = f"{ctx_block}\n\n---\nUSER QUESTION: {question}" if ctx_block else question
    return _call_ai(system, user_msg, max_tokens=700)


# ── Analyse FOMC / Fed event ──────────────────────────────────────────────────

def analyze_fomc_event(title: str, summary: str = "", lang: str = "fr") -> str | None:
    """
    Analyse un événement FOMC/Fed (statement, minutes, discours Powell).
    Retourne une analyse structurée en 3 sections + impact marché 1-5 jours.
    """
    from i18n import t as _t
    lang_instruction = _t("ai_language", lang)
    system = (
        "You are a senior macro economist and bond market specialist with 20 years of "
        "experience analyzing Fed policy. Your analysis is precise, trading-oriented, "
        f"and immediately actionable for traders. {lang_instruction} "
        "Structure your response exactly as requested. No HTML. Use dashes for lists."
    )

    context = f"Event: {title}"
    if summary and len(summary) > 20:
        context += f"\nDetails: {summary[:800]}"

    user_content = (
        f"{context}\n\n"
        "Provide a structured Fed/FOMC analysis in 3 sections:\n\n"
        "1. DÉCISION CLÉE\n"
        "   Résume en 2-3 phrases ce qui a été dit ou décidé. "
        "   Mention exact: taux, dot plot, guidance forward, bilan.\n\n"
        "2. SIGNAUX IMPORTANTS (top 4-5 points)\n"
        "   Les éléments les plus importants pour les traders: "
        "   ton hawkish/dovish, surprise vs consensus, changements de langage clés, "
        "   projections inflation/croissance, timing probable du prochain move.\n\n"
        "3. IMPACT MARCHÉ (prochains 1-5 jours)\n"
        "   - USD: direction et magnitude attendues, pourquoi\n"
        "   - Indices (NAS100/US500): haussier/baissier, niveau clé à surveiller\n"
        "   - Obligations (10Y yield): direction probable\n"
        "   - Or: impact attendu\n"
        "   - Forex clés: EUR/USD, GBP/USD, USD/JPY — niveaux et biais\n"
        "   - Risque principal à surveiller cette semaine\n\n"
        "Be specific with levels when possible. Trading-oriented, not academic."
    )

    return _call_ai(system, user_content, max_tokens=1000)
