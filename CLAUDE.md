# HusCC — Claude icin calisma talimati

Bu depo, Clash of Clans ekran kayitlarini **analiz edip YouTube'a yayinlayan** bir CLI'dir.

**API yok.** Yayin, gercek Chrome uzerinde YouTube Studio surulerek yapilir.
Google Cloud projesi, OAuth istemcisi, API anahtari gerekmez. Kullanici bir kez
Google girisi yapar; oturum `secrets/browser-profile/` icinde kalir.

Sen (Claude) iki isi yapiyorsun:
1. **Goz**: videodan cikan kareleri okuyup icerik kararlarini veriyorsun (brief).
2. **Tamirci**: YouTube arayuzu degistiginde seciciyi guncelliyorsun.

---

## 0. Kullanicinin soyleyecegi cumleler ve karsiligi

| Kullanici derse | Sen sunu yap |
|---|---|
| "HusCC reposunu bu PC'de calistir" | **Bolum 1** — kurulum |
| "**xx** isimli videomu paylas" | **Bolum 2** — yayin akisi |
| "son videomu paylas" | Ayni akis, isim yerine `son` |
| "paneli ac" / "localhost" | `huscc web` |
| "videolarimi listele" | `huscc list` |
| "durum" / "ne yayinlandi" | `huscc status` |
| "Studio'yu ac" | `huscc studio` |
| "**xx** videosunun basligini/aciklamasini degistir" | `huscc update "xx" --rebuild` |
| "hepsini paylas" | `huscc publish-all` |
| "kanal ayarlarini yapalim" | `huscc init` |

**Izin sorma.** Kullanici tarayici, yukleme ve dosya islemleri icin onayi bastan verdi.
Hata cikarsa dur, Turkce acikla, coz, devam et.

---

## 1. Kurulum akisi (yeni bilgisayarda ilk kez)

Sirayla, atlamadan:

Depo private; once `gh auth login` (ya da token ile klon).

```bash
gh repo clone GhostFelina/HusCC
cd HusCC
python check.py           # 1) kurulumdan ONCE ne eksik (bagimlilik gerektirmez)
python bootstrap.py       # 2) her seyi kurar ve sonunda selftest calistirir
```

`bootstrap.py` ciktisinin sonunda **`MAKINE HAZIR`** gormeden ilerleme.
Gormediysen orada yazan eksigi coz ve `huscc selftest` ile tekrar dogrula.

```bash
huscc login               # 3) giris sihirbazi: YouTube + ChatGPT (kullanici yapar)
huscc probe               # 4) Studio secicilerini dogrula (yukleme yapmaz)
```

`huscc login --check` hicbir sey acmadan hangi platformda oturum oldugunu yazar;
`--only youtube` ile tek platform. Giris eksikse ilk yayin patlar, once bunu bak.

### Komutu nasil calistiracaksin

`bootstrap.py` sonunda `huscc` komutunu PATH'e baglar (Windows'ta
`%LOCALAPPDATA%/Programs/HusCC/bin`, mac/Linux'ta `~/.local/bin`) - ama PATH
yalnizca **yeni acilan** terminalde gecerlidir. Ayni oturumda calisiyorsan tam
yolu kullan:

* Windows : `.venv\Scripts\huscc <komut>`
* mac/Linux: `.venv/bin/huscc <komut>`

Depo kokundeki `huscc.cmd` (Windows) ve `./huscc` (mac/Linux) sarmalayicilari da
ayni isi yapar. Kisayol hic yazilmadiysa: `huscc doctor --fix`.

`bootstrap.py` her seyi kurar. Yine de eksik kalirsa once `huscc doctor --fix`
dene (eksik bileseni kurar, kisayolu yazar); elle cozmek gerekirse:

* **Playwright yok** → `uv pip install --python .venv playwright`
* **Chrome yok** → `winget install --id Google.Chrome -e`
  (mac: `brew install --cask google-chrome`)
  Edge kullanilacaksa `config/channel.yaml > browser.channel: msedge`
