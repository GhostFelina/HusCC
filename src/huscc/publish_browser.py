"""Tarayici uzerinden yayin - boru hattinin YouTube Studio ayagi.

`pipeline.upload` bu modulu cagirir. Burada:
  * oturum acilir (kalici profil, bir kez giris),
  * yayin oncesi kontroller yapilir,
  * Studio akisi surulur,
  * yayin sonrasi isler (altyazi, bitis ekrani, sabit yorum, A/B, dogrulama)
    tek tek denenir ve hicbiri yayini riske atmaz.
"""
from __future__ import annotations

from pathlib import Path

from . import studio
from .browser import Selectors, Session
from .config import Config
from .seo import Metadata
from .util import HusccError, err, info, ok, opt_path, read_json, step, utc_now, warn, write_json


# ------------------------------------------------------------ oturum isareti
def marker_path(cfg: Config) -> Path:
    """Gercekten giris yapildigini gosteren kayit."""
    return cfg.browser_profile_dir / "huscc-session.json"


def session_info(cfg: Config) -> dict:
    return read_json(marker_path(cfg), {}) or {}


def is_logged_in(cfg: Config) -> bool:
    """Tarayici acmadan, daha once basarili giris yapilmis mi diye bakar."""
    return bool(session_info(cfg).get("signed_in_at"))


def _remember(cfg: Config, title: str = "") -> None:
    write_json(
        marker_path(cfg),
        {
            "signed_in_at": utc_now().isoformat(),
            "channel": title,
            "profile": str(cfg.browser_profile_dir),
        },
    )


# --------------------------------------------------------------- on kontrol
def preflight(meta: Metadata, video: Path, thumbnail: Path | None) -> list[str]:
    """Yayindan once dosyalari ve sinirlari denetler. Bos liste = temiz."""
    problems: list[str] = []

    if not video.exists():
        problems.append(f"Video yok: {video}")
    elif video.stat().st_size < 100_000:
        problems.append(f"Video sasirtici derecede kucuk: {video.name}")

    if not meta.title.strip():
        problems.append("Baslik bos")
    elif len(meta.title) > 100:
        problems.append(f"Baslik 100 karakteri asiyor ({len(meta.title)})")
    if "<" in meta.title or ">" in meta.title:
        problems.append("Baslikta < veya > karakteri olamaz")

    if len(meta.description) > 5000:
        problems.append(f"Aciklama 5000 karakteri asiyor ({len(meta.description)})")
    if "<" in meta.description or ">" in meta.description:
        problems.append("Aciklamada < veya > karakteri olamaz")

    tag_chars = len(", ".join(meta.tags))
    if tag_chars > 500:
        problems.append(f"Etiketler 500 karakteri asiyor ({tag_chars})")

    if thumbnail is not None:
        if not thumbnail.exists():
            problems.append(f"Kapak yok: {thumbnail}")
        elif thumbnail.stat().st_size > 2_000_000:
            problems.append(f"Kapak 2 MB'i asiyor ({thumbnail.stat().st_size // 1024} KB)")

    if meta.privacy not in {"public", "unlisted", "private"}:
        problems.append(f"Gecersiz gizlilik: {meta.privacy}")

    return problems


def open_session(cfg: Config, shots_dir: Path | None = None) -> Session:
    selectors = Selectors.load(cfg.selectors_path)
    return Session(
        cfg.browser_profile_dir,
        selectors,
        shots_dir=shots_dir,
        headless=bool(cfg.get("browser.headless", False)),
        slow_mo=int(cfg.get("browser.slow_mo", 0)),
        browser_channel=str(cfg.get("browser.channel", "chrome")),
    )


def login(cfg: Config) -> str:
    """Bir kerelik Google girisi. Kanal adini dondurur."""
    session = open_session(cfg, cfg.work_dir / "login")
    try:
        session.start()
        session.ensure_signed_in(timeout=float(cfg.get("browser.login_timeout", 900)))
        session.goto("https://studio.youtube.com/")
        session.page.wait_for_timeout(2_000)
        title = (session.page.title() or "").replace(" - YouTube Studio", "").strip()
        _remember(cfg, title)
        ok(f"Oturum hazir: {title or 'YouTube Studio'}")
        return title
    finally:
        session.stop()


