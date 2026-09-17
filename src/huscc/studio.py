"""YouTube Studio yayin akisi - tamamen tarayici uzerinden, API kullanmadan.

Akis adimlara bolunmustur. Her adim:
  * kendi ekran goruntusunu alir,
  * basarisiz olursa neyi denedigini raporlar,
  * "zorunlu degil" isaretliyse hatayi yutup devam eder.

Boylece tek bir buton degisirse tum yayin cokmez; eksik kalan is raporlanir.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .browser import BROWSER_CLOSED_MESSAGE, Session, StepFailure, is_closed_error
from .util import HusccError, hhmmss, info, ok, step as log_step, warn

VIDEO_ID_RE = re.compile(r"(?:youtu\.be/|/video/|v=)([A-Za-z0-9_-]{11})")

PRIVACY_KEYS = {"public": "public_radio", "unlisted": "unlisted_radio", "private": "private_radio"}

CATEGORY_NAMES = {
    "20": ("Oyun", "Gaming"),
    "24": ("Eğlence", "Entertainment"),
    "22": ("İnsanlar ve Bloglar", "People & Blogs"),
    "27": ("Eğitim", "Education"),
    "28": ("Bilim ve Teknoloji", "Science & Technology"),
}


@dataclass
class UploadPlan:
    video: Path
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    playlist: str = ""
    privacy: str = "public"
    publish_at: str | None = None          # ISO 8601 UTC
    thumbnail: Path | None = None
    subtitles: dict[str, Path] = field(default_factory=dict)
    made_for_kids: bool = False
    category_id: str = "20"
    notify_subscribers: bool = True
    pinned_comment: str = ""
    end_screen: bool = True
    ab_thumbnails: list[Path] = field(default_factory=list)
    is_short: bool = False


@dataclass
class UploadResult:
    video_id: str = ""
    url: str = ""
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    manual_todo: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.video_id)


# --------------------------------------------------------------- adim sarmali
class Runner:
    def __init__(self, session: Session, result: UploadResult) -> None:
        self.s = session
        self.result = result

    def step(self, name: str, label: str, fn, *, required: bool = True):
        info(f"  · {label}")
        try:
            value = fn()
            self.result.completed.append(name)
            self.s.shot(name)
            return value
        except StepFailure as exc:
            if required:
                raise
            warn(f"    atlandi: {label} ({exc.step})")
            self.result.skipped.append(name)
            self.result.warnings.append(f"{label}: {exc.step} bulunamadi")
            return None
        except Exception as exc:  # noqa: BLE001
            if is_closed_error(exc):
                raise HusccError(BROWSER_CLOSED_MESSAGE) from exc
            if required:
                raise HusccError(f"{label} basarisiz: {exc}") from exc
            warn(f"    atlandi: {label} ({exc})")
            self.result.skipped.append(name)
            self.result.warnings.append(f"{label}: {exc}")
            return None


# ------------------------------------------------------------------- yardim
def _video_id_from(text: str) -> str:
    match = VIDEO_ID_RE.search(text or "")
    return match.group(1) if match else ""


def _local_schedule(publish_at: str) -> tuple[str, str]:
    """ISO UTC -> Studio'nun bekledigi (tarih, saat) yerel metinleri."""
    raw = publish_at.replace("Z", "+00:00")
    moment = datetime.fromisoformat(raw).astimezone()
    return moment.strftime("%d.%m.%Y"), moment.strftime("%H:%M")


