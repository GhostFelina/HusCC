"""ffmpeg / ffprobe katmani: teknik analiz, kare cikarma, sahne tespiti, ses."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path

from .util import HusccError, ensure_dir, info, run, which

# ffmpeg winget ile kurulunca PATH'e bu sezonda yansimayabilir; olasi yerleri tara.
_WINGET_LINKS = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"
_EXTRA_DIRS = [
    _WINGET_LINKS,
    Path("C:/ffmpeg/bin"),
    Path("C:/Program Files/ffmpeg/bin"),
]


_CACHE: dict[str, str] = {}


def _scoop_choco_dirs() -> list[Path]:
    home = Path.home()
    return [
        home / "scoop" / "shims",
        Path("C:/ProgramData/chocolatey/bin"),
        home / "AppData/Local/Programs/ffmpeg/bin",
    ]


def _bundled(binary: str) -> str | None:
    """imageio-ffmpeg ile gelen statik ffmpeg (son care, kurulum gerektirmez)."""
    if binary != "ffmpeg":
        return None
    try:
        import imageio_ffmpeg

        path = imageio_ffmpeg.get_ffmpeg_exe()
        return path if path and Path(path).exists() else None
    except Exception:
        return None


def _resolve(binary: str) -> str:
    if binary in _CACHE:
        return _CACHE[binary]

    # 1) Yapilandirmada acikca verilmisse
    override = os.environ.get(f"HUSCC_{binary.upper()}")
    if override and Path(override).exists():
        _CACHE[binary] = override
        return override

    # 2) PATH
    found = which(binary)
    if found:
        _CACHE[binary] = found
        return found

    # 3) Bilinen klasorler
    for folder in _EXTRA_DIRS + _scoop_choco_dirs():
        for suffix in (".exe", ".cmd", ".bat", ""):
            cand = folder / f"{binary}{suffix}"
            if cand.exists():
                _CACHE[binary] = str(cand)
                return str(cand)

    # 4) winget paket klasoru (PATH'e ancak yeni oturumda yansir)
    packages = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if packages.exists():
        for cand in packages.glob(f"*FFmpeg*/**/bin/{binary}.exe"):
            _CACHE[binary] = str(cand)
            return str(cand)

    # 5) Pip ile gelen statik ikili
    fallback = _bundled(binary)
    if fallback:
        _CACHE[binary] = fallback
        return fallback

    raise HusccError(
        f"{binary} bulunamadi. Kurmak icin:\n"
        "  Windows: winget install --id Gyan.FFmpeg -e --accept-package-agreements\n"
        "  macOS  : brew install ffmpeg\n"
        "  Linux  : sudo apt install -y ffmpeg\n"
        "  Ya da : uv pip install --python .venv imageio-ffmpeg"
    )


def ffmpeg_bin() -> str:
    return _resolve("ffmpeg")


def ffprobe_bin() -> str:
    return _resolve("ffprobe")


def have_ffprobe() -> bool:
    try:
        ffprobe_bin()
        return True
    except HusccError:
        return False


def have_ffmpeg() -> bool:
    try:
        ffmpeg_bin()
        return True
    except HusccError:
        return False


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    video_codec: str
    audio_codec: str
    size_bytes: int
    bitrate: int

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 16 / 9

    @property
    def is_vertical(self) -> bool:
        return self.aspect < 1.0

    def to_dict(self) -> dict:
        data = asdict(self)
        data["aspect"] = round(self.aspect, 4)
        data["is_vertical"] = self.is_vertical
        return data


def probe(path: Path) -> MediaInfo:
    """Videonun teknik bilgilerini cikarir.

    ffprobe varsa onu kullanir; yoksa `ffmpeg -i` ciktisini ayristirir.
    Boylece yalnizca statik ffmpeg ikilisi olan makinelerde de calisir.
    """
    if not have_ffprobe():
        return _probe_with_ffmpeg(path)
    proc = run(
        [
            ffprobe_bin(), "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ]
    )
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise HusccError(f"Video akisi bulunamadi: {path.name}")

    fps = 30.0
    rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "30/1"
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            fps = float(num) / float(den) if float(den) else 30.0
        except ValueError:
            fps = 30.0

    duration = float(fmt.get("duration") or video.get("duration") or 0.0)
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    # Doner meta verisi varsa gercek en/boy
    rotation = 0
    for entry in video.get("side_data_list", []) or []:
        if "rotation" in entry:
            rotation = abs(int(entry["rotation"])) % 180
    if rotation == 90:
        width, height = height, width

    return MediaInfo(
        path=str(path),
        duration=duration,
        width=width,
        height=height,
        fps=round(fps, 3),
        has_audio=audio is not None,
        video_codec=str(video.get("codec_name", "")),
        audio_codec=str((audio or {}).get("codec_name", "")),
        size_bytes=int(fmt.get("size") or path.stat().st_size),
        bitrate=int(fmt.get("bit_rate") or 0),
    )


_DUR_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)")
_VIDEO_RE = re.compile(
    r"Stream #\d+:\d+.*?: Video:\s*(\w+).*?,\s*(\d{2,5})x(\d{2,5})", re.S
)
_FPS_RE = re.compile(r"(\d+\.?\d*)\s*(?:fps|tbr)")
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?: Audio:\s*(\w+)")
_ROT_RE = re.compile(r"rotate\s*:\s*(-?\d+)")


def _probe_with_ffmpeg(path: Path) -> MediaInfo:
    """ffprobe yokken teknik bilgiyi `ffmpeg -i` ciktisindan okur."""
    proc = run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], check=False)
    text = (proc.stderr or "") + (proc.stdout or "")

    duration = 0.0
    match = _DUR_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    video = _VIDEO_RE.search(text)
    if not video:
        raise HusccError(f"Video akisi okunamadi: {path.name}")
    codec, width, height = video.group(1), int(video.group(2)), int(video.group(3))

    fps = 30.0
    tail = text[video.end() : video.end() + 220]
    fps_match = _FPS_RE.search(tail)
    if fps_match:
        try:
            fps = float(fps_match.group(1))
        except ValueError:
            fps = 30.0

    audio = _AUDIO_RE.search(text)
    rotation = 0
    rot_match = _ROT_RE.search(text)
    if rot_match:
        rotation = abs(int(rot_match.group(1))) % 180
    if rotation == 90:
        width, height = height, width

    return MediaInfo(
        path=str(path),
        duration=duration,
        width=width,
        height=height,
        fps=round(fps, 3),
        has_audio=audio is not None,
        video_codec=codec,
        audio_codec=audio.group(1) if audio else "",
        size_bytes=path.stat().st_size,
        bitrate=0,
    )


# ------------------------------------------------------------------ sahneler
_SHOWINFO_TS = re.compile(r"pts_time:([0-9.]+)")


def scene_timestamps(path: Path, threshold: float = 0.28, limit: int = 60) -> list[float]:
    """Sahne degisim anlarini (saniye) dondurur - aksiyon yogunlugunun isareti."""
    proc = run(
        [
            ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path),
            "-filter_complex", f"select='gt(scene,{threshold})',showinfo",
            "-an", "-f", "null", "-",
        ],
        check=False,
    )
    stamps = [float(m) for m in _SHOWINFO_TS.findall(proc.stderr or "")]
    stamps.sort()
    deduped: list[float] = []
    for stamp in stamps:
        if not deduped or stamp - deduped[-1] > 1.5:
            deduped.append(stamp)
    return deduped[:limit]


def motion_profile(path: Path, duration: float, buckets: int = 24) -> list[float]:
    """Videoyu N parcaya bolup her parcanin sahne-degisim yogunlugunu dondurur."""
    if duration <= 0:
        return []
    stamps = scene_timestamps(path, threshold=0.16, limit=1000)
    profile = [0.0] * buckets
    span = duration / buckets
    for stamp in stamps:
        idx = min(buckets - 1, int(stamp / span))
        profile[idx] += 1.0
    peak = max(profile) or 1.0
    return [round(v / peak, 3) for v in profile]


# --------------------------------------------------------------------- kare
def extract_frames(
    path: Path,
    dest: Path,
    *,
    timestamps: list[float],
    width: int = 1280,
    prefix: str = "f",
) -> list[Path]:
    """Verilen zaman damgalarindan tek tek kare cikarir."""
    ensure_dir(dest)
    out: list[Path] = []
    for index, stamp in enumerate(timestamps):
        target = dest / f"{prefix}{index:02d}_{int(stamp):05d}s.jpg"
        run(
            [
                ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
                "-ss", f"{max(stamp, 0):.3f}", "-i", str(path),
                "-frames:v", "1", "-vf", f"scale={width}:-2:flags=lanczos",
                "-q:v", "3", str(target),
            ],
            check=False,
        )
        if target.exists() and target.stat().st_size > 1000:
            out.append(target)
    return out


def storyboard_timestamps(duration: float, count: int, scenes: list[float]) -> list[float]:
    """Duzenli araliklar + sahne kesimlerini harmanlayan kare zaman listesi."""
    if duration <= 0:
        return [0.0]
    count = max(4, count)
    uniform = [duration * (i + 0.5) / count for i in range(count)]
    picks = list(uniform)
    for stamp in scenes:
        if 1.0 < stamp < duration - 1.0:
            picks.append(stamp + 0.35)
    picks = sorted(set(round(p, 2) for p in picks if 0 <= p < duration))
    # Cok yakin olanlari ele
    spaced: list[float] = []
    min_gap = max(1.2, duration / (count * 3))
    for stamp in picks:
        if not spaced or stamp - spaced[-1] >= min_gap:
            spaced.append(stamp)
    if len(spaced) > count * 2:
        stride = len(spaced) / (count * 2)
        spaced = [spaced[int(i * stride)] for i in range(count * 2)]
    return spaced


# ---------------------------------------------------------------------- ses
def extract_audio(path: Path, dest: Path) -> Path | None:
    """Altyazi icin 16 kHz mono wav uretir; ses yoksa None."""
    ensure_dir(dest.parent)
    proc = run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", str(dest),
        ],
        check=False,
    )
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size < 4000:
        return None
    return dest


def loudness(path: Path) -> dict:
    """EBU R128 olcumu - sesin duzgun olup olmadigini anlamak icin."""
    proc = run(
        [
            ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path),
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ],
        check=False,
    )
    text = proc.stderr or ""
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def cut(path: Path, dest: Path, start: float, duration: float, *, reencode: bool = True) -> Path:
    """Videodan bir parca keser."""
    ensure_dir(dest.parent)
    cmd = [
        ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(start, 0):.3f}", "-i", str(path), "-t", f"{duration:.3f}",
    ]
    if reencode:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k"]
    else:
        cmd += ["-c", "copy"]
    cmd.append(str(dest))
    run(cmd)
    return dest


def still(path: Path, dest: Path, stamp: float, width: int = 1920) -> Path | None:
    """Tek bir yuksek cozunurluklu kare (thumbnail kaynagi)."""
    ensure_dir(dest.parent)
    run(
        [
            ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{max(stamp, 0):.3f}", "-i", str(path), "-frames:v", "1",
            "-vf", f"scale={width}:-2:flags=lanczos", "-q:v", "2", str(dest),
        ],
        check=False,
    )
    return dest if dest.exists() and dest.stat().st_size > 2000 else None


def describe(info: MediaInfo) -> str:
    mins = int(info.duration // 60)
    secs = int(info.duration % 60)
    return (
        f"{info.width}x{info.height} @ {info.fps:g}fps, "
        f"{mins}:{secs:02d}, ses: {'var' if info.has_audio else 'yok'}"
    )


def log_info(media: MediaInfo) -> None:
    info(describe(media))
