"""Yerel kontrol paneli: http://127.0.0.1:8765

Sadece standart kutuphane. Varsayilan tarayicida acilir, disari hicbir sey
acilmaz; sunucu yalnizca 127.0.0.1 uzerinde dinler.
"""
from __future__ import annotations

import io
import json
import mimetypes
import os
import queue
import threading
import time
import traceback
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import brief as brief_mod
from . import imagegen, media, pipeline, publish_browser, subtitles, thumbnail, youtube
from .config import Config, load_config
from .discover import list_videos
from .util import HusccError, human_size, read_json, slugify, write_json

from .web_ui import PAGE


# --------------------------------------------------------------- is yoneticisi
class JobRunner:
    """Ayni anda tek is calistirir, ciktisini SSE icin kuyruklar."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None
        self.listeners: list[queue.Queue] = []
        self.history: list[str] = []
        self.current: dict | None = None

    @property
    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def subscribe(self) -> queue.Queue:
        channel: queue.Queue = queue.Queue()
        with self.lock:
            self.listeners.append(channel)
            for line in self.history[-400:]:
                channel.put(line)
        return channel

    def unsubscribe(self, channel: queue.Queue) -> None:
        with self.lock:
            if channel in self.listeners:
                self.listeners.remove(channel)

    def emit(self, line: str) -> None:
        with self.lock:
            self.history.append(line)
            self.history = self.history[-2000:]
            listeners = list(self.listeners)
        for channel in listeners:
            channel.put(line)

    def start(self, label: str, target, *args, **kwargs) -> bool:
        if self.busy:
            return False
        self.history = []
        self.current = {"label": label, "started": time.time()}

        def wrapper() -> None:
            stream = _LineStream(self.emit)
            self.emit(f"::start::{label}")
            try:
                with redirect_stdout(stream), redirect_stderr(stream):
                    target(*args, **kwargs)
                stream.flush()
                self.emit("::done::ok")
            except HusccError as exc:
                stream.flush()
                for line in str(exc).splitlines():
                    self.emit(f"x {line}")
                self.emit("::done::error")
            except Exception:
                stream.flush()
                for line in traceback.format_exc().splitlines()[-12:]:
                    self.emit(f"x {line}")
                self.emit("::done::error")
            finally:
                self.current = None

        self.thread = threading.Thread(target=wrapper, daemon=True)
        self.thread.start()
        return True


class _LineStream(io.TextIOBase):
    """print() ciktisini satir satir yakalayip yayinlar."""

    def __init__(self, emit) -> None:
        self._emit = emit
        self._buffer = ""

    def write(self, text: str) -> int:  # type: ignore[override]
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line.rstrip("\r"))
        if len(self._buffer) > 400:
            self._emit(self._buffer)
            self._buffer = ""
        return len(text)

    def flush(self) -> None:  # type: ignore[override]
        if self._buffer.strip():
            self._emit(self._buffer)
        self._buffer = ""


RUNNER = JobRunner()


# ------------------------------------------------------------------ veri katmani
def _video_rows(cfg: Config) -> list[dict]:
    rows = []
    for video in list_videos(cfg.video_dir):
        slug = slugify(video.name)
        state = read_json(cfg.work_dir / slug / "state.json", {}) or {}
        meta = state.get("metadata", {}) or {}
        rows.append(
            {
                "name": video.name,
                "file": video.path.name,
                "slug": slug,
                "size": human_size(video.size),
                "stage": state.get("stage", ""),
                "title": meta.get("title", ""),
                "url": state.get("url", ""),
                "has_brief": (cfg.work_dir / slug / "brief.json").exists(),
                "has_thumb": bool(state.get("thumbnail")),
                "mtime": video.path.stat().st_mtime,
            }
        )
    return rows


def _browser_ready(cfg: Config) -> dict:
    """Tarayici yolunun hazir olup olmadigini (tarayici acmadan) anlar."""
    try:
        import playwright  # noqa: F401

        have_playwright = True
    except ImportError:
        have_playwright = False

    from .cli import _find_browser

    channel = str(cfg.get("browser.channel", "chrome"))
    browser_path = _find_browser(channel)
    logged_in = publish_browser.is_logged_in(cfg)
    return {
        "playwright": have_playwright,
        "browser": bool(browser_path),
        "browser_path": browser_path,
        "browser_channel": channel,
        "selectors": cfg.selectors_path.exists(),
        "profile_ready": bool(logged_in),
        "session": publish_browser.session_info(cfg),
    }


def _doctor(cfg: Config) -> dict:
    browser = _browser_ready(cfg)
    return {
        "via": str(cfg.get("upload.via", "browser")),
        "ffmpeg": media.have_ffmpeg(),
        "whisper": subtitles.available(),
        "oauth_client": youtube.client_secret_path(cfg.secrets_dir) is not None,
        "api_key": bool(os.environ.get("OPENAI_API_KEY")),
        "video_dir": str(cfg.video_dir),
        "out_dir": str(cfg.out_dir),
        "setup_help": youtube.setup_help(cfg.secrets_dir),
        **browser,
    }


def _detail(cfg: Config, name: str) -> dict:
    job = pipeline.make_job(cfg, name)
    state = job.state()
    current = brief_mod.load_brief(job.work)
    draft = read_json(job.work / "brief.draft.json", {}) or {}
    thumbs = sorted((job.work / "thumbs").glob("thumb_*.jpg")) if (job.work / "thumbs").exists() else []
    return {
        "name": job.video.name,
        "slug": job.slug,
        "path": str(job.video.path),
        "state": state,
        "brief": current.to_dict() if current else None,
        "draft": draft,
        "metadata": state.get("metadata", {}),
        "thumbs": [t.name for t in thumbs],
        "chosen_thumb": Path(state.get("thumbnail", "")).name if state.get("thumbnail") else "",
        "frames": [Path(f).name for f in state.get("frames", [])],
        "shorts": [Path(s).name for s in state.get("shorts", [])],
        "ai_prompt": (job.work / "ai" / "thumb_prompt.txt").read_text(encoding="utf-8")
        if (job.work / "ai" / "thumb_prompt.txt").exists()
        else (imagegen.build_prompt(current, channel_game=cfg.game) if current else ""),
        "ai_dir": str(job.work / "ai"),
        "ai_image": bool((job.work / "ai" / "thumb_ai.png").exists()),
        "thumb_source": state.get("thumbnail_source", ""),
        "shots": sorted(p.name for p in (job.work / "browser").glob("*.png"))
        if (job.work / "browser").exists()
        else [],
        "browser_issue": (job.work / "browser" / "SORUN.md").read_text(encoding="utf-8")
        if (job.work / "browser" / "SORUN.md").exists()
        else "",
        "manual_todo": state.get("manual_todo", []),
        "published": bool(state.get("video_id")),
        "video_id": state.get("video_id", ""),
        "analysis_doc": str(job.work / "ANALIZ.md"),
        "work_dir": str(job.work),
    }


# --------------------------------------------------------------------- handler
class Handler(BaseHTTPRequestHandler):
    cfg: Config = None  # type: ignore[assignment]
    server_version = "HusCC/1.0"

    def log_message(self, fmt: str, *args) -> None:  # sessiz
        pass

    # ------------------------------------------------------------- yardimcilar
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, data, status: int = 200) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # -------------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        path = unquote(route.path)
        cfg = self.cfg

        if path in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return

        if path == "/api/bootstrap":
            self._json(
                {
                    "channel": cfg.section("channel"),
                    "doctor": _doctor(cfg),
                    "videos": _video_rows(cfg),
                    "history": (read_json(cfg.history_file, []) or [])[-30:],
                    "busy": RUNNER.busy,
                    "config": cfg.raw,
                }
            )
            return

        if path == "/api/videos":
            self._json({"videos": _video_rows(cfg), "busy": RUNNER.busy})
            return

        if path.startswith("/api/detail/"):
            name = path[len("/api/detail/"):]
            try:
                self._json(_detail(cfg, name))
            except HusccError as exc:
                self._json({"error": str(exc)}, 404)
            return

        if path == "/api/stream":
            self._stream()
            return

        if path.startswith("/media/"):
            self._media(path[len("/media/"):])
            return

        self._send(404, b"yok", "text/plain; charset=utf-8")

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        channel = RUNNER.subscribe()
        try:
            while True:
                try:
                    line = channel.get(timeout=15)
                    payload = json.dumps({"line": line}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            RUNNER.unsubscribe(channel)

    def _media(self, rel: str) -> None:
        cfg = self.cfg
        parts = rel.split("/")
        if len(parts) < 2:
            self._send(404, b"yok", "text/plain")
            return
        kind, slug = parts[0], parts[1]
        target: Path | None = None
        if kind == "thumb" and len(parts) >= 3:
            target = cfg.work_dir / slug / "thumbs" / parts[2]
        elif kind == "frame" and len(parts) >= 3:
            target = cfg.work_dir / slug / "frames" / parts[2]
        elif kind == "shot" and len(parts) >= 3:
            target = cfg.work_dir / slug / "browser" / parts[2]
        elif kind == "video":
            target = cfg.out_dir / f"{slug}.mp4"
        elif kind == "short" and len(parts) >= 3:
            target = cfg.out_dir / parts[2]

        if not target or not target.exists() or not target.is_file():
            self._send(404, b"yok", "text/plain")
            return
        try:
            target.resolve().relative_to(cfg.root.resolve())
        except ValueError:
            if cfg.out_dir not in target.resolve().parents:
                self._send(403, b"izin yok", "text/plain")
                return

        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self._send(200, data, ctype)

    # ------------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path)
        path = unquote(route.path)
        cfg = self.cfg
        body = self._body()

        if path == "/api/run":
            self._run(body)
            return

        if path == "/api/brief":
            try:
                job = pipeline.make_job(cfg, str(body.get("name", "")))
                payload = body.get("brief") or {}
                current = brief_mod.Brief.from_dict(payload)
                current.video_name = current.video_name or job.video.name
                current.source = current.source or "panel"
                brief_mod.save_brief(job.work, brief_mod.normalize(current))
                self._json({"ok": True, "problems": brief_mod.validate(current)})
            except (HusccError, TypeError, ValueError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/thumb":
            try:
                job = pipeline.make_job(cfg, str(body.get("name", "")))
                chosen = job.work / "thumbs" / str(body.get("file", ""))
                if not chosen.exists():
                    raise HusccError("Kapak varyanti bulunamadi")
                final = job.work / "thumbs" / "thumbnail.jpg"
                from PIL import Image

                with Image.open(chosen) as image:
                    image.save(final, "JPEG", quality=92, optimize=True, progressive=True)
                job.save_state(thumbnail=str(final))
                self._json({"ok": True})
            except (HusccError, OSError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/config":
            try:
                import yaml

                data = body.get("config") or {}
                (cfg.root / "config" / "channel.yaml").write_text(
                    yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
                )
                self.cfg = load_config()
                Handler.cfg = self.cfg
                self._json({"ok": True})
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/aiopen":
            try:
                job = pipeline.make_job(cfg, str(body.get("name", "")))
                current = brief_mod.load_brief(job.work) or brief_mod.Brief.from_dict(
                    read_json(job.work / "brief.draft.json", {}) or {}
                )
                prompt = imagegen.build_prompt(current, channel_game=cfg.game)
                ai_dir = job.work / "ai"
                ai_dir.mkdir(parents=True, exist_ok=True)
                (ai_dir / "thumb_prompt.txt").write_text(prompt, encoding="utf-8")
                copied = imagegen.copy_to_clipboard(prompt)
                webbrowser.open(imagegen.CHATGPT_URL)
                self._json({"ok": True, "copied": copied, "prompt": prompt, "dir": str(ai_dir)})
            except (HusccError, OSError) as exc:
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/aiupload":
            try:
                import base64 as _b64

                job = pipeline.make_job(cfg, str(body.get("name", "")))
                raw = str(body.get("data", ""))
                if "," in raw:
                    raw = raw.split(",", 1)[1]
                ai_dir = job.work / "ai"
                ai_dir.mkdir(parents=True, exist_ok=True)
                target = ai_dir / "thumb_ai.png"
                from PIL import Image
                import io as _io

                with Image.open(_io.BytesIO(_b64.b64decode(raw))) as image:
                    image.convert("RGB").save(target, "PNG")
                self._json({"ok": True, "path": str(target)})
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
            return

        if path == "/api/open":
            target = Path(str(body.get("path", "")))
            try:
                if target.exists():
                    if os.name == "nt":
                        os.startfile(str(target))  # type: ignore[attr-defined]
                    else:
                        import subprocess

                        subprocess.Popen(["xdg-open", str(target)])
                    self._json({"ok": True})
                else:
                    self._json({"error": "yol yok"}, 404)
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
            return

        self._send(404, b"yok", "text/plain")

    def _run(self, body: dict) -> None:
        cfg = self.cfg
        action = str(body.get("action", ""))
        name = str(body.get("name", ""))
        options = body.get("options") or {}

        if RUNNER.busy:
            self._json({"error": "Zaten calisan bir is var."}, 409)
            return

        try:
            if action == "login":
                started = RUNNER.start("Google girisi (tarayici)", publish_browser.login, cfg)
            elif action == "auth":
                started = RUNNER.start("YouTube yetkilendirme (API)", _do_auth, cfg)
            elif action == "doctor":
                from .cli import cmd_doctor

                class _A:
                    config = None

                started = RUNNER.start("Sistem kontrolu", cmd_doctor, _A())
            else:
                job = pipeline.make_job(cfg, name)
                if action == "prep":
                    started = RUNNER.start(
                        f"Analiz: {job.video.name}", pipeline.prep, job,
                        brain=str(options.get("brain", "claude-code")),
                        frame_count=int(options.get("frames", 14)),
                        do_subtitles=bool(options.get("subs", True)),
                    )
                elif action == "render":
                    started = RUNNER.start(
                        f"Kurgu: {job.video.name}", pipeline.render, job,
                        skip_edit=bool(options.get("skip_edit", False)),
                        make_shorts=None if options.get("shorts", True) else False,
                        image_source=options.get("image_source") or None,
                        interactive=False,
                    )
                elif action == "upload":
                    started = RUNNER.start(
                        f"Yukleme: {job.video.name}", pipeline.upload, job,
                        dry_run=bool(options.get("dry_run", False)),
                        upload_shorts=bool(options.get("upload_shorts", False)),
                        via=options.get("via") or None,
                        force=bool(options.get("force", False)),
                    )
                elif action == "update":
                    started = RUNNER.start(
                        f"Meta veri guncelleme: {job.video.name}", pipeline.update, job,
                        rebuild=bool(options.get("rebuild", False)),
                    )
                elif action == "publish":
                    started = RUNNER.start(
                        f"Tam yayin: {job.video.name}", pipeline.publish, job,
                        brain=str(options.get("brain", "claude-code")),
                        dry_run=bool(options.get("dry_run", False)),
                        skip_edit=bool(options.get("skip_edit", False)),
                        upload_shorts=bool(options.get("upload_shorts", False)),
                        frame_count=int(options.get("frames", 14)),
                        image_source=options.get("image_source") or None,
                        interactive=False,
                        via=options.get("via") or None,
                        force=bool(options.get("force", False)),
                    )
                else:
                    self._json({"error": f"bilinmeyen islem: {action}"}, 400)
                    return
        except HusccError as exc:
            self._json({"error": str(exc)}, 400)
            return

        self._json({"ok": bool(started)})


def _do_probe(cfg: Config) -> None:
    from . import studio

    report = publish_browser.probe(cfg)
    broken = studio.print_probe(report)
    write_json(cfg.work_dir / "probe" / "rapor.json", report)
    if broken:
        print(f"x {broken} secici tutmadi - config/selectors.yaml guncellenmeli")
    else:
        print("+ Tum seciciler tuttu.")


def _do_auth(cfg: Config) -> None:
    service = youtube.authorize(cfg.secrets_dir)
    channel = youtube.channel_info(service)
    print(f"+ Baglanildi: {channel['title']} ({channel['subscribers']} abone)")


# ----------------------------------------------------------------------- calistir
def serve(cfg: Config, *, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    Handler.cfg = cfg
    # Panelde ffmpeg ilerleme cubugu log'u bogmasin
    os.environ.setdefault("HUSCC_QUIET_FFMPEG", "1")

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print()
    print("=" * 62)
    print(f"  HusCC kontrol paneli calisiyor: {url}")
    print(f"  Video klasoru : {cfg.video_dir}")
    print("  Durdurmak icin: Ctrl+C")
    print("=" * 62)
    print()
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nPanel kapatildi.")
    finally:
        httpd.server_close()