* **ffmpeg yok** → `winget install --id Gyan.FFmpeg -e --accept-package-agreements`
* **faster-whisper yok** → `uv pip install --python .venv faster-whisper`
  (zorunlu degil; yoksa altyazi adimi atlanir, yayin etkilenmez)
* **Python 3.14** → sanal ortam 3.12 ile kurulur; bootstrap bunu kendi halleder

Kurulumun tokezleyebilecegi her yerde yedek zincir var, bunlari bilerek hareket et:
ffmpeg (PATH → winget → scoop/choco → pip'in statik ikilisi), ffprobe (yoksa
`ffmpeg -i` ayristirilir), tarayici (Chrome → Edge → Playwright Chromium),
kapak fontu (Anton depoda gomulu). Yani "bulunamadi" hatasi gorursen once
`huscc selftest` calistir; gercekten eksik olani o soyler.

`huscc login` gorunur bir Chrome penceresi acar. Giris **kullanicinin kendisi**
tarafindan yapilir; sen sifre girmeye calisma, beklemeyi komut zaten yonetiyor.
Giris bitince `secrets/browser-profile/huscc-session.json` yazilir ve
`huscc doctor` "Google oturumu kayitli" der.

### Girisden hemen sonra: sonda calistir

```bash
huscc probe
```

Bu komut **hicbir sey yuklemeden** Studio'yu gezer ve secici haritasindaki her
anahtarin tutup tutmadigini tek tek raporlar. Ciktida `TUTMADI` goren her anahtar,
ilk gercek yayinda patlayacak demektir — yayina girmeden once duzelt (Bolum 3).

Kanalda yayinlanmis video varsa `huscc probe` duzenleme sayfasini da dener;
yoksa `--video <kimlik>` ile bir video verebilirsin. Yeni kanalda yayinlanmis
video yoksa sonda yalnizca ana sayfa ve yukleme penceresini kontrol eder,
bu da normaldir.

### Her sey calisiyor mu?

```bash
huscc selftest            # sentetik videoyla tum boru hattini calistirir (~10 sn)
huscc selftest --browser  # tarayici acilisini da dener
```

Bu komut YouTube'a dokunmaz, kullanicinin klasorlerine dokunmaz; gecici bir
dizinde sentetik video uretip analiz-brief-kapak-kurgu-meta veri-preflight
zincirinin tamamini gercek dosyalarla kosar. Bir sey bozduysan once bunu calistir.

`secrets/` klasoru `.gitignore`'da. Icine bakma, yazdirma, commit etme.

---

## 2. Yayin akisi — "xx isimli videomu paylas"

```bash
huscc publish "xx"
```

Bu komut adim adim su ucunu calistirir. `claude-code` beyninde ikinci adimda
durur, cunku o adim sana ait.

### Adim 1 — Analiz
```bash
huscc prep "xx"
```
Teknik veri, sahne kesimleri, hareket profili, 14 analiz karesi, TR altyazi +
EN ceviri. Ciktilar `work/<slug>/`.

### Adim 2 — Brief (SEN yaziyorsun)

1. `work/<slug>/ANALIZ.md` dosyasini oku.
2. `work/<slug>/frames/` icindeki kareleri **Read araci ile tek tek ac ve gercekten bak.**
   Koy kasabasi seviyesi, kullanilan birlikler, yildiz sayisi, yuzde — hepsi
   ekrandaki arayuzde yazar. Tahmin etme, gordugunu yaz.
3. `work/<slug>/brief.json` dosyasini yaz (sema `ANALIZ.md` icinde).

Kurallar:

* **title_candidates**: 3 adet, her biri ≤70 karakter. Biri merak kancasi,
  biri net fayda, biri sonuc/sayi odakli. Anahtar kelime (TH seviyesi +
  strateji adi) basligin **ilk 30 karakterinde** gecsin.
* **thumbnail_text**: en fazla 3 kelime, TAMAMI BUYUK. Baslikta yazani tekrar etme.
* **hero_timestamp**: kapak icin en dramatik an. Menu / yukleme ekrani / kara kare secme.
* **highlights**: bolum zaman damgalari. En az 3, aralarinda ≥10 sn, ilk 10 sn'de degil.
* **faq**: izleyicinin arama kutusuna yazacagi gercek sorular + 1-2 cumlelik net cevap.
* **keywords**: 15-25 terim, TR + EN karisik.

