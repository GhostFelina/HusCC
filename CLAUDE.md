# HusCC — Claude icin calisma talimati

Bu depo, Clash of Clans ekran kayitlarini **analiz edip YouTube'a yayinlayan** bir CLI
projesidir. Sen (Claude) bu boru hattinin "gozu"sun: videodan cikarilan kareleri
gercekten okuyup icerik kararlarini veren parcasin.

---

## 0. Kullanicinin soyleyecegi cumleler ve karsiligi

| Kullanici derse | Sen sunu yap |
|---|---|
| "HusCC reposunu bu PC'de calistir" | **Kurulum akisi** (asagida Bolum 1) |
| "**xx** isimli videomu paylas" | **Yayin akisi** (Bolum 2) — `xx` video adidir |
| "son videomu paylas" | Ayni akis, isim yerine `son` yaz |
| "paneli ac" / "localhost'ta ac" | `huscc web` (varsayilan tarayicida acilir) |
| "videolarimi listele" | `huscc list` |
| "durum" / "ne yayinlandi" | `huscc status` |

**Izin sorma.** Kullanici tarayici, yukleme ve dosya islemleri icin onayi bastan verdi.
Hata cikarsa dur, hatayi Turkce acikla, cozumu uygula, devam et.

---

## 1. Kurulum akisi (yeni bilgisayarda ilk kez)

```bash
# 1. Bagimliliklar
python bootstrap.py          # ya da: ./bootstrap.ps1  (Windows) / ./bootstrap.sh (mac, Linux)

# 2. Kontrol
huscc doctor
```

`doctor` ciktisinda eksik ne varsa sen tamamla:

* **ffmpeg yok** → `winget install --id Gyan.FFmpeg -e --accept-package-agreements`
  (mac: `brew install ffmpeg`, Linux: `sudo apt install -y ffmpeg`)
* **Pillow/numpy eksik** → `uv pip install --python .venv -e .`
* **faster-whisper yok** → `uv pip install --python .venv faster-whisper`
* **OAuth istemci dosyasi yok** → Kullaniciya `huscc doctor` ciktisindaki 6 adimi
  goster ve inen JSON'u `secrets/client_secret.json` olarak koymasini iste.
  Bu **tek seferlik** ve senin yapamayacagin tek adim (Google Cloud hesabi gerekiyor).
* **Yetki yok** → `huscc auth` (varsayilan tarayicida Google girisi acilir)

`secrets/` klasoru `.gitignore`'da. Icindeki hicbir seyi commit etme, ekrana basma.

---

## 2. Yayin akisi — "xx isimli videomu paylas"

Dort adim. Ikinci adim sana ait.

### Adim 1 — Analiz
```bash
huscc prep "xx"
```
Bu komut: videoyu bulur, teknik bilgiyi cikarir, sahne kesimlerini tarar,
14 analiz karesi uretir, sesi altyaziya cevirir ve
`work/<slug>/ANALIZ.md` + `work/<slug>/analysis_request.json` yazar.

### Adim 2 — Brief (SEN yaziyorsun)

1. `work/<slug>/ANALIZ.md` dosyasini oku.
2. `work/<slug>/frames/` icindeki kareleri **Read araci ile tek tek ac ve gercekten bak.**
   Tahmin yok: koy kasabasi seviyesi, kullanilan birlikler, yildiz sayisi, yuzde —
   hepsi ekrandaki arayuzde yazar.
3. `work/<slug>/brief.json` dosyasini yaz (sema `ANALIZ.md` icinde).

Brief yazarken uyulacak kurallar:

* **title_candidates**: 3 adet, her biri ≤70 karakter.
  Biri merak kancasi ("Bu Base Neden Yikilmiyor?"), biri net fayda ("TH16 Hydra Rehberi"),
  biri sonuc/sayi odakli ("%100 3 Yildiz — 12 Saniyede").
  Anahtar kelime (TH seviyesi + strateji adi) basligin **ilk 30 karakterinde** gecsin.
* **thumbnail_text**: en fazla 3 kelime, TAMAMI BUYUK. Telefonda okunacak.
  Baslikta yazani tekrar etme — kapak ile baslik birbirini tamamlasin.
* **hero_timestamp**: kapak icin en dramatik an. Menu, yukleme ekrani, kara kare secme.
* **highlights**: bolum (chapter) zaman damgalari olacak. En az 3 tane, aralarinda
  en az 10 saniye olsun, ilk 10 saniyede olmasin.
* **faq**: izleyicinin Google/YouTube'a yazacagi gercek sorular + 1-2 cumlelik net cevap.
  Bu blok uretken arama motorlari (AI Overviews, Perplexity) icin.
* **keywords**: 15-25 terim, Turkce + Ingilizce karisik.

Yazdiktan sonra dogrula:
```bash
huscc brief "xx" --show
```
Eksik varsa duzelt, tekrar calistir. Cikti "Brief gecerli" demeden ilerleme.

> Acele bir ise ihtiyac varsa `huscc prep "xx" --brain heuristic` dosya adindan
> kural tabanli brief uretir; ama kaliteli sonuc icin kareleri sen oku.

### Adim 2.5 — Kapak gorseli (ChatGPT)

Kapak arka plani **ChatGPT gorseli** ile uretilir. Sirasiyla:

1. `OPENAI_API_KEY` varsa (`.env`) → `gpt-image-1` otomatik cagrilir. Hicbir sey yapma.
2. Anahtar yoksa → `huscc render "xx" --image-source browser` calistir.
   Prompt panoya kopyalanir, **varsayilan tarayicida** ChatGPT acilir, kullanici
   goruntuyu indirip `work/<slug>/ai/` klasorune birakir, CLI otomatik alir.
   Prompt dosyasi: `work/<slug>/ai/thumb_prompt.txt`
3. Ikisi de yoksa → `--image-source frame` ile videodan kare kullanilir.

**Tarayici otomasyonu kullanma** (chrome-devtools MCP yasak). ChatGPT varsayilan
tarayicida acilir, kullanici prompt'u yapistirir. Panelde de ayni akis var:
Kapak sekmesi → "ChatGPT'yi ac + prompt'u kopyala" → gorseli surukle-birak.

Kapak yazisini gorsel modeline yazdirma; prompt zaten "no text" diyor.
Turkce tipografi (ı, ş, ğ) PIL ile yerel basiliyor.

### Adim 3 — Kurgu + kapak
```bash
huscc render "xx"
```
Uretilenler: 3 kapak varyanti (en okunakli olani secilir), ses normalizasyonu,
"ABONE OL" bindirmesi, filigran, 10 sn bitis karti, dikey Shorts, tam meta veri.

Kapak varyantlarini `work/<slug>/thumbs/` icinden **Read ile ac ve bak**.
Secilen kapak zayifsa `thumbnail_text` / `hero_timestamp` degerini brief'te degistirip
`huscc render` komutunu tekrar calistir.

### Adim 4 — Yayin
```bash
huscc upload "xx" --dry-run    # once onizle
huscc upload "xx"              # sonra gercekten yukle
```
Yukleme sonrasi otomatik yapilanlar: kapak, TR + EN altyazi, Ingilizce lokalizasyon,
oynatma listesi, ilk yorum.

Tek elle is kaliyor — kullaniciya bunu soyle:
**Studio > bitis ekrani/kart ekleme ve ilk yorumu sabitleme** (YouTube API bunlari desteklemiyor).

### Kisayol
```bash
huscc publish "xx"
```
Adim 1'i calistirir, brief yoksa durur (sen yazarsin), sonra `huscc render` + `huscc upload`.

---

## 3. Mimari — nerede ne var

```
src/huscc/
  cli.py        komutlar (doctor, auth, list, prep, brief, render, upload, publish, web, status)
  config.py     config/channel.yaml okuyucu
  discover.py   CC klasorunde bulanik isim eslestirme ("son", parca isim, tam ad)
  media.py      ffmpeg/ffprobe: teknik analiz, sahne tespiti, kare cikarma, ses
  brief.py      Brief veri yapisi + heuristik/API uretimi + ANALIZ.md yazimi
  keywords.py   CoC anahtar kelime hazinesi, icerik turleri, baslik kaliplari
  seo.py        Brief -> baslik/aciklama/etiket/bolum/lokalizasyon + CTR puanlama
  thumbnail.py  kare puanlama, 3 kapak sablonu, okunabilirlik puani, outro/overlay kartlari
  subtitles.py  faster-whisper ile SRT (TR + EN ceviri), Shorts'a gomme
  editor.py     bindirmeler, ses normalizasyonu, outro birlestirme, 9:16 Shorts
  youtube.py    OAuth + yukleme + kapak + altyazi + liste + yorum (+ Turkce hata mesajlari)
  pipeline.py   prep -> render -> upload orkestrasyonu, durum takibi
  server.py     yerel kontrol paneli (stdlib HTTP, SSE log akisi)
  web_ui.py     panelin HTML/CSS/JS'i
```

Calisma dosyalari `work/<slug>/`, yayina hazir ciktilar `out/`, gizli anahtarlar `secrets/`.
Ucu de `.gitignore` icinde.

---

## 4. Kod degisikligi yaparken

* Turkce kullanici mesajlari, ASCII kod tanimlayicilari. Mevcut dosyalarin uslubuna uy.
* Kullaniciya gosterilecek hatalari `HusccError` ile firlat — CLI bunlari
  yigin izi olmadan, Turkce basar.
* YouTube API sinirlari: baslik ≤100, aciklama ≤5000, etiketler toplam ≤500 karakter,
  kapak ≤2 MB. `seo.py` bunlari zaten uyguluyor; yeni alan eklerken koru.
* Kota: bir yukleme ~1600 birim, gunluk varsayilan 10.000 → gunde ~6 video.
  Kullanici "kota doldu" hatasi alirsa bunu acikla.
* Degisiklikten sonra en az `huscc doctor` ve mumkunse
  `huscc prep ... --brain heuristic` + `huscc render` + `huscc upload --dry-run` ile dene.

## 5. Yapma

* `secrets/` icerigini okuma, yazdirma, commit etme.
* Kullanicinin onayi olmadan `--dry-run` olmadan toplu yukleme yapma (tek video hariç:
  "paylas" komutu zaten yukleme talebidir).
* Tarayici otomasyonu (chrome-devtools MCP) kullanma — kullanici yasakladi.
  Google girisi `huscc auth` ile **varsayilan** tarayicida acilir.
* `work/` ve `out/` icindeki buyuk medya dosyalarini git'e ekleme.