# ----------------------------------------------------------------- ana akis
def publish(session: Session, plan: UploadPlan, *, wait_upload: float = 3600.0) -> UploadResult:
    """Videoyu Studio uzerinden yukler ve yayinlar."""
    result = UploadResult()
    run = Runner(session, result)
    s = session

    if not plan.video.exists():
        raise HusccError(f"Video bulunamadi: {plan.video}")

    log_step("YouTube Studio")
    run.step("open_studio", "Studio aciliyor", lambda: s.goto("https://studio.youtube.com/"))
    s.ensure_signed_in()

    run.step("open_create", "Yukleme penceresi aciliyor", lambda: _open_upload(s))
    run.step("select_file", f"Dosya seciliyor ({plan.video.name})",
             lambda: s.upload_file("file_input", plan.video, timeout=30_000))

    # Video kimligi yukleme baslar baslamaz gorunur - erken yakala
    video_id = run.step("capture_id", "Video kimligi aliniyor",
                        lambda: _capture_video_id(s), required=False) or ""
    if video_id:
        result.video_id = video_id
        result.url = f"https://youtu.be/{video_id}"
        ok(f"    video kimligi: {video_id}")

    log_step("Ayrintilar")
    run.step("title", "Baslik yaziliyor",
             lambda: s.type_into("title_box", plan.title, timeout=60_000))
    run.step("description", "Aciklama yaziliyor",
             lambda: s.type_into("description_box", plan.description))

    if plan.thumbnail and plan.thumbnail.exists():
        run.step("thumbnail", "Kucuk resim yukleniyor",
                 lambda: s.upload_file("thumbnail_input", plan.thumbnail), required=False)

    if plan.playlist:
        run.step("playlist", f"Oynatma listesi: {plan.playlist}",
                 lambda: _set_playlist(s, plan.playlist), required=False)

    run.step("audience", "Hedef kitle: cocuklara yonelik degil",
             lambda: _set_audience(s, plan.made_for_kids))

    run.step("show_more", "Gelismis ayarlar aciliyor",
             lambda: s.click("show_more_button", required=False), required=False)

    if plan.tags:
        run.step("tags", f"Etiketler ({len(plan.tags)} adet)",
                 lambda: _set_tags(s, plan.tags), required=False)

    run.step("category", "Kategori seciliyor",
             lambda: _set_category(s, plan.category_id), required=False)

    log_step("Yukleme")
    percent = run.step("wait_upload", "Yuklemenin bitmesi bekleniyor",
                       lambda: _wait_upload(s, wait_upload), required=False)

    log_step("Gorunurluk")
    run.step("to_visibility", "Gorunurluk adimina geciliyor", lambda: _advance_to_visibility(s))

    if plan.publish_at:
        run.step("schedule", f"Yayin planlaniyor ({plan.publish_at})",
                 lambda: _set_schedule(s, plan.publish_at))
    else:
        run.step("visibility", f"Gorunurluk: {plan.privacy}",
                 lambda: s.click(PRIVACY_KEYS.get(plan.privacy, "public_radio")))

    if not plan.notify_subscribers:
        run.step("notify", "Abone bildirimi kapatiliyor",
                 lambda: s.click("notify_subscribers_checkbox", required=False), required=False)

    run.step("publish", "Yayinlaniyor", lambda: _publish(s))

    if not result.video_id:
        found = run.step("capture_id_late", "Video kimligi aliniyor",
                         lambda: _capture_video_id(s, timeout=20_000), required=False)
        if found:
            result.video_id = found
            result.url = f"https://youtu.be/{found}"

    run.step("close_dialog", "Pencere kapatiliyor",
             lambda: s.click("close_dialog_button", required=False), required=False)

    if result.video_id:
        ok(f"Yayinlandi: https://youtu.be/{result.video_id}")
    else:
        result.warnings.append("Video kimligi okunamadi - Studio'dan kontrol edin.")
        warn("Video kimligi okunamadi.")

    return result


# ---------------------------------------------------------------- alt adimlar
def _open_upload(s: Session) -> None:
    s.click("create_button")
    if not s.click("upload_menu_item", required=False):
        # Bazi surumlerde dogrudan yukleme sayfasina gidilebilir
        s.goto("https://studio.youtube.com/channel/upload")
    s.find("upload_dialog", timeout=30_000)


def _capture_video_id(s: Session, *, timeout: int = 45_000) -> str:
    deadline = time.time() + timeout / 1000.0
    while time.time() < deadline:
        link = s.find("published_url_link", timeout=3_000, required=False)
        if link is not None:
            try:
                href = link.get_attribute("href") or ""
                text = link.inner_text() or ""
            except Exception:
                href = text = ""
            found = _video_id_from(href) or _video_id_from(text)
            if found:
                return found
        try:
            found = _video_id_from(s.page.url)
            if found:
                return found
        except Exception:
            pass
        s.page.wait_for_timeout(1_500)
    return ""