Dogrula:
```bash
huscc brief "xx" --show
```
"Brief gecerli" demeden ilerleme.

> Acele is icin `huscc prep "xx" --brain heuristic` dosya adindan kural tabanli
> brief uretir. Kaliteli sonuc icin kareleri sen oku.

### Adim 2.5 — Kapak gorseli (ChatGPT)

1. `OPENAI_API_KEY` varsa (`.env`) → `gpt-image-1` otomatik cagrilir, sen bir sey yapma.
2. Anahtar yoksa → `huscc render "xx" --image-source browser`
   Prompt panoya kopyalanir, **varsayilan tarayicida** ChatGPT acilir, kullanici
   goruntuyu indirip `work/<slug>/ai/` klasorune birakir, CLI otomatik alir.
   Prompt dosyasi: `work/<slug>/ai/thumb_prompt.txt`
3. Ikisi de yoksa → `--image-source frame` (videodan kare).

Kapak yazisini gorsel modeline yazdirma; prompt zaten "no text" diyor.
Turkce tipografi (ı, ş, ğ) PIL ile yerel basiliyor.

### Adim 3 — Kurgu + kapak
```bash
huscc render "xx"
```
3 kapak varyanti, ses normalizasyonu, "ABONE OL" bindirmesi, filigran,
bitis karti, dikey Shorts, tam meta veri.

Kapak varyantlarini `work/<slug>/thumbs/` icinden **Read ile ac ve bak.**
Zayifsa brief'te `thumbnail_text` / `hero_timestamp` degistirip tekrar calistir.

### Adim 4 — Yayin (tarayici)
```bash
huscc upload "xx" --dry-run    # onizleme + on kontroller
huscc upload "xx"              # gercek yayin
```

`upload` gorunur bir Chrome penceresi acar ve Studio'da sirasiyla:
yukleme penceresi → dosya → baslik → aciklama → kapak → oynatma listesi →
hedef kitle → etiketler → kategori → yuklemenin bitmesi → gorunurluk/planlama →
yayinla. Ardindan yayin sonrasi: altyazilar, **bitis ekrani**, **sabit ilk yorum**,
istege bagli kucuk resim A/B testi, ve videoyu acip dogrulama.

Her adimin ekran goruntusu `work/<slug>/browser/` altina dusuyor.

---

## 3. Bir tarayici adimi tikandiginda (onemli)

YouTube arayuzunu degistirdiginde boru hatti **coker gibi gorunur ama cokmez**:
adim raporlanir, tarayici penceresi acik birakilir.

Su dosyalar olusur:
* `work/<slug>/log.txt` — o isin tum terminal ciktisi (her komut buraya da yazar)
* `work/<slug>/browser/SORUN.md` — ne oldu, ne denendi, nasil duzeltilir
* `work/<slug>/browser/SORUN_<adim>.json` — URL, denenen seciciler, HTML parcasi
* `work/<slug>/browser/HATA-<adim>.png` — ekran goruntusu

Yapman gereken:

1. **Ekran goruntusunu Read ile ac ve bak.** Element gercekten ekranda mi?
2. Ekrandaysa `config/selectors.yaml` icindeki ilgili anahtara dogru seciciyi
   **basa** ekle:

```yaml
publish_button:
  - css: "<yeni secici>"          # yeni, once denenir
  - css: "ytcp-button#done-button"
  - role: "button|Yayınla|Publish"
```

3. Duzelttigini `huscc probe` ile dogrula (yukleme yapmaz).
4. Komutu tekrar calistir: `huscc upload "xx"`. Video zaten yuklenmis ve kimligi
   kaydedilmisse `huscc update "xx"` ile eksik alanlari tamamla — bu, ikinci bir
   kopya olusturmaz.

Secici yazarken:
* Once `css`, sonra `role`, en son `text` yaz. `css` en hizli ve kararli olan.
* `role` stratejisinde ad kismini **TR|EN** birlikte yaz: `"button|Yayınla|Publish"`.
* Arayuz dili kullanicinin Google hesabina gore degisir; tek dile guvenme.
* Kodun icine asla CSS secici yazma. Hepsi `config/selectors.yaml` icinde.

