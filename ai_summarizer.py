import logging
from config import ANTHROPIC_API_KEY

log = logging.getLogger(__name__)

def summarize_articles(articles: list) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        content = "\n".join(
            f"- [{a.source}] {a.title}: {a.summary}" for a in articles[:20]
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=(
                "Tu es un analyste financier. Résume les news les plus importantes "
                "en 5 points concis en français, en te concentrant sur l'impact marché. "
                "Format: bullet points avec •, une ligne par point."
            ),
            messages=[{"role": "user", "content": f"Voici les news du jour:\n{content}"}],
        )
        return msg.content[0].text.strip()
    except Exception as exc:
        log.warning("AI summarizer error: %s", exc)
        return None
