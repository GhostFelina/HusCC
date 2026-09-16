"""Uctan uca boru hatti: hazirlik -> brief -> kurgu/kapak -> yukleme."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import brief as brief_mod
from . import editor, imagegen, media, publish_browser, seo, subtitles, thumbnail, youtube
from .config import Config
from .discover import VideoFile, find_video
from .util import (
    HusccError, ensure_dir, hhmmss, human_size, info, log_to, next_slot, ok,
    opt_path, read_json, slugify, step, utc_now, warn, write_json,
)


@dataclass
class Job:
    video: VideoFile
    slug: str
    work: Path
    cfg: Config

    @property
    def state_file(self) -> Path:
        return self.work / "state.json"

    def log(self):
        """Bu isin tum ekran ciktisini work/<slug>/log.txt dosyasina da yazar."""
        return log_to(self.work / "log.txt")

    def state(self) -> dict:
        return read_json(self.state_file, {}) or {}

    def save_state(self, **updates) -> dict:
        data = self.state()
        data.update(updates)
        data["video_path"] = str(self.video.path)
        data["slug"] = self.slug
        data["updated_at"] = utc_now().isoformat()
        write_json(self.state_file, data)
        return data


def make_job(cfg: Config, query: str) -> Job:
    video = find_video(cfg.video_dir, query)
    slug = slugify(video.name)
    return Job(video=video, slug=slug, work=cfg.work_for(slug), cfg=cfg)


# ---------------------------------------------------------------- varliklar
def ensure_assets(cfg: Config) -> dict[str, Path]:
    """Abone-ol karti, filigran ve font gibi varsayilan varliklari uretir."""
    overlays = ensure_dir(cfg.assets_dir / "overlays")
    font = thumbnail.resolve_font(cfg.assets_dir)
    palette = cfg.get("thumbnail.palette", {}) or {}

    subscribe = overlays / "subscribe.png"
    if not subscribe.exists():
        thumbnail.make_overlay_card(
            text="ABONE OL",
            subtext="ve zili aç 🔔",
            out_path=subscribe,
            palette_cfg=palette,
            font_path=font,
        )
        ok(f"Abone karti uretildi: {subscribe.name}")

    watermark = overlays / "watermark.png"
    if not watermark.exists():
        _make_watermark(cfg.channel_name, watermark, palette, font)
        ok(f"Filigran uretildi: {watermark.name}")

    return {"subscribe": subscribe, "watermark": watermark, "font": font}


def _make_watermark(name: str, out_path: Path, palette_cfg: dict, font_path: Path) -> Path:
    from PIL import ImageFont

    size = (460, 120)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    primary = palette_cfg.get("primary", "#FFC400")
    draw.rounded_rectangle(
        [0, 0, size[0] - 1, size[1] - 1], radius=26, fill=(11, 18, 32, 190),
        outline=primary, width=4,
    )
    font = ImageFont.truetype(str(font_path), 52)
    text = name[:14]
    width = draw.textlength(text, font=font)
    draw.text(((size[0] - width) / 2, 28), text, font=font, fill="#FFFFFF")
    canvas.save(out_path, "PNG")
    return out_path


# ------------------------------------------------------------------- 1. prep
def prep(
    job: Job,
    *,
    brain: str = "claude-code",
    frame_count: int = 14,
    do_subtitles: bool = True,
) -> dict:
    """Videoyu analiz eder: teknik veri, kareler, sahneler, altyazi."""
    cfg = job.cfg
    step(f"1/4 Hazirlik - {job.video.path.name}")
    info(f"Dosya: {job.video.path}  ({human_size(job.video.size)})")

    media_info = media.probe(job.video.path)
    media.log_info(media_info)
    if media_info.duration < 8:
        warn("Video 8 saniyeden kisa - Shorts olarak degerlendirilecek.")

    info("Sahne kesimleri taraniyor...")
    scenes = media.scene_timestamps(job.video.path)
    motion = media.motion_profile(job.video.path, media_info.duration)
    info(f"{len(scenes)} sahne kesimi bulundu.")

    frames_dir = ensure_dir(job.work / "frames")
    stamps = media.storyboard_timestamps(media_info.duration, frame_count, scenes)
    frames = media.extract_frames(job.video.path, frames_dir, timestamps=stamps)
    ok(f"{len(frames)} analiz karesi cikarildi -> {frames_dir}")

    transcript = ""
    srt_tr: Path | None = None
    srt_en: Path | None = None
    if do_subtitles and media_info.has_audio and cfg.get("subtitles.enabled", True):
        audio = media.extract_audio(job.video.path, job.work / "audio.wav")
        if audio and subtitles.available():
            model_size = str(cfg.get("subtitles.model", "small"))
            segments = subtitles.transcribe(
                audio, model_size=model_size,
                language=str(cfg.get("subtitles.source_language", "tr")),
            )
            transcript = subtitles.transcript_text(segments)
            srt_tr = subtitles.write_srt(segments, job.work / "subs_tr.srt")
            if srt_tr:
                ok(f"Turkce altyazi: {srt_tr.name} ({len(segments)} satir)")
            for lang in cfg.get("subtitles.translate_to", []) or []:
                if lang == "en":
                    translated = subtitles.transcribe(
                        audio, model_size=model_size, language=None, task="translate"
                    )
                    srt_en = subtitles.write_srt(translated, job.work / "subs_en.srt")
                    if srt_en:
                        ok(f"Ingilizce altyazi: {srt_en.name}")
        elif audio:
            warn("faster-whisper yok - altyazi uretilmedi (uv pip install faster-whisper).")
    elif not media_info.has_audio:
        info("Videoda ses yok - altyazi adimi atlandi.")

    brief_mod.write_analysis_request(
        job.work,
        video_name=job.video.name,
        media=media_info.to_dict(),
        frames=frames,
        scenes=scenes,
        motion=motion,
        transcript=transcript,
    )

    fallback = brief_mod.heuristic_brief(
        job.video.name, transcript=transcript,
        duration=media_info.duration, motion=motion, scenes=scenes,
    )
    write_json(job.work / "brief.draft.json", fallback.to_dict())

    if brain == "api":
        generated = brief_mod.api_brief(
            frames, video_name=job.video.name, media=media_info.to_dict(),
            transcript=transcript, fallback=fallback,
        )
        brief_mod.save_brief(job.work, brief_mod.normalize(generated))
        ok(f"Brief uretildi (kaynak: {generated.source})")
    elif brain == "heuristic":
        brief_mod.save_brief(job.work, brief_mod.normalize(fallback))
        ok("Brief uretildi (kaynak: heuristik)")
    else:
        info("Brief bekleniyor: kareleri inceleyip brief.json yazilmali.")
        info(f"Yonerge: {job.work / 'ANALIZ.md'}")

    return job.save_state(
        stage="prep",
        media=media_info.to_dict(),
        scenes=scenes[:60],
        motion=motion,
        frames=[str(f) for f in frames],
        transcript_chars=len(transcript),
        srt_tr=str(srt_tr) if srt_tr else "",
        srt_en=str(srt_en) if srt_en else "",
        brain=brain,
    )


# ----------------------------------------------------------------- 2. render
def render(
    job: Job,
    *,
    skip_edit: bool = False,
    make_shorts: bool | None = None,
    image_source: str | None = None,
    interactive: bool = True,
) -> dict:
    """Brief'i alir; meta veriyi, kapagi ve yayina hazir videoyu uretir."""
    cfg = job.cfg
    state = job.state()
    if not state:
        raise HusccError("Once 'huscc prep' calistirin.")

    step(f"2/4 Kurgu ve kapak - {job.video.path.name}")

    current = brief_mod.load_brief(job.work)
    if current is None:
        draft = read_json(job.work / "brief.draft.json")
        if not draft:
            raise HusccError("brief.json yok. 'huscc prep' calistirin.")
        warn("brief.json bulunamadi - heuristik taslak kullaniliyor.")
        current = brief_mod.Brief.from_dict(draft)
    current.video_name = current.video_name or job.video.name
    current = brief_mod.normalize(current)

    problems = brief_mod.validate(current)
    if problems:
        for problem in problems:
            warn(f"brief: {problem}")

    media_info = media.MediaInfo(**{
        k: v for k, v in state["media"].items()
        if k in media.MediaInfo.__dataclass_fields__
    })

    # --- meta veri -------------------------------------------------------
    publish_at = _resolve_publish_at(cfg)
    meta = seo.build_metadata(current, cfg, duration=media_info.duration, publish_at=publish_at)
    write_json(job.work / "metadata.json", meta.to_dict())
    ok(f"Baslik: {meta.title}")
    info(f"Etiket: {len(meta.tags)} adet | Bolum: {len(meta.chapters)} | Liste: {meta.playlist}")
    if meta.publish_at:
        info(f"Planlanan yayin: {meta.publish_at} (UTC)")

    # --- kapak -----------------------------------------------------------
    assets = ensure_assets(cfg)
    source = image_source or str(cfg.get("thumbnail.source", "auto"))
    ai_background, used_source = imagegen.acquire_background(
        current, job.work,
        source=source,
        channel_game=cfg.game,
        wait_seconds=float(cfg.get("thumbnail.ai_wait_seconds", 420)),
        interactive=interactive,
    )
    hero_source = ai_background or _hero_frame(job, current, media_info, state)
    if ai_background:
        ok(f"Kapak arka plani: ChatGPT gorseli ({used_source})")
    else:
        info("Kapak arka plani: video karesi")
    text, badge = seo.thumbnail_words(current)
    thumb, variants = thumbnail.generate(
        hero=hero_source,
        text=text,
        badge=badge,
        out_dir=ensure_dir(job.work / "thumbs"),
        palette_cfg=cfg.get("thumbnail.palette", {}) or {},
        font_path=assets["font"],
        size=(int(cfg.get("thumbnail.width", 1280)), int(cfg.get("thumbnail.height", 720))),
        mood=current.thumbnail_mood,
        variants=int(cfg.get("thumbnail.variants", 3)),
    )
    ok(f"Kapak hazir: {thumb}  ({len(variants)} varyant)")

    # --- video -----------------------------------------------------------
    out_dir = ensure_dir(cfg.out_dir)
    final = out_dir / f"{job.slug}.mp4"

    if skip_edit or not cfg.get("edit.watermark", True) and not cfg.get("edit.outro", True):
        editor.burn_free_copy(job.video.path, final)
    else:
        plan = editor.RenderPlan(
            loudnorm=bool(cfg.get("edit.loudnorm", True)),
            watermark=assets["watermark"] if cfg.get("edit.watermark", True) else None,
            subscribe_card=assets["subscribe"] if cfg.get("edit.subscribe_overlay", True) else None,
            subscribe_times=editor.parse_positions(
                cfg.get("edit.subscribe_at", []) or [], media_info.duration
            ),
            subscribe_duration=float(cfg.get("edit.subscribe_duration", 5)),
        )
        info("Ana video kodlaniyor (bindirmeler + ses normalizasyonu)...")
        rendered = editor.render_main(job.video.path, job.work / "render_main.mp4", media_info, plan)

        if cfg.get("edit.outro", True):
            info("Bitis karti ekleniyor...")
            outro_bg = None
            if cfg.get("thumbnail.ai_outro", True):
                outro_bg, _ = imagegen.acquire_background(
                    current, job.work,
                    source=source if source != "browser" else "auto",
                    channel_game=cfg.game,
                    for_outro=True,
                    interactive=False,
                )
            card = thumbnail.make_outro_card(
                title=meta.title,
                channel=f"{cfg.channel_name} {cfg.handle}".strip(),
                out_path=job.work / "outro.png",
                palette_cfg=cfg.get("thumbnail.palette", {}) or {},
                font_path=assets["font"],
                size=(media_info.width or 1920, media_info.height or 1080),
                background=outro_bg,
            )
            outro_clip = editor.make_outro_clip(
                card, job.work / "outro.mp4",
                width=media_info.width or 1920,
                height=media_info.height or 1080,
                fps=media_info.fps or 30,
                duration=float(cfg.get("edit.outro_duration", 10)),
            )
            editor.concat([rendered, outro_clip], final)
        else:
            rendered.replace(final)

    ok(f"Yayina hazir video: {final}  ({human_size(final.stat().st_size)})")

    # --- Shorts ----------------------------------------------------------
    shorts: list[str] = []
    want_shorts = cfg.get("edit.shorts", True) if make_shorts is None else make_shorts
    if want_shorts and media_info.duration > 70:
        shorts = _render_shorts(job, current, media_info, state, meta)

    return job.save_state(
        stage="render",
        metadata=meta.to_dict(),
        thumbnail=str(thumb),
        thumbnail_source=used_source,
        thumbnail_variants=[str(v) for v in variants],
        final_video=str(final),
        shorts=shorts,
        brief_source=current.source,
    )


