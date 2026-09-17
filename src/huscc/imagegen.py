"""Yapay zeka gorsel uretimi (ChatGPT / gpt-image-1).

Kapak arka plani dort yoldan gelebilir, sirayla denenir:

  1. api             : OPENAI_API_KEY ile gpt-image-1 cagrilir (en hizli)
  2. chatgpt-browser : HusCC'nin kendi Chrome oturumunda ChatGPT acilir, prompt
                       yazilir, uretilen gorsel indirilir. Anahtar gerekmez;
                       yalnizca bir kez `huscc login --only chatgpt` yeterli.
  3. elle devir      : Prompt panoya kopyalanir, kullanici gorseli
                       `work/<slug>/ai/` klasorune birakir, CLI onu alir.
  4. frame           : Videodan secilen kare (internet gerekmez)

Metin her zaman PIL ile ustune yazilir: gorsel modelleri Turkce tipografide
(ozellikle ı, ş, ğ) guvenilir degil, kapak yazisi okunakli olmak zorunda.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from . import keywords as kw
from .brief import Brief
from .util import HusccError, ensure_dir, info, ok, warn

CHATGPT_URL = "https://chatgpt.com/"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# Gorsel modeline verilecek uslup cercevesi
_STYLE = (
    "mobile strategy game cinematic key art in the style of Clash of Clans: "
    "bright saturated colors, chunky stylized 3D cartoon rendering, thick outlines, "
    "dramatic rim lighting, high contrast, clean readable silhouettes, "
    "epic battle atmosphere, no text, no letters, no watermark, no UI overlay"
)

_MOOD = {
    "action": "explosive mid-battle moment, smoke and fire, debris flying, intense",
    "shock": "dramatic freeze-frame, glowing highlight on the key subject, high tension",
    "guide": "clear tactical overview, calm confident hero character in focus, tidy composition",
    "chill": "warm relaxed village scene, soft golden light, friendly mood",
}

_TYPE_SCENE = {
    "war_attack": "an all-out clan war assault: troops breaking through walls of a maxed enemy base, three golden stars bursting in the sky",
    "strategy_guide": "a commander planning an attack over a glowing tactical map of an enemy village, troop icons arranged in formation",
    "base_review": "a heavily fortified village layout seen from a low dramatic angle, defenses glowing, shield energy dome",
    "farming": "piles of gold and elixir loot exploding out of storages, treasure spilling everywhere",
    "upgrade": "a builder hammering a glowing upgrading building, scaffolding and sparks, progress arrows rising",
    "event": "a festive seasonal event banner over the village, fireworks and new special troops appearing",
    "legend": "a champion standing on a mountain of trophies under a legendary purple sky",
    "builder": "the builder base at night, master builder machines clashing, neon blue energy",
    "funny": "a chaotic comedic battle mishap, exaggerated expressions, cartoon slapstick energy",
    "general": "a sprawling village under attack at golden hour, troops charging across the field",
}


def build_prompt(brief: Brief, *, channel_game: str = "Clash of Clans", for_outro: bool = False) -> str:
    """Brief'ten gorsel modeli icin ayrintili, Ingilizce prompt uretir."""
    scene = _TYPE_SCENE.get(brief.content_type, _TYPE_SCENE["general"])
    mood = _MOOD.get(brief.thumbnail_mood, _MOOD["action"])
    th = brief.town_hall or brief.builder_hall or ""
    troops = ", ".join(brief.strategies[:3])

    bits = [f"YouTube thumbnail background for a {channel_game} video."]
    bits.append(f"Scene: {scene}.")
    if troops:
        bits.append(f"Featured troops: {troops}, clearly recognizable and heroic.")
    if th:
        bits.append(f"Town hall level {th.replace('TH', '').replace('BH', '')} era architecture and visual power level.")
    if brief.outcome:
        outcome_en = {
            "3 yildiz": "a decisive total victory, three stars",
            "2 yildiz": "a hard-fought partial victory",
            "1 yildiz": "a narrow result, tension",
            "basarisiz": "a dramatic failed assault, defenders holding",
        }.get(brief.outcome, "")
        if outcome_en:
            bits.append(f"Outcome to convey: {outcome_en}.")
    bits.append(f"Mood: {mood}.")
    bits.append(_STYLE + ".")

    if for_outro:
        bits.append(
            "Composition: wide horizontal 16:9, the subject pushed to the LEFT third, "
            "the RIGHT half kept simple and uncluttered so end screen cards fit there. "
            "Slightly darker overall so white text stays readable."
        )
    else:
        bits.append(
            "Composition: 16:9, one single clear focal subject in the RIGHT two thirds, "
            "the BOTTOM LEFT third kept visually simple and darker so large text can be "
            "placed there. Shot from a dynamic low angle. Shallow depth of field. "
            "Extremely high contrast so it reads at thumbnail size on a phone."
        )
    return " ".join(bits)