Adim hic tutmuyorsa ve is acele ise: tarayici penceresi zaten acik, kullaniciya
"su alani elle doldur" de, sonra kalan adimlari calistir.

---

## 4. Mimari — nerede ne var

```
src/huscc/
  cli.py             komutlar: doctor login studio list prep brief render upload publish web status clean
  config.py          config/channel.yaml + .env okuyucu
  discover.py        CC klasorunde bulanik isim eslestirme ("son", parca isim, tam ad)
  media.py           ffmpeg/ffprobe: teknik analiz, sahne tespiti, kare cikarma, ses
  brief.py           Brief veri yapisi + heuristik/API uretimi + ANALIZ.md yazimi
  keywords.py        CoC anahtar kelime hazinesi, icerik turleri, baslik kaliplari
  seo.py             Brief -> baslik/aciklama/etiket/bolum/lokalizasyon + CTR puanlama
  imagegen.py        ChatGPT gorsel uretimi (API veya tarayici devri) + prompt kurgusu
  thumbnail.py       kare puanlama, 3 kapak sablonu, okunabilirlik puani, outro kartlari
  subtitles.py       faster-whisper ile SRT (TR + EN ceviri), Shorts'a gomme
  editor.py          bindirmeler, ses normalizasyonu, outro birlestirme, 9:16 Shorts
  browser.py         Playwright + gercek Chrome, kalici oturum, secici motoru, hata raporu
  studio.py          Studio akisi (yukleme, guncelleme, bitis ekrani, sabit yorum, A/B, sonda)
  publish_browser.py on kontroller + oturum + yayin sonrasi orkestrasyonu + probe
  youtube.py         (opsiyonel) Data API yolu - sadece `--via api` icin
  pipeline.py        prep -> render -> upload orkestrasyonu, durum takibi
  server.py          yerel kontrol paneli (stdlib HTTP, SSE log akisi)
  web_ui.py          panelin HTML/CSS/JS'i
  selftest.py        sentetik videoyla uctan uca dogrulama

check.py             kurulum oncesi stdlib kontrolu (bagimlilik gerektirmez)
bootstrap.py         kurulum + sonunda otomatik dogrulama

config/
  channel.yaml       kanal kimligi, yayin tercihleri, kapak, kurgu, tarayici ayarlari
  selectors.yaml     YouTube Studio element haritasi (TEK secici kaynagi)
```

`work/<slug>/` ara dosyalar · `out/` yayina hazir ciktilar · `secrets/` oturum.
Ucu de `.gitignore` icinde.

---

## 5. Kod degisikligi yaparken

* Turkce kullanici mesajlari, ASCII kod tanimlayicilari. Mevcut uslubu koru.
* Kullanici hatalarini `HusccError` ile firlat — CLI yigin izi olmadan basar.
* Tarayici adimlarinda `required=False` kullanmayi ihmal etme: yayini bozmamasi
  gereken her sey (kapak, oynatma listesi, etiket) atlanabilir olmali.
  Zorunlu olanlar yalnizca: dosya secimi, baslik, hedef kitle, gorunurluk, yayinla.
* YouTube sinirlari: baslik ≤100, aciklama ≤5000, etiketler toplam ≤500, kapak ≤2 MB.
  `publish_browser.preflight` bunlari yayin oncesi denetliyor; yeni alan eklerken koru.
* Degisiklikten sonra sirayla: `python -m pytest tests -q`, `huscc selftest`,
  ve tarayici tarafina dokunduysan `huscc probe`.

## 6. Yapma

* `secrets/` icerigini okuma, yazdirma, commit etme.
* **chrome-devtools MCP kullanma.** Tarayici isi `huscc` uzerinden yapilir;
  kullanicinin oturumu HusCC profilinde, otomasyon profilinde degil.
* Kullanicinin sifresini isteme, yazmaya calisma. Girisi kullanici yapar.
* `work/` ve `out/` icindeki buyuk medya dosyalarini git'e ekleme.
* Kod icine CSS secici gomme.
