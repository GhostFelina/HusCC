"""Yapilandirma yukleyici: config/channel.yaml + .env + ortam degiskenleri."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .util import HusccError, ensure_dir

PKG_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PKG_ROOT.parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and not os.environ.get(key):
            os.environ[key] = value


def _deep_get(data: dict, dotted: str, default: Any = None) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


@dataclass
class Config:
    raw: dict = field(default_factory=dict)
    root: Path = PROJECT_ROOT

    # ---------------------------------------------------------------- yollar
    @property
    def video_dir(self) -> Path:
        env = os.environ.get("HUSCC_VIDEO_DIR")
        raw = env or self.get("paths.video_dir", "~/Desktop/CC")
        return Path(raw).expanduser().resolve()

    @property
    def work_dir(self) -> Path:
        env = os.environ.get("HUSCC_WORK_DIR")
        raw = env or self.get("paths.work_dir", "./work")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return ensure_dir(path.resolve())

    @property
    def out_dir(self) -> Path:
        raw = self.get("paths.out_dir", "./out")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return ensure_dir(path.resolve())

    @property
    def secrets_dir(self) -> Path:
        return ensure_dir(self.root / "secrets")

    @property
    def assets_dir(self) -> Path:
        return ensure_dir(self.root / "assets")

    @property
    def selectors_path(self) -> Path:
        return self.root / "config" / "selectors.yaml"

    @property
    def browser_profile_dir(self) -> Path:
        raw = self.get("browser.profile_dir", "./secrets/browser-profile")
        path = Path(str(raw)).expanduser()
        if not path.is_absolute():
            path = self.root / path
        return ensure_dir(path.resolve())

    @property
    def history_file(self) -> Path:
        return self.work_dir / "history.json"

    # ------------------------------------------------------------------ eris
    def get(self, dotted: str, default: Any = None) -> Any:
        return _deep_get(self.raw, dotted, default)

    def section(self, name: str) -> dict:
        value = self.raw.get(name)
        return value if isinstance(value, dict) else {}

    # --------------------------------------------------------------- kisayol
    @property
    def channel_name(self) -> str:
        return str(self.get("channel.name", "HusCC"))

    @property
    def handle(self) -> str:
        return str(self.get("channel.handle", "") or "")

    @property
    def game(self) -> str:
        return str(self.get("channel.game", "Clash of Clans"))

    def work_for(self, slug: str) -> Path:
        return ensure_dir(self.work_dir / slug)


def load_config(path: str | Path | None = None) -> Config:
    root = PROJECT_ROOT
    _load_dotenv(root / ".env")
    cfg_path = Path(path) if path else root / "config" / "channel.yaml"
    if not cfg_path.exists():
        raise HusccError(
            f"Yapilandirma bulunamadi: {cfg_path}\n"
            "  config/channel.yaml dosyasini olusturun (ornegi depoda mevcut)."
        )
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise HusccError(f"Gecersiz yapilandirma: {cfg_path}")
    return Config(raw=data, root=root)