def _resolve_publish_at(cfg: Config) -> str | None:
    schedule = str(cfg.get("upload.schedule", "") or "").strip()
    if not schedule:
        return None
    if schedule.lower() == "auto":
        history = read_json(cfg.history_file, []) or []
        taken = [item.get("publish_at", "") for item in history if item.get("publish_at")]
        slot = next_slot(
            list(cfg.get("upload.best_hours_local", [20]) or [20]),
            str(cfg.get("upload.timezone", "Europe/Istanbul")),
            taken,
        )
        return slot.isoformat().replace("+00:00", "Z")
    return schedule


def _hero_frame(job: Job, current: brief_mod.Brief, media_info: media.MediaInfo, state: dict) -> Path:
    """Kapak icin yuksek cozunurluklu kare uretir."""
    stamp = current.hero_timestamp
    if stamp is None or not (0 <= float(stamp) < media_info.duration):
        motion = state.get("motion") or []
        if motion:
            peak = max(range(len(motion)), key=lambda i: motion[i])
            stamp = media_info.duration * (peak + 0.5) / len(motion)
        else:
            stamp = media_info.duration * 0.45

    hero = media.still(job.video.path, job.work / "hero.jpg", float(stamp), width=1920)
    if hero:
        return hero
    frames = [Path(f) for f in state.get("frames", []) if Path(f).exists()]
    if not frames:
        raise HusccError("Kapak icin kare bulunamadi - 'huscc prep' tekrar calistirin.")
    return thumbnail.pick_hero(frames)


