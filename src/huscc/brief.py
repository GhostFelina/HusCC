"""Brief = videonun yaratici karar dosyasi (ne anlatiyor, nasil paketlenecek).

Brief uc yoldan uretilebilir:
  1. claude-code : Claude kareleri kendi gozuyle okur ve brief.json'u yazar (varsayilan)
  2. api         : ANTHROPIC_API_KEY / OPENAI_API_KEY ile gorsel model cagrilir
  3. heuristic   : dosya adi + altyazi metninden kural tabanli uretim (her zaman calisir)
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from . import keywords as kw
from .util import HusccError, hhmmss, read_json, tr_upper, warn, write_json

BRIEF_VERSION = 2


@dataclass
class Highlight:
    t: float
    label: str

    def to_dict(self) -> dict:
        return {"t": round(float(self.t), 2), "label": self.label}


@dataclass
class Brief:
    video_name: str = ""
    content_type: str = "general"
    town_hall: str | None = None
    builder_hall: str | None = None
    strategies: list[str] = field(default_factory=list)
    outcome: str = ""               # "3 yildiz", "2 yildiz", "basarisiz", ""
    summary: str = ""               # 2-3 cumle, ne oldugu
    hook: str = ""                  # aciklamanin ilk cumlesi / merak kancasi
    key_points: list[str] = field(default_factory=list)
    highlights: list[dict] = field(default_factory=list)   # {"t": sn, "label": "..."}
    hero_timestamp: float | None = None       # kapak icin en iyi kare
    title_candidates: list[str] = field(default_factory=list)
    thumbnail_text: str = ""        # 1-3 kelime, buyuk
    thumbnail_sub: str = ""         # kose rozeti (orn. TH16)
    thumbnail_mood: str = "action"  # action | guide | shock | chill
    faq: list[dict] = field(default_factory=list)          # {"q":..., "a":...}
    keywords: list[str] = field(default_factory=list)
    language: str = "tr"
    source: str = "heuristic"
    version: int = BRIEF_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Brief":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in (data or {}).items() if k in known}
        return cls(**clean)


# ------------------------------------------------------------------ dosya io
def brief_path(work: Path) -> Path:
    return work / "brief.json"


def save_brief(work: Path, brief: Brief) -> Path:
    return write_json(brief_path(work), brief.to_dict())


def load_brief(work: Path) -> Brief | None:
    data = read_json(brief_path(work))
    if not data:
        return None
    return Brief.from_dict(data)


# ---------------------------------------------------------------- dogrulama
def validate(brief: Brief) -> list[str]:
    """Briefte eksik/hatali ne varsa listeler (bos liste = temiz)."""
    problems: list[str] = []
    if not brief.summary or len(brief.summary) < 25:
        problems.append("summary en az 25 karakter olmali (videoda ne oldugu)")
    if not brief.title_candidates:
        problems.append("title_candidates bos - en az 3 baslik onerisi gerekiyor")
    for title in brief.title_candidates:
        if len(title) > 100:
            problems.append(f"baslik 100 karakteri asiyor: {title[:40]}...")
    if not brief.thumbnail_text:
        problems.append("thumbnail_text bos - kapak icin 1-3 kelime gerekiyor")
    elif len(brief.thumbnail_text.split()) > 4:
        problems.append("thumbnail_text en fazla 4 kelime olmali (uzaktan okunabilirlik)")
    if brief.content_type not in kw.CONTENT_TYPES:
        problems.append(
            f"content_type gecersiz: {brief.content_type} "
            f"(secenekler: {', '.join(kw.CONTENT_TYPES)})"
        )
    if not brief.hook:
        problems.append("hook bos - aciklamanin ilk cumlesi gerekiyor")
    return problems


# ---------------------------------------------------------------- heuristik
_OUTCOME_HINTS = [
    ("3 yildiz", ["3 yildiz", "3 star", "uc yildiz", "triple"]),
    ("2 yildiz", ["2 yildiz", "2 star", "iki yildiz"]),
    ("basarisiz", ["fail", "basarisiz", "yanlis", "kotu"]),
]


def heuristic_brief(
    video_name: str,
    *,
    transcript: str = "",
    duration: float = 0.0,
    motion: list[float] | None = None,
    scenes: list[float] | None = None,
) -> Brief:
    """Gorsel model olmadan, dosya adi + konusma metninden brief uretir."""
    corpus = f"{video_name} {transcript}"
    content_type = kw.detect_content_type(corpus)
    th = kw.detect_th(corpus)
    bh = kw.detect_bh(corpus)
    strategies = kw.detect_strategies(corpus)

    outcome = ""
    folded = corpus.lower()
    for label, hints in _OUTCOME_HINTS:
        if any(h in folded for h in hints):
            outcome = label
            break

    strategy_label = strategies[0].title() if strategies else "Ordu"
    th_label = th or bh or "Koy Kasabasi"
    meta = kw.CONTENT_TYPES[content_type]

    pretty_name = re.sub(r"[_\-]+", " ", video_name).strip()
    context = pretty_name.title() if len(pretty_name) < 40 else meta["label"]

    titles = []
    for formula in meta["title_formulas"]:
        titles.append(
            formula.format(
                th=th_label, bh=(bh or "BH10"), strategy=strategy_label,
                context=context, hook="Adim Adim", number="5",
            ).strip()
        )

    phrases = kw.THUMB_PHRASES.get(content_type, kw.THUMB_PHRASES["general"])
    thumb_text = phrases[0]

    highlights: list[dict] = []
    for stamp in (scenes or [])[:6]:
        if 3 < stamp < max(duration - 3, 4):
            highlights.append({"t": round(stamp, 2), "label": "Onemli an"})

    hero = None
    if motion:
        peak_index = max(range(len(motion)), key=lambda i: motion[i])
        hero = round(duration * (peak_index + 0.5) / len(motion), 2)
    elif duration:
        hero = round(duration * 0.45, 2)

    summary = (
        f"{th_label} seviyesinde {strategy_label} agirlikli bir {meta['label'].lower()}. "
        f"Videoda ordu kurulumu, acilis ve sonuc bastan sona gosteriliyor."
    )
    if outcome:
        summary += f" Sonuc: {outcome}."

    return Brief(
        video_name=video_name,
        content_type=content_type,
        town_hall=th,
        builder_hall=bh,
        strategies=strategies,
        outcome=outcome,
        summary=summary,
        hook=f"{th_label} {strategy_label} ile {meta['label'].lower()} - tum detaylar videoda.",
        key_points=[
            "Ordu kurulumu ve neden bu dizilim secildi",
            "Acilis hamlesi ve savunma agirlik merkezi",
            "Sonuca giden kritik anlar",
        ],
        highlights=highlights,
        hero_timestamp=hero,
        title_candidates=titles,
        thumbnail_text=thumb_text,
        thumbnail_sub=th or bh or "",
        thumbnail_mood="action" if content_type in {"war_attack", "legend", "funny"} else "guide",
        faq=[
            {
                "q": question.format(th=th_label, strategy=strategy_label),
                "a": answer.format(th=th_label, strategy=strategy_label),
            }
            for question, answer in kw.FAQ_TEMPLATES
        ],
        keywords=kw.keyword_pool(content_type, th, strategies)[:25],
        source="heuristic",
    )


# --------------------------------------------------------------- claude/api
ANALYSIS_SCHEMA_HINT = """{
  "content_type": "war_attack|strategy_guide|base_review|farming|upgrade|event|legend|builder|funny|general",
  "town_hall": "TH16 veya null",
  "builder_hall": "BH10 veya null",
  "strategies": ["root rider", "queen charge"],
  "outcome": "3 yildiz | 2 yildiz | 1 yildiz | basarisiz | ''",
  "summary": "2-3 cumle: videoda tam olarak ne oluyor",
  "hook": "Aciklamanin ilk cumlesi. Merak uyandirsin, anahtar kelime icersin. <=150 karakter",
  "key_points": ["izleyicinin ogrenecegi 3-5 madde"],
  "highlights": [{"t": 12.5, "label": "Kralice yuruyusu basliyor"}],
  "hero_timestamp": 42.0,
  "title_candidates": ["3 farkli baslik - <=70 karakter, anahtar kelime basta, merak kancasi"],
  "thumbnail_text": "EN FAZLA 3 KELIME, BUYUK HARF",
  "thumbnail_sub": "TH16",
  "thumbnail_mood": "action|guide|shock|chill",
  "faq": [{"q": "izleyicinin arayacagi soru", "a": "1-2 cumlelik net cevap"}],
  "keywords": ["15-25 arama terimi, Turkce + Ingilizce karisik"]
}"""


def write_analysis_request(
    work: Path,
    *,
    video_name: str,
    media: dict,
    frames: list[Path],
    scenes: list[float],
    motion: list[float],
    transcript: str,
) -> Path:
    """Claude'un okuyacagi analiz paketini yazar (kareler + teknik veri + sablon)."""
    request = {
        "video_name": video_name,
        "media": media,
        "frame_files": [str(p) for p in frames],
        "frame_timestamps": [_stamp_of(p) for p in frames],
        "scene_cuts": scenes[:40],
        "motion_profile": motion,
        "transcript_excerpt": transcript[:6000],
        "brief_schema": json.loads(_schema_as_json()),
    }
    path = work / "analysis_request.json"
    write_json(path, request)

    frame_list = "\n".join(
        f"  {i + 1:2d}. {p.name}   (video zamani {hhmmss(_stamp_of(p))})"
        for i, p in enumerate(frames)
    )
    prompt = f"""# Analiz Gorevi: {video_name}

Bu bir Clash of Clans ekran kaydi. Asagidaki kareleri **Read araciyla tek tek ac ve gercekten bak**,
sonra `brief.json` dosyasini yaz.

## Teknik veri
- Sure: {hhmmss(media.get('duration', 0))}
- Cozunurluk: {media.get('width')}x{media.get('height')} @ {media.get('fps')}fps
- Ses: {'var' if media.get('has_audio') else 'yok'}
- Sahne kesimi sayisi: {len(scenes)}

## Kareler (klasor: {work / 'frames'})
{frame_list}

## Konusma metni (varsa)
{(transcript[:1500] or '(ses yok / konusma alinamadi)')}

## Ne uretmelisin
`{work / 'brief.json'}` dosyasini tam olarak su semada yaz:

```json
{ANALYSIS_SCHEMA_HINT}
```

### Kurallar
1. **Karelere bak.** Koy kasabasi seviyesini, kullanilan birlikleri, saldirinin sonucunu
   (yildiz sayisi, yuzde) ekrandaki arayuzden oku. Tahmin etme, gordugunu yaz.
2. `hero_timestamp` kapak icin kullanilacak: en dramatik, en dolu, en renkli an olsun.
   Kara ekran, menu, yukleme ekrani secme.
3. `title_candidates` 3 adet olsun; hepsi 70 karakteri gecmesin, anahtar kelime bas tarafta
   olsun, biri merak kancasi, biri net fayda, biri sayisal/sonuc odakli.
4. `thumbnail_text` en fazla 3 kelime, TAMAMI BUYUK HARF, telefonda okunacak kadar kisa.
5. `faq` uretken arama motorlari icin: izleyicinin Google/YouTube'a yazacagi gercek sorular.
6. Turkce yaz (keywords icinde Ingilizce terimler olabilir).

Yazdiktan sonra: `huscc render "{video_name}"`
"""
    (work / "ANALIZ.md").write_text(prompt, encoding="utf-8")
    return path


