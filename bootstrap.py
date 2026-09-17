#!/usr/bin/env python3
"""HusCC tek komutluk kurulum.

    python bootstrap.py                # her seyi kur ve dogrula
    python bootstrap.py --no-whisper   # altyazi motorunu atla (hizli kurulum)
    python bootstrap.py --no-test      # sondaki dogrulamayi atla

Windows, macOS ve Linux'ta calisir. Var olan hicbir seyi silmez.
Kurulum bittiginde `huscc selftest` calistirilir; "MAKINE HAZIR" yaziyorsa
makine gercekten hazirdir.
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

# Bu surumler icin tum bagimliliklarin hazir tekerlekleri var.
PREFERRED_PYTHONS = ["3.12", "3.13", "3.11", "3.10"]


def say(mark: str, text: str) -> None:
    print(f"{mark} {text}", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def venv_bin() -> Path:
    return VENV / ("Scripts" if IS_WIN else "bin")


def huscc_exe() -> Path:
    return venv_bin() / ("huscc.exe" if IS_WIN else "huscc")


def run(cmd: list, *, check: bool = True, quiet: bool = False) -> int:
    printable = " ".join(str(c) for c in cmd)
    if not quiet:
        print(f"  $ {printable}")
    proc = subprocess.run(
        [str(c) for c in cmd],
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )
    if check and proc.returncode != 0:
        say("x", f"Komut basarisiz: {printable}")
        sys.exit(proc.returncode)
    return proc.returncode


def have(binary: str) -> bool:
    path = shutil.which(binary)
    if not path:
        return False
    # Windows'ta "python" Microsoft Store kisayolu olabilir; o gercek Python degil.
    if IS_WIN and "WindowsApps" in path and binary.startswith("python"):
        return False
    return True


# ------------------------------------------------------------------- python
def check_python() -> None:
    if sys.version_info < (3, 10):
        say("x", f"Python 3.10+ gerekiyor (su an {platform.python_version()}).")
        print("    Windows: winget install --id Python.Python.3.12 -e")
        print("    macOS  : brew install python@3.12")
        print("    Linux  : sudo apt install -y python3.12 python3.12-venv")
        sys.exit(1)
    if sys.version_info >= (3, 14):
        say("!", f"Python {platform.python_version()} cok yeni; bazi paketlerin")
        say("!", "tekerlegi olmayabilir. Sanal ortam icin 3.12 denenecek.")
    say("+", f"Python {platform.python_version()}")


# ------------------------------------------------------------- sanal ortam
def create_venv() -> None:
    if venv_python().exists():
        say("+", f"Sanal ortam zaten var: {VENV}")
        return

    say(">", "Sanal ortam olusturuluyor...")
    if have("uv"):
        for version in PREFERRED_PYTHONS:
            if run(["uv", "venv", "--python", version, str(VENV)],
                   check=False, quiet=True) == 0:
                say("+", f"Sanal ortam hazir (Python {version})")
                return
        run(["uv", "venv", str(VENV)])
    else:
        run([sys.executable, "-m", "venv", str(VENV)])
    if not venv_python().exists():
        say("x", "Sanal ortam olusturulamadi.")
        sys.exit(1)
    say("+", f"Sanal ortam hazir: {VENV}")


def install_deps(with_whisper: bool) -> None:
    say(">", "Bagimliliklar kuruluyor (birkac dakika surebilir)...")
    if have("uv"):
        run(["uv", "pip", "install", "--python", str(venv_python()), "-e", str(ROOT)])
        if with_whisper:
            run(["uv", "pip", "install", "--python", str(venv_python()), "faster-whisper"],
                check=False)
    else:
        run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
            check=False)
        run([str(venv_python()), "-m", "pip", "install", "-e", str(ROOT)])
        if with_whisper:
            run([str(venv_python()), "-m", "pip", "install", "faster-whisper"], check=False)
    say("+", "Bagimliliklar kuruldu.")


# ---------------------------------------------------------------- tarayici
def find_browser() -> str:
    candidates = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google/Chrome/Application/chrome.exe"),
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/microsoft-edge",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    for binary in ("google-chrome", "google-chrome-stable", "chromium", "microsoft-edge"):
        if have(binary):
            return shutil.which(binary) or ""
    return ""


def ensure_browser() -> None:
    found = find_browser()
    if found:
        say("+", f"Tarayici bulundu: {found}")
        return

    system = platform.system()
    say("!", "Chrome/Edge bulunamadi, kuruluyor...")
    if system == "Windows" and have("winget"):
        run(["winget", "install", "--id", "Google.Chrome", "-e",
             "--accept-package-agreements", "--accept-source-agreements",
             "--disable-interactivity"], check=False)
    elif system == "Darwin" and have("brew"):
        run(["brew", "install", "--cask", "google-chrome"], check=False)

    if find_browser():
        say("+", "Chrome kuruldu.")
        return

    say("!", "Sistem tarayicisi kurulamadi; Playwright Chromium indiriliyor...")
    run([str(venv_python()), "-m", "playwright", "install", "chromium"], check=False)
    say("+", "Yedek tarayici hazir (Playwright Chromium).")


# ------------------------------------------------------------------ ffmpeg
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
        say("!", "Sistem ffmpeg'i kurulamadi - pip ile gelen statik surum kullanilacak.")
        return
    say("+", "ffmpeg kurulumu denendi.")


# ------------------------------------------------------------------ klasor
def ensure_dirs() -> None:
    video_dir = Path.home() / "Desktop" / "CC"
    try:
        video_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        video_dir = ROOT / "CC"
        video_dir.mkdir(parents=True, exist_ok=True)
        say("!", f"Masaustu bulunamadi; video klasoru: {video_dir}")
    for name in ("secrets", "work", "out"):
        (ROOT / name).mkdir(exist_ok=True)
    env_file = ROOT / ".env"
    if not env_file.exists() and (ROOT / ".env.example").exists():
        env_file.write_text((ROOT / ".env.example").read_text(encoding="utf-8"),
                            encoding="utf-8")
    say("+", f"Video klasoru: {video_dir}")


# ------------------------------------------------------------------ dogrula
def link_command() -> bool:
    """`huscc` komutunu PATH'e bagla (yeni makinede tek adim kalmasin)."""
    say(">", "'huscc' komutu PATH'e baglaniyor...")
    return run([str(venv_python()), "-m", "huscc.installer", str(ROOT)], check=False) == 0


