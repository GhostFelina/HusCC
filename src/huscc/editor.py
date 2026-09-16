"""Video kurgu katmani: ses normalizasyonu, abone-ol bindirmesi, filigran,
bitis karti ve dikey Shorts uretimi. Hepsi tek gecislik ffmpeg grafikleriyle.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .media import MediaInfo, ffmpeg_bin
from .util import ensure_dir, info, run


@dataclass
class RenderPlan:
    loudnorm: bool = True
    watermark: Path | None = None
    subscribe_card: Path | None = None
    subscribe_times: list[float] | None = None
    subscribe_duration: float = 5.0
    outro_card: Path | None = None
    outro_duration: float = 10.0


def parse_positions(values: list, duration: float) -> list[float]:
    """['8%', 45, '80%'] -> saniye listesi."""
    out: list[float] = []
    for value in values or []:
        text = str(value).strip()
        try:
            if text.endswith("%"):
                out.append(duration * float(text[:-1]) / 100.0)
            else:
                out.append(float(text))
        except ValueError:
            continue
    return [t for t in sorted(out) if 2 <= t <= max(duration - 8, 3)]


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def render_main(
    source: Path,
    dest: Path,
    media: MediaInfo,
    plan: RenderPlan,
) -> Path:
    """Ana videoyu bindirmelerle birlikte yeniden kodlar."""
    ensure_dir(dest.parent)
    inputs: list[str] = ["-i", str(source)]
    filters: list[str] = []
    index = 1

    width = _even(media.width or 1920)
    height = _even(media.height or 1080)
    video_label = "[0:v]"
    filters.append(f"[0:v]scale={width}:{height}:flags=lanczos,format=yuv420p[base]")
    video_label = "[base]"

    times = plan.subscribe_times or []
    if plan.subscribe_card and plan.subscribe_card.exists() and times:
        inputs += ["-i", str(plan.subscribe_card)]
        card_index = index
        index += 1
        card_w = max(240, int(width * 0.30))
        splits = "".join(f"[sub{i}]" for i in range(len(times)))
        filters.append(
            f"[{card_index}:v]scale={card_w}:-1,format=rgba,split={len(times)}{splits}"
        )
        for i, start in enumerate(times):
            end = start + plan.subscribe_duration
            slide = 0.45
            x_expr = (
                f"'if(lt(t-{start:.2f},{slide}),"
                f"-w+(w+{int(width * 0.035)})*(t-{start:.2f})/{slide},"
                f"{int(width * 0.035)})'"
            )
            out_label = f"[v{i}]"
            filters.append(
                f"{video_label}[sub{i}]overlay=x={x_expr}:"
                f"y=main_h-h-{int(height * 0.09)}:"
                f"enable='between(t,{start:.2f},{end:.2f})'{out_label}"
            )
            video_label = out_label

    if plan.watermark and plan.watermark.exists():
        inputs += ["-i", str(plan.watermark)]
        wm_index = index
        index += 1
        wm_w = max(120, int(width * 0.10))
        filters.append(
            f"[{wm_index}:v]scale={wm_w}:-1,format=rgba,"
            f"colorchannelmixer=aa=0.62[wm]"
        )
        filters.append(
            f"{video_label}[wm]overlay=W-w-{int(width * 0.022)}:{int(height * 0.035)}[vwm]"
        )
        video_label = "[vwm]"

    filters.append(f"{video_label}null[vout]")

    if media.has_audio:
        audio_filter = (
            "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[aout]"
            if plan.loudnorm
            else "[0:a]aresample=48000[aout]"
        )
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio_filter = f"[{index}:a]anull[aout]"
        index += 1
    filters.append(audio_filter)

    cmd = [
        ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-stats", "-y",
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
        "-x264-params", "keyint=48:min-keyint=48:scenecut=0",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        str(dest),
    ]
    run(cmd, quiet=False)
    return dest


def make_outro_clip(
    card: Path,
    dest: Path,
    *,
    width: int,
    height: int,
    fps: float,
    duration: float,
) -> Path:
    """Sabit gorselden, ana video ile ayni parametrelerde outro klibi uretir."""
    ensure_dir(dest.parent)
    run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-loop", "1", "-t", f"{duration:.2f}", "-i", str(card),
            "-f", "lavfi", "-t", f"{duration:.2f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf",
            f"scale={_even(width)}:{_even(height)}:force_original_aspect_ratio=decrease,"
            f"pad={_even(width)}:{_even(height)}:(ow-iw)/2:(oh-ih)/2:color=0x0B1220,"
            f"fps={fps:g},format=yuv420p",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(dest),
        ]
    )
    return dest


def concat(parts: list[Path], dest: Path) -> Path:
    """Ayni parametrelerdeki klipleri birlestirir."""
    ensure_dir(dest.parent)
    inputs: list[str] = []
    for part in parts:
        inputs += ["-i", str(part)]
    streams = "".join(f"[{i}:v][{i}:a]" for i in range(len(parts)))
    run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-stats", "-y",
            *inputs,
            "-filter_complex", f"{streams}concat=n={len(parts)}:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(dest),
        ],
        quiet=False,
    )
    return dest


# -------------------------------------------------------------------- Shorts
def pick_short_window(
    motion: list[float],
    duration: float,
    *,
    length: float = 50.0,
    highlights: list[dict] | None = None,
) -> tuple[float, float]:
    """En hareketli / en degerli araligi secer."""
    length = min(length, max(10.0, duration - 1))
    if highlights:
        best = max(highlights, key=lambda h: float(h.get("weight", 1)))
        start = max(0.0, float(best.get("t", 0)) - length * 0.35)
        start = min(start, max(0.0, duration - length))
        return start, length
    if not motion or duration <= length:
        return max(0.0, (duration - length) / 2), length

    buckets = len(motion)
    span = duration / buckets
    window = max(1, int(length / span))
    best_index, best_sum = 0, -1.0
    for i in range(0, buckets - window + 1):
        total = sum(motion[i : i + window])
        if total > best_sum:
            best_index, best_sum = i, total
    start = min(max(0.0, best_index * span), max(0.0, duration - length))
    return start, length


def render_short(
    source: Path,
    dest: Path,
    *,
    start: float,
    length: float,
    srt: Path | None = None,
    style: str = "",
    hook_text: str = "",
) -> Path:
    """9:16 dikey Shorts uretir; altyazi varsa goruntuye gomer."""
    ensure_dir(dest.parent)
    chain = [
        "scale=1080:-2:flags=lanczos",
        "crop=1080:min(1920\\,ih):0:(ih-min(1920\\,ih))/2",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0B1220",
        "fps=30",
    ]
    if srt and srt.exists():
        escaped = str(srt).replace("\\", "/").replace(":", "\\:")
        force = f":force_style='{style}'" if style else ""
        chain.append(f"subtitles='{escaped}'{force}")
    chain.append("format=yuv420p")

    run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-stats", "-y",
            "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{length:.3f}",
            "-vf", ",".join(chain),
            "-c:v", "libx264", "-preset", "medium", "-crf", "21",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", str(dest),
        ],
        quiet=False,
    )
    return dest


def burn_free_copy(source: Path, dest: Path) -> Path:
    """Kurgu kapaliysa: sadece hizli yayina uygun kopya (faststart)."""
    ensure_dir(dest.parent)
    run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-c", "copy", "-movflags", "+faststart", str(dest),
        ]
    )
    info("Kurgu kapali - video yeniden kodlanmadan kopyalandi.")
    return dest
