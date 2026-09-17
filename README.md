# HusCC

Masaüstündeki **CC** klasörüne attığın Clash of Clans ekran kaydını tek komutla
YouTube'a yayınlayan otomasyon. Videoyu analiz eder, kapağı üretir, altyazıyı
çıkarır, SEO/GEO/AEO/CTR açısından paketler, kurgular ve **gerçek tarayıcıda
YouTube Studio'ya girip yayınlar**.

```bash
huscc publish "th16 root rider savaşı"
```

**API anahtarı yok, Google Cloud projesi yok, OAuth kurulumu yok.** Bir kez
Google girişi yaparsın, oturum kalır.

---

## Neden tarayıcı, neden API değil

YouTube Data API bazı şeyleri hiç yapamaz. Studio üzerinden hepsi yapılabiliyor:

| | Data API | HusCC (tarayıcı) |
|---|---|---|
| Video yükleme, başlık, açıklama, etiket | ✅ | ✅ |
| Kapak, oynatma listesi, altyazı | ✅ | ✅ |
| **Bitiş ekranı ve kartlar** | ❌ | ✅ |
| **İlk yorumu sabitleme** | ❌ | ✅ |
| **Küçük resim A/B testi (Test & Compare)** | ❌ | ✅ |
| Kurulum | Cloud projesi + OAuth + onay ekranı | Bir kez Google girişi |
| Günlük sınır | ~6 video (kota) | Kanalın normal yükleme sınırı |

API yolu yine duruyor: `--via api` ya da `config/channel.yaml > upload.via: api`.

---

## Ne yapıyor

| Aşama | İçerik |
|---|---|
| **Analiz** | Teknik bilgi, sahne kesimi tespiti, hareket profili, 14 anahtar kare, `faster-whisper` ile Türkçe altyazı + İngilizce çeviri |
| **Brief** | Videoda ne olduğunun yapılandırılmış kararı: TH seviyesi, ordu, sonuç, öne çıkan anlar, başlık adayları, kapak metni. Claude kareleri okuyarak yazar |
| **SEO** | CoC'a özel TR+EN anahtar kelime havuzu, 500 karakter sınırında etiketler, açıklamanın ilk 150 karakterine yerleşen kanca |
| **CTR** | 3 başlık adayı puanlanır (uzunluk, anahtar kelimenin konumu, merak kancası, sayı, güçlü kelime, spam sinyalleri) |
| **AEO** | Açıklamada "Sıkça Sorulan Sorular" — üretken arama motorlarının alıntılayabileceği net cevaplar |
| **GEO** | Yapılandırılmış İngilizce lokalizasyon + İngilizce altyazı |
| **Kapak** | ChatGPT (`gpt-image-1`) arka planı + 3 tipografi şablonu; en okunaklı olan seçilir, hepsi A/B için saklanır |
| **Kurgu** | Ses normalizasyonu (−14 LUFS), "ABONE OL" animasyonu, filigran, 10 sn bitiş kartı, altyazısı gömülü dikey Shorts |
| **Yayın** | Studio'da tam akış + bitiş ekranı + sabit yorum + doğrulama |

---

## Kurulum (sıfır bilgisayarda)

Depo **private**; yeni bilgisayarda once GitHub girisi gerekir
(`gh auth login`, ya da klonlarken kullanici adi + personal access token).

```bash
gh repo clone GhostFelina/HusCC        # ya da: git clone https://github.com/GhostFelina/HusCC.git
cd HusCC
python check.py           # kurulumdan ÖNCE: ne eksik? (hiçbir bağımlılık gerektirmez)
python bootstrap.py       # sanal ortam, bağımlılıklar, ffmpeg, Chrome + doğrulama
```

`bootstrap.py` iki şey daha yapar: **`huscc` komutunu PATH'e bağlar** (Windows'ta
`%LOCALAPPDATA%\Programs\HusCC\bin`, diğerlerinde `~/.local/bin`) ve sonunda
**otomatik olarak `huscc selftest` çalıştırır.** Çıktıda `MAKINE HAZIR` yazıyorsa
makine gerçekten hazırdır — tahmin değil, ölçüm.

Sonra tek seferlik giriş — **yeni bir terminal aç** (PATH yeni güncellendi):

```bash
huscc login          # gereken platformları sırayla açar
huscc login --check  # hiçbir şey açmadan durumu göster
```

