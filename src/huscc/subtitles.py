"""Altyazi uretimi (faster-whisper) ve SRT islemleri.

faster-whisper kurulu degilse sessizce atlanir; boru hatti calismaya devam eder.
Kurmak icin:  uv pip install faster-whisper   (ya da pip install huscc[whisper])
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .util import ensure_dir, info, srt_ts, warn


@dataclass
class Segment:
    start: float
    end: float
    text: str


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def transcribe(
    audio: Path,
    *,
    model_size: str = "small",
    language: str | None = "tr",
    task: str = "transcribe",
) -> list[Segment]:
    """Sesi metne cevirir. task='translate' Ingilizce ceviri uretir."""
    if not available():
        warn("faster-whisper kurulu degil - altyazi atlaniyor.")
        return []
    from faster_whisper import WhisperModel

    info(f"Altyazi cikariliyor ({model_size}, {task})...")
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segments, _ = model.transcribe(
        str(audio),
        language=language if task == "transcribe" else None,
        task=task,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 420},
        beam_size=5,
    )
    out: list[Segment] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if text:
            out.append(Segment(float(seg.start), float(seg.end), text))
    return out


def write_srt(segments: list[Segment], path: Path) -> Path | None:
    if not segments:
        return None
    ensure_dir(path.parent)
    lines: list[str] = []
    for index, seg in enumerate(segments, start=1):
        lines.append(str(index))
        lines.append(f"{srt_ts(seg.start)} --> {srt_ts(max(seg.end, seg.start + 0.4))}")
        lines.append(seg.text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def read_srt(path: Path) -> list[Segment]:
    if not path.exists():
        return []
    blocks = path.read_text(encoding="utf-8").strip().split("\n\n")
    segments: list[Segment] = []
    for block in blocks:
        rows = [r for r in block.splitlines() if r.strip()]
        if len(rows) < 3 or "-->" not in rows[1]:
            continue
        start_raw, end_raw = [p.strip() for p in rows[1].split("-->")]
        segments.append(
            Segment(_parse_ts(start_raw), _parse_ts(end_raw), " ".join(rows[2:]))
        )
    return segments


def _parse_ts(value: str) -> float:
    value = value.replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except ValueError:
        return 0.0


def slice_srt(segments: list[Segment], start: float, end: float) -> list[Segment]:
    """Shorts icin altyazinin ilgili araligini kaydirarak keser."""
    out: list[Segment] = []
    for seg in segments:
        if seg.end <= start or seg.start >= end:
            continue
        out.append(
            Segment(
                max(0.0, seg.start - start),
                min(end - start, seg.end - start),
                seg.text,
            )
        )
    return out


def transcript_text(segments: list[Segment]) -> str:
    return " ".join(seg.text for seg in segments).strip()


def shorts_style() -> str:
    """Shorts icin ffmpeg force_style dizesi - kalin, ortali, okunakli."""
    return (
        "FontName=Arial Black,FontSize=15,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BackColour=&H90000000,BorderStyle=1,"
        "Outline=3,Shadow=1,Alignment=2,MarginV=90,Bold=1"
    )