# ------------------------------------------------------------------ 1. API
def generate_api(prompt: str, out_path: Path, *, size: str = "1536x1024") -> Path:
    """OpenAI Images API (gpt-image-1) ile gorsel uretir."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HusccError("OPENAI_API_KEY yok (.env dosyasina ekleyin).")

    import requests

    model = os.environ.get("HUSCC_IMAGE_MODEL", "gpt-image-1")
    info(f"ChatGPT gorsel uretimi ({model})...")
    response = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "prompt": prompt[:3900], "size": size, "n": 1},
        timeout=300,
    )
    if response.status_code >= 400:
        raise HusccError(f"Gorsel API hatasi {response.status_code}: {response.text[:400]}")

    payload = response.json().get("data", [{}])[0]
    ensure_dir(out_path.parent)
    if payload.get("b64_json"):
        out_path.write_bytes(base64.b64decode(payload["b64_json"]))
    elif payload.get("url"):
        image = requests.get(payload["url"], timeout=180)
        image.raise_for_status()
        out_path.write_bytes(image.content)
    else:
        raise HusccError("Gorsel API bos yanit dondurdu.")
    ok(f"Yapay zeka gorseli hazir: {out_path.name}")
    return out_path


# -------------------------------------------------- 2a. ChatGPT'yi surerek
def generate_with_chatgpt(session, prompt: str, out_path: Path, *, timeout: float = 420.0):
    """Acik ChatGPT oturumunda prompt'u yazip uretilen gorseli indirir.

    Basarisiz olursa None doner; boru hatti video karesine ya da elle devre
    akisina duser. Hicbir durumda yayini bloklamaz.
    """
    from . import platforms

    chatgpt = platforms.by_key("chatgpt")
    if not platforms.is_signed_in(session, chatgpt):
        warn("ChatGPT oturumu yok - 'huscc login --only chatgpt' ile giris yapin.")
        return None

    info("ChatGPT'de kapak gorseli uretiliyor...")
    try:
        box = session.find("chatgpt_input", timeout=20_000)
        box.click(timeout=8_000)
        session.page.wait_for_timeout(300)
        # Uzun metni tek seferde yaz (harf harf yazmak cok yavas)
        session.page.keyboard.insert_text(
            "Generate a single 16:9 image. " + prompt
        )
        session.page.wait_for_timeout(600)

        if not session.click("chatgpt_send", timeout=8_000, required=False):
            session.page.keyboard.press("Enter")
        session.shot("chatgpt-istek")

        deadline = time.time() + timeout
        last_src = ""
        stable_since = 0.0
        while time.time() < deadline:
            session.page.wait_for_timeout(3_000)
            node = session.find("chatgpt_generated_image", timeout=2_000, required=False)
            if node is not None:
                try:
                    src = node.get_attribute("src") or ""
                except Exception:
                    src = ""
                if src and src.startswith("http"):
                    # Uretim bitene kadar gorsel degisebilir; sabitlenmesini bekle
                    if src == last_src:
                        if stable_since and time.time() - stable_since > 4:
                            return _download(session, src, out_path)
                    else:
                        last_src, stable_since = src, time.time()
            still_working = session.exists("chatgpt_stop_button", timeout=1_000)
            if not still_working and last_src:
                return _download(session, last_src, out_path)
        warn("ChatGPT gorseli zamaninda gelmedi.")
        return None
    except Exception as exc:  # noqa: BLE001
        warn(f"ChatGPT surulemedi: {exc}")
        session.shot("chatgpt-hata")
        return None


def _download(session, url: str, out_path: Path):
    """Gorseli tarayicinin oturumuyla indirir (imzali adresler icin sart)."""
    try:
        response = session.context.request.get(url, timeout=120_000)
        if not response.ok:
            warn(f"Gorsel indirilemedi: HTTP {response.status}")
            return None
        ensure_dir(out_path.parent)
        out_path.write_bytes(response.body())
        ok(f"ChatGPT gorseli kaydedildi: {out_path.name}")
        return out_path
    except Exception as exc:  # noqa: BLE001
        warn(f"Gorsel indirilemedi: {exc}")
        return None


# -------------------------------------------------------------- 2b. tarayici
def copy_to_clipboard(text: str) -> bool:
    """Prompt'u panoya kopyalar (Windows/mac/Linux)."""
    try:
        if sys.platform == "win32":
            subprocess.run("clip", input=text, text=True, encoding="utf-16-le", check=True)
            return True
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
            return True
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
        return True
    except Exception:
        return False


