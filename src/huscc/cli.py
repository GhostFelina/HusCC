"""HusCC komut satiri arayuzu."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import brief as brief_mod
from . import media, pipeline, publish_browser, subtitles, thumbnail, youtube
from .config import Config, load_config
from .discover import list_videos
from .util import HusccError, err, human_size, info, ok, step, warn

BANNER = r"""
  _   _           ____ ____
 | | | |_   _ ___/ ___/ ___|     Clash of Clans -> YouTube otomasyonu
 | |_| | | | / __| |  | |
 |  _  | |_| \__ \ |__| |___     SEO · GEO · AEO · CTR · Thumbnail · Altyazi
 |_| |_|\__,_|___/\____\____|
"""


def _cfg(args) -> Config:
    return load_config(getattr(args, "config", None))


# ---------------------------------------------------------------- komutlar
def cmd_doctor(args) -> int:
    print(BANNER)
    step("Sistem kontrolu")
    cfg = _cfg(args)
    problems: list[str] = []

    print(f"  Proje klasoru   : {cfg.root}")
    print(f"  Video klasoru   : {cfg.video_dir}")
    if not cfg.video_dir.exists():
        cfg.video_dir.mkdir(parents=True, exist_ok=True)
        warn(f"Video klasoru yoktu, olusturuldu: {cfg.video_dir}")
    videos = list_videos(cfg.video_dir)
    print(f"  Bulunan video   : {len(videos)}")

    print(f"  Calisma klasoru : {cfg.work_dir}")
    print(f"  Cikti klasoru   : {cfg.out_dir}")

    if media.have_ffmpeg():
        ok(f"ffmpeg: {media.ffmpeg_bin()}")
    else:
        problems.append("ffmpeg yok -> winget install --id Gyan.FFmpeg -e")
        err("ffmpeg bulunamadi")

    try:
        font = thumbnail.resolve_font(cfg.assets_dir)
        ok(f"Kapak fontu: {Path(font).name}")
    except HusccError as exc:
        problems.append(str(exc))
        err(str(exc))

    try:
        import PIL  # noqa: F401
        import numpy  # noqa: F401

        ok("Goruntu kutuphaneleri (Pillow, numpy) hazir")
    except ImportError:
        problems.append("Pillow/numpy eksik -> uv pip install pillow numpy")
        err("Pillow/numpy eksik")

    if subtitles.available():
        ok(f"Altyazi motoru hazir (model: {cfg.get('subtitles.model', 'small')})")
    else:
        warn("faster-whisper yok - altyazi uretilmez (uv pip install faster-whisper)")

    # --- yayin yolu: tarayici -------------------------------------------
    route = str(cfg.get("upload.via", "browser")).lower()
    print(f"  Yayin yolu      : {route}")

    try:
        import playwright  # noqa: F401

        ok("Playwright kurulu")
    except ImportError:
        problems.append("Playwright yok -> uv pip install --python .venv playwright")
        err("Playwright yok")

    channel_name = str(cfg.get("browser.channel", "chrome"))
    browser_path = _find_browser(channel_name)
    if browser_path:
        ok(f"Tarayici: {channel_name} ({browser_path})")
    else:
        problems.append(
            f"{channel_name} bulunamadi -> winget install --id Google.Chrome -e"
        )
        err(f"{channel_name} bulunamadi")

    if cfg.selectors_path.exists():
        ok(f"Element haritasi: {cfg.selectors_path.name}")
    else:
        problems.append("config/selectors.yaml yok")
        err("config/selectors.yaml yok")

    if publish_browser.is_logged_in(cfg):
        detail = publish_browser.session_info(cfg)
        channel_title = detail.get("channel") or "YouTube"
        ok(f"Google oturumu kayitli: {channel_title}")
    else:
        warn("Henuz Google girisi yapilmamis -> huscc login")

    if args.browser:
        info("Tarayici acilip oturum deneniyor...")
        try:
            title = publish_browser.login(cfg)
            ok(f"Oturum dogrulandi: {title or 'YouTube Studio'}")
        except HusccError as exc:
            problems.append(f"Oturum dogrulanamadi: {exc}")
            err(str(exc))

    # --- opsiyonel: API yolu --------------------------------------------
    secret = youtube.client_secret_path(cfg.secrets_dir)
    if secret:
        ok(f"OAuth istemcisi (API yolu): {secret.name}")
    elif route == "api":
        problems.append("API yolu secili ama OAuth istemci dosyasi yok")
        err("OAuth istemci dosyasi yok")
        print(youtube.setup_help(cfg.secrets_dir))
    else:
        info("API yolu kurulu degil (gerekmiyor - tarayici yolu kullaniliyor)")

    if os.environ.get("OPENAI_API_KEY"):
        ok("OPENAI_API_KEY bulundu - kapak gorseli otomatik uretilir")
    else:
        info("OPENAI_API_KEY yok - kapak icin --image-source browser ya da frame")

    print()
    if problems:
        err(f"{len(problems)} sorun var:")
        for problem in problems:
            print(f"    - {problem}")
        return 1
    ok("Her sey hazir. Kullanim:  huscc publish \"video adi\"")
    return 0


_BROWSER_PATHS = {
    "chrome": [
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ],
    "msedge": [
        "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/usr/bin/microsoft-edge",
    ],
}


def _find_browser(channel: str) -> str:
    """Kurulu tarayicinin yolunu bulur (yoksa bos dize)."""
    import os as _os

    for candidate in _BROWSER_PATHS.get(channel, []):
        expanded = _os.path.expandvars(candidate)
        if Path(expanded).exists():
            return expanded
    local = _os.environ.get("LOCALAPPDATA", "")
    if local and channel == "chrome":
        candidate = Path(local) / "Google/Chrome/Application/chrome.exe"
        if candidate.exists():
            return str(candidate)
    return ""


def cmd_login(args) -> int:
    """Bir kerelik Google girisi - oturum kalici profile yazilir."""
    cfg = _cfg(args)
    if args.reset:
        import shutil

        shutil.rmtree(cfg.browser_profile_dir, ignore_errors=True)
        info("Mevcut tarayici profili silindi.")
    title = publish_browser.login(cfg)
    ok(f"Giris tamam: {title or 'YouTube Studio'}")
    print("  Artik 'huscc publish \"video adi\"' calistirabilirsiniz.")
    return 0


def cmd_studio(args) -> int:
    """Studio'yu HusCC tarayicisinda acar ve acik birakir."""
    cfg = _cfg(args)
    session = publish_browser.open_session(cfg, cfg.work_dir / "studio")
    session.start()
    session.ensure_signed_in(timeout=float(cfg.get("browser.login_timeout", 900)))
    target = args.url or "https://studio.youtube.com/"
    session.goto(target)
    ok(f"Acildi: {target}")
    print("  Pencere acik kalacak. Kapatmak icin Enter'a basin.")
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass
    session.stop()
    return 0


