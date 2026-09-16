"""Kendi kendini sinama: makinenin gercekten hazir olup olmadigini kanitlar.

`huscc selftest` sentetik bir video uretir ve boru hattinin tamamini
(analiz -> brief -> kapak -> kurgu -> yayin oncesi kontroller) gercek dosyalarla
calistirir. YouTube'a hicbir sey gitmez, kullanicinin klasorlerine dokunulmaz;
her sey gecici bir dizinde olur ve sonunda silinir.

Amac: "baska bir bilgisayarda calisir mi?" sorusunu tahminle degil, kanitla
cevaplamak.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import brief as brief_mod
from . import media, pipeline, publish_browser, seo, thumbnail
from .config import Config, load_config
from .discover import VideoFile
from .util import HusccError, ensure_dir, human_size, info, ok, err, step, warn

TEST_VIDEO_NAME = "th16 hydra klan savasi 3 yildiz"
TEST_SECONDS = 40


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    fatal: bool = True


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    seconds: float = 0.0

    def add(self, name: str, passed: bool, detail: str = "", *, fatal: bool = True) -> bool:
        self.checks.append(Check(name, passed, detail, fatal))
        if passed:
            ok(f"{name}" + (f" — {detail}" if detail else ""))
        elif fatal:
            err(f"{name}" + (f" — {detail}" if detail else ""))
        else:
            warn(f"{name}" + (f" — {detail}" if detail else ""))
        return passed

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and c.fatal]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.passed and not c.fatal]

    @property
    def ok(self) -> bool:
        return not self.failures


# --------------------------------------------------------------- 1. ortam
def check_environment(cfg: Config, report: Report) -> None:
    step("1/5 Ortam")

    import sys

    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    report.add("Python surumu", sys.version_info >= (3, 10), version)

    try:
        report.add("ffmpeg", True, media.ffmpeg_bin())
    except HusccError as exc:
        report.add("ffmpeg", False, str(exc).splitlines()[0])
        return

    report.add(
        "ffprobe", media.have_ffprobe(),
        "bulundu" if media.have_ffprobe() else "yok - ffmpeg ciktisi ayristirilacak",
        fatal=False,
    )

    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401

        report.add("Pillow + numpy", True)
    except ImportError as exc:
        report.add("Pillow + numpy", False, str(exc))

    try:
        font = thumbnail.resolve_font(cfg.assets_dir)
        bundled = "assets" in str(font)
        report.add("Kapak fontu", True, f"{Path(font).name}" + (" (depoda)" if bundled else " (sistem)"))
    except HusccError as exc:
        report.add("Kapak fontu", False, str(exc).splitlines()[0])

    try:
        import playwright  # noqa: F401

        report.add("Playwright", True)
    except ImportError:
        report.add("Playwright", False, "uv pip install playwright")

    from .cli import _find_browser

    channel = str(cfg.get("browser.channel", "chrome"))
    found = _find_browser(channel) or _find_browser("msedge")
    report.add(
        "Tarayici", bool(found),
        found or "Chrome/Edge yok - Playwright Chromium'a dusulecek",
        fatal=False,
    )

    report.add("Element haritasi", cfg.selectors_path.exists(), cfg.selectors_path.name)

    from . import subtitles

    report.add(
        "Altyazi motoru", subtitles.available(),
        "hazir" if subtitles.available() else "yok - altyazi uretilmez",
        fatal=False,
    )


# ----------------------------------------------------------- 2. test videosu
def make_test_video(dest: Path, seconds: int = TEST_SECONDS) -> Path:
    """Sentetik ama gercek bir mp4 uretir (gorsel desen + ses tonu)."""
    ensure_dir(dest.parent)
    from .util import run

    run([
        media.ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=420:duration={seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
        str(dest),
    ])
    return dest


# ------------------------------------------------------------------ 3. akis
def run_pipeline(cfg: Config, video: Path, report: Report) -> pipeline.Job | None:
    from .util import slugify

    job = pipeline.Job(
        video=VideoFile(video),
        slug=slugify(TEST_VIDEO_NAME),
        work=cfg.work_for(slugify(TEST_VIDEO_NAME)),
        cfg=cfg,
    )

    step("3/5 Analiz")
    try:
        state = pipeline.prep(job, brain="heuristic", frame_count=6, do_subtitles=False)
        frames = [Path(f) for f in state.get("frames", [])]
        report.add("Kare cikarma", len(frames) >= 4, f"{len(frames)} kare")
        info_data = state.get("media", {})
        report.add(
            "Teknik analiz",
            info_data.get("width") == 1280 and info_data.get("duration", 0) > 30,
            f"{info_data.get('width')}x{info_data.get('height')}, "
            f"{info_data.get('duration', 0):.0f} sn, ses: "
            f"{'var' if info_data.get('has_audio') else 'yok'}",
        )
        current = brief_mod.load_brief(job.work)
        problems = brief_mod.validate(current) if current else ["brief yok"]
        report.add("Brief uretimi", not problems, "; ".join(problems) or "gecerli")
        report.add(
            "Icerik tespiti",
            bool(current and current.town_hall == "TH16"),
            f"TH: {current.town_hall if current else '-'}, "
            f"tur: {current.content_type if current else '-'}",
        )
    except Exception as exc:  # noqa: BLE001
        report.add("Analiz", False, str(exc).splitlines()[0])
        return None

    step("4/5 Kapak ve kurgu")
    try:
        state = pipeline.render(
            job, image_source="frame", make_shorts=False, interactive=False
        )
    except Exception as exc:  # noqa: BLE001
        report.add("Kurgu", False, str(exc).splitlines()[0])
        return job

    thumb = Path(state.get("thumbnail", ""))
    if thumb.exists():
        from PIL import Image

        with Image.open(thumb) as image:
            size = image.size
        report.add(
            "Kapak uretimi",
            size == (1280, 720) and thumb.stat().st_size <= 2_000_000,
            f"{size[0]}x{size[1]}, {human_size(thumb.stat().st_size)}",
        )
        report.add(
            "Kapak varyantlari",
            len(state.get("thumbnail_variants", [])) >= 2,
            f"{len(state.get('thumbnail_variants', []))} adet",
        )
    else:
        report.add("Kapak uretimi", False, "kapak dosyasi yok")

    final = Path(state.get("final_video", ""))
    if final.exists():
        try:
            rendered = media.probe(final)
            report.add(
                "Kurgulanmis video",
                rendered.duration > 40 and rendered.has_audio,
                f"{human_size(final.stat().st_size)}, {rendered.duration:.0f} sn "
                f"(outro dahil), ses: {'var' if rendered.has_audio else 'yok'}",
            )
        except Exception as exc:  # noqa: BLE001
            report.add("Kurgulanmis video", False, str(exc).splitlines()[0])
    else:
        report.add("Kurgulanmis video", False, "cikti dosyasi yok")

    meta_dict = state.get("metadata", {})
    meta = seo.Metadata(**{
        k: v for k, v in meta_dict.items() if k in seo.Metadata.__dataclass_fields__
    })
    report.add(
        "Meta veri",
        bool(meta.title) and len(meta.title) <= 100 and len(meta.tags) > 5,
        f"baslik {len(meta.title)} karakter, {len(meta.tags)} etiket, "
        f"{len(meta.chapters)} bolum",
    )
    report.add(
        "Aciklama (SEO/AEO)",
        "SIKÇA SORULAN" in meta.description and len(meta.description) <= 5000,
        f"{len(meta.description)} karakter",
    )
    report.add(
        "Lokalizasyon (GEO)",
        "en" in meta.localizations,
        ", ".join(meta.localizations) or "yok",
        fatal=False,
    )

    step("5/5 Yayin oncesi kontroller")
    problems = publish_browser.preflight(meta, final, thumb if thumb.exists() else None)
    report.add("Preflight", not problems, "; ".join(problems) or "temiz")
    return job


# -------------------------------------------------------------- 4. tarayici
def check_browser(cfg: Config, report: Report) -> None:
    step("Tarayici (yalnizca acilis - giris gerekmez)")
    session = publish_browser.open_session(cfg, cfg.work_dir / "selftest-browser")
    session.headless = True
    try:
        started = time.time()
        session.start()
        report.add("Tarayici acilisi", True, f"{session.channel}, {time.time() - started:.1f} sn")
        session.goto("https://studio.youtube.com/", timeout=45_000)
        url = session.page.url
        reachable = "google.com" in url or "youtube.com" in url
        report.add("Studio erisimi", reachable, url[:60])
        signed = "accounts.google.com" not in url
        report.add(
            "Google oturumu", signed,
            "acik" if signed else "yok - 'huscc login' calistirin",
            fatal=False,
        )
    except Exception as exc:  # noqa: BLE001
        report.add("Tarayici acilisi", False, str(exc).splitlines()[0])
    finally:
        session.stop()


# ------------------------------------------------------------------- calistir
def run(*, keep: bool = False, with_browser: bool = False) -> int:
    started = time.time()
    report = Report()

    base = load_config()
    check_environment(base, report)
    if report.failures:
        _summary(report, time.time() - started, None)
        return 1

    sandbox = Path(tempfile.mkdtemp(prefix="huscc-selftest-"))
    video_dir = ensure_dir(sandbox / "CC")
    info(f"Gecici alan: {sandbox}")

    cfg = Config(
        raw={
            **base.raw,
            "paths": {
                "video_dir": str(video_dir),
                "work_dir": str(sandbox / "work"),
                "out_dir": str(sandbox / "out"),
            },
            "upload": {**base.section("upload"), "schedule": ""},
            "subtitles": {**base.section("subtitles"), "enabled": False},
            "edit": {**base.section("edit"), "shorts": False, "outro_duration": 6},
            "thumbnail": {**base.section("thumbnail"), "source": "frame", "ai_outro": False},
        },
        root=base.root,
    )

    job = None
    try:
        step("2/5 Test videosu")
        video = make_test_video(video_dir / f"{TEST_VIDEO_NAME}.mp4")
        report.add("Sentetik video", video.exists(), f"{human_size(video.stat().st_size)}")

        job = run_pipeline(cfg, video, report)

        if with_browser:
            check_browser(cfg, report)
    except Exception:  # noqa: BLE001
        report.add("Beklenmeyen hata", False, traceback.format_exc().splitlines()[-1])
    finally:
        if keep:
            info(f"Gecici alan korundu: {sandbox}")
        else:
            shutil.rmtree(sandbox, ignore_errors=True)

    return _summary(report, time.time() - started, job)


def _summary(report: Report, seconds: float, job) -> int:
    print()
    print("=" * 72)
    passed = sum(1 for c in report.checks if c.passed)
    total = len(report.checks)
    print(f"  SONUC: {passed}/{total} kontrol gecti   ({seconds:.1f} sn)")
    print("=" * 72)

    if report.warnings:
        print()
        print("  Uyarilar (calismayi engellemez):")
        for check in report.warnings:
            print(f"    ! {check.name}: {check.detail}")

    if report.failures:
        print()
        err("HAZIR DEGIL. Su kontroller basarisiz:")
        for check in report.failures:
            print(f"    x {check.name}: {check.detail}")
        print()
        print("  Coz, sonra tekrar calistir:  huscc selftest")
        return 1

    print()
    ok("MAKINE HAZIR.")
    print("  Yerel boru hattinin tamami calisti: analiz, brief, kapak,")
    print("  kurgu, meta veri ve yayin oncesi kontroller.")
    print()
    print("  Siradaki adim:")
    print("    1. huscc login      (bir kerelik Google girisi)")
    print("    2. huscc probe      (Studio secicilerini dogrula)")
    print('    3. huscc publish "video adi"')
    return 0
