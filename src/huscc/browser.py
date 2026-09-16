"""Gercek Chrome uzerinde calisan tarayici katmani.

Tasarim kararlari:

* **API yok.** Yukleme, YouTube Studio arayuzu uzerinden yapilir. Bu sayede
  API'nin desteklemedigi seyler de yapilabilir: bitis ekrani, kartlar,
  yorum sabitleme, kucuk resim A/B testi.
* **Kullanicinin kendi tarayicisi.** Playwright, kurulu Chrome'u
  (`channel="chrome"`) kalici bir profille acar. Kullanici bir kez Google
  girisi yapar, oturum `secrets/browser-profile/` icinde kalir.
* **Pencere gorunur.** Kullanici ne olup bittigini izler, gerekirse elle
  mudahale eder; surec kaldigi yerden devam eder.
* **Secici yok.** Hicbir CSS secici kodun icinde degildir; hepsi
  `config/selectors.yaml` dosyasindadir. Arayuz degisirse kod degil YAML
  guncellenir.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .util import HusccError, ensure_dir, info, ok, warn, write_json

STUDIO_URL = "https://studio.youtube.com/"
YOUTUBE_URL = "https://www.youtube.com/"
LOGIN_HINT = "accounts.google.com"


# ------------------------------------------------------------------ secici
@dataclass
class Selectors:
    data: dict = field(default_factory=dict)
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "Selectors":
        if not path.exists():
            raise HusccError(f"Secici dosyasi yok: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(data=raw, path=path)

    def strategies(self, key: str) -> list[tuple[str, str]]:
        entries = self.data.get(key)
        if not entries:
            raise HusccError(
                f"'{key}' icin secici tanimli degil.\n"
                f"  {self.path} dosyasina ekleyin."
            )
        out: list[tuple[str, str]] = []
        for entry in entries:
            if isinstance(entry, dict):
                for kind, value in entry.items():
                    out.append((str(kind), str(value)))
            elif isinstance(entry, str) and "=" in entry:
                kind, _, value = entry.partition("=")
                out.append((kind.strip(), value.strip()))
        return out


class StepFailure(HusccError):
    """Bir adim tamamlanamadi; rapor diske yazildi."""

    def __init__(self, message: str, *, step: str, report: Path | None = None):
        super().__init__(message)
        self.step = step
        self.report = report


# ----------------------------------------------------------------- oturum
class Session:
    """Kalici profille acilan Chrome penceresi."""

    def __init__(
        self,
        profile_dir: Path,
        selectors: Selectors,
        *,
        shots_dir: Path | None = None,
        headless: bool = False,
        slow_mo: int = 0,
        browser_channel: str = "chrome",
    ) -> None:
        self.profile_dir = ensure_dir(profile_dir)
        self.selectors = selectors
        self.shots_dir = ensure_dir(shots_dir) if shots_dir else None
        self.headless = headless
        self.slow_mo = slow_mo
        self.channel = browser_channel
        self._pw = None
        self._ctx = None
        self._page = None
        self._shot_index = 0

    # ------------------------------------------------------------ yasam dongusu
    def start(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        args = [
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--window-size=1600,1000",
        ]
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.channel,
                headless=self.headless,
                args=args,
                viewport={"width": 1600, "height": 950},
                accept_downloads=True,
            )
        except Exception as exc:
            self.stop()
            raise HusccError(
                "Chrome baslatilamadi.\n"
                f"  {exc}\n"
                "  Chrome kurulu mu? Degilse: winget install --id Google.Chrome -e\n"
                "  Edge denemek icin: config/channel.yaml > browser.channel: msedge"
            ) from exc

        self._ctx.set_default_timeout(30_000)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def stop(self) -> None:
        for closer in (getattr(self._ctx, "close", None), getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        self._ctx = self._page = self._pw = None

    def __enter__(self) -> "Session":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def page(self):
        if self._page is None:
            raise HusccError("Tarayici baslatilmadi (Session.start).")
        return self._page

    @property
    def context(self):
        if self._ctx is None:
            raise HusccError("Tarayici baslatilmadi (Session.start).")
        return self._ctx

    # -------------------------------------------------------------- gezinme
    def goto(self, url: str, *, wait: str = "domcontentloaded", timeout: int = 60_000):
        self.page.goto(url, wait_until=wait, timeout=timeout)
        self.page.wait_for_timeout(700)
        return self.page

    def shot(self, name: str) -> Path | None:
        if not self.shots_dir:
            return None
        self._shot_index += 1
        target = self.shots_dir / f"{self._shot_index:02d}_{name}.png"
        try:
            self.page.screenshot(path=str(target), full_page=False)
            return target
        except Exception:
            return None

    # --------------------------------------------------------------- oturum
    def is_signed_in(self) -> bool:
        """Studio'ya girip giris yapilmis mi diye bakar."""
        try:
            self.goto(STUDIO_URL, timeout=60_000)
        except Exception:
            return False
        if LOGIN_HINT in self.page.url:
            return False
        if "/channel/" in self.page.url or "studio.youtube.com" in self.page.url:
            # Avatar gorunuyorsa kesin giris var
            return self.exists("signed_in_avatar", timeout=8_000) or "/channel/" in self.page.url
        return False

    def ensure_signed_in(self, *, timeout: float = 600.0) -> None:
        """Giris yoksa kullaniciya birakir ve tamamlanmasini bekler."""
        if self.is_signed_in():
            ok("YouTube oturumu acik.")
            return

        print()
        print("=" * 70)
        print("  GOOGLE GIRISI GEREKIYOR  (bir defaya mahsus)")
        print("=" * 70)
        print("  Acilan Chrome penceresinde YouTube kanalinin sahibi oldugun")
        print("  Google hesabiyla giris yap. Giris yaptiktan sonra bu ekran")
        print("  kendiliginden devam edecek.")
        print()
        print(f"  Oturum su klasorde saklanacak: {self.profile_dir}")
        print("  Bir daha giris istemeyecek.")
        print("=" * 70)
        print()
        self.shot("login-bekleniyor")

        try:
            self.goto("https://accounts.google.com/ServiceLogin?service=youtube", timeout=60_000)
        except Exception:
            pass

        deadline = time.time() + timeout
        last_note = 0.0
        while time.time() < deadline:
            self.page.wait_for_timeout(2_500)
            url = ""
            try:
                url = self.page.url
            except Exception:
                pass
            if LOGIN_HINT not in url:
                if self.is_signed_in():
                    ok("Giris tamamlandi, oturum kaydedildi.")
                    self.shot("login-tamam")
                    return
            remaining = deadline - time.time()
            if remaining - last_note < -30:
                last_note = remaining
                info(f"Giris bekleniyor... ({int(remaining)} sn kaldi)")
        raise HusccError(
            "Google girisi tamamlanmadi.\n"
            "  'huscc login' komutunu calistirip girisi tamamlayin, sonra tekrar deneyin."
        )

    # --------------------------------------------------------------- bulma
    def _build(self, kind: str, value: str, *, root=None):
        scope = root if root is not None else self.page
        kind = kind.lower()
        if kind == "css":
            return scope.locator(value)
        if kind == "xpath":
            return scope.locator(f"xpath={value}")
        if kind == "text":
            return scope.get_by_text(value, exact=False)
        if kind == "label":
            return scope.get_by_label(re.compile(value, re.I))
        if kind == "testid":
            return scope.get_by_test_id(value)
        if kind == "role":
            role, _, name = value.partition("|")
            role = role.strip()
            if name:
                return scope.get_by_role(role, name=re.compile(name.strip(), re.I))
            return scope.get_by_role(role)
        return scope.locator(value)

    def candidates(self, key: str, *, root=None) -> Iterable:
        for kind, value in self.selectors.strategies(key):
            try:
                yield self._build(kind, value, root=root), f"{kind}={value}"
            except Exception:
                continue

    def find(
        self,
        key: str,
        *,
        timeout: int = 15_000,
        root=None,
        required: bool = True,
        state: str = "visible",
    ):
        """Seciciyi dener, ilk gorunur eslesmeyi dondurur."""
        deadline = time.time() + timeout / 1000.0
        tried: list[str] = []
        while time.time() < deadline:
            for locator, label in self.candidates(key, root=root):
                tried.append(label)
                try:
                    target = locator.first
                    if target.count() == 0:
                        continue
                    if state == "visible" and not target.is_visible():
                        continue
                    return target
                except Exception:
                    continue
            self.page.wait_for_timeout(400)
        if not required:
            return None
        raise self.failure(
            key,
            f"'{key}' ekranda bulunamadi.",
            tried=sorted(set(tried)),
        )

    def exists(self, key: str, *, timeout: int = 4_000, root=None) -> bool:
        return self.find(key, timeout=timeout, root=root, required=False) is not None

    # ---------------------------------------------------------------- eylem
    def click(self, key: str, *, timeout: int = 15_000, root=None, required: bool = True) -> bool:
        target = self.find(key, timeout=timeout, root=root, required=required)
        if target is None:
            return False
        try:
            target.scroll_into_view_if_needed(timeout=4_000)
        except Exception:
            pass
        try:
            target.click(timeout=8_000)
        except Exception:
            try:
                target.click(timeout=5_000, force=True)
            except Exception as exc:
                if not required:
                    return False
                raise self.failure(key, f"'{key}' tiklanamadi: {exc}") from exc
        self.page.wait_for_timeout(500)
        return True

    def type_into(
        self,
        key: str,
        text: str,
        *,
        clear: bool = True,
        timeout: int = 15_000,
        root=None,
        verify: bool = True,
    ) -> None:
        """contenteditable ve input alanlarina guvenli yazim + dogrulama."""
        target = self.find(key, timeout=timeout, root=root)
        try:
            target.scroll_into_view_if_needed(timeout=4_000)
        except Exception:
            pass
        target.click(timeout=8_000)
        if clear:
            try:
                target.press("Control+a")
                target.press("Delete")
            except Exception:
                pass
        # fill() contenteditable'da her zaman calismaz; once dene, sonra yaz
        written = False
        try:
            target.fill(text, timeout=5_000)
            written = True
        except Exception:
            pass
        if not written:
            target.type(text, delay=6)
        self.page.wait_for_timeout(400)

        if verify:
            actual = self.read(key, root=root) or ""
            head = text.strip()[:40]
            if head and head[:20] not in actual:
                warn(f"'{key}' alani dogrulanamadi; yeniden yaziliyor.")
                try:
                    target.press("Control+a")
                    target.press("Delete")
                    target.type(text, delay=10)
                    self.page.wait_for_timeout(400)
                except Exception:
                    pass

    def read(self, key: str, *, root=None, timeout: int = 6_000) -> str:
        target = self.find(key, timeout=timeout, root=root, required=False)
        if target is None:
            return ""
        try:
            value = target.input_value(timeout=2_000)
            if value:
                return value
        except Exception:
            pass
        try:
            return (target.inner_text(timeout=2_000) or "").strip()
        except Exception:
            return ""

    def upload_file(self, key: str, path: Path, *, timeout: int = 20_000, root=None) -> None:
        """Gizli olsa bile dosya girisine dosya verir."""
        deadline = time.time() + timeout / 1000.0
        last_error: Exception | None = None
        while time.time() < deadline:
            for locator, _label in self.candidates(key, root=root):
                try:
                    if locator.count() == 0:
                        continue
                    locator.first.set_input_files(str(path), timeout=8_000)
                    self.page.wait_for_timeout(700)
                    return
                except Exception as exc:
                    last_error = exc
                    continue
            self.page.wait_for_timeout(400)
        raise self.failure(key, f"Dosya verilemedi ({path.name}): {last_error}")

    def pick_option(self, text: str, *, timeout: int = 8_000) -> bool:
        """Acilan menude metne gore secenek secer."""
        pattern = re.compile(re.escape(text), re.I)
        for key in ("dropdown_option",):
            for locator, _label in self.candidates(key):
                try:
                    option = locator.filter(has_text=pattern).first
                    if option.count() and option.is_visible():
                        option.click(timeout=timeout)
                        self.page.wait_for_timeout(400)
                        return True
                except Exception:
                    continue
        try:
            fallback = self.page.get_by_text(pattern).first
            if fallback.count() and fallback.is_visible():
                fallback.click(timeout=timeout)
                self.page.wait_for_timeout(400)
                return True
        except Exception:
            pass
        return False

    # ----------------------------------------------------------- hata raporu
    def failure(self, step: str, message: str, *, tried: list[str] | None = None) -> StepFailure:
        shot = self.shot(f"HATA-{step}")
        report_path = None
        if self.shots_dir:
            report_path = self.shots_dir / f"SORUN_{step}.json"
            html = ""
            try:
                html = self.page.content()[:20_000]
            except Exception:
                pass
            write_json(
                report_path,
                {
                    "step": step,
                    "message": message,
                    "url": getattr(self.page, "url", ""),
                    "tried_selectors": tried or self._safe_strategies(step),
                    "screenshot": str(shot) if shot else "",
                    "html_excerpt": html,
                },
            )
            self._write_repair_note(step, message, shot, report_path)
        return StepFailure(
            f"{message}\n"
            + (f"  Ekran goruntusu: {shot}\n" if shot else "")
            + (f"  Rapor: {report_path}\n" if report_path else "")
            + "  Tarayici acik birakildi; elle tamamlayabilir ya da\n"
            + "  config/selectors.yaml dosyasindaki seciciyi guncelleyebilirsiniz.",
            step=step,
            report=report_path,
        )

    def _safe_strategies(self, key: str) -> list[str]:
        try:
            return [f"{k}={v}" for k, v in self.selectors.strategies(key)]
        except HusccError:
            return []

    def _write_repair_note(self, step: str, message: str, shot: Path | None, report: Path) -> None:
        note = self.shots_dir / "SORUN.md" if self.shots_dir else None
        if not note:
            return
        strategies = "\n".join(f"  - `{s}`" for s in self._safe_strategies(step)) or "  (tanimli degil)"
        note.write_text(
            f"""# Tarayici adimi tamamlanamadi: `{step}`

{message}

- Sayfa: {getattr(self.page, 'url', '')}
- Ekran goruntusu: `{shot}`
- Ayrinti (HTML dahil): `{report}`

## Denenen seciciler
{strategies}

## Nasil duzeltilir

1. Ekran goruntusune bak. Element gercekten ekranda mi?
2. Ekrandaysa `config/selectors.yaml` icindeki `{step}` anahtarina
   dogru seciciyi ekle (ilk sirada denenir):

```yaml
{step}:
  - css: "<yeni secici>"
  - role: "button|Turkce ad|English name"
```

3. Komutu tekrar calistir. Boru hatti kaldigi adimdan devam eder.

> Arayuz dili TR ya da EN olabilir; metin tabanli secicileri her iki dili
> kapsayacak sekilde yaz.
""",
            encoding="utf-8",
        )