def cmd_auth(args) -> int:
    cfg = _cfg(args)
    token = cfg.secrets_dir / youtube.TOKEN_NAME
    if args.force and token.exists():
        token.unlink()
        info("Mevcut yetkilendirme silindi.")
    service = youtube.authorize(cfg.secrets_dir, headless=args.headless)
    channel = youtube.channel_info(service)
    ok(f"Baglanildi: {channel['title']}")
    print(f"  Kanal kimligi : {channel['id']}")
    print(f"  Abone         : {channel['subscribers']}")
    print(f"  Video         : {channel['videos']}")
    return 0


def cmd_list(args) -> int:
    cfg = _cfg(args)
    videos = list_videos(cfg.video_dir)
    if not videos:
        warn(f"{cfg.video_dir} bos.")
        return 0
    step(f"{cfg.video_dir} icindeki videolar")
    for index, video in enumerate(videos, start=1):
        state = cfg.work_dir / video.path.stem
        marker = ""
        try:
            from .util import read_json, slugify

            data = read_json(cfg.work_dir / slugify(video.name) / "state.json", {}) or {}
            stage = data.get("stage", "")
            if stage:
                marker = f"  [{stage}]"
            if data.get("url"):
                marker += f"  {data['url']}"
        except Exception:
            pass
        print(f"  {index:2d}. {video.path.name}  ({human_size(video.size)}){marker}")
    return 0


def cmd_prep(args) -> int:
    cfg = _cfg(args)
    job = pipeline.make_job(cfg, args.name)
    pipeline.prep(
        job, brain=args.brain, frame_count=args.frames, do_subtitles=not args.no_subs
    )
    print()
    if args.brain == "claude-code" and brief_mod.load_brief(job.work) is None:
        print(f"Siradaki adim -> Claude su dosyayi okusun: {job.work / 'ANALIZ.md'}")
    else:
        print(f'Siradaki adim -> huscc render "{job.video.name}"')
    return 0