def _schema_as_json() -> str:
    """Sema ipucunu gecerli JSON'a cevirir (yorum benzeri degerler string kalir)."""
    return json.dumps(
        {
            "content_type": "war_attack",
            "town_hall": "TH16",
            "builder_hall": None,
            "strategies": ["root rider"],
            "outcome": "3 yildiz",
            "summary": "",
            "hook": "",
            "key_points": [],
            "highlights": [{"t": 0.0, "label": ""}],
            "hero_timestamp": 0.0,
            "title_candidates": [],
            "thumbnail_text": "",
            "thumbnail_sub": "",
            "thumbnail_mood": "action",
            "faq": [{"q": "", "a": ""}],
            "keywords": [],
        },
        ensure_ascii=False,
    )


_STAMP_RE = re.compile(r"_(\d+)s\.jpg$")


def _stamp_of(path: Path) -> float:
    match = _STAMP_RE.search(path.name)
    return float(match.group(1)) if match else 0.0


# ------------------------------------------------------------------ API yolu
def api_brief(
    frames: list[Path],
    *,
    video_name: str,
    media: dict,
    transcript: str,
    fallback: Brief,
) -> Brief:
    """ANTHROPIC_API_KEY veya OPENAI_API_KEY varsa gorsel modelle brief uretir."""
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not (anthropic_key or openai_key):
        raise HusccError(
            "API beyni icin ANTHROPIC_API_KEY veya OPENAI_API_KEY gerekiyor "
            "(.env dosyasina ekleyin) ya da --brain claude-code kullanin."
        )

    picked = _spread(frames, 10)
    instruction = (
        "Sen bir Clash of Clans YouTube kanalinin icerik stratejistisin. "
        "Verilen kareleri incele ve SADECE gecerli JSON dondur (aciklama yazma).\n\n"
        f"Video dosya adi: {video_name}\n"
        f"Sure: {hhmmss(media.get('duration', 0))}\n"
        f"Konusma metni: {transcript[:2000] or '(yok)'}\n\n"
        f"Istenen JSON semasi:\n{ANALYSIS_SCHEMA_HINT}\n\n"
        "Turkce yaz. Basliklar 70 karakteri gecmesin. thumbnail_text en fazla 3 kelime."
    )

    try:
        if anthropic_key:
            raw = _call_anthropic(anthropic_key, instruction, picked)
        else:
            raw = _call_openai(openai_key or "", instruction, picked)
        data = _extract_json(raw)
        brief = Brief.from_dict({**fallback.to_dict(), **data})
        brief.video_name = video_name
        brief.source = "anthropic-api" if anthropic_key else "openai-api"
        return brief
    except Exception as exc:  # pragma: no cover - ag hatalari
        warn(f"API beyni basarisiz ({exc}); heuristik brief kullanilacak.")
        return fallback


