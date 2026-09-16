"""CC klasorundeki videolari bulur; kullanicinin yazdigi ismi dosyaya cozer."""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path

from .util import HusccError, human_size, tr_fold

VIDEO_EXT = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm",
    ".m4v", ".flv", ".ts", ".mpg", ".mpeg",
}

# Kullanicinin cumlesinde gecebilecek, dosya adiyla ilgisi olmayan kelimeler
_STOP = {
    "isimli", "adli", "adindaki", "videomu", "videoyu", "video", "videom",
    "kaydi", "kaydimi", "kayit", "paylas", "paylasir", "paylasabilir",
    "misin", "musun", "yukle", "yukler", "at", "atar", "lutfen",
    "the", "my", "share", "upload", "please",
}


@dataclass
class VideoFile:
    path: Path

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def size(self) -> int:
        return self.path.stat().st_size

    def __str__(self) -> str:
        return f"{self.path.name}  ({human_size(self.size)})"


def clean_query(query: str) -> str:
    """'kizilay saldirisi isimli videomu paylas' -> 'kizilay saldirisi'."""
    raw = query.replace('"', " ").replace("'", " ")
    tokens = [t for t in raw.split() if t]
    kept = [t for t in tokens if tr_fold(t).strip(".,!?") not in _STOP]
    return " ".join(kept).strip() or query.strip()


def list_videos(video_dir: Path) -> list[VideoFile]:
    if not video_dir.exists():
        return []
    files = [
        VideoFile(p)
        for p in video_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXT and not p.name.startswith("~")
    ]
    files.sort(key=lambda v: v.path.stat().st_mtime, reverse=True)
    return files


def _score(query_folded: str, candidate: VideoFile) -> float:
    name = tr_fold(candidate.name)
    if query_folded == name:
        return 1.0
    score = difflib.SequenceMatcher(None, query_folded, name).ratio()
    if query_folded and query_folded in name:
        score = max(score, 0.90 + 0.09 * (len(query_folded) / max(len(name), 1)))
    # Kelime bazli ortusme
    q_words = {w for w in query_folded.split() if len(w) > 2}
    n_words = {
        w for w in name.replace("-", " ").replace("_", " ").split() if len(w) > 2
    }
    if q_words:
        overlap = len(q_words & n_words) / len(q_words)
        if overlap:
            score = max(score, 0.55 + 0.4 * overlap)
    return score


def find_video(video_dir: Path, query: str, *, threshold: float = 0.52) -> VideoFile:
    """Isim / parca isim / 'son' ifadesine gore tek bir video dondurur."""
    videos = list_videos(video_dir)
    if not videos:
        raise HusccError(
            f"{video_dir} klasorunde video bulunamadi.\n"
            "  Ekran kaydini bu klasore koyup tekrar deneyin."
        )

    query = clean_query(query)
    folded = tr_fold(query).strip()

    if folded in {"son", "sonuncu", "en son", "last", "latest", ""}:
        return videos[0]

    for video in videos:
        if tr_fold(video.path.name) == folded or tr_fold(video.name) == folded:
            return video

    ranked = sorted(videos, key=lambda v: _score(folded, v), reverse=True)
    best = ranked[0]
    best_score = _score(folded, best)
    if best_score < threshold:
        listing = "\n".join(f"    - {v.path.name}" for v in videos[:15])
        raise HusccError(
            f"'{query}' ile eslesen video bulunamadi.\n"
            f"  Klasordeki videolar:\n{listing}"
        )

    runner_up = _score(folded, ranked[1]) if len(ranked) > 1 else 0.0
    if best_score - runner_up < 0.06 and best_score < 0.95:
        options = "\n".join(
            f"    - {v.path.name}  (benzerlik {_score(folded, v):.0%})"
            for v in ranked[:5]
        )
        raise HusccError(
            f"'{query}' birden fazla videoya benziyor, tam adi yazin:\n{options}"
        )
    return best
