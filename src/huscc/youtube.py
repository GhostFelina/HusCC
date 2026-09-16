"""YouTube Data API v3 katmani: yetkilendirme, yukleme, kapak, altyazi,
oynatma listesi, lokalizasyon ve ilk yorum.
"""
from __future__ import annotations

import random
import time
from pathlib import Path
from typing import Any

from .util import HusccError, err, info, ok, warn

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

CLIENT_SECRET_NAMES = ["client_secret.json", "client_secrets.json", "oauth_client.json"]
TOKEN_NAME = "token.json"

SETUP_HELP = """
YouTube yetkilendirmesi icin tek seferlik kurulum:

 1. https://console.cloud.google.com/projectcreate  -> yeni proje olustur (ad: HusCC)
 2. "APIs & Services" > "Library" > "YouTube Data API v3" > ENABLE
 3. "APIs & Services" > "OAuth consent screen"
      User type: External -> App name: HusCC -> destek e-postasi: kendi adresin
      Audience > Test users bolumune YouTube kanalinin sahibi olan Google hesabini EKLE
 4. "APIs & Services" > "Credentials" > "Create credentials" > "OAuth client ID"
      Application type: Desktop app -> Create -> "Download JSON"
 5. Inen dosyayi su konuma koy:
      {target}
 6. Terminalde:  huscc auth
"""