def _render_shorts(
    job: Job,
    current: brief_mod.Brief,
    media_info: media.MediaInfo,
    state: dict,
    meta: seo.Metadata,
) -> list[str]:
    cfg = job.cfg
    count = max(1, int(cfg.get("edit.shorts_count", 1)))
    length = float(cfg.get("edit.shorts_max_seconds", 58))
    produced: list[str] = []
    motion = state.get("motion") or []
    used: list[float] = []

    srt_path = opt_path(state.get("srt_tr"))
    segments = subtitles.read_srt(srt_path) if srt_path else []

    for index in range(count):
        local_motion = list(motion)
        for start_used in used:
            if local_motion:
                bucket = int(start_used / max(media_info.duration, 1) * len(local_motion))
                for offset in range(-2, 3):
                    pos = bucket + offset
                    if 0 <= pos < len(local_motion):
                        local_motion[pos] = 0.0
        start, span = editor.pick_short_window(local_motion, media_info.duration, length=length)
        used.append(start)

        short_srt = None
        if segments and cfg.get("subtitles.burn_in_shorts", True):
            sliced = subtitles.slice_srt(segments, start, start + span)
            short_srt = subtitles.write_srt(sliced, job.work / f"short_{index + 1}.srt")

        dest = cfg.out_dir / f"{job.slug}_short{index + 1}.mp4"
        info(f"Shorts {index + 1} uretiliyor ({hhmmss(start)} - {hhmmss(start + span)})...")
        editor.render_short(
            job.video.path, dest, start=start, length=span,
            srt=short_srt, style=subtitles.shorts_style(),
        )
        write_json(
            job.work / f"short_{index + 1}_meta.json",
            seo.shorts_metadata(meta, current),
        )
        produced.append(str(dest))
        ok(f"Shorts hazir: {dest.name}")
    return produced