def cmd_brief(args) -> int:
    cfg = _cfg(args)
    job = pipeline.make_job(cfg, args.name)

    if args.from_draft:
        draft = json.loads((job.work / "brief.draft.json").read_text(encoding="utf-8"))
        brief_mod.save_brief(job.work, brief_mod.normalize(brief_mod.Brief.from_dict(draft)))
        ok("Taslak brief, brief.json olarak kabul edildi.")
        return 0

    if args.set:
        payload = json.loads(Path(args.set).read_text(encoding="utf-8")) if Path(args.set).exists() else json.loads(args.set)
        current = brief_mod.Brief.from_dict(payload)
        current.video_name = current.video_name or job.video.name
        current.source = current.source or "claude-code"
        brief_mod.save_brief(job.work, brief_mod.normalize(current))
        ok(f"brief.json yazildi: {brief_mod.brief_path(job.work)}")
        args.show = True

    current = brief_mod.load_brief(job.work)
    if current is None:
        warn("brief.json yok.")
        print(f"  Yonerge: {job.work / 'ANALIZ.md'}")
        return 1

    problems = brief_mod.validate(current)
    if args.show:
        print(json.dumps(current.to_dict(), ensure_ascii=False, indent=2))
    if problems:
        warn("Brief eksikleri:")
        for problem in problems:
            print(f"    - {problem}")
        return 1
    ok("Brief gecerli.")
    return 0


def cmd_render(args) -> int:
    cfg = _cfg(args)
    job = pipeline.make_job(cfg, args.name)
    pipeline.render(
        job,
        skip_edit=args.skip_edit,
        make_shorts=False if args.no_shorts else None,
        image_source=args.image_source,
    )
    print()
    print(f'Siradaki adim -> huscc upload "{job.video.name}"')
    return 0


def cmd_upload(args) -> int:
    cfg = _cfg(args)
    job = pipeline.make_job(cfg, args.name)
    pipeline.upload(job, dry_run=args.dry_run, upload_shorts=args.shorts, via=args.via)
    return 0


def cmd_publish(args) -> int:
    cfg = _cfg(args)
    job = pipeline.make_job(cfg, args.name)
    pipeline.publish(
        job,
        brain=args.brain,
        dry_run=args.dry_run,
        skip_edit=args.skip_edit,
        upload_shorts=args.shorts,
        frame_count=args.frames,
        image_source=args.image_source,
        via=args.via,
    )
    return 0


def cmd_status(args) -> int:
    cfg = _cfg(args)
    if args.name:
        job = pipeline.make_job(cfg, args.name)
        print(pipeline.report(job))
        return 0
    from .util import read_json

    history = read_json(cfg.history_file, []) or []
    if not history:
        info("Henuz yayinlanmis video yok.")
        return 0
    step(f"Yayin gecmisi ({len(history)} video)")
    for record in history[-20:]:
        print(f"  {record.get('uploaded_at', '')[:16]}  {record.get('title', '')}")
        print(f"      {record.get('url', '')}")
    return 0


def cmd_web(args) -> int:
    """Yerel kontrol panelini baslatir ve varsayilan tarayicida acar."""
    from .server import serve

    cfg = _cfg(args)
    print(BANNER)
    serve(cfg, host=args.host, port=args.port, open_browser=not args.no_open)
    return 0


def cmd_clean(args) -> int:
    cfg = _cfg(args)
    import shutil

    if args.name:
        job = pipeline.make_job(cfg, args.name)
        shutil.rmtree(job.work, ignore_errors=True)
        ok(f"Temizlendi: {job.work}")
        return 0
    for child in cfg.work_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
    ok("Tum ara dosyalar temizlendi.")
    return 0


