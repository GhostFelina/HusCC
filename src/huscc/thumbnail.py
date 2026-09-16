"""Kapak (thumbnail) uretimi.

Yaklasim: videodan aday kareler cikarilir, her kare "kapak olabilirlik" puani
alir (keskinlik + renk zenginligi + kontrast + yuz/arayuz yogunlugu), en iyisi
uzerine CTR odakli tipografi ve grafik katmanlari bindirilir.
Uc farkli sablon uretilir; en yuksek okunabilirlik puanini alan varsayilan olur.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .util import HusccError, ensure_dir, tr_upper, warn

# ------------------------------------------------------------------- fontlar
_SYSTEM_FONTS = [
    "C:/Windows/Fonts/ariblk.ttf",      # Arial Black - Turkce tam destek
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/seguibl.ttf",     # Segoe UI Black
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def resolve_font(assets_dir: Path, *, bold: bool = True) -> Path:
    """Once depodaki fontlar, sonra sistem fontlari."""
    fonts_dir = assets_dir / "fonts"
    if fonts_dir.exists():
        preferred = ["Anton-Regular.ttf", "BebasNeue-Regular.ttf", "Montserrat-ExtraBold.ttf"]
        for name in preferred:
            candidate = fonts_dir / name
            if candidate.exists():
                return candidate
        for candidate in sorted(fonts_dir.glob("*.ttf")):
            return candidate
    for path in _SYSTEM_FONTS:
        if Path(path).exists():
            return Path(path)
    raise HusccError("Kapak icin kalin bir font bulunamadi (assets/fonts/ klasorune .ttf koyun)")


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


# ------------------------------------------------------------- kare puanlama
@dataclass
class FrameScore:
    path: Path
    sharpness: float
    colorfulness: float
    contrast: float
    brightness: float
    total: float


def _score_image(path: Path) -> FrameScore:
    with Image.open(path) as image:
        rgb = image.convert("RGB").resize((320, 180))
        arr = np.asarray(rgb, dtype=np.float32)

    grey = arr.mean(axis=2)
    # Laplacian benzeri keskinlik
    gx = np.abs(np.diff(grey, axis=1)).mean()
    gy = np.abs(np.diff(grey, axis=0)).mean()
    sharpness = float(gx + gy)

    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    rg = np.abs(red - green)
    yb = np.abs(0.5 * (red + green) - blue)
    colorfulness = float(
        math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )
    contrast = float(grey.std())
    brightness = float(grey.mean())

    # Cok karanlik veya patlamis kareleri cezalandir
    penalty = 0.0
    if brightness < 40:
        penalty += (40 - brightness) * 1.5
    if brightness > 215:
        penalty += (brightness - 215) * 1.5

    total = sharpness * 2.2 + colorfulness * 1.4 + contrast * 1.1 - penalty
    return FrameScore(path, sharpness, colorfulness, contrast, brightness, total)


def pick_hero(frames: list[Path], preferred: Path | None = None) -> Path:
    """Kapak icin en iyi kareyi secer."""
    if preferred and preferred.exists():
        return preferred
    if not frames:
        raise HusccError("Kapak icin kare bulunamadi")
    scored = [_score_image(f) for f in frames]
    scored.sort(key=lambda s: s.total, reverse=True)
    return scored[0].path


# ------------------------------------------------------------------ renkler
def _hex(value: str, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return fallback


# ---------------------------------------------------------------- yardimcilar
def _fit_cover(image: Image.Image, size: tuple[int, int], focus: float = 0.5) -> Image.Image:
    """Hedef orana kirparak sigdirir; focus yatay odak noktasi (0-1)."""
    target_w, target_h = size
    src_w, src_h = image.size
    scale = max(target_w / src_w, target_h / src_h)
    new_size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
    resized = image.resize(new_size, Image.LANCZOS)
    max_left = max(0, resized.width - target_w)
    left = int(max_left * focus)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _grade(image: Image.Image) -> Image.Image:
    """Kapak icin renk/kontrast/keskinlik islemesi - kucuk boyutta bile canli dursun."""
    image = ImageEnhance.Color(image).enhance(1.32)
    image = ImageEnhance.Contrast(image).enhance(1.18)
    image = ImageEnhance.Brightness(image).enhance(1.04)
    image = image.filter(ImageFilter.UnsharpMask(radius=2.2, percent=135, threshold=3))
    return image


def _vignette(image: Image.Image, strength: float = 0.55) -> Image.Image:
    width, height = image.size
    xs = np.linspace(-1, 1, width, dtype=np.float32)[None, :]
    ys = np.linspace(-1, 1, height, dtype=np.float32)[:, None]
    radius = np.sqrt(xs**2 + ys**2) / math.sqrt(2)
    mask = np.clip(1 - strength * radius**2.1, 0, 1)
    arr = np.asarray(image, dtype=np.float32) * mask[..., None]
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _autosize(
    text: str,
    font_path: Path,
    draw: ImageDraw.ImageDraw,
    *,
    max_width: int,
    max_height: int,
    start: int,
    min_size: int = 40,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = start
    while size > min_size:
        font = _font(font_path, size)
        lines = _wrap(text, font, max_width, draw)
        line_h = int(size * 1.08)
        if len(lines) * line_h <= max_height and all(
            draw.textlength(line, font=font) <= max_width for line in lines
        ):
            return font, lines
        size -= 4
    font = _font(font_path, min_size)
    return font, _wrap(text, font, max_width, draw)


def _text_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    *,
    origin: tuple[int, int],
    fill: tuple[int, int, int],
    stroke: tuple[int, int, int],
    stroke_width: int,
    line_gap: float = 1.06,
    shadow: bool = True,
    align_center: bool = False,
    block_width: int = 0,
) -> int:
    x, y = origin
    size = font.size
    for line in lines:
        line_w = draw.textlength(line, font=font)
        draw_x = x + (block_width - line_w) / 2 if align_center and block_width else x
        if shadow:
            draw.text(
                (draw_x + size * 0.055, y + size * 0.075), line, font=font,
                fill=(0, 0, 0), stroke_width=stroke_width, stroke_fill=(0, 0, 0),
            )
        draw.text(
            (draw_x, y), line, font=font, fill=fill,
            stroke_width=stroke_width, stroke_fill=stroke,
        )
        y += int(size * line_gap)
    return y


def _badge(
    canvas: Image.Image,
    text: str,
    font_path: Path,
    *,
    color: tuple[int, int, int],
    corner: str = "tr",
) -> None:
    if not text:
        return
    draw = ImageDraw.Draw(canvas)
    size = int(canvas.height * 0.085)
    font = _font(font_path, size)
    pad_x, pad_y = int(size * 0.45), int(size * 0.22)
    text_w = draw.textlength(text, font=font)
    box_w, box_h = int(text_w + pad_x * 2), int(size * 1.34 + pad_y)
    margin = int(canvas.height * 0.045)
    x = canvas.width - box_w - margin if corner.endswith("r") else margin
    y = margin if corner.startswith("t") else canvas.height - box_h - margin

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    layer_draw.rounded_rectangle(
        [x, y, x + box_w, y + box_h], radius=int(box_h * 0.22),
        fill=(*color, 240), outline=(255, 255, 255, 235), width=max(3, int(size * 0.07)),
    )
    canvas.alpha_composite(layer)
    ImageDraw.Draw(canvas).text(
        (x + pad_x, y + pad_y * 0.4), text, font=font, fill=(10, 14, 22),
        stroke_width=0,
    )


def _accent_bar(canvas: Image.Image, color: tuple[int, int, int], height_ratio: float = 0.022) -> None:
    height = max(6, int(canvas.height * height_ratio))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, canvas.height - height, canvas.width, canvas.height], fill=(*color, 255))


def _arrow(canvas: Image.Image, color: tuple[int, int, int], *, at: tuple[float, float], size_ratio: float = 0.14) -> None:
    """Dikkat oku - bakisi hedefe cekmek icin."""
    width, height = canvas.size
    size = height * size_ratio
    cx, cy = width * at[0], height * at[1]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    points = [
        (cx - size, cy - size * 0.32),
        (cx + size * 0.18, cy - size * 0.32),
        (cx + size * 0.18, cy - size * 0.72),
        (cx + size, cy),
        (cx + size * 0.18, cy + size * 0.72),
        (cx + size * 0.18, cy + size * 0.32),
        (cx - size, cy + size * 0.32),
    ]
    draw.polygon(points, fill=(*color, 245), outline=(255, 255, 255, 240))
    layer = layer.filter(ImageFilter.GaussianBlur(0.6))
    canvas.alpha_composite(layer)


def _circle_highlight(canvas: Image.Image, color: tuple[int, int, int], *, at: tuple[float, float], radius_ratio: float = 0.17) -> None:
    width, height = canvas.size
    radius = height * radius_ratio
    cx, cy = width * at[0], height * at[1]
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    thickness = max(6, int(height * 0.014))
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=(*color, 250), width=thickness,
    )
    canvas.alpha_composite(layer)


def _gradient_panel(
    canvas: Image.Image,
    *,
    side: str = "left",
    width_ratio: float = 0.52,
    color: tuple[int, int, int] = (11, 18, 32),
    strength: int = 232,
) -> None:
    width, height = canvas.size
    panel_w = int(width * width_ratio)
    gradient = np.zeros((height, panel_w, 4), dtype=np.uint8)
    ramp = np.linspace(strength, 0, panel_w, dtype=np.float32)
    if side == "right":
        ramp = ramp[::-1]
    gradient[..., 0] = color[0]
    gradient[..., 1] = color[1]
    gradient[..., 2] = color[2]
    gradient[..., 3] = ramp[None, :].astype(np.uint8)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(Image.fromarray(gradient, "RGBA"), (0 if side == "left" else width - panel_w, 0))
    canvas.alpha_composite(layer)


def _bottom_scrim(canvas: Image.Image, ratio: float = 0.46, strength: int = 215) -> None:
    width, height = canvas.size
    band = int(height * ratio)
    gradient = np.zeros((band, width, 4), dtype=np.uint8)
    ramp = np.linspace(0, strength, band, dtype=np.float32)
    gradient[..., 3] = ramp[:, None].astype(np.uint8)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    layer.paste(Image.fromarray(gradient, "RGBA"), (0, height - band))
    canvas.alpha_composite(layer)


# ------------------------------------------------------------------ sablonlar
def _template_bold_bottom(base: Image.Image, text: str, badge: str, palette: dict, font_path: Path) -> Image.Image:
    canvas = base.copy().convert("RGBA")
    _bottom_scrim(canvas, 0.5, 222)
    draw = ImageDraw.Draw(canvas)
    margin = int(canvas.width * 0.045)
    max_width = int(canvas.width * 0.80)
    max_height = int(canvas.height * 0.42)
    font, lines = _autosize(
        text, font_path, draw, max_width=max_width, max_height=max_height,
        start=int(canvas.height * 0.22),
    )
    total_h = int(len(lines) * font.size * 1.06)
    y = canvas.height - total_h - int(canvas.height * 0.10)
    _text_block(
        draw, lines, font, origin=(margin, y),
        fill=palette["light"], stroke=(8, 10, 16),
        stroke_width=max(6, int(font.size * 0.085)),
    )
    _accent_bar(canvas, palette["primary"])
    _badge(canvas, badge, font_path, color=palette["primary"], corner="tr")
    return canvas


def _template_split_panel(base: Image.Image, text: str, badge: str, palette: dict, font_path: Path) -> Image.Image:
    canvas = base.copy().convert("RGBA")
    _gradient_panel(canvas, side="left", width_ratio=0.62, color=palette["dark"], strength=240)
    draw = ImageDraw.Draw(canvas)
    margin = int(canvas.width * 0.05)
    max_width = int(canvas.width * 0.46)
    max_height = int(canvas.height * 0.62)
    font, lines = _autosize(
        text, font_path, draw, max_width=max_width, max_height=max_height,
        start=int(canvas.height * 0.21),
    )
    total_h = int(len(lines) * font.size * 1.08)
    y = (canvas.height - total_h) // 2
    # Vurgu cizgisi
    bar_w = max(8, int(canvas.width * 0.009))
    draw.rectangle(
        [margin - bar_w * 2, y, margin - bar_w, y + total_h], fill=(*palette["primary"], 255)
    )
    _text_block(
        draw, lines, font, origin=(margin, y),
        fill=palette["light"], stroke=(8, 10, 16),
        stroke_width=max(5, int(font.size * 0.07)),
    )
    _badge(canvas, badge, font_path, color=palette["secondary"], corner="br")
    _accent_bar(canvas, palette["primary"], height_ratio=0.018)
    return canvas


def _template_shock_top(base: Image.Image, text: str, badge: str, palette: dict, font_path: Path) -> Image.Image:
    canvas = base.copy().convert("RGBA")
    # Ust banda koyu serit
    width, height = canvas.size
    band = int(height * 0.34)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle([0, 0, width, band], fill=(*palette["dark"], 226))
    canvas.alpha_composite(layer)

    draw = ImageDraw.Draw(canvas)
    margin = int(width * 0.04)
    font, lines = _autosize(
        text, font_path, draw, max_width=int(width * 0.92),
        max_height=int(band * 0.82), start=int(height * 0.19),
    )
    total_h = int(len(lines) * font.size * 1.04)
    y = (band - total_h) // 2
    _text_block(
        draw, lines, font, origin=(margin, y), fill=palette["primary"],
        stroke=(8, 10, 16), stroke_width=max(5, int(font.size * 0.08)),
        align_center=True, block_width=width - margin * 2,
    )
    _circle_highlight(canvas, palette["secondary"], at=(0.72, 0.68), radius_ratio=0.16)
    _arrow(canvas, palette["secondary"], at=(0.40, 0.68), size_ratio=0.10)
    _badge(canvas, badge, font_path, color=palette["primary"], corner="bl")
    return canvas


TEMPLATES = {
    "bold_bottom": _template_bold_bottom,
    "split_panel": _template_split_panel,
    "shock_top": _template_shock_top,
}

_MOOD_ORDER = {
    "action": ["bold_bottom", "shock_top", "split_panel"],
    "shock": ["shock_top", "bold_bottom", "split_panel"],
    "guide": ["split_panel", "bold_bottom", "shock_top"],
    "chill": ["split_panel", "shock_top", "bold_bottom"],
}


# ------------------------------------------------------------------ okunurluk
def readability_score(image: Image.Image) -> float:
    """Kucuk boyutta (telefon) okunabilirlik tahmini: kenar yogunlugu + kontrast."""
    small = image.convert("RGB").resize((214, 120))
    arr = np.asarray(small, dtype=np.float32).mean(axis=2)
    edges = np.abs(np.diff(arr, axis=1)).mean() + np.abs(np.diff(arr, axis=0)).mean()
    contrast = arr.std()
    # Asiri kalabalik da kotu: kenar yogunlugu cok yuksekse cezalandir
    penalty = max(0.0, edges - 26) * 2.0
    return float(edges * 1.6 + contrast * 1.2 - penalty)


# ---------------------------------------------------------------------- API
def generate(
    *,
    hero: Path,
    text: str,
    badge: str,
    out_dir: Path,
    palette_cfg: dict,
    font_path: Path,
    size: tuple[int, int] = (1280, 720),
    mood: str = "action",
    variants: int = 3,
    seed: int = 7,
) -> tuple[Path, list[Path]]:
    """Kapak varyantlarini uretir; (secilen, tum_varyantlar) dondurur."""
    ensure_dir(out_dir)
    random.seed(seed)

    palette = {
        "primary": _hex(str(palette_cfg.get("primary", "#FFC400")), (255, 196, 0)),
        "secondary": _hex(str(palette_cfg.get("secondary", "#E63946")), (230, 57, 70)),
        "dark": _hex(str(palette_cfg.get("dark", "#0B1220")), (11, 18, 32)),
        "light": _hex(str(palette_cfg.get("light", "#FFFFFF")), (255, 255, 255)),
    }

    with Image.open(hero) as raw:
        source = raw.convert("RGB")

    text = tr_upper(text.strip()) or "CLASH OF CLANS"
    badge = badge.strip()

    order = _MOOD_ORDER.get(mood, _MOOD_ORDER["action"])
    produced: list[tuple[Path, float]] = []

    for index, name in enumerate(order[: max(1, variants)]):
        focus = 0.5 if name != "split_panel" else 0.72
        base = _fit_cover(source, size, focus=focus)
        base = _grade(base)
        base = _vignette(base, 0.45 if name == "split_panel" else 0.55)
        canvas = TEMPLATES[name](base, text, badge, palette, font_path)
        flat = canvas.convert("RGB")
        path = out_dir / f"thumb_{index + 1}_{name}.jpg"
        flat.save(path, "JPEG", quality=92, optimize=True, progressive=True)
        produced.append((path, readability_score(flat)))

    produced.sort(key=lambda item: item[1], reverse=True)
    best = produced[0][0]
    chosen = out_dir / "thumbnail.jpg"
    with Image.open(best) as image:
        image.save(chosen, "JPEG", quality=92, optimize=True, progressive=True)

    # YouTube siniri 2 MB
    quality = 92
    while chosen.stat().st_size > 2_000_000 and quality > 60:
        quality -= 8
        with Image.open(best) as image:
            image.save(chosen, "JPEG", quality=quality, optimize=True, progressive=True)
    if chosen.stat().st_size > 2_000_000:
        warn("Kapak 2 MB'i asiyor, kalite dusuruldu.")

    return chosen, [p for p, _ in produced]


def make_overlay_card(
    *,
    text: str,
    subtext: str,
    out_path: Path,
    palette_cfg: dict,
    font_path: Path,
    size: tuple[int, int] = (720, 220),
) -> Path:
    """'ABONE OL' gibi video ustu bindirme karti (seffaf PNG) uretir."""
    palette = {
        "primary": _hex(str(palette_cfg.get("primary", "#FFC400")), (255, 196, 0)),
        "dark": _hex(str(palette_cfg.get("dark", "#0B1220")), (11, 18, 32)),
        "light": _hex(str(palette_cfg.get("light", "#FFFFFF")), (255, 255, 255)),
    }
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    radius = int(size[1] * 0.26)
    draw.rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=radius,
        fill=(*palette["dark"], 232), outline=(*palette["primary"], 255), width=6,
    )
    # Zil ikonu yerine dolu daire + cubuk (font bagimsiz)
    icon_cx, icon_cy = int(size[1] * 0.52), int(size[1] * 0.5)
    icon_r = int(size[1] * 0.20)
    draw.ellipse(
        [icon_cx - icon_r, icon_cy - icon_r, icon_cx + icon_r, icon_cy + icon_r],
        fill=(*palette["primary"], 255),
    )
    draw.rectangle(
        [icon_cx - icon_r * 0.18, icon_cy - icon_r * 0.55,
         icon_cx + icon_r * 0.18, icon_cy + icon_r * 0.35],
        fill=(*palette["dark"], 255),
    )

    text_x = icon_cx + icon_r + int(size[1] * 0.20)
    main_font = _font(font_path, int(size[1] * 0.42))
    draw.text(
        (text_x, int(size[1] * 0.18)), tr_upper(text), font=main_font,
        fill=palette["light"], stroke_width=0,
    )
    if subtext:
        sub_font = _font(font_path, int(size[1] * 0.20))
        draw.text(
            (text_x, int(size[1] * 0.64)), subtext, font=sub_font,
            fill=palette["primary"],
        )
    ensure_dir(out_path.parent)
    canvas.save(out_path, "PNG")
    return out_path


def make_outro_card(
    *,
    title: str,
    channel: str,
    out_path: Path,
    palette_cfg: dict,
    font_path: Path,
    size: tuple[int, int] = (1920, 1080),
    background: Path | None = None,
) -> Path:
    """Bitis ekrani karti: YouTube end-screen ogelerine yer birakan sade tasarim."""
    palette = {
        "primary": _hex(str(palette_cfg.get("primary", "#FFC400")), (255, 196, 0)),
        "secondary": _hex(str(palette_cfg.get("secondary", "#E63946")), (230, 57, 70)),
        "dark": _hex(str(palette_cfg.get("dark", "#0B1220")), (11, 18, 32)),
        "light": _hex(str(palette_cfg.get("light", "#FFFFFF")), (255, 255, 255)),
    }
    if background and Path(background).exists():
        with Image.open(background) as raw:
            canvas = _fit_cover(raw.convert("RGB"), size, focus=0.35)
        canvas = ImageEnhance.Brightness(canvas).enhance(0.42)
        canvas = _vignette(canvas, 0.62)
        canvas = canvas.convert("RGB")
        draw = ImageDraw.Draw(canvas)
    else:
        canvas = Image.new("RGB", size, palette["dark"])
        draw = ImageDraw.Draw(canvas)
        # Hafif diagonal doku
        for i in range(0, size[0] * 2, 90):
            draw.line([(i, 0), (i - size[1], size[1])], fill=tuple(
                min(255, c + 8) for c in palette["dark"]
            ), width=26)

    head_font = _font(font_path, int(size[1] * 0.085))
    sub_font = _font(font_path, int(size[1] * 0.042))

    draw.text(
        (int(size[0] * 0.06), int(size[1] * 0.16)), tr_upper("ABONE OL"),
        font=head_font, fill=palette["primary"],
    )
    draw.text(
        (int(size[0] * 0.06), int(size[1] * 0.28)),
        "Her hafta yeni taktik ve rehber",
        font=sub_font, fill=palette["light"],
    )
    draw.text(
        (int(size[0] * 0.06), int(size[1] * 0.36)),
        channel, font=sub_font, fill=palette["secondary"],
    )

    # Sag alt: bir sonraki video icin bos alan cercevesi (end screen ogesi buraya)
    box_w, box_h = int(size[0] * 0.30), int(size[1] * 0.30)
    x = size[0] - box_w - int(size[0] * 0.07)
    y = size[1] - box_h - int(size[1] * 0.16)
    draw.rounded_rectangle(
        [x, y, x + box_w, y + box_h], radius=24,
        outline=palette["primary"], width=5,
    )
    draw.text(
        (x + 24, y - int(size[1] * 0.06)), "SIRADAKİ VİDEO",
        font=sub_font, fill=palette["light"],
    )

    wrapped = _wrap(title, sub_font, int(size[0] * 0.5), draw)[:2]
    ty = int(size[1] * 0.60)
    for line in wrapped:
        draw.text((int(size[0] * 0.06), ty), line, font=sub_font, fill=palette["light"])
        ty += int(sub_font.size * 1.25)

    ensure_dir(out_path.parent)
    canvas.save(out_path, "PNG")
    return out_path
