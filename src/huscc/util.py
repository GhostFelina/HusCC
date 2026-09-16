"""Ortak yardimcilar: log, Turkce slug, zaman, dosya islemleri."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ----------------------------------------------------------------- konsol
def _setup_console() -> bool:
    """Windows konsolunu UTF-8'e cevirir; olmuyorsa ASCII isaretlere duser."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
            ctypes.windll.kernel32.SetConsoleCP(65001)  # type: ignore[attr-defined]
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass
    encoding = (getattr(sys.stdout, "encoding", "") or "ascii").lower()
    try:
        "✓▸›✗".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_UNICODE_OK = _setup_console()
_SYM = (
    {"info": "›", "ok": "✓", "warn": "!", "err": "✗", "step": "▸"}
    if _UNICODE_OK
    else {"info": ">", "ok": "+", "warn": "!", "err": "x", "step": "*"}
)

_ANSI = os.environ.get("HUSCC_NO_COLOR") is None and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI else text


def safe(text: str) -> str:
    """Konsol Unicode desteklemiyorsa metni kayipsiz sekilde sadelestirir."""
    if _UNICODE_OK:
        return text
    encoding = (getattr(sys.stdout, "encoding", "") or "ascii")
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def info(msg: str) -> None:
    print(f"{_c('36', _SYM['info'])} {safe(msg)}", flush=True)


def ok(msg: str) -> None:
    print(f"{_c('32', _SYM['ok'])} {safe(msg)}", flush=True)


def warn(msg: str) -> None:
    print(f"{_c('33', _SYM['warn'])} {safe(msg)}", flush=True)


def err(msg: str) -> None:
    print(f"{_c('31', _SYM['err'])} {safe(msg)}", file=sys.stderr, flush=True)


def step(msg: str) -> None:
    print(f"\n{_c('1;35', _SYM['step'] + ' ' + safe(msg))}", flush=True)


def log_to(path: Path):
    """Ekrana basilan her seyi ayni anda bir dosyaya da yazar."""
    import contextlib

    @contextlib.contextmanager
    def _wrap():
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a", encoding="utf-8")
        original = sys.stdout
        handle.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} =====\n")

        class _Tee:
            def write(self, text: str) -> int:
                original.write(text)
                try:
                    handle.write(text)
                except Exception:
                    pass
                return len(text)

            def flush(self) -> None:
                original.flush()
                try:
                    handle.flush()
                except Exception:
                    pass

            def isatty(self) -> bool:
                return original.isatty()

        sys.stdout = _Tee()  # type: ignore[assignment]
        try:
            yield path
        finally:
            sys.stdout = original
            handle.close()

    return _wrap()


class HusccError(RuntimeError):
    """Kullaniciya gosterilecek, beklenen hata."""


# ------------------------------------------------------------------ Turkce
_TR_MAP = str.maketrans(
    {
        "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
        "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
    }
)


def tr_fold(text: str) -> str:
    """Turkce karakterleri ASCII'ye indirger, kucuk harfe cevirir (arama icin)."""
    text = text.translate(_TR_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def slugify(text: str, max_len: int = 60) -> str:
    s = tr_fold(text)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:max_len] or "video"


def tr_upper(text: str) -> str:
    """Turkce'ye uygun buyuk harf (i -> İ, ı -> I)."""
    return text.replace("i", "İ").replace("ı", "I").upper()


# ------------------------------------------------------------------- zaman
def hhmmss(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------- json
def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, data: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# ------------------------------------------------------------------- shell
def run(cmd: list[str], *, quiet: bool = True, check: bool = True,
        timeout: int | None = None) -> subprocess.CompletedProcess:
    """Harici komut calistirir. quiet=False ise cikti canli akar."""
    if os.environ.get("HUSCC_QUIET_FFMPEG"):
        quiet = True
    if quiet:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout,
        )
    else:
        proc = subprocess.run(cmd, text=True, timeout=timeout)
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:] if quiet else ""
        raise HusccError(f"Komut basarisiz ({' '.join(cmd[:3])}...): {tail}")
    return proc


def which(binary: str) -> str | None:
    from shutil import which as _which

    return _which(binary)


def human_size(num_bytes: int) -> str:
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if val < 1024 or unit == "GB":
            return f"{val:.1f} {unit}"
        val /= 1024
    return f"{val:.1f} GB"


def opt_path(value) -> Path | None:
    """Bos string/None icin None dondurur (Path('') -> '.' tuzagini onler)."""
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.exists() else None


def ensure_dir(path: Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def next_slot(best_hours: list[int], tz_name: str, taken: list[str]) -> datetime:
    """Bir sonraki bos yayin slotunu (UTC) dondurur."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
    except Exception:  # pragma: no cover - tzdata yoksa
        tz = timezone(timedelta(hours=3))
    taken_set = set(taken or [])
    now = datetime.now(tz)
    for day in range(0, 30):
        for hour in sorted(best_hours or [20]):
            cand = (now + timedelta(days=day)).replace(
                hour=hour, minute=0, second=0, microsecond=0
            )
            if cand <= now + timedelta(minutes=45):
                continue
            iso = cand.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            if iso not in taken_set:
                return cand.astimezone(timezone.utc).replace(microsecond=0)
    return (now + timedelta(days=1)).astimezone(timezone.utc).replace(microsecond=0)