def _lazy_imports():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:  # pragma: no cover
        raise HusccError(
            "Google kutuphaneleri eksik. Kurmak icin:\n"
            "  uv pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        ) from exc
    return Request, Credentials, InstalledAppFlow, build, HttpError, MediaFileUpload


def client_secret_path(secrets_dir: Path) -> Path | None:
    for name in CLIENT_SECRET_NAMES:
        candidate = secrets_dir / name
        if candidate.exists():
            return candidate
    # Indirilen dosya adi uzun olabilir: client_secret_1234-abc.apps.googleusercontent.com.json
    for candidate in sorted(secrets_dir.glob("client_secret*.json")):
        return candidate
    return None


def setup_help(secrets_dir: Path) -> str:
    return SETUP_HELP.format(target=secrets_dir / "client_secret.json")


def authorize(secrets_dir: Path, *, headless: bool = False):
    """Kimlik dogrular ve YouTube servis nesnesi dondurur."""
    Request, Credentials, InstalledAppFlow, build, _, _ = _lazy_imports()

    token_path = secrets_dir / TOKEN_NAME
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception:
            creds = None

    if creds and creds.valid:
        return build("youtube", "v3", credentials=creds, cache_discovery=False)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return build("youtube", "v3", credentials=creds, cache_discovery=False)
        except Exception as exc:
            warn(f"Token yenilenemedi ({exc}); yeniden giris gerekiyor.")

    secret = client_secret_path(secrets_dir)
    if not secret:
        raise HusccError(
            "OAuth istemci dosyasi bulunamadi.\n" + setup_help(secrets_dir)
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    if headless:
        creds = flow.run_console()  # type: ignore[attr-defined]
    else:
        info("Tarayici aciliyor - YouTube kanalinin sahibi olan Google hesabiyla giris yapin.")
        creds = flow.run_local_server(
            port=0,
            prompt="consent",
            authorization_prompt_message="Tarayicida su adresi acin:\n{url}",
            success_message="HusCC yetkilendirildi. Bu sekmeyi kapatabilirsiniz.",
            open_browser=True,
        )
    secrets_dir.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    ok(f"Yetkilendirme kaydedildi: {token_path}")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def channel_info(youtube) -> dict:
    response = (
        youtube.channels()
        .list(part="snippet,statistics,contentDetails", mine=True)
        .execute()
    )
    items = response.get("items", [])
    if not items:
        raise HusccError("Bu hesaba bagli bir YouTube kanali bulunamadi.")
    item = items[0]
    return {
        "id": item["id"],
        "title": item["snippet"]["title"],
        "custom_url": item["snippet"].get("customUrl", ""),
        "subscribers": item.get("statistics", {}).get("subscriberCount", "0"),
        "videos": item.get("statistics", {}).get("videoCount", "0"),
        "uploads_playlist": item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads", ""),
    }


# ------------------------------------------------------------------- yukleme
def upload_video(
    youtube,
    file_path: Path,
    *,
    title: str,
    description: str,
    tags: list[str],
    category_id: str = "20",
    privacy: str = "public",
    publish_at: str | None = None,
    made_for_kids: bool = False,
    default_language: str = "tr",
    notify_subscribers: bool = True,
    progress_cb=None,
) -> str:
    _, _, _, _, HttpError, MediaFileUpload = _lazy_imports()

    status: dict[str, Any] = {
        "privacyStatus": "private" if publish_at else privacy,
        "selfDeclaredMadeForKids": made_for_kids,
        "embeddable": True,
        "license": "youtube",
        "publicStatsViewable": True,
    }
    if publish_at:
        status["publishAt"] = publish_at

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:60],
            "categoryId": str(category_id),
            "defaultLanguage": default_language,
            "defaultAudioLanguage": default_language,
        },
        "status": status,
    }

    media = MediaFileUpload(
        str(file_path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/*"
    )
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
        notifySubscribers=notify_subscribers,
    )

    response = None
    retries = 0
    last_percent = -5
    while response is None:
        try:
            status_obj, response = request.next_chunk()
            if status_obj and progress_cb:
                percent = int(status_obj.progress() * 100)
                if percent - last_percent >= 5:
                    progress_cb(percent)
                    last_percent = percent
        except HttpError as exc:
            if exc.resp.status in (500, 502, 503, 504) and retries < 6:
                retries += 1
                sleep_for = min(60, (2**retries) + random.random())
                warn(f"Gecici hata ({exc.resp.status}); {sleep_for:.0f} sn sonra tekrar.")
                time.sleep(sleep_for)
                continue
            raise HusccError(_explain(exc)) from exc
        except (OSError, ConnectionError) as exc:
            if retries < 6:
                retries += 1
                time.sleep(min(30, 2**retries))
                continue
            raise HusccError(f"Yukleme baglantisi koptu: {exc}") from exc

    if progress_cb:
        progress_cb(100)
    video_id = response.get("id", "")
    if not video_id:
        raise HusccError("Yukleme tamamlandi ama video kimligi alinamadi.")
    return video_id


def set_thumbnail(youtube, video_id: str, image: Path) -> bool:
    _, _, _, _, HttpError, MediaFileUpload = _lazy_imports()
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(image), mimetype="image/jpeg"),
        ).execute()
        return True
    except HttpError as exc:
        warn(f"Kapak yuklenemedi: {_explain(exc)}")
        return False


def upload_caption(
    youtube, video_id: str, srt: Path, *, language: str = "tr", name: str = ""
) -> bool:
    _, _, _, _, HttpError, MediaFileUpload = _lazy_imports()
    try:
        youtube.captions().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "language": language,
                    "name": name or ("Türkçe" if language == "tr" else language.upper()),
                    "isDraft": False,
                }
            },
            media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream"),
        ).execute()
        return True
    except HttpError as exc:
        warn(f"Altyazi yuklenemedi ({language}): {_explain(exc)}")
        return False


def set_localizations(
    youtube, video_id: str, localizations: dict[str, dict[str, str]], *, default_language: str
) -> bool:
    if not localizations:
        return False
    _, _, _, _, HttpError, _ = _lazy_imports()
    try:
        current = youtube.videos().list(part="snippet", id=video_id).execute()
        items = current.get("items", [])
        if not items:
            return False
        snippet = items[0]["snippet"]
        snippet["defaultLanguage"] = default_language
        payload = {
            lang: {
                "title": data.get("title", "")[:100],
                "description": data.get("description", "")[:5000],
            }
            for lang, data in localizations.items()
        }
        youtube.videos().update(
            part="snippet,localizations",
            body={"id": video_id, "snippet": snippet, "localizations": payload},
        ).execute()
        return True
    except HttpError as exc:
        warn(f"Lokalizasyon yazilamadi: {_explain(exc)}")
        return False


def ensure_playlist(youtube, title: str, *, description: str = "") -> str | None:
    if not title:
        return None
    _, _, _, _, HttpError, _ = _lazy_imports()
    try:
        page_token = None
        while True:
            response = (
                youtube.playlists()
                .list(part="snippet", mine=True, maxResults=50, pageToken=page_token)
                .execute()
            )
            for item in response.get("items", []):
                if item["snippet"]["title"].strip().lower() == title.strip().lower():
                    return item["id"]
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        created = (
            youtube.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {"title": title[:150], "description": description[:5000]},
                    "status": {"privacyStatus": "public"},
                },
            )
            .execute()
        )
        ok(f"Oynatma listesi olusturuldu: {title}")
        return created["id"]
    except HttpError as exc:
        warn(f"Oynatma listesi islemi basarisiz: {_explain(exc)}")
        return None


def add_to_playlist(youtube, playlist_id: str, video_id: str) -> bool:
    _, _, _, _, HttpError, _ = _lazy_imports()
    try:
        youtube.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        ).execute()
        return True
    except HttpError as exc:
        warn(f"Oynatma listesine eklenemedi: {_explain(exc)}")
        return False


def post_comment(youtube, video_id: str, text: str) -> bool:
    if not text.strip():
        return False
    _, _, _, _, HttpError, _ = _lazy_imports()
    try:
        youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {"snippet": {"textOriginal": text[:9000]}},
                }
            },
        ).execute()
        return True
    except HttpError as exc:
        warn(f"Ilk yorum atilamadi: {_explain(exc)}")
        return False


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def studio_url(video_id: str) -> str:
    return f"https://studio.youtube.com/video/{video_id}/edit"


def _explain(exc) -> str:
    """HttpError'u anlasilir Turkce mesaja cevirir."""
    try:
        status = exc.resp.status
        detail = exc.error_details if hasattr(exc, "error_details") else ""
        reason = ""
        if isinstance(detail, list) and detail:
            reason = str(detail[0].get("reason", ""))
    except Exception:
        return str(exc)

    table = {
        "quotaExceeded": (
            "Gunluk API kotasi doldu (varsayilan 10.000 birim ≈ 6 yukleme). "
            "Yarin tekrar deneyin veya Google Cloud'dan kota artisi isteyin."
        ),
        "uploadLimitExceeded": "Kanalin gunluk yukleme siniri doldu.",
        "forbidden": "Yetki yok. 'huscc auth' ile dogru kanala giris yaptiginizdan emin olun.",
        "youtubeSignupRequired": "Bu Google hesabinda YouTube kanali yok.",
        "videoNotFound": "Video bulunamadi.",
        "invalidCategoryId": "Gecersiz kategori kimligi (Oyun = 20).",
        "invalidTitle": "Baslik gecersiz (< veya > karakteri olamaz, 100 karakteri asamaz).",
        "invalidDescription": "Aciklama gecersiz (< veya > karakteri olamaz).",
        "invalidTags": "Etiketler gecersiz (toplam 500 karakteri asamaz).",
        "insufficientPermissions": "Token'in yetkisi yetersiz - 'huscc auth --force' calistirin.",
        "captionsNotEnabled": "Bu video icin altyazi kapali.",
    }
    if reason in table:
        return table[reason]
    if status == 403:
        return f"Erisim reddedildi ({reason or 'forbidden'}). Kanal secimini ve kotayi kontrol edin."
    if status == 401:
        return "Yetkilendirme gecersiz - 'huscc auth --force' calistirin."
    return f"YouTube API hatasi {status}: {exc}"