# -------------------------------------------------------------------- yayin
def run(
    cfg: Config,
    *,
    video: Path,
    meta: Metadata,
    thumbnail: Path | None,
    subtitles: dict[str, Path],
    shots_dir: Path,
    thumbnail_variants: list[Path] | None = None,
    shorts: list[Path] | None = None,
    dry_run: bool = False,
) -> dict:
    """Tum yayin akisini calistirir ve sonucu sozluk olarak dondurur."""
    problems = preflight(meta, video, thumbnail)
    if problems:
        raise HusccError(
            "Yayin oncesi kontrol basarisiz:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )
    ok("Yayin oncesi kontroller temiz.")

    if dry_run:
        return {"dry_run": True}

    plan = studio.UploadPlan(
        video=video,
        title=meta.title,
        description=meta.description,
        tags=meta.tags,
        playlist=meta.playlist,
        privacy=meta.privacy,
        publish_at=meta.publish_at,
        thumbnail=thumbnail,
        subtitles=subtitles,
        made_for_kids=meta.made_for_kids,
        category_id=meta.category_id,
        notify_subscribers=meta.notify_subscribers,
        pinned_comment=meta.pinned_comment,
        end_screen=bool(cfg.get("upload.end_screen", True)),
        ab_thumbnails=[Path(p) for p in (thumbnail_variants or [])],
    )

    session = open_session(cfg, shots_dir)
    keep_open = bool(cfg.get("browser.keep_open_on_error", True))
    result: studio.UploadResult | None = None

    try:
        session.start()
        session.ensure_signed_in(timeout=float(cfg.get("browser.login_timeout", 900)))
        _remember(cfg)
        result = studio.publish(
            session, plan, wait_upload=float(cfg.get("browser.upload_timeout", 5400))
        )

        if result.video_id:
            _post_publish(cfg, session, plan, result, shorts=shorts)
        else:
            result.manual_todo.append(
                "Video kimligi okunamadi; yayin sonrasi islemler yapilamadi."
            )

        return {
            "video_id": result.video_id,
            "url": result.url,
            "completed": result.completed,
            "skipped": result.skipped,
            "warnings": result.warnings,
            "manual_todo": result.manual_todo,
            "shots_dir": str(shots_dir),
        }

    except Exception:
        if keep_open:
            err("Adim tamamlanamadi. Tarayici penceresi ACIK birakiliyor;")
            err("elle tamamlayabilir ya da secicileri duzeltip tekrar calistirabilirsiniz.")
            info(f"Ekran goruntuleri: {shots_dir}")
            raise
        raise
    finally:
        if not keep_open:
            session.stop()


def _post_publish(
    cfg: Config,
    session: Session,
    plan: studio.UploadPlan,
    result: studio.UploadResult,
    *,
    shorts: list[Path] | None = None,
) -> None:
    """Yayin sonrasi isler. Hicbiri zorunlu degil; hata yayini bozmaz."""
    step("Yayin sonrasi")
    video_id = result.video_id

    if plan.subtitles:
        info("  · Altyazilar ekleniyor")
        added = studio.add_subtitles(session, video_id, plan.subtitles)
        if added:
            result.completed.append("subtitles")
        else:
            result.manual_todo.append("Altyazilari Studio > Altyazilar bolumunden ekleyin.")

    if cfg.get("upload.end_screen", True):
        info("  · Bitis ekrani uygulaniyor")
        if studio.add_end_screen(session, video_id):
            result.completed.append("end_screen")
            ok("    bitis ekrani eklendi")
        else:
            result.manual_todo.append(
                "Bitis ekranini Studio > Duzenleyici > Bitis ekrani'ndan ekleyin."
            )

    if cfg.get("upload.pin_first_comment", True) and plan.pinned_comment:
        info("  · Ilk yorum atiliyor ve sabitleniyor")
        if studio.pin_first_comment(session, video_id, plan.pinned_comment):
            result.completed.append("pinned_comment")
            ok("    yorum atildi")
        else:
            result.manual_todo.append("Ilk yorumu elle atip sabitleyin.")

    if cfg.get("upload.ab_thumbnails", False) and len(plan.ab_thumbnails) >= 2:
        info("  · Kucuk resim A/B testi kuruluyor")
        if studio.add_ab_thumbnails(session, video_id, plan.ab_thumbnails):
            result.completed.append("ab_thumbnails")
            ok("    A/B testi kuruldu")
        else:
            result.warnings.append("A/B testi bu kanalda kullanilamiyor olabilir.")

    if shorts:
        info(f"  · Shorts yukleniyor ({len(shorts)} adet)")
        for index, path in enumerate(shorts, start=1):
            short_path = opt_path(path)
            if not short_path:
                continue
            short_plan = studio.UploadPlan(
                video=short_path,
                title=f"{plan.title[:60]} #Shorts",
                description=f"{plan.description[:300]}\n\nTam video: https://youtu.be/{video_id}",
                tags=plan.tags[:20],
                privacy=plan.privacy,
                made_for_kids=plan.made_for_kids,
                category_id=plan.category_id,
                notify_subscribers=False,
                end_screen=False,
                is_short=True,
            )
            try:
                short_result = studio.publish(session, short_plan)
                if short_result.video_id:
                    result.completed.append(f"short_{index}")
                    ok(f"    Shorts {index}: https://youtu.be/{short_result.video_id}")
            except Exception as exc:  # noqa: BLE001
                warn(f"    Shorts {index} yuklenemedi: {exc}")
                result.manual_todo.append(f"Shorts {index} elle yuklenmeli: {short_path.name}")

    if cfg.get("upload.verify_after", True):
        info("  · Yayin dogrulaniyor")
        outcome = studio.verify(session, video_id, plan.title)
        if outcome.get("reachable"):
            ok(f"    video yayinda: {outcome.get('title', '')[:60]}")
            result.completed.append("verified")
            if not outcome.get("title_match"):
                result.warnings.append("Yayindaki baslik beklenenden farkli gorunuyor.")
        else:
            result.warnings.append("Video dogrulanamadi (planli yayinsa normaldir).")
