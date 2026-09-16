#!/usr/bin/env python3
"""Kurulum oncesi hizli kontrol - hicbir bagimlilik gerektirmez.

    python check.py

Bu dosya yalnizca standart kutuphane kullanir; HusCC kurulmadan once
"bu makinede ne eksik?" sorusunu cevaplar. Kurulum sonrasi asil dogrulama
komutu `huscc selftest`.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"


def mark(good: bool) -> str:
    return "+" if good else "x"


def which(binary: str) -> str:
    path = shutil.which(binary) or ""
    if IS_WIN and "WindowsApps" in path and binary.startswith("python"):
        return ""  # Microsoft Store kisayolu - gercek Python degil
    return path


def find_browser() -> str:
    candidates = [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google/Chrome/Application/chrome.exe"),
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    for binary in ("google-chrome", "google-chrome-stable", "chromium", "microsoft-edge"):
        found = which(binary)
        if found:
            return found
    return ""


def internet() -> bool:
    import socket

    for host in ("pypi.org", "github.com"):
        try:
            socket.create_connection((host, 443), timeout=4).close()
            return True
        except OSError:
            continue
    return False


def free_gb(path: Path) -> float:
    try:
        return shutil.disk_usage(path).free / (1024**3)
    except OSError:
        return -1.0


def main() -> int:
    print()
    print("=" * 62)
    print("  HusCC - kurulum oncesi kontrol")
    print("=" * 62)
    print(f"  Sistem : {platform.system()} {platform.release()}")
    print(f"  Konum  : {ROOT}")
    print()

    problems: list[str] = []
    notes: list[str] = []

    # Python
    version = platform.python_version()
    good = sys.version_info >= (3, 10)
    print(f"  {mark(good)} Python {version}")
    if not good:
        problems.append(
            "Python 3.10+ gerekiyor.\n"
            "      Windows: winget install --id Python.Python.3.12 -e\n"
            "      macOS  : brew install python@3.12\n"
            "      Linux  : sudo apt install -y python3.12 python3.12-venv"
        )
    elif sys.version_info >= (3, 14):
        notes.append(
            f"Python {version} cok yeni; kurulum sanal ortam icin 3.12 secmeye calisacak."
        )

    # venv modulu
    try:
        import venv  # noqa: F401

        print(f"  {mark(True)} venv modulu")
    except ImportError:
        print(f"  {mark(False)} venv modulu")
        problems.append("python3-venv paketi eksik: sudo apt install -y python3-venv")

    # uv (opsiyonel ama hizlandirir)
    uv = which("uv")
    print(f"  {mark(bool(uv))} uv {'(' + uv + ')' if uv else '(yok - pip kullanilacak)'}")

    # git
    git = which("git")
    print(f"  {mark(bool(git))} git")
    if not git:
        notes.append("git yok - depoyu zip olarak indirdiyseniz sorun degil.")

    # ffmpeg
    ffmpeg = which("ffmpeg")
    print(f"  {mark(bool(ffmpeg))} ffmpeg {'(' + ffmpeg + ')' if ffmpeg else ''}")
    if not ffmpeg:
        notes.append(
            "ffmpeg yok - kurulum otomatik kurmayi deneyecek, olmazsa pip ile gelen "
            "statik surumu kullanacak."
        )

    # tarayici
    browser = find_browser()
    print(f"  {mark(bool(browser))} Tarayici {'(' + browser + ')' if browser else ''}")
    if not browser:
        notes.append(
            "Chrome/Edge yok - kurulum once Chrome'u, olmazsa Playwright Chromium'u kuracak."
        )

    # internet
    online = internet()
    print(f"  {mark(online)} Internet baglantisi")
    if not online:
        problems.append("Internet yok - bagimliliklar indirilemez.")

    # disk
    space = free_gb(ROOT)
    enough = space < 0 or space >= 3
    print(f"  {mark(enough)} Bos disk alani: {space:.1f} GB" if space >= 0 else "  ? Disk alani")
    if not enough:
        problems.append("En az 3 GB bos alan gerekiyor (altyazi modeli ~0.5 GB).")

    # depo butunlugu
    required = ["pyproject.toml", "src/huscc/cli.py", "config/channel.yaml",
                "config/selectors.yaml"]
    missing = [name for name in required if not (ROOT / name).exists()]
    print(f"  {mark(not missing)} Depo dosyalari" + (f" (eksik: {', '.join(missing)})" if missing else ""))
    if missing:
        problems.append("Depo eksik indirilmis - 'git clone' ile tekrar alin.")

    print()
    if notes:
        print("  Notlar:")
        for note in notes:
            print(f"    ! {note}")
        print()

    if problems:
        print("=" * 62)
        print("  EKSIKLER VAR - once bunlari cozun:")
        for problem in problems:
            print(f"    x {problem}")
        print("=" * 62)
        return 1

    print("=" * 62)
    print("  Hazir. Kurulumu baslatin:")
    print(f"    {sys.executable} bootstrap.py")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