# ----------------------------------------------------------------- 3. upload
def upload(
    job: Job,
    *,
    dry_run: bool = False,
    upload_shorts: bool = False,
    via: str | None = None,
    force: bool = False,
) -> dict:
    """Yayin. Varsayilan yol tarayici (Studio); 'api' istenirse Data API."""
    cfg = job.cfg
    state = job.state()

    existing = already_published(job)
    if existing and not dry_run and not force:
        raise HusccError(
            "Bu video daha once yayinlanmis:\n"
            f"  {existing.get('title', job.video.name)}\n"
            f"  {existing.get('url', '')}\n"
            f"  Tarih: {(existing.get('uploaded_at') or '')[:16]}\n\n"
            "  Meta veriyi guncellemek icin:  huscc update \"" + job.video.name + "\"\n"
            "  Yeniden yuklemek icin (kopya olusur):  --force"
        )
    if not state.get("final_video"):
        raise HusccError("Once 'huscc render' calistirin.")

    final = Path(state["final_video"])
    if not final.exists():
        raise HusccError(f"Yayina hazir video bulunamadi: {final}")

    meta_dict = state.get("metadata") or {}
    meta = seo.Metadata(**{
        k: v for k, v in meta_dict.items() if k in seo.Metadata.__dataclass_fields__
    })

    route = (via or str(cfg.get("upload.via", "browser"))).lower()
    label = "tarayici" if route == "browser" else "API"
    step(f"3/4 Yayin ({label}) - {meta.title}")

    if dry_run:
        _print_preview(meta, state)
        problems = publish_browser.preflight(meta, final, opt_path(state.get("thumbnail")))
        if problems:
            warn("Yayin oncesi kontrol uyarilari:")
            for problem in problems:
                print(f"    - {problem}")
        else:
            ok("Yayin oncesi kontroller temiz.")
        ok("Deneme modu: hicbir sey yuklenmedi.")
        return state

    if route == "browser":
        return _upload_browser(job, state, final, meta, upload_shorts=upload_shorts)
    return _upload_api(job, state, final, meta, upload_shorts=upload_shorts)


