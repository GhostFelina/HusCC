"""Giris gereken platformlar ve yonlendirmeli giris sihirbazi.

`huscc login` bu listedeki her platformu sirayla acar:
  * zaten girilmisse dokunmadan gecer,
  * girilmemisse sayfayi acar ve kullanicinin giris yapmasini bekler,
  * kullanici atlamak isterse Ctrl+C ile o platform atlanir, digerlerine devam edilir.

Oturumlar ayni kalici profilde tutulur; bir daha sorulmaz.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .browser import Session
from .util import HusccError, info, ok, step, warn


@dataclass
class Platform:
    key: str
    label: str
    why: str                      # kullaniciya "neden gerekli"
    url: str                      # girisin yapilacagi adres
    ready_key: str                # giris yapilmissa gorunen element
    login_hint: str = ""          # adreste bu varsa giris yapilmamis demektir
    login_key: str = ""           # "Giris yap" dugmesi (varsa giris yok)
    required: bool = True
    extra_check: Callable[[Session], bool] | None = field(default=None, repr=False)


PLATFORMS: list[Platform] = [
    Platform(
        key="youtube",
        label="YouTube / Google",
        why="Videolari Studio uzerinden yayinlamak icin (zorunlu)",
        url="https://studio.youtube.com/",
        ready_key="signed_in_avatar",
        login_hint="accounts.google.com",
        login_key="sign_in_button",
        required=True,
    ),
    Platform(
        key="chatgpt",
        label="ChatGPT",
        why="Kapak gorselini uretmek icin (istege bagli - atlanabilir)",
        url="https://chatgpt.com/",
        ready_key="chatgpt_ready",
        login_hint="auth.openai.com",
        login_key="chatgpt_login_button",
        required=False,
    ),
]


def by_key(key: str) -> Platform:
    for platform in PLATFORMS:
        if platform.key == key:
            return platform
    raise HusccError(
        f"Bilinmeyen platform: {key}\n"
        f"  Secenekler: {', '.join(p.key for p in PLATFORMS)}"
    )


# ------------------------------------------------------------------ kontrol
def is_signed_in(session: Session, platform: Platform, *, navigate: bool = True) -> bool:
    """Platformda oturum acik mi. Sayfayi acar (navigate=False ise mevcut sayfaya bakar)."""
    if navigate:
        try:
            session.goto(platform.url, timeout=60_000)
        except Exception:
            return False
        session.page.wait_for_timeout(1_200)

    try:
        url = session.page.url
    except Exception:
        return False

    if platform.login_hint and platform.login_hint in url:
        return False
    if platform.login_key and session.exists(platform.login_key, timeout=2_500):
        return False
    if session.exists(platform.ready_key, timeout=8_000):
        return True
    # Bazi sayfalarda hazir elementi gec yuklenir; adres yine de ipucu verir
    return platform.login_hint not in url if platform.login_hint else False


def status(session: Session, platforms: list[Platform] | None = None) -> dict[str, bool]:
    """Tarayici acmadan degil, acik oturumda her platformun durumunu dondurur."""
    outcome: dict[str, bool] = {}
    for platform in platforms or PLATFORMS:
        outcome[platform.key] = is_signed_in(session, platform)
    return outcome


# ------------------------------------------------------------------- giris
def login_one(
    session: Session,
    platform: Platform,
    *,
    timeout: float = 600.0,
) -> bool:
    """Tek platform icin yonlendirmeli giris. Zaten girilmisse dokunmaz."""
    step(f"{platform.label}")
    info(platform.why)

    if is_signed_in(session, platform):
        ok(f"{platform.label}: oturum zaten acik, atlaniyor.")
        return True

    print()
    print("  " + "-" * 66)
    print(f"  {platform.label} girisi gerekiyor.")
    print(f"  Acilan tarayici penceresinde giris yapin: {platform.url}")
    print("  Giris tamamlaninca bu ekran kendiliginden devam edecek.")
    print("  Atlamak icin: Ctrl+C")
    print("  " + "-" * 66)
    print()

    try:
        session.goto(platform.url, timeout=60_000)
    except Exception:
        pass
    session.shot(f"login-{platform.key}")

    deadline = time.time() + timeout
    announced = 0.0
    try:
        while time.time() < deadline:
            session.page.wait_for_timeout(2_500)
            if is_signed_in(session, platform, navigate=False):
                ok(f"{platform.label}: giris tamamlandi.")
                session.shot(f"login-{platform.key}-tamam")
                return True
            remaining = deadline - time.time()
            if remaining < announced - 60 or announced == 0.0:
                announced = remaining
                info(f"  bekleniyor... ({int(remaining)} sn)")
    except KeyboardInterrupt:
        print()
        warn(f"{platform.label}: atlandi.")
        return False

    warn(f"{platform.label}: sure doldu, giris algilanamadi.")
    return False


def login_all(
    session: Session,
    *,
    only: list[str] | None = None,
    timeout: float = 600.0,
) -> dict[str, bool]:
    """Tum platformlari sirayla gezer. Sonuc: {platform: giris_var_mi}."""
    wanted = [by_key(k) for k in only] if only else PLATFORMS
    results: dict[str, bool] = {}

    for platform in wanted:
        try:
            results[platform.key] = login_one(session, platform, timeout=timeout)
        except KeyboardInterrupt:
            print()
            warn(f"{platform.label}: atlandi.")
            results[platform.key] = False

    return results


def summarize(results: dict[str, bool]) -> int:
    """Sonucu basar; zorunlu bir platform eksikse 1 dondurur."""
    print()
    print("=" * 72)
    print("  OTURUM DURUMU")
    print("=" * 72)
    missing_required = 0
    for platform in PLATFORMS:
        if platform.key not in results:
            continue
        signed = results[platform.key]
        if signed:
            print(f"  ✓ {platform.label:22} acik")
        elif platform.required:
            missing_required += 1
            print(f"  ✗ {platform.label:22} YOK  (zorunlu)")
        else:
            print(f"  · {platform.label:22} yok  (istege bagli)")
    print("=" * 72)

    if missing_required:
        print()
        warn("Zorunlu bir giris eksik. Tekrar denemek icin:  huscc login")
        return 1

    if not all(results.get(p.key, True) for p in PLATFORMS if not p.required):
        print()
        info("ChatGPT girisi yok - kapak arka plani video karesinden uretilecek.")
        info("Sonradan eklemek icin:  huscc login --only chatgpt")
    return 0
