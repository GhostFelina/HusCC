"""Cekirdek davranis testleri - ffmpeg veya ag gerektirmez."""
from __future__ import annotations

from pathlib import Path

import pytest

from huscc import keywords as kw
from huscc import brief as brief_mod
from huscc import seo
from huscc.config import Config
from huscc.discover import clean_query, find_video, list_videos
from huscc.util import HusccError, hhmmss, slugify, srt_ts, tr_fold, tr_upper


# ------------------------------------------------------------------- util
def test_tr_fold_handles_turkish():
    assert tr_fold("Kızılay Saldırısı") == "kizilay saldirisi"
    assert tr_fold("ÇÖĞÜŞİ") == "cogusi"


def test_slugify():
    assert slugify("TH16 Root Rider — Klan Savaşı!") == "th16-root-rider-klan-savasi"
    assert slugify("!!!") == "video"


def test_tr_upper():
    assert tr_upper("ilk video") == "İLK VİDEO"


def test_timestamps():
    assert hhmmss(75) == "1:15"
    assert hhmmss(3725) == "1:02:05"
    assert srt_ts(3.5) == "00:00:03,500"


# --------------------------------------------------------------- discover
def test_clean_query_strips_filler():
    assert clean_query("kizilay saldirisi isimli videomu paylas") == "kizilay saldirisi"


def _make_videos(tmp_path: Path, names: list[str]) -> Path:
    for name in names:
        (tmp_path / name).write_bytes(b"0" * 2048)
    return tmp_path


def test_find_video_exact_and_partial(tmp_path: Path):
    folder = _make_videos(tmp_path, ["th16 hydra savas.mp4", "th15 base inceleme.mp4"])
    assert find_video(folder, "th16 hydra savas").path.name == "th16 hydra savas.mp4"
    assert find_video(folder, "hydra").path.name == "th16 hydra savas.mp4"
    assert find_video(folder, "th16 hydra isimli videomu paylas").path.name == "th16 hydra savas.mp4"


def test_find_video_latest(tmp_path: Path):
    folder = _make_videos(tmp_path, ["a.mp4"])
    (folder / "b.mp4").write_bytes(b"0" * 4096)
    assert find_video(folder, "son").path.name in {"a.mp4", "b.mp4"}


def test_find_video_missing_raises(tmp_path: Path):
    _make_videos(tmp_path, ["th16 hydra.mp4"])
    with pytest.raises(HusccError):
        find_video(tmp_path, "tamamen alakasiz bir sey")


def test_list_videos_ignores_other_files(tmp_path: Path):
    (tmp_path / "not.txt").write_text("x", encoding="utf-8")
    (tmp_path / "v.mp4").write_bytes(b"0" * 1024)
    assert [v.path.name for v in list_videos(tmp_path)] == ["v.mp4"]


# --------------------------------------------------------------- keywords
def test_detect_town_hall():
    assert kw.detect_th("th16 hydra") == "TH16"
    assert kw.detect_th("TH 9 saldiri") == "TH9"
    assert kw.detect_th("hicbir sey") is None


def test_detect_strategies_and_type():
    assert "root rider" in kw.detect_strategies("th16 root rider push")
    assert kw.detect_content_type("klan savasi 3 yildiz saldiri") == "war_attack"
    assert kw.detect_content_type("en iyi base duzeni anti 3") == "base_review"


def test_keyword_pool_is_deduped():
    pool = kw.keyword_pool("war_attack", "TH16", ["root rider"])
    assert len(pool) == len(set(pool))
    assert "clash of clans" in pool


# -------------------------------------------------------------------- seo
def _cfg() -> Config:
    from huscc.config import load_config

    return load_config()


def test_title_scoring_prefers_keyword_first():
    tags = ["th16 saldiri", "root rider", "clash of clans"]
    good, _ = seo.score_title("TH16 Root Rider Rehberi | Adim Adim 3 Yildiz", keywords=tags, limit=70)
    bad, _ = seo.score_title("VIDEO", keywords=tags, limit=70)
    assert good > bad


