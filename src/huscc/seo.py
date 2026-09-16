"""Brief -> yayina hazir YouTube meta verisi.

Burada dort sey birden kurgulanir:
  SEO : baslik/etiket/aciklama arama terimlerine gore dizilir
  CTR : baslik adaylari puanlanir, en tiklanabilir olani secilir
  AEO : aciklamaya dogrudan cevap veren S/C blogu eklenir
  GEO : yapilandirilmis Ingilizce paket + lokalizasyon uretilir
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any

from . import keywords as kw
from .brief import Brief
from .config import Config
from .util import hhmmss, tr_fold, tr_upper

TITLE_HARD_LIMIT = 100
DESC_HARD_LIMIT = 4900          # YouTube siniri 5000
TAG_TOTAL_LIMIT = 500


@dataclass
class Metadata:
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    category_id: str = "20"
    default_language: str = "tr"
    privacy: str = "public"
    made_for_kids: bool = False
    publish_at: str | None = None
    playlist: str = ""
    pinned_comment: str = ""
    localizations: dict[str, dict[str, str]] = field(default_factory=dict)
    chapters: list[dict] = field(default_factory=list)
    title_alternatives: list[dict] = field(default_factory=list)
    notify_subscribers: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ CTR puan
_NUMBER_RE = re.compile(r"\d")
_CURIOSITY = [
    "neden", "nasil", "kimse", "sonunda", "inanilmaz", "sok", "gercek",
    "hic", "meger", "bu yuzden", "bakin", "dikkat", "asla",
]
_BENEFIT = [
    "rehber", "adim adim", "en iyi", "kolay", "hizli", "ucretsiz", "tam",
    "garanti", "calisan", "yeni",
]


def score_title(title: str, *, keywords: list[str], limit: int) -> tuple[float, list[str]]:
    """Basligi CTR + SEO acisindan 0-100 arasi puanlar, gerekcelerini dondurur."""
    score = 50.0
    notes: list[str] = []
    folded = tr_fold(title)
    length = len(title)

    # Uzunluk: 45-65 karakter tatli nokta
    if 40 <= length <= limit:
        score += 10
        notes.append("uzunluk ideal")
    elif length < 30:
        score -= 8
        notes.append("cok kisa")
    elif length > limit:
        score -= 14
        notes.append("mobilde kesilir")

    # Anahtar kelime bas tarafta mi
    head = folded[:32]
    if any(tr_fold(k) in head for k in keywords[:8]):
        score += 14
        notes.append("anahtar kelime basta")
    elif any(tr_fold(k) in folded for k in keywords[:12]):
        score += 6
        notes.append("anahtar kelime var")
    else:
        score -= 6
        notes.append("anahtar kelime zayif")

    if _NUMBER_RE.search(title):
        score += 7
        notes.append("sayi iceriyor")
    if any(word in folded for word in _CURIOSITY):
        score += 9
        notes.append("merak kancasi")
    if any(word in folded for word in _BENEFIT):
        score += 7
        notes.append("net fayda")
    if any(p in title for p in kw.POWER_WORDS_TR):
        score += 5
        notes.append("guclu kelime")
    if "|" in title or "-" in title:
        score += 3
        notes.append("ayrac ile okunur")
    if title.isupper():
        score -= 10
        notes.append("tamami buyuk harf (spam sinyali)")
    if title.count("!") > 1 or title.count("?") > 1:
        score -= 6
        notes.append("asiri noktalama")
    if folded.count("clash of clans") > 1:
        score -= 5
        notes.append("tekrar eden terim")

    return max(0.0, min(100.0, score)), notes


def rank_titles(brief: Brief, keywords: list[str], limit: int) -> list[dict]:
    candidates = list(dict.fromkeys(brief.title_candidates))
    ranked = []
    for title in candidates:
        title = " ".join(title.split())[:TITLE_HARD_LIMIT]
        value, notes = score_title(title, keywords=keywords, limit=limit)
        ranked.append({"title": title, "score": round(value, 1), "notes": notes})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


# ---------------------------------------------------------------- etiketler
def build_tags(brief: Brief, cfg: Config) -> list[str]:
    pool = list(brief.keywords)
    pool += kw.keyword_pool(brief.content_type, brief.town_hall, brief.strategies)

    limit_count = int(cfg.get("seo.tag_limit", 40))
    limit_chars = min(int(cfg.get("seo.tag_chars_limit", 480)), TAG_TOTAL_LIMIT)

    tags: list[str] = []
    seen: set[str] = set()
    used_chars = 0
    for raw in pool:
        tag = " ".join(str(raw).split()).strip().lower()
        if not tag or len(tag) > 40:
            continue
        key = tr_fold(tag)
        if key in seen:
            continue
        cost = len(tag) + 2  # ', ' ayraci
        if used_chars + cost > limit_chars or len(tags) >= limit_count:
            break
        seen.add(key)
        tags.append(tag)
        used_chars += cost
    return tags


# ----------------------------------------------------------------- bolumler
def build_chapters(brief: Brief, duration: float) -> list[dict]:
    """YouTube bolum listesi. Ilk bolum 0:00 olmak zorunda, en az 3 bolum, >=10sn."""
    if duration < 120:
        return []
    points = [
        {"t": 0.0, "label": "Giris"},
    ]
    for item in brief.highlights:
        stamp = float(item.get("t", 0))
        label = str(item.get("label", "")).strip() or "Onemli an"
        if 10 <= stamp <= duration - 15:
            points.append({"t": stamp, "label": label[:48]})

    if len(points) < 3:
        # Yedek: esit araliklarla otomatik bolumleme
        segments = ["Ordu kurulumu", "Saldiri basliyor", "Kritik anlar", "Sonuc"]
        points = [{"t": 0.0, "label": "Giris"}]
        for index, label in enumerate(segments, start=1):
            stamp = duration * index / (len(segments) + 1)
            points.append({"t": round(stamp, 1), "label": label})

    cleaned: list[dict] = []
    for point in sorted(points, key=lambda p: p["t"]):
        if cleaned and point["t"] - cleaned[-1]["t"] < 10:
            continue
        cleaned.append(point)
    return cleaned[:12] if len(cleaned) >= 3 else []


# ---------------------------------------------------------------- aciklama
def build_description(
    brief: Brief,
    cfg: Config,
    *,
    chapters: list[dict],
    tags: list[str],
) -> str:
    channel = cfg.channel_name
    handle = cfg.handle
    hook = brief.hook.strip() or brief.summary[:140]
    hook_max = int(cfg.get("seo.hook_max", 150))
    if len(hook) > hook_max:
        hook = hook[: hook_max - 1].rsplit(" ", 1)[0] + "…"

    parts: list[str] = [hook, ""]
    if brief.summary and brief.summary not in hook:
        parts += [brief.summary, ""]

    if brief.key_points:
        parts.append("✅ BU VİDEODA NE VAR")
        parts += [f"• {point}" for point in brief.key_points[:6]]
        parts.append("")

    if chapters and cfg.get("seo.chapters", True):
        parts.append("⏱️ BÖLÜMLER")
        parts += [f"{hhmmss(c['t'])} {c['label']}" for c in chapters]
        parts.append("")

    if brief.faq and cfg.get("seo.faq_block", True):
        parts.append("❓ SIKÇA SORULAN SORULAR")
        for item in brief.faq[:5]:
            question = str(item.get("q", "")).strip()
            answer = str(item.get("a", "")).strip()
            if question and answer:
                parts.append(f"S: {question}")
                parts.append(f"C: {answer}")
                parts.append("")

    english = english_pack(brief)
    if english:
        parts.append("🌍 ENGLISH SUMMARY")
        parts.append(english["description"].split("\n")[0])
        parts.append("")

    cta = f"🔔 Kanala abone ol ve zili aç — her yeni taktikte haberin olsun."
    if handle:
        cta += f"\n👉 {handle}"
    parts.append(cta)
    parts.append("")

    links = cfg.get("channel.links", {}) or {}
    link_lines = [
        f"• {name.title()}: {url}" for name, url in links.items() if str(url).strip()
    ]
    if link_lines:
        parts.append("🔗 BAĞLANTILAR")
        parts += link_lines
        parts.append("")

    hashtags = kw.hashtags_for(brief.content_type, brief.town_hall)
    parts.append(" ".join(hashtags))
    parts.append("")
    parts.append("Etiketler: " + ", ".join(tags[:18]))
    parts.append("")
    parts.append(
        f"{channel} — Clash of Clans Türkçe taktik, rehber ve klan savaşı içerikleri. "
        "Bu video Supercell tarafından desteklenmemektedir. "
        "Daha fazla bilgi: supercell.com/fan-content-policy"
    )

    text = "\n".join(parts).strip()
    return text[:DESC_HARD_LIMIT]


# --------------------------------------------------------------------- GEO
_TYPE_EN = {
    "war_attack": "Clan War Attack",
    "strategy_guide": "Attack Strategy Guide",
    "base_review": "Base Layout Review",
    "farming": "Farming Strategy",
    "upgrade": "Upgrade Guide",
    "event": "Update & Event Breakdown",
    "legend": "Legend League Attacks",
    "builder": "Builder Base Attack",
    "funny": "Funny Moments",
    "general": "Gameplay",
}


def english_pack(brief: Brief) -> dict[str, str] | None:
    """Ceviri yapmadan, yapilandirilmis veriden Ingilizce baslik/aciklama uretir."""
    label = _TYPE_EN.get(brief.content_type, "Gameplay")
    th = brief.town_hall or brief.builder_hall or ""
    strategy = brief.strategies[0].title() if brief.strategies else ""
    outcome_map = {
        "3 yildiz": "3 Star", "2 yildiz": "2 Star",
        "1 yildiz": "1 Star", "basarisiz": "Failed Attempt",
    }
    outcome = outcome_map.get(brief.outcome, "")

    bits = [b for b in [th, strategy, label] if b]
    title = " ".join(bits)
    if outcome:
        title = f"{title} - {outcome}"
    title = (title or "Clash of Clans Gameplay")[:TITLE_HARD_LIMIT]

    lines = [
        f"{label} in Clash of Clans"
        + (f" at {th}" if th else "")
        + (f" using {strategy}." if strategy else "."),
    ]
    if brief.key_points:
        lines.append("")
        lines.append("In this video:")
        lines += [f"- {p}" for p in brief.key_points[:4]]
    lines.append("")
    lines.append("Turkish commentary with English subtitles available.")
    return {"title": title, "description": "\n".join(lines)}


def build_localizations(brief: Brief, cfg: Config) -> dict[str, dict[str, str]]:
    wanted = cfg.get("seo.localizations", ["en"]) or []
    out: dict[str, dict[str, str]] = {}
    if "en" in wanted:
        pack = english_pack(brief)
        if pack:
            out["en"] = pack
    return out


# ------------------------------------------------------------------- yorum
def build_pinned_comment(brief: Brief, cfg: Config) -> str:
    question = ""
    if brief.faq:
        question = str(brief.faq[0].get("q", "")).strip()
    strategy = brief.strategies[0].title() if brief.strategies else "bu taktik"
    lines = [
        f"📌 {strategy} ile ilgili takıldığın yeri buraya yaz, tek tek cevaplıyorum.",
    ]
    if question:
        lines.append(f"En çok sorulan: {question}")
    lines.append("🔔 Abone olmayı ve zili açmayı unutma!")
    return "\n".join(lines)[:900]


# ---------------------------------------------------------------- ana kurgu
def build_metadata(
    brief: Brief,
    cfg: Config,
    *,
    duration: float,
    publish_at: str | None = None,
) -> Metadata:
    tags = build_tags(brief, cfg)
    title_limit = int(cfg.get("seo.title_max", 70))
    ranked = rank_titles(brief, tags, title_limit)
    title = ranked[0]["title"] if ranked else (brief.video_name or "Clash of Clans")
    if len(title) > TITLE_HARD_LIMIT:
        title = title[:TITLE_HARD_LIMIT].rsplit(" ", 1)[0]

    chapters = build_chapters(brief, duration) if cfg.get("seo.chapters", True) else []
    description = build_description(brief, cfg, chapters=chapters, tags=tags)

    playlist = _playlist_name(brief, cfg)

    return Metadata(
        title=title,
        description=description,
        tags=tags,
        category_id=str(cfg.get("upload.category_id", "20")),
        default_language=str(cfg.get("upload.default_language", "tr")),
        privacy=str(cfg.get("upload.privacy", "public")),
        made_for_kids=bool(cfg.get("upload.made_for_kids", False)),
        publish_at=publish_at,
        playlist=playlist,
        pinned_comment=build_pinned_comment(brief, cfg) if cfg.get("upload.pin_comment", True) else "",
        localizations=build_localizations(brief, cfg),
        chapters=chapters,
        title_alternatives=ranked[1:],
        notify_subscribers=bool(cfg.get("upload.notify_subscribers", True)),
    )


def _playlist_name(brief: Brief, cfg: Config) -> str:
    if not cfg.get("upload.auto_playlist", True):
        return ""
    label = kw.CONTENT_TYPES.get(brief.content_type, kw.CONTENT_TYPES["general"])["label"]
    if brief.town_hall:
        return f"{brief.town_hall} {label}"
    return f"Clash of Clans {label}"


def shorts_metadata(meta: Metadata, brief: Brief) -> dict[str, Any]:
    """Shorts icin kisaltilmis meta (baslik + #Shorts)."""
    base = meta.title
    if len(base) > 60:
        base = base[:60].rsplit(" ", 1)[0]
    title = f"{base} #Shorts"
    description = (
        f"{brief.hook}\n\n"
        f"Tam video kanalda! 🔔 Abone ol.\n\n"
        + " ".join(kw.hashtags_for(brief.content_type, brief.town_hall))
        + " #Shorts #ClashOfClans"
    )
    return {
        "title": title[:TITLE_HARD_LIMIT],
        "description": description[:DESC_HARD_LIMIT],
        "tags": meta.tags[:20],
    }


def thumbnail_words(brief: Brief) -> tuple[str, str]:
    """Kapak icin ana metin + rozet."""
    main = tr_upper(brief.thumbnail_text.strip()) or tr_upper(
        kw.THUMB_PHRASES.get(brief.content_type, kw.THUMB_PHRASES["general"])[0]
    )
    badge = (brief.thumbnail_sub or brief.town_hall or brief.builder_hall or "").strip()
    return main, badge
