"""Tarayici katmani testleri - gercek tarayici acmadan calisir."""
from __future__ import annotations

from pathlib import Path

import pytest

from huscc import studio
from huscc.browser import Selectors
from huscc.config import load_config
from huscc.publish_browser import preflight
from huscc.seo import Metadata
from huscc.util import HusccError


# ------------------------------------------------------------------ secici
def _selectors() -> Selectors:
    return Selectors.load(load_config().selectors_path)


def test_selector_file_loads():
    sel = _selectors()
    assert len(sel.data) > 30


def test_every_selector_key_has_strategies():
    sel = _selectors()
    for key in sel.data:
        strategies = sel.strategies(key)
        assert strategies, f"{key} bos"
        for kind, value in strategies:
            assert kind in {"css", "text", "role", "xpath", "label", "testid"}, f"{key}: {kind}"
            assert value.strip()


def test_critical_keys_present():
    """Akisin kirilma noktalari her zaman tanimli olmali."""
    sel = _selectors()
    required = [
        "create_button", "upload_menu_item", "file_input",
        "title_box", "description_box", "thumbnail_input",
        "not_for_kids_radio", "next_button", "public_radio",
        "publish_button", "published_url_link",
    ]
    for key in required:
        assert key in sel.data, f"eksik secici: {key}"


def test_role_strategies_are_bilingual():
    """Metin tabanli seciciler hem TR hem EN karsiligi icermeli."""
    sel = _selectors()
    for key, entries in sel.data.items():
        for kind, value in sel.strategies(key):
            if kind == "role" and "|" in value:
                _role, _, names = value.partition("|")
                assert names.strip(), f"{key}: rol adi bos"


def test_unknown_key_raises():
    with pytest.raises(HusccError):
        _selectors().strategies("boyle_bir_sey_yok")


# --------------------------------------------------------------- on kontrol
def _meta(**over) -> Metadata:
    base = dict(
        title="TH16 Root Rider ile 3 Yildiz",
        description="Aciklama metni",
        tags=["th16 saldiri", "root rider"],
        privacy="public",
    )
    base.update(over)
    return Metadata(**base)


def _video(tmp_path: Path, size: int = 500_000) -> Path:
    path = tmp_path / "video.mp4"
    path.write_bytes(b"0" * size)
    return path


def test_preflight_clean(tmp_path: Path):
    assert preflight(_meta(), _video(tmp_path), None) == []


def test_preflight_catches_missing_video(tmp_path: Path):
    problems = preflight(_meta(), tmp_path / "yok.mp4", None)
    assert any("Video yok" in p for p in problems)


def test_preflight_catches_long_title(tmp_path: Path):
    problems = preflight(_meta(title="x" * 120), _video(tmp_path), None)
    assert any("100 karakteri asiyor" in p for p in problems)


def test_preflight_rejects_angle_brackets(tmp_path: Path):
    problems = preflight(_meta(title="TH16 <b> saldiri"), _video(tmp_path), None)
    assert any("< veya >" in p for p in problems)


def test_preflight_catches_tag_overflow(tmp_path: Path):
    tags = [f"etiket-{i:03d}-uzun-bir-anahtar-kelime" for i in range(40)]
    problems = preflight(_meta(tags=tags), _video(tmp_path), None)
    assert any("Etiketler 500" in p for p in problems)


def test_preflight_catches_big_thumbnail(tmp_path: Path):
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"0" * 2_500_000)
    problems = preflight(_meta(), _video(tmp_path), thumb)
    assert any("2 MB" in p for p in problems)


def test_preflight_rejects_bad_privacy(tmp_path: Path):
    problems = preflight(_meta(privacy="herkese-acik"), _video(tmp_path), None)
    assert any("gizlilik" in p.lower() for p in problems)


# -------------------------------------------------------------------- studio
def test_video_id_extraction():
    assert studio._video_id_from("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert studio._video_id_from("https://studio.youtube.com/video/abcdefghijk/edit") == "abcdefghijk"
    assert studio._video_id_from("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
    assert studio._video_id_from("hicbir sey yok") == ""


def test_schedule_conversion_is_local():
    date_text, time_text = studio._local_schedule("2026-09-20T17:00:00Z")
    assert len(date_text.split(".")) == 3
    assert ":" in time_text


def test_privacy_keys_cover_all_options():
    assert set(studio.PRIVACY_KEYS) == {"public", "unlisted", "private"}
    sel = _selectors()
    for key in studio.PRIVACY_KEYS.values():
        assert key in sel.data


def test_gaming_category_named_in_both_languages():
    assert studio.CATEGORY_NAMES["20"] == ("Oyun", "Gaming")


def test_upload_plan_defaults():
    plan = studio.UploadPlan(video=Path("x.mp4"), title="t", description="d")
    assert plan.privacy == "public"
    assert plan.category_id == "20"
    assert plan.made_for_kids is False
    assert plan.end_screen is True


def test_upload_result_ok_needs_video_id():
    assert studio.UploadResult().ok is False
    assert studio.UploadResult(video_id="abcdefghijk").ok is True