def _set_playlist(s: Session, name: str) -> None:
    s.click("playlist_trigger")
    s.page.wait_for_timeout(800)

    search = s.find("playlist_search", timeout=6_000, required=False)
    if search is not None:
        try:
            search.fill(name, timeout=4_000)
            s.page.wait_for_timeout(900)
        except Exception:
            pass

    # Var olan listeyi sec
    pattern = re.compile(re.escape(name), re.I)
    try:
        existing = s.page.get_by_text(pattern).first
        if existing.count() and existing.is_visible():
            existing.click(timeout=4_000)
            s.page.wait_for_timeout(500)
            s.click("playlist_done", required=False)
            return
    except Exception:
        pass

    # Yoksa olustur
    if s.click("playlist_new_button", required=False):
        s.page.wait_for_timeout(600)
        title_field = s.find("playlist_new_title", timeout=8_000, required=False)
        if title_field is not None:
            try:
                title_field.fill(name, timeout=4_000)
            except Exception:
                title_field.type(name, delay=8)
        s.click("playlist_new_create", required=False)
        s.page.wait_for_timeout(1_200)
    s.click("playlist_done", required=False)


def _set_audience(s: Session, made_for_kids: bool) -> None:
    key = "for_kids_radio" if made_for_kids else "not_for_kids_radio"
    if not s.click(key, required=False):
        raise s.failure(key, "Hedef kitle secenegi bulunamadi")


def _set_tags(s: Session, tags: list[str]) -> None:
    field_ = s.find("tags_input", timeout=10_000)
    field_.click(timeout=6_000)
    # Etiketler virgulle ayrilarak tek seferde yazilabilir
    budget = 480
    chunk: list[str] = []
    used = 0
    for tag in tags:
        cost = len(tag) + 2
        if used + cost > budget:
            break
        chunk.append(tag)
        used += cost
    field_.type(", ".join(chunk), delay=4)
    s.page.wait_for_timeout(400)


def _set_category(s: Session, category_id: str) -> None:
    names = CATEGORY_NAMES.get(str(category_id))
    if not names:
        return
    if not s.click("category_dropdown", required=False):
        return
    s.page.wait_for_timeout(600)
    for name in names:
        if s.pick_option(name):
            return
    warn("    kategori secilemedi, varsayilan birakildi")