def test_title_scoring_penalizes_all_caps():
    tags = ["th16 saldiri"]
    normal, _ = seo.score_title("TH16 Saldiri Rehberi | Adim Adim", keywords=tags, limit=70)
    shouty, notes = seo.score_title("TH16 SALDIRI REHBERI ADIM ADIM", keywords=tags, limit=70)
    assert shouty < normal
    assert any("buyuk harf" in note for note in notes)


def test_build_tags_respects_limits():
    cfg = _cfg()
    brief = brief_mod.heuristic_brief("th16 root rider klan savasi 3 yildiz", duration=300)
    tags = seo.build_tags(brief, cfg)
    assert len(", ".join(tags)) <= 500
    assert all(len(tag) <= 40 for tag in tags)


def test_chapters_need_three_points_and_gap():
    brief = brief_mod.heuristic_brief("th16 hydra", duration=600)
    brief.highlights = [{"t": 30, "label": "a"}, {"t": 35, "label": "cok yakin"}, {"t": 120, "label": "b"}]
    chapters = seo.build_chapters(brief, 600)
    assert chapters[0]["t"] == 0.0
    assert len(chapters) >= 3
    gaps = [chapters[i + 1]["t"] - chapters[i]["t"] for i in range(len(chapters) - 1)]
    assert all(gap >= 10 for gap in gaps)


def test_short_video_has_no_chapters():
    brief = brief_mod.heuristic_brief("kisa klip", duration=40)
    assert seo.build_chapters(brief, 40) == []


def test_metadata_limits():
    cfg = _cfg()
    brief = brief_mod.heuristic_brief("th16 root rider klan savasi 3 yildiz", duration=420)
    meta = seo.build_metadata(brief, cfg, duration=420)
    assert 0 < len(meta.title) <= 100
    assert len(meta.description) <= 5000
    assert meta.category_id == "20"
    assert "ClashOfClans" in meta.description or "#Coc" in meta.description


def test_english_localization_generated():
    brief = brief_mod.heuristic_brief("th16 root rider klan savasi 3 yildiz", duration=300)
    pack = seo.english_pack(brief)
    assert pack and pack["title"]
    assert "TH16" in pack["title"]


# ------------------------------------------------------------------ brief
def test_heuristic_brief_reads_filename():
    brief = brief_mod.heuristic_brief("th16 root rider klan savasi 3 yildiz", duration=300)
    assert brief.town_hall == "TH16"
    assert brief.content_type == "war_attack"
    assert brief.outcome == "3 yildiz"
    assert len(brief.title_candidates) == 3


def test_brief_validation_catches_gaps():
    brief = brief_mod.Brief(video_name="x")
    problems = brief_mod.validate(brief)
    assert any("summary" in p for p in problems)
    assert any("title_candidates" in p for p in problems)


def test_normalize_uppercases_thumbnail_text():
    brief = brief_mod.Brief(thumbnail_text="ilk yıldız", summary="x" * 30, hook="h",
                            title_candidates=["a"])
    brief_mod.normalize(brief)
    assert brief.thumbnail_text == "İLK YILDIZ"


def test_brief_roundtrip(tmp_path: Path):
    brief = brief_mod.heuristic_brief("th15 hydra", duration=200)
    brief_mod.save_brief(tmp_path, brief)
    loaded = brief_mod.load_brief(tmp_path)
    assert loaded is not None
    assert loaded.town_hall == "TH15"


# -------------------------------------------------------------- imagegen
def test_image_prompt_mentions_scene_and_no_text():
    from huscc import imagegen

    brief = brief_mod.heuristic_brief("th16 root rider klan savasi 3 yildiz", duration=300)
    prompt = imagegen.build_prompt(brief)
    assert "no text" in prompt
    assert "root rider" in prompt
    assert "16:9" in prompt
