"""Sistem kurulumu: eksik bileseni indirir, `huscc` komutunu PATH'e baglar.

Iki yerden kullanilir:
  * `bootstrap.py`  -> kurulum sonunda kisayolu olusturur
  * `huscc doctor --fix` -> sonradan eksilen bileseni tamamlar

Hicbir sey silmez. PATH'e yalnizca tek bir klasor ekler (venv'in tamami degil),
boylece `python`/`pip` gibi komutlar kullanicinin ortamina sizmaz.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from .util import HusccError, info, ok, warn

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"


# ------------------------------------------------------------------ kisayol
def shim_dir() -> Path:
    """Yalnizca huscc kisayolunun konacagi klasor."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / "Programs" / "HusCC" / "bin"
    return Path.home() / ".local" / "bin"


def venv_huscc(root: Path) -> Path:
    return root / ".venv" / ("Scripts/huscc.exe" if IS_WIN else "bin/huscc")


def write_shim(root: Path) -> Path:
    """`huscc` komutunu her yerden calisir hale getirir."""
    target = venv_huscc(root)
    if not target.exists():
        raise HusccError(
            f"Sanal ortam bulunamadi: {target}\n  Once: python bootstrap.py"
        )

    folder = shim_dir()
    folder.mkdir(parents=True, exist_ok=True)

    if IS_WIN:
        shim = folder / "huscc.cmd"
        shim.write_text(
            "@echo off\r\n"
            f'"{target}" %*\r\n',
            encoding="utf-8",
        )
        # PowerShell'de de dogrudan calissin
        (folder / "huscc.ps1").write_text(
            f'& "{target}" @args\n', encoding="utf-8"
        )
    else:
        shim = folder / "huscc"
        if shim.exists() or shim.is_symlink():
            shim.unlink()
        try:
            shim.symlink_to(target)
        except OSError:
            shim.write_text(f'#!/usr/bin/env bash\nexec "{target}" "$@"\n', encoding="utf-8")
        shim.chmod(0o755)
    return shim


def _windows_path_add(folder: Path) -> bool:
    """Kullanici PATH'ine klasor ekler (sistem PATH'ine dokunmaz)."""
    import winreg

    text = str(folder)
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            current, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current, kind = "", winreg.REG_EXPAND_SZ

        parts = [p for p in str(current).split(os.pathsep) if p.strip()]
        if any(os.path.normcase(p.rstrip("\\")) == os.path.normcase(text.rstrip("\\"))
               for p in parts):
            return False
        parts.append(text)
        winreg.SetValueEx(key, "Path", 0, kind or winreg.REG_EXPAND_SZ,
                          os.pathsep.join(parts))

    # Acik programlar degisikligi gorsun
    try:
        import ctypes

        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x1A, 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment",
            SMTO_ABORTIFHUNG, 3000, None,
        )
    except Exception:
        pass
    return True


def _unix_path_add(folder: Path) -> bool:
    """~/.local/bin PATH'te degilse kabuk dosyasina ekler."""
    text = str(folder)
    if text in os.environ.get("PATH", "").split(os.pathsep):
        return False

    line = f'\n# HusCC\nexport PATH="{text}:$PATH"\n'
    changed = False
    for name in (".zshrc", ".bashrc", ".bash_profile", ".profile"):
        rc = Path.home() / name
        if not rc.exists():
            continue
        content = rc.read_text(encoding="utf-8", errors="replace")
        if text in content:
            continue
        rc.write_text(content + line, encoding="utf-8")
        changed = True
    if not changed:
        rc = Path.home() / ".profile"
        rc.write_text((rc.read_text(encoding="utf-8") if rc.exists() else "") + line,
                      encoding="utf-8")
        changed = True
    return changed


def link(root: Path, *, add_path: bool = True) -> dict:
    """Kisayolu olusturur ve gerekirse PATH'e ekler."""
    shim = write_shim(root)
    result = {"shim": str(shim), "path_updated": False, "dir": str(shim_dir())}
    if add_path:
        try:
            result["path_updated"] = (
                _windows_path_add(shim_dir()) if IS_WIN else _unix_path_add(shim_dir())
            )
        except Exception as exc:  # noqa: BLE001
            warn(f"PATH guncellenemedi: {exc}")
    return result


def is_linked() -> bool:
    shim = shim_dir() / ("huscc.cmd" if IS_WIN else "huscc")
    return shim.exists()


# ------------------------------------------------------------ eksik tamamla
def _have(binary: str) -> bool:
    path = shutil.which(binary)
    if not path:
        return False
    if IS_WIN and "WindowsApps" in path and binary.startswith("python"):
        return False
    return True


def _run(cmd: list[str], *, timeout: int = 1800) -> bool:
    info(f"  $ {' '.join(cmd)}")
    try:
        return subprocess.run(cmd, timeout=timeout).returncode == 0
    except Exception as exc:  # noqa: BLE001
        warn(f"  komut calistirilamadi: {exc}")
        return False


def install_ffmpeg() -> bool:
    system = platform.system()
    if system == "Windows" and _have("winget"):
        return _run(["winget", "install", "--id", "Gyan.FFmpeg", "-e",
                     "--accept-package-agreements", "--accept-source-agreements",
                     "--disable-interactivity"])
    if system == "Darwin" and _have("brew"):
        return _run(["brew", "install", "ffmpeg"])
    if system == "Linux":
        if _have("apt-get"):
            return _run(["sudo", "apt-get", "install", "-y", "ffmpeg"])
        if _have("dnf"):
            return _run(["sudo", "dnf", "install", "-y", "ffmpeg"])
        if _have("pacman"):
            return _run(["sudo", "pacman", "-S", "--noconfirm", "ffmpeg"])
    # Son care: pip ile statik ikili
    return _run([sys.executable, "-m", "pip", "install", "imageio-ffmpeg"])


def install_browser() -> bool:
    system = platform.system()
    if system == "Windows" and _have("winget"):
        if _run(["winget", "install", "--id", "Google.Chrome", "-e",
                 "--accept-package-agreements", "--accept-source-agreements",
                 "--disable-interactivity"]):
            return True
    elif system == "Darwin" and _have("brew"):
        if _run(["brew", "install", "--cask", "google-chrome"]):
            return True
    elif system == "Linux" and _have("apt-get"):
        if _run(["sudo", "apt-get", "install", "-y", "google-chrome-stable"]):
            return True
    info("  Sistem tarayicisi kurulamadi; Playwright Chromium indiriliyor...")
    return _run([sys.executable, "-m", "playwright", "install", "chromium"])


def install_whisper() -> bool:
    return _run([sys.executable, "-m", "pip", "install", "faster-whisper"])


def install_playwright() -> bool:
    return _run([sys.executable, "-m", "pip", "install", "playwright"])


FIXERS = {
    "ffmpeg": ("ffmpeg", install_ffmpeg),
    "browser": ("Tarayici (Chrome/Chromium)", install_browser),
    "whisper": ("Altyazi motoru (faster-whisper)", install_whisper),
    "playwright": ("Playwright", install_playwright),
}


def fix(names: list[str]) -> dict[str, bool]:
    """Verilen bilesenleri kurmayi dener."""
    outcome: dict[str, bool] = {}
    for name in names:
        entry = FIXERS.get(name)
        if not entry:
            continue
        label, action = entry
        info(f"Kuruluyor: {label}")
        outcome[name] = action()
        if outcome[name]:
            ok(f"{label} kuruldu.")
        else:
            warn(f"{label} kurulamadi.")
    return outcome