def _wait_upload(s: Session, timeout: float) -> int:
    """Yukleme yuzdesini izler; islenmeye gecince doner."""
    deadline = time.time() + timeout
    last_percent = -1
    done_words = re.compile(r"(işleniyor|isleniyor|processing|yüklendi|yuklendi|complete|tamam)", re.I)
    started = time.time()
    while time.time() < deadline:
        label = s.read("upload_progress_label", timeout=2_500)
        if label:
            match = re.search(r"(\d{1,3})\s*%", label)
            if match:
                percent = int(match.group(1))
                if percent != last_percent and percent % 5 == 0:
                    bar = "█" * (percent // 4) + "·" * (25 - percent // 4)
                    print(f"\r    [{bar}] %{percent}  ({hhmmss(time.time() - started)})",
                          end="", flush=True)
                    last_percent = percent
                if percent >= 100:
                    print()
                    return 100
            if done_words.search(label):
                print()
                info(f"    {label.strip()}")
                return 100
        s.page.wait_for_timeout(2_000)
    print()
    warn("    yukleme suresi doldu, yine de devam ediliyor")
    return last_percent if last_percent > 0 else 0


def _advance_to_visibility(s: Session) -> None:
    """Ayrintilar -> Video ogeleri -> Kontroller -> Gorunurluk."""
    for attempt in range(6):
        if s.exists("public_radio", timeout=2_500) or s.exists("schedule_radio", timeout=1_500):
            return
        if not s.click("next_button", required=False):
            break
        s.page.wait_for_timeout(1_200)
    if s.exists("public_radio", timeout=5_000):
        return
    raise s.failure("next_button", "Gorunurluk adimina gecilemedi")


def _set_schedule(s: Session, publish_at: str) -> None:
    date_text, time_text = _local_schedule(publish_at)
    if not s.click("schedule_radio", required=False):
        raise s.failure("schedule_radio", "Planlama secenegi bulunamadi")
    s.page.wait_for_timeout(700)

    s.click("schedule_date_trigger", required=False)
    s.page.wait_for_timeout(500)
    date_field = s.find("schedule_date_input", timeout=8_000, required=False)
    if date_field is not None:
        try:
            date_field.fill(date_text, timeout=4_000)
            date_field.press("Enter")
        except Exception:
            warn("    tarih alani doldurulamadi")
    s.page.wait_for_timeout(500)

    time_field = s.find("schedule_time_input", timeout=6_000, required=False)
    if time_field is not None:
        try:
            time_field.fill(time_text, timeout=4_000)
            time_field.press("Enter")
        except Exception:
            warn("    saat alani doldurulamadi")
    s.page.wait_for_timeout(500)
    info(f"    planlandi: {date_text} {time_text} (yerel saat)")


def _publish(s: Session) -> None:
    if not s.click("publish_button", timeout=20_000, required=False):
        raise s.failure("publish_button", "Yayinla dugmesi bulunamadi")
    s.page.wait_for_timeout(3_500)


# ------------------------------------------------------------ yayin sonrasi
def add_subtitles(s: Session, video_id: str, subtitles: dict[str, Path]) -> list[str]:
    """Yayin sonrasi altyazi yukler. Basarili dilleri dondurur."""
    added: list[str] = []
    if not video_id or not subtitles:
        return added
    for lang, path in subtitles.items():
        if not path or not Path(path).exists():
            continue
        try:
            s.goto(f"https://studio.youtube.com/video/{video_id}/translations")
            s.page.wait_for_timeout(1_500)
            if not s.click("subtitles_add_button", required=False):
                warn(f"    altyazi ekleme dugmesi yok ({lang})")
                continue
            s.page.wait_for_timeout(700)
            s.click("subtitles_upload_option", required=False)
            s.page.wait_for_timeout(700)
            s.upload_file("subtitles_file_input", Path(path))
            s.page.wait_for_timeout(1_500)
            s.click("publish_button", required=False)
            added.append(lang)
            ok(f"    altyazi eklendi: {lang}")
        except Exception as exc:  # noqa: BLE001
            warn(f"    altyazi eklenemedi ({lang}): {exc}")
    return added


def add_end_screen(s: Session, video_id: str) -> bool:
    """Bitis ekranini sablondan uygular (API'nin yapamadigi is)."""
    if not video_id:
        return False
    try:
        s.goto(f"https://studio.youtube.com/video/{video_id}/editor")
        s.page.wait_for_timeout(2_500)
        if not s.click("endscreen_add_button", required=False):
            return False
        s.page.wait_for_timeout(1_500)
        s.click("endscreen_template_first", required=False)
        s.page.wait_for_timeout(1_000)
        s.click("endscreen_apply", required=False)
        s.page.wait_for_timeout(1_000)
        saved = s.click("editor_save_button", required=False)
        s.page.wait_for_timeout(2_000)
        return bool(saved)
    except Exception as exc:  # noqa: BLE001
        warn(f"    bitis ekrani eklenemedi: {exc}")
        return False


def pin_first_comment(s: Session, video_id: str, text: str) -> bool:
    """Ilk yorumu atar ve sabitler (API'nin yapamadigi is)."""
    if not video_id or not text.strip():
        return False
    try:
        s.goto(f"https://www.youtube.com/watch?v={video_id}")
        s.page.wait_for_timeout(3_000)
        s.page.mouse.wheel(0, 1400)
        s.page.wait_for_timeout(2_000)

        if not s.click("watch_comment_box", required=False):
            return False
        s.page.wait_for_timeout(800)
        box = s.find("watch_comment_input", timeout=8_000, required=False)
        if box is None:
            return False
        box.click(timeout=5_000)
        box.type(text, delay=5)
        s.page.wait_for_timeout(500)
        if not s.click("watch_comment_submit", required=False):
            return False
        s.page.wait_for_timeout(3_000)

        # Sabitle
        if s.click("own_comment_menu", required=False):
            s.page.wait_for_timeout(800)
            if s.click("pin_menu_item", required=False):
                s.page.wait_for_timeout(700)
                s.click("pin_confirm", required=False)
                s.page.wait_for_timeout(1_200)
                return True
        return True  # yorum atildi, sabitlenemedi
    except Exception as exc:  # noqa: BLE001
        warn(f"    yorum atilamadi: {exc}")
        return False


def add_ab_thumbnails(s: Session, video_id: str, images: list[Path]) -> bool:
    """Kucuk resim A/B testi (Test ve karsilastir) - yalnizca uygun kanallarda."""
    usable = [Path(p) for p in images if Path(p).exists()][:3]
    if not video_id or len(usable) < 2:
        return False
    try:
        s.goto(f"https://studio.youtube.com/video/{video_id}/edit")
        s.page.wait_for_timeout(2_500)
        if not s.click("ab_test_button", required=False):
            return False
        s.page.wait_for_timeout(1_200)
        for image in usable[1:]:
            s.upload_file("ab_add_thumbnail_input", image, timeout=10_000)
            s.page.wait_for_timeout(1_200)
        s.click("publish_button", required=False)
        s.page.wait_for_timeout(1_500)
        return True
    except Exception as exc:  # noqa: BLE001
        warn(f"    A/B testi kurulamadi: {exc}")
        return False


def verify(s: Session, video_id: str, expected_title: str) -> dict:
    """Yayin sonrasi dogrulama: video gercekten yayinda mi, baslik dogru mu."""
    outcome = {"reachable": False, "title_match": False, "title": ""}
    if not video_id:
        return outcome
    try:
        s.goto(f"https://www.youtube.com/watch?v={video_id}")
        s.page.wait_for_timeout(3_000)
        title = (s.page.title() or "").replace(" - YouTube", "").strip()
        outcome["reachable"] = "youtube.com/watch" in s.page.url
        outcome["title"] = title
        head = expected_title.strip()[:25].lower()
        outcome["title_match"] = bool(head and head in title.lower())
        s.shot("dogrulama")
    except Exception as exc:  # noqa: BLE001
        warn(f"    dogrulama yapilamadi: {exc}")
    return outcome


# ------------------------------------------------ yayinlanmis videoyu guncelle
EDIT_VISIBILITY_KEYS = {
    "public": "edit_visibility_option_public",
    "unlisted": "edit_visibility_option_unlisted",
    "private": "edit_visibility_option_private",
}


def update_existing(
    session: Session,
    video_id: str,
    plan: UploadPlan,
    *,
    fields: set[str] | None = None,
) -> UploadResult:
    """Yayindaki bir videonun meta verisini duzenleme sayfasindan gunceller.

    `fields` verilmezse hepsi guncellenir:
    title, description, tags, thumbnail, playlist, visibility
    """
    result = UploadResult(video_id=video_id, url=f"https://youtu.be/{video_id}")
    run = Runner(session, result)
    s = session
    wanted = fields or {"title", "description", "tags", "thumbnail", "playlist", "visibility"}

    log_step(f"Meta veri guncelleniyor - {video_id}")
    run.step("open_edit", "Duzenleme sayfasi aciliyor",
             lambda: s.goto(f"https://studio.youtube.com/video/{video_id}/edit"))
    s.ensure_signed_in()
    run.step("edit_ready", "Sayfa hazir", lambda: s.find("edit_page_ready", timeout=30_000))

    if "title" in wanted and plan.title:
        run.step("title", "Baslik", lambda: s.type_into("title_box", plan.title))
    if "description" in wanted and plan.description:
        run.step("description", "Aciklama",
                 lambda: s.type_into("description_box", plan.description))
    if "thumbnail" in wanted and plan.thumbnail and plan.thumbnail.exists():
        run.step("thumbnail", "Kucuk resim",
                 lambda: s.upload_file("thumbnail_input", plan.thumbnail), required=False)
    if "playlist" in wanted and plan.playlist:
        run.step("playlist", f"Oynatma listesi: {plan.playlist}",
                 lambda: _set_playlist(s, plan.playlist), required=False)
    if "tags" in wanted and plan.tags:
        run.step("show_more", "Gelismis ayarlar",
                 lambda: s.click("show_more_button", required=False), required=False)
        run.step("tags", f"Etiketler ({len(plan.tags)})",
                 lambda: _set_tags(s, plan.tags), required=False)
    if "visibility" in wanted:
        run.step("visibility", f"Gorunurluk: {plan.privacy}",
                 lambda: _set_edit_visibility(s, plan.privacy), required=False)

    run.step("save", "Kaydediliyor", lambda: _save_edit(s))
    ok(f"Guncellendi: https://youtu.be/{video_id}")
    return result


def _set_edit_visibility(s: Session, privacy: str) -> None:
    if not s.click("edit_visibility_dropdown", required=False):
        return
    s.page.wait_for_timeout(600)
    key = EDIT_VISIBILITY_KEYS.get(privacy, "edit_visibility_option_public")
    if not s.click(key, required=False):
        warn("    gorunurluk secenegi bulunamadi")


def _save_edit(s: Session) -> None:
    if not s.click("edit_save_button", timeout=15_000, required=False):
        raise s.failure("edit_save_button", "Kaydet dugmesi bulunamadi")
    s.page.wait_for_timeout(2_500)


# ------------------------------------------------------------ sonda (probe)
#  Canli Studio'da hangi secicilerin tuttugunu, hicbir sey yuklemeden olcer.
PROBE_HOME = ["probe_studio_home", "create_button", "signed_in_avatar"]
PROBE_EDIT = [
    "edit_page_ready", "title_box", "description_box", "thumbnail_input",
    "playlist_trigger", "show_more_button", "tags_input",
    "edit_visibility_dropdown", "edit_save_button",
]
PROBE_UPLOAD_DIALOG = ["upload_dialog", "file_input"]


def probe(session: Session, *, video_id: str = "") -> dict:
    """Secici haritasinin canli Studio'da ne kadar tuttugunu raporlar."""
    report: dict[str, dict] = {"home": {}, "upload_dialog": {}, "edit": {}}
    s = session

    log_step("Studio ana sayfasi")
    s.goto("https://studio.youtube.com/")
    s.ensure_signed_in()
    s.page.wait_for_timeout(1_500)
    for key in PROBE_HOME:
        report["home"][key] = _check(s, key)

    log_step("Yukleme penceresi")
    try:
        s.click("create_button", required=False)
        s.page.wait_for_timeout(800)
        s.click("upload_menu_item", required=False)
        s.page.wait_for_timeout(1_500)
        for key in PROBE_UPLOAD_DIALOG:
            report["upload_dialog"][key] = _check(s, key)
        s.click("close_dialog_button", required=False)
        s.page.wait_for_timeout(800)
    except Exception as exc:  # noqa: BLE001
        warn(f"  yukleme penceresi acilamadi: {exc}")

    if video_id:
        log_step(f"Duzenleme sayfasi ({video_id})")
        s.goto(f"https://studio.youtube.com/video/{video_id}/edit")
        s.page.wait_for_timeout(2_500)
        for key in PROBE_EDIT:
            report["edit"][key] = _check(s, key)
    else:
        info("  Duzenleme sayfasi atlandi (yayinlanmis video yok).")

    return report


def _check(s: Session, key: str) -> dict:
    """Bir anahtarin hangi strateji ile tuttugunu bulur."""
    for kind, value in s.selectors.strategies(key):
        try:
            locator = s._build(kind, value)
            target = locator.first
            if target.count() and target.is_visible():
                return {"ok": True, "matched": f"{kind}={value}"}
        except Exception:
            continue
    # Gorunmez ama DOM'da olabilir (orn. gizli dosya girisi)
    for kind, value in s.selectors.strategies(key):
        try:
            if s._build(kind, value).first.count():
                return {"ok": True, "matched": f"{kind}={value}", "hidden": True}
        except Exception:
            continue
    return {"ok": False, "matched": ""}


def print_probe(report: dict) -> int:
    """Raporu basar, tutmayan anahtar sayisini dondurur."""
    broken = 0
    labels = {"home": "Studio ana sayfasi", "upload_dialog": "Yukleme penceresi",
              "edit": "Duzenleme sayfasi", "chatgpt": "ChatGPT (kapak gorseli)"}
    for section, rows in report.items():
        if not rows:
            continue
        print()
        print(f"  {labels.get(section, section)}")
        for key, outcome in rows.items():
            if outcome["ok"]:
                note = " (gizli)" if outcome.get("hidden") else ""
                ok(f"  {key:28} {outcome['matched']}{note}")
            else:
                broken += 1
                from .util import err as _err

                _err(f"  {key:28} TUTMADI")
    return broken