def already_published(job: Job) -> dict | None:
    """Bu video daha once yayinlandiysa kaydini dondurur."""
    state = job.state()
    if state.get("video_id"):
        return {"video_id": state["video_id"], "url": state.get("url", ""),
                "title": state.get("title", ""), "uploaded_at": state.get("uploaded_at", "")}
    for record in reversed(read_json(job.cfg.history_file, []) or []):
        if record.get("slug") == job.slug and record.get("video_id"):
            return record
    return None


def _subtitle_map(state: dict) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for lang, key in (("tr", "srt_tr"), ("en", "srt_en")):
        path = opt_path(state.get(key))
        if path:
            out[lang] = path
    return out


def _record(job: Job, meta: seo.Metadata, video_id: str, url: str, extra: dict) -> dict:
    record = {
        "slug": job.slug,
        "video_id": video_id,
        "url": url,
        "title": meta.title,
        "privacy": meta.privacy,
        "publish_at": meta.publish_at or "",
        "playlist": meta.playlist,
        "uploaded_at": utc_now().isoformat(),
        "source_file": str(job.video.path),
        **extra,
    }
    history = read_json(job.cfg.history_file, []) or []
    history.append(record)
    write_json(job.cfg.history_file, history)
    return record


# ------------------------------------------------------------ tarayici yolu
def _upload_browser(
    job: Job,
    state: dict,
    final: Path,
    meta: seo.Metadata,
    *,
    upload_shorts: bool,
) -> dict:
    cfg = job.cfg
    shots_dir = ensure_dir(job.work / "browser")
    want_shorts = upload_shorts or bool(cfg.get("upload.upload_shorts", False))
    shorts = [Path(s) for s in state.get("shorts", [])] if want_shorts else []

    outcome = publish_browser.run(
        cfg,
        video=final,
        meta=meta,
        thumbnail=opt_path(state.get("thumbnail")),
        subtitles=_subtitle_map(state),
        shots_dir=shots_dir,
        thumbnail_variants=[Path(v) for v in state.get("thumbnail_variants", [])],
        shorts=shorts,
    )

    record = _record(
        job, meta, outcome.get("video_id", ""), outcome.get("url", ""),
        {
            "via": "browser",
            "completed": outcome.get("completed", []),
            "skipped": outcome.get("skipped", []),
            "manual_todo": outcome.get("manual_todo", []),
        },
    )
    _print_browser_summary(meta, outcome)
    return job.save_state(stage="uploaded", **record)