Sihirbaz YouTube ve ChatGPT'yi sırayla açar; zaten girilmiş olanı atlar,
istemediğini Ctrl+C ile geçersin. Girişi sen yaparsın; oturumlar
`secrets/browser-profile/` içinde saklanır, bir daha sorulmaz.

### Komut nasıl çalıştırılır

Kurulumdan sonra her yerden `huscc <komut>` çalışır. PATH bağlanmadıysa:

| | Komut |
|---|---|
| Windows (PowerShell) | `.\huscc.cmd publish "video adı"` |
| Windows (tam yol) | `.venv\Scripts\huscc publish "video adı"` |
| macOS / Linux | `./huscc publish "video adı"` |

Kısayolu sonradan kurmak ya da eksik bir bileşeni (ffmpeg, Chrome, Playwright,
altyazı motoru) tamamlamak için: `huscc doctor --fix`

### Makine gerçekten hazır mı?

```bash
huscc selftest              # sentetik videoyla tüm boru hattı (~10 sn)
huscc selftest --browser    # tarayıcı açılışını da dener
```

Sentetik bir video üretir; analiz, brief, kapak (3 varyant), kurgu, outro, meta
veri ve yayın öncesi kontrollerin tamamını **gerçek dosyalarla** çalıştırır.
YouTube'a hiçbir şey gitmez, senin klasörlerine dokunulmaz — her şey geçici bir
dizinde olur ve silinir.

```
  SONUC: 21/21 kontrol gecti   (9.2 sn)
  ✓ MAKINE HAZIR.
```

### Görsel üretimi (opsiyonel)

`.env` dosyasına `OPENAI_API_KEY=sk-...` koyarsan kapak arka planı otomatik üretilir.
Koymazsan:

* `--image-source browser` → prompt panoya kopyalanır, varsayılan tarayıcıda ChatGPT
  açılır, ürettiğin görseli `work/<slug>/ai/` klasörüne bırakırsın
* `--image-source frame` → videodan seçilen kare (internet gerekmez)

Kapak yazısı her zaman yerel basılır; görsel modelleri Türkçe tipografide güvenilir değil.

---

## Kullanım

```bash
huscc list                           # CC klasöründeki videolar
huscc publish "video adı"            # baştan sona
huscc publish "son"                  # en yeni kayıt

# Adım adım
huscc prep    "video adı"            # analiz + kareler + altyazı
huscc brief   "video adı" --show     # brief'i gör / doğrula
huscc render  "video adı"            # kapak + meta veri + kurgu
huscc upload  "video adı" --dry-run  # ön kontroller + önizleme
huscc upload  "video adı"            # Studio'da yayınla

huscc login                          # Google girişi (bir kerelik)
huscc probe                          # seçicileri canlı Studio'da dene (yükleme yapmaz)
huscc update "video adı" --rebuild   # yayındaki videonun meta verisini tazele
huscc publish-all --limit 3          # birikmiş kayıtları sırayla yayınla
huscc init                           # kanal bilgilerini sor, yapılandırmayı yaz
huscc studio                         # Studio'yu HusCC tarayıcısında aç
huscc web                            # yerel panel (127.0.0.1:8765)
huscc status                         # yayın geçmişi
huscc doctor --browser               # oturumu da doğrulayarak kontrol
huscc doctor --fix                   # eksik bileşeni kur, komutu PATH'e bağla
```

### İlk kurulumdan sonra: `huscc probe`

Hiçbir şey yüklemeden Studio'yu gezer ve seçici haritasındaki her anahtarın tutup
tutmadığını tek tek raporlar:

```
  Studio ana sayfası
  + probe_studio_home            css=ytcp-navigation-drawer
  + create_button                css=ytcp-button#create-icon
  Yükleme penceresi
  + upload_dialog                css=ytcp-uploads-dialog
  + file_input                   css=input[type='file'] (gizli)
```

`TUTMADI` gören her satır, ilk gerçek yayında patlayacak demektir — önce onu düzelt.

### Çift yükleme koruması

Bir video daha önce yayınlandıysa `huscc upload` reddeder ve mevcut kaydı gösterir.
Meta veriyi değiştirmek istiyorsan `huscc update`, gerçekten ikinci kopya istiyorsan
`--force`.

İsim eşleştirme esnek: tam ad, ad parçası, `son`, hatta
`"kızılay saldırısı isimli videomu paylaş"` çalışır.

---

## Yayındaki videoyu güncelleme

Başlığı, açıklamayı, etiketleri veya kapağı sonradan değiştirmek için video yeniden
yüklenmez; Studio'daki düzenleme sayfası güncellenir:

```bash
huscc update "video adı"                        # kayıtlı meta veriyi tekrar yaz
huscc update "video adı" --rebuild              # brief'ten SEO'yu yeniden üret
huscc update "video adı" --fields title,thumbnail
```

---

## YouTube arayüzü değişirse

Kodda tek bir CSS seçici yok; hepsi [`config/selectors.yaml`](config/selectors.yaml) içinde.
Bir adım tıkanırsa süreç çökmez:

* `work/<slug>/browser/SORUN.md` — ne oldu, ne denendi, nasıl düzeltilir
* `work/<slug>/browser/HATA-<adım>.png` — o andaki ekran görüntüsü
* `work/<slug>/log.txt` — o işin tüm terminal çıktısı
* Tarayıcı penceresi **açık bırakılır**, elle tamamlayabilirsin

Düzeltmek için doğru seçiciyi ilgili anahtarın başına eklemen yeterli:

```yaml
publish_button:
  - css: "<yeni seçici>"
  - css: "ytcp-button#done-button"
  - role: "button|Yayınla|Publish"
```

Metin tabanlı seçiciler hem Türkçe hem İngilizce arayüzü kapsar.
Düzelttiğini `huscc probe` ile yükleme yapmadan doğrulayabilirsin.

---

## Yapılandırma

Her şey [`config/channel.yaml`](config/channel.yaml) içinde:

```yaml
upload:
  via: "browser"                    # browser | api
  privacy: "public"
  schedule: "auto"                  # bir sonraki prime-time slotu
  best_hours_local: [19, 20, 21, 22]
  end_screen: true                  # bitiş ekranını uygula
  pin_first_comment: true           # ilk yorumu at ve sabitle
  verify_after: true                # yayından sonra videoyu aç ve doğrula
thumbnail:
  source: "auto"                    # auto | api | browser | frame
browser:
  channel: "chrome"                 # chrome | msedge
  headless: false                   # pencere görünür olsun
  keep_open_on_error: true          # hata halinde açık bırak
```

---

## Yerel panel

`huscc web` → `http://127.0.0.1:8765`

Video listesi, tek tıkla tüm aşamalar, canlı log akışı, brief düzenleyici, kapak
varyantı seçimi, ChatGPT prompt'u + sürükle-bırak görsel yükleme, meta veri
önizlemesi, kare galerisi, tarayıcı adımlarının ekran görüntüleri.
Sunucu yalnızca `127.0.0.1` dinler.

---

## Tek nokta bağımlılığı yok

Kurulumun tökezleyebileceği her yerde yedek zincir var:

| Bileşen | Zincir |
|---|---|
| **ffmpeg** | PATH → bilinen klasörler → winget paketi → scoop/choco → pip ile gelen statik ikili |
| **ffprobe** | Varsa kullanılır; yoksa teknik bilgi `ffmpeg -i` çıktısından ayrıştırılır |
| **Tarayıcı** | Yapılandırılan kanal → Chrome → Edge → Playwright Chromium (gerekirse kendi indirir) |
| **Kapak fontu** | Anton (OFL) depoda gömülü — sistem fontu gerekmez, Türkçe kapsamı garanti |
| **Python** | Sanal ortam için 3.12 → 3.13 → 3.11 sırayla denenir (3.14'te bazı paketlerin tekerleği yok) |
| **Altyazı** | faster-whisper yoksa adım atlanır, yayın etkilenmez |

Windows'ta `python` komutu Microsoft Store kısayoluysa kurulum bunu fark eder ve
gerçek Python'un nasıl kurulacağını söyler.

---

## Sınırlar

* Kanalın normal yükleme sınırları geçerli (yeni kanallarda günde birkaç video).
* Google, tanımadığı cihazda ek doğrulama isteyebilir — giriş penceresi görünür
  olduğu için doğrulamayı sen yaparsın, sonra oturum kalıcı olur.
* İlk `faster-whisper` çalıştırmasında model indirilir (~500 MB, `small`).

---

## Geliştirme

```bash
python -m pytest tests -q        # 67 test
python -m compileall -q src/huscc
huscc selftest                   # uçtan uca, gerçek dosyalarla
```

Mimari ve Claude ile çalışma kuralları: [`CLAUDE.md`](CLAUDE.md)

---

Bu proje Supercell tarafından desteklenmemektedir.
[Supercell Fan Content Policy](https://supercell.com/fan-content-policy)