# ------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="huscc",
        description="Clash of Clans ekran kayitlarini SEO/CTR optimize ederek YouTube'a yayinlar.",
    )
    parser.add_argument("--config", help="Alternatif channel.yaml yolu")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Kurulumu ve baglantilari kontrol et")
    doctor.add_argument("--browser", action="store_true",
                        help="Tarayiciyi acip YouTube oturumunu da dogrula")
    doctor.set_defaults(func=cmd_doctor)

    login = sub.add_parser("login", help="Google girisi (bir kerelik, tarayicida)")
    login.add_argument("--reset", action="store_true", help="Kayitli oturumu sil, bastan gir")
    login.set_defaults(func=cmd_login)

    studio = sub.add_parser("studio", help="YouTube Studio'yu HusCC tarayicisinda ac")
    studio.add_argument("--url", help="Acilacak adres (varsayilan: Studio ana sayfasi)")
    studio.set_defaults(func=cmd_studio)

    auth = sub.add_parser("auth", help="YouTube hesabini yetkilendir")
    auth.add_argument("--force", action="store_true", help="Mevcut token'i sil, bastan giris yap")
    auth.add_argument("--headless", action="store_true", help="Tarayicisiz (konsol) akisi")
    auth.set_defaults(func=cmd_auth)

    sub.add_parser("list", help="CC klasorundeki videolari listele").set_defaults(func=cmd_list)

    prep = sub.add_parser("prep", help="Videoyu analiz et (kare, sahne, altyazi)")
    prep.add_argument("name", help="Video adi veya bir parcasi")
    prep.add_argument("--brain", choices=["claude-code", "api", "heuristic"], default="claude-code")
    prep.add_argument("--frames", type=int, default=14, help="Analiz karesi sayisi")
    prep.add_argument("--no-subs", action="store_true", help="Altyazi uretme")
    prep.set_defaults(func=cmd_prep)

    brief = sub.add_parser("brief", help="Brief'i goster / dogrula / yaz")
    brief.add_argument("name")
    brief.add_argument("--show", action="store_true", help="brief.json icerigini bas")
    brief.add_argument("--set", help="JSON dosyasi yolu veya JSON metni")
    brief.add_argument("--from-draft", action="store_true", help="Heuristik taslagi kabul et")
    brief.set_defaults(func=cmd_brief)

    render = sub.add_parser("render", help="Kapak + meta veri + yayina hazir video uret")
    render.add_argument("name")
    render.add_argument("--skip-edit", action="store_true", help="Yeniden kodlama yapma")
    render.add_argument("--no-shorts", action="store_true", help="Shorts uretme")
    render.add_argument("--image-source", choices=["auto", "api", "browser", "frame"],
                        help="Kapak arka plani: ChatGPT API / tarayici / video karesi")
    render.set_defaults(func=cmd_render)

    upload = sub.add_parser("upload", help="YouTube'a yukle")
    upload.add_argument("name")
    upload.add_argument("--dry-run", action="store_true", help="Yuklemeden onizle")
    upload.add_argument("--shorts", action="store_true", help="Shorts'lari da yukle")
    upload.add_argument("--via", choices=["browser", "api"],
                        help="Yayin yolu (varsayilan: config > upload.via)")
    upload.set_defaults(func=cmd_upload)

    publish = sub.add_parser("publish", help="Bastan sona: analiz -> kurgu -> yayin")
    publish.add_argument("name")
    publish.add_argument("--brain", choices=["claude-code", "api", "heuristic"], default="claude-code")
    publish.add_argument("--frames", type=int, default=14)
    publish.add_argument("--dry-run", action="store_true")
    publish.add_argument("--skip-edit", action="store_true")
    publish.add_argument("--shorts", action="store_true")
    publish.add_argument("--image-source", choices=["auto", "api", "browser", "frame"],
                         help="Kapak arka plani: ChatGPT API / tarayici / video karesi")
    publish.add_argument("--via", choices=["browser", "api"],
                         help="Yayin yolu (varsayilan: config > upload.via)")
    publish.set_defaults(func=cmd_publish)

    status = sub.add_parser("status", help="Durum / yayin gecmisi")
    status.add_argument("name", nargs="?")
    status.set_defaults(func=cmd_status)

    web = sub.add_parser("web", help="Yerel kontrol panelini ac (localhost)")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--no-open", action="store_true", help="Tarayiciyi acma")
    web.set_defaults(func=cmd_web)

    clean = sub.add_parser("clean", help="Ara dosyalari sil")
    clean.add_argument("name", nargs="?")
    clean.set_defaults(func=cmd_clean)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except HusccError as exc:
        print()
        err(str(exc))
        return 1
    except KeyboardInterrupt:
        print()
        warn("Iptal edildi.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
