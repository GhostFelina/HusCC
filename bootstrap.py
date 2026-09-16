#!/usr/bin/env python3
"""HusCC tek komutluk kurulum.

Kullanim:
    python bootstrap.py            # sanal ortam + bagimliliklar + ffmpeg kontrolu
    python bootstrap.py --no-whisper   # altyazi motorunu atla (daha hizli kurulum)

Windows, macOS ve Linux'ta calisir. Hicbir sey silmez, hicbir seyi ezmez.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"


def say(mark: str, text: str) -> None:
    print(f"{mark} {text}", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def venv_bin() -> Path:
    return VENV / ("Scripts" if IS_WIN else "bin")


def run(cmd: list[str], *, check: bool = True) -> int:
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    proc = subprocess.run([str(c) for c in cmd])
    if check and proc.returncode != 0:
        say("x", f"Komut basarisiz: {' '.join(str(c) for c in cmd)}")
        sys.exit(proc.returncode)
    return proc.returncode


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def create_venv() -> None:
    if venv_python().exists():
        say("+", f"Sanal ortam zaten var: {VENV}")
        return
    say(">", "Sanal ortam olusturuluyor...")
    if have("uv"):
        run(["uv", "venv", str(VENV)])
    else:
        run([sys.executable, "-m", "venv", str(VENV)])
    say("+", f"Sanal ortam hazir: {VENV}")


def install_deps(with_whisper: bool) -> None:
    say(">", "Bagimliliklar kuruluyor...")
    if have("uv"):
        run(["uv", "pip", "install", "--python", str(venv_python()), "-e", str(ROOT)])
        if with_whisper:
            run(["uv", "pip", "install", "--python", str(venv_python()), "faster-whisper"],
                check=False)
    else:
        run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"], check=False)
        run([str(venv_python()), "-m", "pip", "install", "-e", str(ROOT)])
        if with_whisper:
            run([str(venv_python()), "-m", "pip", "install", "faster-whisper"], check=False)
    say("+", "Bagimliliklar kuruldu.")


def ensure_ffmpeg() -> None:
    if have("ffmpeg"):
        say("+", "ffmpeg bulundu.")
        return
    system = platform.system()
    say("!", "ffmpeg bulunamadi, kuruluyor...")
    if system == "Windows" and have("winget"):
        run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
             "--accept-package-agreements", "--accept-source-agreements",
             "--disable-interactivity"], check=False)
    elif system == "Darwin" and have("brew"):
        run(["brew", "install", "ffmpeg"], check=False)
    elif system == "Linux" and have("apt"):
        run(["sudo", "apt", "install", "-y", "ffmpeg"], check=False)
    else:
        say("!", "ffmpeg'i elle kurun: https://ffmpeg.org/download.html")
        return
    say("+", "ffmpeg kurulumu denendi (yeni terminalde PATH'e yansir).")


def ensure_dirs() -> None:
    video_dir = Path.home() / "Desktop" / "CC"
    video_dir.mkdir(parents=True, exist_ok=True)
    (ROOT / "secrets").mkdir(exist_ok=True)
    (ROOT / "work").mkdir(exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    env_file = ROOT / ".env"
    if not env_file.exists() and (ROOT / ".env.example").exists():
        env_file.write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    say("+", f"Video klasoru: {video_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="HusCC kurulumu")
    parser.add_argument("--no-whisper", action="store_true", help="Altyazi motorunu kurma")
    parser.add_argument("--no-ffmpeg", action="store_true", help="ffmpeg kurulumunu atla")
    args = parser.parse_args()

    print()
    print("=" * 62)
    print("  HusCC kurulumu")
    print("=" * 62)

    if sys.version_info < (3, 10):
        say("x", f"Python 3.10+ gerekiyor (su an {platform.python_version()}).")
        return 1

    create_venv()
    install_deps(not args.no_whisper)
    if not args.no_ffmpeg:
        ensure_ffmpeg()
    ensure_dirs()

    huscc = venv_bin() / ("huscc.exe" if IS_WIN else "huscc")
    print()
    print("=" * 62)
    say("+", "Kurulum tamam.")
    print()
    print("  Siradaki adimlar:")
    print(f"    1. {huscc} doctor")
    print("    2. Google OAuth istemci dosyasini secrets/client_secret.json olarak koy")
    print(f"    3. {huscc} auth")
    print(f"    4. {huscc} web          (yerel panel)")
    print(f'    5. {huscc} publish "video adi"')
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
