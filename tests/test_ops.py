"""Isletim davranislari: kayit dosyasi, cift yukleme korumasi, yapilandirma yazimi."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from huscc import pipeline
from huscc.cli import _yaml_set
from huscc.config import Config, load_config
from huscc.discover import VideoFile
from huscc.util import HusccError, log_to, write_json


# ---------------------------------------------------------------- log_to
def test_log_to_writes_and_restores(tmp_path: Path, capsys):
    target = tmp_path / "log.txt"
    with log_to(target):
        print("merhaba kayit")
    assert target.exists()
    assert "merhaba kayit" in target.read_text(encoding="utf-8")
    # stdout geri verilmis olmali
    print("ekrana geri dondu")
    assert "ekrana geri dondu" in capsys.readouterr().out


def test_log_to_appends(tmp_path: Path):
    target = tmp_path / "log.txt"
    with log_to(target):
        print("birinci")
    with log_to(target):
        print("ikinci")
    text = target.read_text(encoding="utf-8")
    assert "birinci" in text and "ikinci" in text


# ------------------------------------------------------------ yapilandirma
SAMPLE_YAML = """# Ust yorum
channel:
  # kanal adi yorumu
  name: "HusCC"
  handle: "@HusCC"

upload:
  privacy: "public"   # satir sonu yorumu
  schedule: "auto"
"""


def test_yaml_set_changes_only_target():
    out = _yaml_set(SAMPLE_YAML, "channel", "name", "Yeni Kanal")
    assert 'name: "Yeni Kanal"' in out
    assert 'handle: "@HusCC"' in out
    assert 'privacy: "public"' in out


def test_yaml_set_preserves_comments():
    out = _yaml_set(SAMPLE_YAML, "upload", "privacy", "unlisted")
    assert "# Ust yorum" in out
    assert "# kanal adi yorumu" in out
    assert "# satir sonu yorumu" in out
    assert 'privacy: "unlisted"' in out


def test_yaml_set_respects_section():
    """Ayni ada sahip anahtar baska bolumdeyse dokunulmamali."""
    text = 'a:\n  name: "bir"\nb:\n  name: "iki"\n'
    out = _yaml_set(text, "b", "name", "uc")
    assert 'name: "bir"' in out
    assert 'name: "uc"' in out


def test_yaml_set_unknown_key_is_noop():
    assert _yaml_set(SAMPLE_YAML, "channel", "olmayan", "x") == SAMPLE_YAML


def test_yaml_set_output_is_valid_yaml():
    import yaml

    out = _yaml_set(SAMPLE_YAML, "channel", "name", "Test Kanal")
    data = yaml.safe_load(out)
    assert data["channel"]["name"] == "Test Kanal"
    assert data["upload"]["schedule"] == "auto"


# ------------------------------------------------------ cift yukleme koruma
def _job(tmp_path: Path) -> pipeline.Job:
    cfg = load_config()
    cfg = Config(raw={**cfg.raw, "paths": {**cfg.section("paths"),
                                           "work_dir": str(tmp_path / "work"),
                                           "out_dir": str(tmp_path / "out")}},
                 root=cfg.root)
    video = tmp_path / "th16 test.mp4"
    video.write_bytes(b"0" * 200_000)
    return pipeline.Job(video=VideoFile(video), slug="th16-test",
                        work=cfg.work_for("th16-test"), cfg=cfg)


def test_already_published_reads_state(tmp_path: Path):
    job = _job(tmp_path)
    assert pipeline.already_published(job) is None
    job.save_state(video_id="abcdefghijk", url="https://youtu.be/abcdefghijk")
    record = pipeline.already_published(job)
    assert record and record["video_id"] == "abcdefghijk"


def test_already_published_reads_history(tmp_path: Path):
    job = _job(tmp_path)
    write_json(job.cfg.history_file, [
        {"slug": "baska-video", "video_id": "11111111111"},
        {"slug": "th16-test", "video_id": "22222222222", "url": "https://youtu.be/22222222222"},
    ])
    record = pipeline.already_published(job)
    assert record and record["video_id"] == "22222222222"


def test_upload_refuses_duplicate(tmp_path: Path):
    job = _job(tmp_path)
    final = tmp_path / "out" / "th16-test.mp4"
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b"0" * 200_000)
    job.save_state(
        final_video=str(final),
        metadata={"title": "Test", "description": "d", "tags": []},
        video_id="abcdefghijk",
        url="https://youtu.be/abcdefghijk",
    )
    with pytest.raises(HusccError) as caught:
        pipeline.upload(job)
    message = str(caught.value)
    assert "daha once yayinlanmis" in message
    assert "huscc update" in message
    assert "--force" in message


def test_update_without_record_raises(tmp_path: Path):
    job = _job(tmp_path)
    with pytest.raises(HusccError) as caught:
        pipeline.update(job)
    assert "yayin kaydi yok" in str(caught.value)


def test_state_roundtrip(tmp_path: Path):
    job = _job(tmp_path)
    job.save_state(stage="render", thumbnail="x.jpg")
    data = json.loads(job.state_file.read_text(encoding="utf-8"))
    assert data["stage"] == "render"
    assert data["slug"] == "th16-test"
    assert "updated_at" in data