def _spread(items: list[Path], count: int) -> list[Path]:
    if len(items) <= count:
        return items
    stride = len(items) / count
    return [items[int(i * stride)] for i in range(count)]


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _call_anthropic(api_key: str, instruction: str, frames: list[Path]) -> str:
    import requests

    content: list[dict[str, Any]] = []
    for frame in frames:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": _b64(frame),
                },
            }
        )
    content.append({"type": "text", "text": instruction})

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": os.environ.get("HUSCC_ANTHROPIC_MODEL", "claude-sonnet-5"),
            "max_tokens": 3000,
            "messages": [{"role": "user", "content": content}],
        },
        timeout=180,
    )
    response.raise_for_status()
    blocks = response.json().get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _call_openai(api_key: str, instruction: str, frames: list[Path]) -> str:
    import requests

    content: list[dict[str, Any]] = [{"type": "text", "text": instruction}]
    for frame in frames:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{_b64(frame)}"},
            }
        )
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("HUSCC_OPENAI_MODEL", "gpt-4o"),
            "max_tokens": 3000,
            "messages": [{"role": "user", "content": content}],
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _extract_json(text: str) -> dict:
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise HusccError("Model gecerli JSON dondurmedi")
    return json.loads(text[start : end + 1])


# ------------------------------------------------------------------ yardimci
def normalize(brief: Brief) -> Brief:
    """Brief'i temizler: bosluklar, buyuk harf, uzunluk sinirlari."""
    brief.thumbnail_text = tr_upper(brief.thumbnail_text.strip())[:28]
    brief.thumbnail_sub = brief.thumbnail_sub.strip()[:10]
    brief.title_candidates = [t.strip() for t in brief.title_candidates if t and t.strip()]
    brief.hook = " ".join(brief.hook.split())[:200]
    brief.summary = " ".join(brief.summary.split())
    brief.keywords = [k.strip().lower() for k in brief.keywords if k and k.strip()]
    brief.highlights = sorted(
        [h for h in brief.highlights if isinstance(h, dict) and "t" in h],
        key=lambda h: float(h.get("t", 0)),
    )
    if brief.content_type not in kw.CONTENT_TYPES:
        brief.content_type = "general"
    return brief