def verify() -> int:
    print()
    say(">", "Kurulum dogrulaniyor (sentetik videoyla tam boru hatti)...")
    print()
    return run([str(huscc_exe()), "selftest"], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="HusCC kurulumu")
    parser.add_argument("--no-whisper", action="store_true", help="Altyazi motorunu kurma")
    parser.add_argument("--no-ffmpeg", action="store_true", help="ffmpeg kurulumunu atla")
    parser.add_argument("--no-chrome", action="store_true", help="Tarayici kurulumunu atla")
    parser.add_argument("--no-test", action="store_true", help="Sondaki dogrulamayi atla")
    args = parser.parse_args()

    print()
    print("=" * 64)
    print("  HusCC kurulumu")
    print("=" * 64)

    check_python()
    create_venv()
    install_deps(not args.no_whisper)
    if not args.no_ffmpeg:
        ensure_ffmpeg()
    if not args.no_chrome:
        ensure_browser()
    ensure_dirs()
    linked = link_command()

    code = 0 if args.no_test else verify()

    huscc = "huscc" if linked else str(huscc_exe())
    print()
    print("=" * 64)
    if code == 0:
        say("+", "Kurulum tamam.")
    else:
        say("!", "Kurulum bitti ama dogrulama eksik kaldi (yukariya bakin).")
    print()
    print("  Komutu su sekilde calistirin:")
    if IS_WIN:
        print(f"    {huscc} <komut>")
        print("    (ya da depo kokunde:  .\\huscc.cmd <komut>)")
    else:
        print(f"    {huscc} <komut>")
        print("    (ya da depo kokunde:  ./huscc <komut>)")
    print()
    print("  Siradaki adimlar:")
    print(f"    1. {huscc} login      -> bir kerelik Google girisi")
    print(f"    2. {huscc} probe      -> Studio secicilerini dogrula")
    print(f'    3. {huscc} publish "video adi"')
    print()
    print("  API anahtari ya da Google Cloud projesi gerekmiyor.")
    print("=" * 64)
    return code


if __name__ == "__main__":
    sys.exit(main())
