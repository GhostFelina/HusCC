# HusCC

Masaüstündeki **CC** klasörüne attığın Clash of Clans ekran kaydını tek komutla
YouTube'a yayınlayan otomasyon. Videoyu analiz eder, kapağı üretir, altyazıyı
çıkarır, SEO/GEO/AEO/CTR açısından paketler, kurgular ve yükler.

```bash
huscc publish "th16 root rider savaşı"
```

Ya da tarayıcıdan:

```bash
huscc web        # http://127.0.0.1:8765
```

---

## Ne yapıyor

| Aşama | İçerik |
|---|---|
| **Analiz** | Teknik bilgi (süre, çözünürlük, ses), sahne kesimi tespiti, hareket profili, 14 anahtar kare, `faster-whisper` ile Türkçe altyazı + İngilizce çeviri |
| **Brief** | Videoda ne olduğunun yapılandırılmış kararı: TH seviyesi, kullanılan ordu, sonuç, öne çıkan anlar, başlık adayları, kapak metni. Claude kareleri okuyarak yazar; API veya kural tabanlı üretim de var |
| **SEO** | Anahtar kelime havuzu (CoC'a özel Türkçe + İngilizce), etiketler (500 karakter sınırı içinde), açıklamanın ilk 150 karakterine yerleşen kanca |
| **CTR** | 3 başlık adayı puanlanır (uzunluk, anahtar kelimenin konumu, merak kancası, sayı, güçlü kelime, spam sinyalleri) ve en iyisi seçilir |
| **AEO** | Açıklamaya "Sıkça Sorulan Sorular" bloğu — üretken arama motorlarının doğrudan alıntılayabileceği net cevaplar |
| **GEO** | Yapılandırılmış İngilizce başlık/açıklama lokalizasyonu + İngilizce altyazı |
| **Kapak** | ChatGPT (`gpt-image-1`) ile üretilen arka plan + 3 farklı tipografi şablonu; en okunaklı olan otomatik seçilir, hepsi A/B için saklanır |
| **Kurgu** | Ses normalizasyonu (-14 LUFS), "ABONE OL" animasyonu, kanal filigranı, 10 sn bitiş kartı, dikey Shorts (yakılmış altyazıyla) |
| **Yayın** | Yükleme, kapak, TR + EN altyazı, lokalizasyon, oynatma listesi (yoksa oluşturur), ilk yorum, planlı yayın saati |

---

## Kurulum

```bash
git clone https://github.com/<kullanıcı>/HusCC.git
cd HusCC
python bootstrap.py
```

`bootstrap.py`: sanal ortamı kurar, bağımlılıkları yükler, ffmpeg'i kurar,
`~/Desktop/CC` klasörünü açar.

Sonra:

```bash
.venv/Scripts/huscc doctor      # Windows
.venv/bin/huscc doctor          # macOS / Linux
```

### YouTube yetkilendirmesi (tek seferlik)

`huscc doctor` eksikleri sayar. Tek elle yapılacak iş Google OAuth istemcisi:

1. [console.cloud.google.com](https://console.cloud.google.com/projectcreate) → yeni proje
2. **YouTube Data API v3** → ENABLE
3. **OAuth consent screen** → External → test kullanıcılarına kanal sahibi hesabı ekle
4. **Credentials → OAuth client ID → Desktop app** → JSON indir
5. Dosyayı `secrets/client_secret.json` olarak koy
6. `huscc auth`

`secrets/` klasörü `.gitignore` içinde; hiçbir anahtar depoya girmez.

### Görsel üretimi (opsiyonel ama önerilen)

`.env` dosyasına:

```
OPENAI_API_KEY=sk-...
```

Anahtar varsa kapak arka planı ChatGPT ile üretilir. Anahtar yoksa:

* `huscc render "video" --image-source browser` → prompt panoya kopyalanır,
  **varsayılan tarayıcıda** ChatGPT açılır, ürettiğin görseli `work/<slug>/ai/`
  klasörüne bırakırsın, CLI onu alır.
* `--image-source frame` → videodan seçilen kare kullanılır (internet gerekmez).

Kapak yazısı her zaman yerel olarak basılır; görsel modelleri Türkçe tipografide
(ı, ş, ğ) güvenilir değil.

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
huscc upload  "video adı" --dry-run  # yüklemeden önizle
huscc upload  "video adı"            # yayınla

huscc web                            # yerel panel
huscc status                         # yayın geçmişi
huscc clean "video adı"              # ara dosyaları sil
```

İsim eşleştirme esnek: tam ad, ad parçası, `son`, hatta
`"kızılay saldırısı isimli videomu paylaş"` çalışır.

### Yerel panel

`huscc web` → `http://127.0.0.1:8765`

Video listesi, tek tıkla tüm aşamalar, canlı log akışı, brief düzenleyici,
kapak varyantı seçimi, ChatGPT prompt'u + sürükle-bırak görsel yükleme,
meta veri önizlemesi, kare galerisi. Sunucu yalnızca `127.0.0.1` dinler.

---

## Yapılandırma

Her şey [`config/channel.yaml`](config/channel.yaml) içinde: kanal kimliği,
gizlilik, yayın saati, etiket sınırları, kapak paleti, kurgu tercihleri,
altyazı modeli, klasör yolları.

Öne çıkanlar:

```yaml
upload:
  privacy: "public"
  schedule: "auto"                  # bir sonraki uygun prime-time slotu
  best_hours_local: [19, 20, 21, 22]
thumbnail:
  source: "auto"                    # auto | api | browser | frame
  variants: 3
edit:
  subscribe_at: ["8%", "45%", "80%"]
  shorts: true
```

---

## Sınırlar

* **Kota**: bir yükleme ~1600 birim, günlük varsayılan 10.000 → günde ~6 video.
* **Bitiş ekranı ve kart**: YouTube API desteklemiyor. Video, bitiş kartıyla
  birlikte yükleniyor; öğeleri Studio'dan eklemen gerekiyor.
* **Yorum sabitleme**: API desteklemiyor; ilk yorum atılıyor, sabitlemeyi
  Studio'dan yapıyorsun.
* İlk `faster-whisper` çalıştırmasında model indirilir (~500 MB, `small`).

---

## Geliştirme

```bash
python -m pytest tests -q
python -m compileall -q src/huscc
```

Mimari ve Claude ile çalışma kuralları: [`CLAUDE.md`](CLAUDE.md)

---

Bu proje Supercell tarafından desteklenmemektedir.
[Supercell Fan Content Policy](https://supercell.com/fan-content-policy)