def browser_handoff(
    prompt: str,
    drop_dir: Path,
    *,
    timeout: float = 420.0,
    open_browser: bool = True,
) -> Path | None:
    """Prompt'u panoya koyar, ChatGPT'yi varsayilan tarayicida acar, gorseli bekler.

    Kullanici uretilen gorseli `drop_dir` icine indirince dosya otomatik alinir.
    """
    ensure_dir(drop_dir)
    (drop_dir / "PROMPT.txt").write_text(prompt, encoding="utf-8")
    before = {p.name for p in drop_dir.iterdir() if p.suffix.lower() in IMAGE_EXT}

    copied = copy_to_clipboard(prompt)
    print()
    print("=" * 70)
    print("  CHATGPT GORSEL ADIMI")
    print("=" * 70)
    print("  1. Acilan ChatGPT sekmesine prompt'u yapistir (Ctrl+V)"
          + ("  [panoya kopyalandi]" if copied else "  [prompt: " + str(drop_dir / 'PROMPT.txt') + "]"))
    print("  2. Uretilen gorseli indir")
    print(f"  3. Su klasore birak: {drop_dir}")
    print("  (Beklemeyi iptal etmek icin Ctrl+C - kapak video karesinden uretilir)")
    print("=" * 70)
    print()

    if open_browser:
        try:
            webbrowser.open(CHATGPT_URL)
        except Exception:
            warn(f"Tarayici acilamadi, elle acin: {CHATGPT_URL}")

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            found = [
                p for p in drop_dir.iterdir()
                if p.suffix.lower() in IMAGE_EXT and p.name not in before
            ]
            if found:
                newest = max(found, key=lambda p: p.stat().st_mtime)
                # Dosyanin tamamen yazilmasini bekle
                size = -1
                while size != newest.stat().st_size:
                    size = newest.stat().st_size
                    time.sleep(0.4)
                ok(f"Gorsel alindi: {newest.name}")
                return newest
            time.sleep(1.0)
    except KeyboardInterrupt:
        warn("Bekleme iptal edildi.")
        return None
    warn("Sure doldu - gorsel gelmedi.")
    return None


def latest_dropped(drop_dir: Path) -> Path | None:
    """Klasorde hazir bekleyen en yeni gorseli dondurur."""
    if not drop_dir.exists():
        return None
    images = [p for p in drop_dir.iterdir() if p.suffix.lower() in IMAGE_EXT]
    if not images:
        return None
    return max(images, key=lambda p: p.stat().st_mtime)


# --------------------------------------------------------------- yonlendirme
def acquire_background(
    brief: Brief,
    work: Path,
    *,
    source: str = "auto",
    channel_game: str = "Clash of Clans",
    for_outro: bool = False,
    wait_seconds: float = 420.0,
    interactive: bool = True,
    session=None,
) -> tuple[Path | None, str]:
    """Kapak arka planini secilen kaynaktan getirir.

    Donen: (gorsel yolu veya None, kullanilan kaynak)
    """
    kind = "outro" if for_outro else "thumb"
    ai_dir = ensure_dir(work / "ai")
    target = ai_dir / f"{kind}_ai.png"
    prompt = build_prompt(brief, channel_game=channel_game, for_outro=for_outro)
    (ai_dir / f"{kind}_prompt.txt").write_text(prompt, encoding="utf-8")

    if source == "frame":
        return None, "frame"

    # Daha once uretilmis gorsel varsa yeniden uretme
    if target.exists() and target.stat().st_size > 10_000:
        info(f"Mevcut yapay zeka gorseli kullaniliyor: {target.name}")
        return target, "cache"

    has_key = bool(os.environ.get("OPENAI_API_KEY"))
    if source in {"api", "auto"} and has_key:
        try:
            return generate_api(prompt, target), "api"
        except HusccError as exc:
            warn(f"Gorsel API basarisiz: {exc}")
            if source == "api":
                return None, "frame"

    # Tarayici oturumu verilmisse ChatGPT'yi dogrudan sur
    if source in {"browser", "auto"} and session is not None:
        produced = generate_with_chatgpt(session, prompt, target, timeout=wait_seconds)
        if produced:
            return produced, "chatgpt-browser"

    if source in {"browser", "auto"}:
        dropped = latest_dropped(ai_dir)
        if dropped and dropped.name != target.name:
            info(f"Klasorde bekleyen gorsel bulundu: {dropped.name}")
            target.write_bytes(dropped.read_bytes())
            return target, "browser"
        if interactive and source == "browser":
            result = browser_handoff(prompt, ai_dir, timeout=wait_seconds)
            if result:
                target.write_bytes(result.read_bytes())
                return target, "browser"
        elif source == "auto" and not has_key:
            info("OPENAI_API_KEY yok - kapak video karesinden uretilecek.")
            info(f"ChatGPT ile uretmek isterseniz prompt: {ai_dir / f'{kind}_prompt.txt'}")

    return None, "frame"
