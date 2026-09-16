"""Ortam dayanikliligi: ffmpeg zinciri, ffprobe'suz analiz, sinama raporu."""
from __future__ import annotations

from pathlib import Path

import pytest

from huscc import media, selftest
from huscc.util import HusccError

# Gercek bir ffmpeg ciktisi ornegi (ffprobe yokken bunu ayristiriyoruz)
FFMPEG_OUTPUT = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'th16 hydra.mp4':
  Metadata:
    major_brand     : isom
    encoder         : Lavf61.7.100
  Duration: 00:02:20.03, start: 0.000000, bitrate: 4290 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 1280x720 [SAR 1:1 DAR 16:9], 4137 kb/s, 30 fps, 30 tbr, 15360 tbn (default)
      Metadata:
        handler_name    : VideoHandler
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, mono, fltp, 69 kb/s (default)
      Metadata:
        handler_name    : SoundHandler
"""

FFMPEG_OUTPUT_NO_AUDIO = """
Input #0, matroska,webm, from 'kayit.mkv':
  Duration: 00:00:45.50, start: 0.000000, bitrate: 2200 kb/s
  Stream #0:0: Video: vp9 (Profile 0), yuv420p(tv), 1920x1080, 60 fps, 60 tbr, 1k tbn (default)
"""

FFMPEG_OUTPUT_ROTATED = """
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'telefon.mp4':
  Duration: 00:00:30.00, start: 0.000000, bitrate: 8000 kb/s
    rotate          : 90
  Stream #0:0: Video: h264 (High), yuv420p, 1920x1080, 7800 kb/s, 30 fps, 30 tbr (default)
  Stream #0:1: Audio: aac (LC), 48000 Hz, stereo, fltp, 128 kb/s (default)
"""


class _Proc:
    def __init__(self, stderr: str) -> None:
        self.stderr = stderr
        self.stdout = ""
        self.returncode = 1


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """probe() icin ffmpeg cagrisini sabit ciktiyla degistirir."""

    def _use(text: str):
        monkeypatch.setattr(media, "ffmpeg_bin", lambda: "ffmpeg")
        monkeypatch.setattr(media, "run", lambda *a, **k: _Proc(text))

    return _use


# ------------------------------------------------------- ffprobe'suz analiz
def test_probe_without_ffprobe_reads_basics(fake_ffmpeg, tmp_path: Path):
    video = tmp_path / "th16 hydra.mp4"
    video.write_bytes(b"0" * 5000)
    fake_ffmpeg(FFMPEG_OUTPUT)

    info = media._probe_with_ffmpeg(video)
    assert (info.width, info.height) == (1280, 720)
    assert abs(info.duration - 140.03) < 0.1
    assert abs(info.fps - 30) < 0.01
    assert info.has_audio is True
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"


def test_probe_without_ffprobe_detects_missing_audio(fake_ffmpeg, tmp_path: Path):
    video = tmp_path / "kayit.mkv"
    video.write_bytes(b"0" * 5000)
    fake_ffmpeg(FFMPEG_OUTPUT_NO_AUDIO)

    info = media._probe_with_ffmpeg(video)
    assert info.has_audio is False
    assert (info.width, info.height) == (1920, 1080)
    assert abs(info.fps - 60) < 0.01


def test_probe_without_ffprobe_handles_rotation(fake_ffmpeg, tmp_path: Path):
    video = tmp_path / "telefon.mp4"
    video.write_bytes(b"0" * 5000)
    fake_ffmpeg(FFMPEG_OUTPUT_ROTATED)

    info = media._probe_with_ffmpeg(video)
    # 90 derece donmus: en/boy yer degistirmeli -> dikey video
    assert (info.width, info.height) == (1080, 1920)
    assert info.is_vertical is True


def test_probe_without_video_stream_raises(fake_ffmpeg, tmp_path: Path):
    video = tmp_path / "ses.m4a"
    video.write_bytes(b"0" * 5000)
    fake_ffmpeg("Duration: 00:01:00.00\n  Stream #0:0: Audio: aac, 44100 Hz\n")

    with pytest.raises(HusccError):
        media._probe_with_ffmpeg(video)


# ------------------------------------------------------------ ffmpeg zinciri
def test_bundled_ffmpeg_available():
    """pip ile gelen statik ffmpeg son care olarak her zaman bulunmali."""
    assert media._bundled("ffmpeg"), "imageio-ffmpeg kurulu degil"
    assert media._bundled("ffprobe") is None, "ffprobe statik pakette yok"


def test_resolve_uses_env_override(monkeypatch, tmp_path: Path):
    fake = tmp_path / "ffmpeg.exe"
    fake.write_bytes(b"0")
    media._CACHE.clear()
    monkeypatch.setenv("HUSCC_FFMPEG", str(fake))
    try:
        assert media._resolve("ffmpeg") == str(fake)
    finally:
        media._CACHE.clear()


def test_resolve_caches(monkeypatch):
    media._CACHE.clear()
    media._CACHE["ffmpeg"] = "/onbellekten/ffmpeg"
    calls = []
    monkeypatch.setattr(media, "which", lambda b: calls.append(b))
    try:
        assert media._resolve("ffmpeg") == "/onbellekten/ffmpeg"
        assert not calls, "onbellek varken arama yapilmamali"
    finally:
        media._CACHE.clear()


def test_have_ffmpeg_true_on_this_machine():
    assert media.have_ffmpeg()


# -------------------------------------------------------------- sinama raporu
def test_report_tracks_failures_and_warnings(capsys):
    report = selftest.Report()
    report.add("gecen", True, "tamam")
    report.add("uyari", False, "onemsiz", fatal=False)
    report.add("hata", False, "kritik")

    assert len(report.checks) == 3
    assert [c.name for c in report.failures] == ["hata"]
    assert [c.name for c in report.warnings] == ["uyari"]
    assert report.ok is False


def test_report_ok_when_only_warnings():
    report = selftest.Report()
    report.add("gecen", True)
    report.add("uyari", False, fatal=False)
    assert report.ok is True


def test_report_add_returns_result():
    report = selftest.Report()
    assert report.add("x", True) is True
    assert report.add("y", False, fatal=False) is False


# --------------------------------------------------------------- check.py
def test_check_script_is_stdlib_only():
    """check.py kurulumdan once calisacagi icin ucuncu parti import etmemeli."""
    import ast

    source = (Path(__file__).resolve().parent.parent / "check.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed = {
        "os", "platform", "shutil", "subprocess", "sys", "pathlib",
        "socket", "venv", "__future__",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in allowed, f"yasak import: {alias.name}"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] in allowed, f"yasak import: {node.module}"


def test_bundled_font_exists_and_covers_turkish():
    """Kapak fontu depoda olmali; sistem fontuna guvenilmemeli."""
    from PIL import ImageFont

    font_path = Path(__file__).resolve().parent.parent / "assets/fonts/Anton-Regular.ttf"
    assert font_path.exists(), "Anton fontu depoda yok"
    font = ImageFont.truetype(str(font_path), 48)
    for char in "İIŞĞÜÖÇışğüöç":
        assert font.getmask(char).size[0] > 0, f"{char} karakteri fontta yok"