def _print_browser_summary(meta: seo.Metadata, outcome: dict) -> None:
    print()
    print("=" * 72)
    if outcome.get("url"):
        ok(f"YAYINDA: {outcome['url']}")
        print(f"  Studio     : https://studio.youtube.com/video/{outcome.get('video_id', '')}/edit")
    else:
        warn("Video kimligi okunamadi - Studio'dan kontrol edin.")
    print(f"  Baslik     : {meta.title}")
    print(f"  Etiket     : {len(meta.tags)} | Bolum: {len(meta.chapters)}")
    if meta.publish_at:
        print(f"  Planli     : {meta.publish_at} (UTC)")

    done = outcome.get("completed", [])
    if done:
        print(f"  Tamamlanan : {', '.join(done)}")
    for warning in outcome.get("warnings", []):
        print(f"  ! {warning}")

    todo = outcome.get("manual_todo", [])
    if todo:
        print()
        print("  ELLE YAPILACAKLAR:")
        for item in todo:
            print(f"    - {item}")
    else:
        print()
        print("  Elle yapilacak bir sey yok.")
    print(f"  Ekran goruntuleri: {outcome.get('shots_dir', '')}")
    print("=" * 72)


# ----------------------------------------------------------------- API yolu
def _upload_api(
    job: Job,
    state: dict,
    final: Path,
    meta: seo.Metadata,
    *,
    upload_shorts: bool,
) -> dict:
    cfg = job.cfg
    service = youtube.authorize(cfg.secrets_dir)
    channel = youtube.channel_info(service)
    info(f"Kanal: {channel['title']} ({channel['subscribers']} abone)")

    def progress(percent: int) -> None:
        bar = "█" * (percent // 4) + "·" * (25 - percent // 4)
        print(f"\r  yukleniyor [{bar}] %{percent}", end="", flush=True)

    video_id = youtube.upload_video(
        service, final,
        title=meta.title,
        description=meta.description,
        tags=meta.tags,
        category_id=meta.category_id,
        privacy=meta.privacy,
        publish_at=meta.publish_at,
        made_for_kids=meta.made_for_kids,
        default_language=meta.default_language,
        notify_subscribers=meta.notify_subscribers,
        progress_cb=progress,
    )
    print()
    ok(f"Video yuklendi: {youtube.video_url(video_id)}")

    step("4/4 Yayin sonrasi islemler")
    thumb = opt_path(state.get("thumbnail"))
    if thumb and youtube.set_thumbnail(service, video_id, thumb):
        ok("Kapak ayarlandi.")

    for lang, key in (("tr", "srt_tr"), ("en", "srt_en")):
        path = opt_path(state.get(key))
        if path and youtube.upload_caption(service, video_id, path, language=lang):
            ok(f"Altyazi yuklendi: {lang}")

    if meta.localizations and youtube.set_localizations(
        service, video_id, meta.localizations, default_language=meta.default_language
    ):
        ok(f"Lokalizasyon eklendi: {', '.join(meta.localizations)}")

    playlist_id = None
    if meta.playlist:
        playlist_id = youtube.ensure_playlist(
            service, meta.playlist,
            description=f"{cfg.channel_name} - {meta.playlist} derlemesi.",
        )
        if playlist_id and youtube.add_to_playlist(service, playlist_id, video_id):
            ok(f"Oynatma listesine eklendi: {meta.playlist}")

    if meta.pinned_comment and youtube.post_comment(service, video_id, meta.pinned_comment):
        ok("Ilk yorum atildi (Studio'dan sabitleyebilirsiniz).")

    shorts_ids: list[str] = []
    if upload_shorts:
        shorts_ids = _upload_shorts(job, service, state, video_id)

    record = _record(
        job, meta, video_id, youtube.video_url(video_id),
        {"via": "api", "shorts": shorts_ids},
    )
    _print_summary(meta, record, state)
    return job.save_state(stage="uploaded", **record)


def _upload_shorts(job: Job, service, state: dict, parent_id: str) -> list[str]:
    ids: list[str] = []
    for index, path_str in enumerate(state.get("shorts", []), start=1):
        path = Path(path_str)
        if not path.exists():
            continue
        short_meta = read_json(job.work / f"short_{index}_meta.json", {}) or {}
        description = short_meta.get("description", "")
        description += f"\n\nTam video: {youtube.video_url(parent_id)}"
        try:
            short_id = youtube.upload_video(
                service, path,
                title=short_meta.get("title", "Clash of Clans #Shorts"),
                description=description,
                tags=short_meta.get("tags", []),
                category_id="20",
                privacy=str(job.cfg.get("upload.privacy", "public")),
                default_language="tr",
                notify_subscribers=False,
            )
            ids.append(short_id)
            ok(f"Shorts yuklendi: {youtube.video_url(short_id)}")
        except HusccError as exc:
            warn(f"Shorts yuklenemedi: {exc}")
    return ids


def _print_preview(meta: seo.Metadata, state: dict) -> None:
    print()
    print("=" * 72)
    print(f"BASLIK      : {meta.title}  ({len(meta.title)} karakter)")
    print(f"GIZLILIK    : {meta.privacy}" + (f"  (planli: {meta.publish_at})" if meta.publish_at else ""))
    print(f"OYNATMA L.  : {meta.playlist}")
    print(f"ETIKETLER   : {', '.join(meta.tags[:12])} ... (+{max(0, len(meta.tags) - 12)})")
    print(f"KAPAK       : {state.get('thumbnail', '')}")
    print(f"VIDEO       : {state.get('final_video', '')}")
    if meta.title_alternatives:
        print("ALTERNATIF  :")
        for alt in meta.title_alternatives[:2]:
            print(f"              [{alt['score']}] {alt['title']}")
    print("-" * 72)
    print(meta.description[:900])
    if len(meta.description) > 900:
        print(f"... (+{len(meta.description) - 900} karakter)")
    print("=" * 72)


def _print_summary(meta: seo.Metadata, record: dict, state: dict) -> None:
    print()
    print("=" * 72)
    ok(f"YAYINDA: {record['url']}")
    print(f"  Studio     : {youtube.studio_url(record['video_id'])}")
    print(f"  Baslik     : {meta.title}")
    print(f"  Etiket     : {len(meta.tags)} | Bolum: {len(meta.chapters)} | Dil: {meta.default_language}")
    if meta.publish_at:
        print(f"  Planli     : {meta.publish_at} (UTC) - o ana kadar gizli")
    if state.get("shorts"):
        print(f"  Shorts     : {len(state['shorts'])} adet hazir -> {Path(state['shorts'][0]).parent}")
    print()
    print("  Elle yapilacak tek is: Studio > Bitis ekrani ve kartlari ekle,")
    print("  ilk yorumu sabitle. (YouTube API bu ikisini desteklemiyor.)")
    print("=" * 72)


# --------------------------------------------------------------------- akis
def publish(
    job: Job,
    *,
    brain: str = "claude-code",
    dry_run: bool = False,
    skip_edit: bool = False,
    upload_shorts: bool = False,
    frame_count: int = 14,
    image_source: str | None = None,
    interactive: bool = True,
    via: str | None = None,
    force: bool = False,
) -> dict:
    """prep -> render -> upload. claude-code beyninde brief yoksa durur."""
    state = job.state()
    if state.get("stage") not in {"prep", "render", "uploaded"}:
        prep(job, brain=brain, frame_count=frame_count)

    if brain == "claude-code" and brief_mod.load_brief(job.work) is None:
        raise HusccError(
            "Brief bekleniyor.\n"
            f"  Kareler: {job.work / 'frames'}\n"
            f"  Yonerge: {job.work / 'ANALIZ.md'}\n"
            "  Claude kareleri okuyup brief.json yazdiktan sonra:\n"
            f'    huscc render "{job.video.name}" && huscc upload "{job.video.name}"'
        )

    render(job, skip_edit=skip_edit, image_source=image_source, interactive=interactive)
    return upload(job, dry_run=dry_run, upload_shorts=upload_shorts, via=via, force=force)


def report(job: Job) -> str:
    """Isin ozetini metin olarak dondurur."""
    state = job.state()
    meta = state.get("metadata", {})
    lines = [
        f"Video   : {job.video.path.name}",
        f"Asama   : {state.get('stage', '-')}",
        f"Baslik  : {meta.get('title', '-')}",
        f"Kapak   : {state.get('thumbnail', '-')}",
        f"Cikti   : {state.get('final_video', '-')}",
        f"URL     : {state.get('url', '-')}",
    ]
    return "\n".join(lines)


def load_report(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ------------------------------------------------------- 5. meta veri guncelle
def update(
    job: Job,
    *,
    fields: set[str] | None = None,
    video_id: str | None = None,
    rebuild: bool = False,
) -> dict:
    """Yayindaki videonun baslik/aciklama/etiket/kapak/gorunurlugunu gunceller.

    `rebuild=True` ise meta veri brief'ten yeniden uretilir (SEO'yu tazelemek icin).
    """
    cfg = job.cfg
    state = job.state()
    target = video_id or state.get("video_id") or ""
    if not target:
        record = already_published(job)
        target = (record or {}).get("video_id", "")
    if not target:
        raise HusccError(
            "Bu video icin yayin kaydi yok.\n"
            "  Once 'huscc upload' ile yayinlayin ya da --video <kimlik> verin."
        )

    if rebuild:
        current = brief_mod.load_brief(job.work)
        if current is None:
            raise HusccError("brief.json yok - meta veri yeniden uretilemez.")
        media_info = media.MediaInfo(**{
            k: val for k, val in (state.get("media") or {}).items()
            if k in media.MediaInfo.__dataclass_fields__
        })
        meta = seo.build_metadata(current, cfg, duration=media_info.duration)
        write_json(job.work / "metadata.json", meta.to_dict())
        ok("Meta veri brief'ten yeniden uretildi.")
    else:
        meta_dict = state.get("metadata") or {}
        if not meta_dict:
            raise HusccError("Kayitli meta veri yok - once 'huscc render' calistirin.")
        meta = seo.Metadata(**{
            k: val for k, val in meta_dict.items() if k in seo.Metadata.__dataclass_fields__
        })

    step(f"Meta veri guncelleniyor - {meta.title}")
    outcome = publish_browser.update_metadata(
        cfg,
        video_id=target,
        meta=meta,
        thumbnail=opt_path(state.get("thumbnail")),
        fields=fields,
        shots_dir=ensure_dir(job.work / "browser"),
    )
    job.save_state(metadata=meta.to_dict(), last_update=utc_now().isoformat())
    ok(f"Guncellendi: {outcome.get('url', '')}")
    return outcome
