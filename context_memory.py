"""
context_memory.py — Mémoire contextuelle des alertes envoyées.
Buffer circulaire MAX_ENTRIES entrées, TTL 24h.
Appelé à chaque alerte (breaking, trump, market, flash, news).
Injecté dans les prompts IA (/ask, /deep) pour que l'IA ait le contexte récent.
"""

import json
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path

MAX_ENTRIES  = 200
TTL_HOURS    = 24
_MEMORY_FILE = Path(__file__).parent / "context_memory.json"
_lock        = threading.Lock()


# ── Persistence ───────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> list:
    if _MEMORY_FILE.exists():
        try:
            return json.loads(_MEMORY_FILE.read_text())
        except Exception:
            pass
    return []


def _save(entries: list) -> None:
    try:
        _MEMORY_FILE.write_text(json.dumps(entries, ensure_ascii=False))
    except Exception:
        pass


def _prune(entries: list) -> list:
    """Supprime les entrées trop vieilles, garde les MAX_ENTRIES plus récentes."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TTL_HOURS)
    valid  = []
    for e in entries:
        try:
            ts = datetime.fromisoformat(e.get("timestamp", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts > cutoff:
                valid.append(e)
        except Exception:
            pass
    return valid[-MAX_ENTRIES:]


# ── API publique ──────────────────────────────────────────────────────────────

def add_entry(type_: str, title: str, source: str, score: int = 5,
              summary: str = "", url: str = "") -> None:
    """
    Ajoute une alerte/news en mémoire.
    type_ : "breaking" | "trump" | "market" | "flash" | "news"
    score : 0-10 (impact)
    """
    with _lock:
        entries = _load()
        entries = _prune(entries)
        entries.append({
            "type":      type_,
            "title":     title[:300],
            "source":    source[:80],
            "score":     min(max(int(score), 0), 10),
            "timestamp": _now_iso(),
            "summary":   (summary or "")[:300],
            "url":       (url or "")[:200],
        })
        _save(entries)


def get_recent_context(hours: int = 6, min_score: int = 5,
                       max_items: int = 25) -> str:
    """
    Retourne un bloc texte résumant les alertes récentes pour les prompts IA.
    Filtre par fenêtre temporelle et score minimum.
    Retourne "" si rien de pertinent.
    """
    with _lock:
        entries = _load()
    entries = _prune(entries)

    cutoff   = datetime.now(timezone.utc) - timedelta(hours=hours)
    relevant = []
    for e in entries:
        try:
            ts = datetime.fromisoformat(e.get("timestamp", ""))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff and e.get("score", 0) >= min_score:
                relevant.append((ts, e))
        except Exception:
            pass

    if not relevant:
        return ""

    # Trie par score DESC puis date DESC
    relevant.sort(key=lambda x: (-x[1].get("score", 0), -x[0].timestamp()))
    relevant = relevant[:max_items]

    TYPE_LABELS = {
        "breaking": "🚨 BREAKING",
        "trump":    "🇺🇸 TRUMP",
        "market":   "📰 MARKET",
        "flash":    "⚡ FLASH",
        "news":     "📋 NEWS",
    }

    lines = [f"RECENT ALERTS SENT TO TRADERS (last {hours}h, score≥{min_score}):"]
    for ts, e in relevant:
        ts_str = ts.strftime("%H:%M UTC")
        label  = TYPE_LABELS.get(e["type"], "📋")
        lines.append(
            f"  {label} [{ts_str}] [impact:{e['score']}/10] "
            f"{e['title']}  ({e.get('source', '')})"
        )
        if e.get("summary"):
            lines.append(f"    → {e['summary']}")

    return "\n".join(lines)


def get_stats() -> dict:
    """Stats pour /ping ou debug."""
    with _lock:
        entries = _load()
    entries = _prune(entries)
    by_type: dict[str, int] = {}
    for e in entries:
        by_type[e.get("type", "?")] = by_type.get(e.get("type", "?"), 0) + 1
    return {"total": len(entries), "by_type": by_type}
