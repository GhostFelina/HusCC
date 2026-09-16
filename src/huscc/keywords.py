"""Clash of Clans icin Turkce + global anahtar kelime hazinesi ve CTR kaliplari.

Bu dosya kanalin "arama bilgisi"dir:
  * SEO  -> YouTube/Google aramasinda eslesecek terimler
  * GEO  -> uretken arama motorlarinin (AI Overviews, Perplexity) alintilayacagi
            net, yapilandirilmis bilgi kaliplari
  * AEO  -> "nasil yapilir / nedir" sorularina dogrudan cevap kaliplari
  * CTR  -> tiklanma oranini yukselten baslik ve kapak kaliplari
"""
from __future__ import annotations

import re

from .util import tr_fold

# --------------------------------------------------------------- icerik turu
# Anahtar: icerik turu kodu, deger: tespit icin aranan ipuclari
CONTENT_TYPES: dict[str, dict] = {
    "war_attack": {
        "label": "Klan Savasi Saldirisi",
        "hints": ["savas", "war", "cw", "klan savasi", "3 yildiz", "3 star", "saldiri"],
        "title_formulas": [
            "{th} {strategy} ile 3 YILDIZ | {context}",
            "{strategy} {th} Saldirisi - {hook}",
            "Bu {strategy} Kombinasyonu {th} Basesini Yikiyor",
        ],
        "keywords": [
            "klan savasi saldirisi", "3 yildiz saldirisi", "cw saldiri",
            "clan war attack", "war attack strategy",
        ],
    },
    "strategy_guide": {
        "label": "Saldiri Stratejisi Rehberi",
        "hints": ["rehber", "guide", "nasil", "taktik", "strateji", "anlatim", "ogren"],
        "title_formulas": [
            "{th} {strategy} Rehberi | Adim Adim 3 Yildiz",
            "{strategy} Nasil Yapilir? {th} Icin Tam Anlatim",
            "Yeni Baslayanlar Icin {strategy} - {th} Rehberi",
        ],
        "keywords": [
            "coc rehber", "saldiri taktigi", "nasil 3 yildiz yapilir",
            "attack guide", "strategy guide", "coc taktik",
        ],
    },
    "base_review": {
        "label": "Base Incelemesi",
        "hints": ["base", "koy", "duzen", "layout", "savunma", "anti"],
        "title_formulas": [
            "{th} EN IYI Base Duzeni | Anti 3 Yildiz",
            "Bu {th} Basesi Neden Hic Yikilmiyor?",
            "{th} Savunma Duzeni + Link | {context}",
        ],
        "keywords": [
            "base duzeni", "th base", "anti 3 star base", "savunma duzeni",
            "base layout", "coc base link",
        ],
    },
    "farming": {
        "label": "Kaynak Toplama",
        "hints": ["farm", "kaynak", "loot", "iksir", "altin", "elixir", "gold"],
        "title_formulas": [
            "{th} Icin EN HIZLI Kaynak Toplama Yontemi",
            "Gunde {number} Milyon Loot | {th} Farming",
            "Bu Yontemle Kaynak Sorunu Bitiyor - {th}",
        ],
        "keywords": [
            "kaynak toplama", "farming stratejisi", "loot toplama",
            "coc farming", "hizli kaynak",
        ],
    },
    "upgrade": {
        "label": "Gelisim / Yukseltme",
        "hints": ["upgrade", "yukselt", "gelisim", "max", "th gecis", "rush"],
        "title_formulas": [
            "{th} Gecisinde Once Neyi Yukseltmelisin?",
            "{th} Gelisim Rehberi | Dogru Sira",
            "Bu Sirayla Yukseltirsen {th} Hizli Biter",
        ],
        "keywords": [
            "yukseltme sirasi", "gelisim rehberi", "th gecisi",
            "upgrade priority", "coc gelisim",
        ],
    },
    "event": {
        "label": "Etkinlik / Guncelleme",
        "hints": ["guncelleme", "update", "etkinlik", "event", "yeni", "sezon"],
        "title_formulas": [
            "Yeni Guncelleme: {context} | Her Sey Degisti",
            "{context} Etkinligi - Kacirilmamasi Gerekenler",
            "Bu Guncelleme {th} Oyuncularini Nasil Etkiliyor?",
        ],
        "keywords": [
            "coc guncelleme", "yeni guncelleme", "clash of clans update",
            "etkinlik", "sezon odulleri",
        ],
    },
    "legend": {
        "label": "Efsane Lig",
        "hints": ["legend", "efsane", "lig", "league", "trophy", "kupa", "push"],
        "title_formulas": [
            "Efsane Ligde {number} Kupa | {strategy}",
            "Kupa Pushlama Rehberi - {th}",
            "Efsane Lig Saldirilari | {context}",
        ],
        "keywords": [
            "efsane lig", "legend league", "kupa pushlama", "trophy push",
            "legend league attacks",
        ],
    },
    "builder": {
        "label": "Yapici Ussu",
        "hints": ["builder", "yapici", "bh", "gece", "usse"],
        "title_formulas": [
            "Yapici Ussu {bh} - {strategy} ile 3 Yildiz",
            "BH{bh} Saldiri Taktigi | {context}",
            "Yapici Ussunde Hizli Ilerleme Rehberi",
        ],
        "keywords": [
            "yapici ussu", "builder hall", "bh saldiri", "builder base attack",
        ],
    },
    "funny": {
        "label": "Eglence / Klip",
        "hints": ["komik", "fail", "troll", "sans", "klip", "an", "moment"],
        "title_formulas": [
            "Bu Saldiriyi Gorunce Inanamayacaksin",
            "{context} | Clash of Clans Anlari",
            "Son Saniyede Ne Oldu Boyle?",
        ],
        "keywords": [
            "coc komik anlar", "clash of clans fail", "coc klip",
            "funny moments", "coc anlar",
        ],
    },
    "general": {
        "label": "Genel Oynanis",
        "hints": [],
        "title_formulas": [
            "{th} Oynanis | {context}",
            "Clash of Clans - {context}",
            "{context} | {th} Gunlugu",
        ],
        "keywords": ["clash of clans", "coc", "oynanis", "gameplay"],
    },
}

# --------------------------------------------------------------- temel havuz
CORE_TAGS_TR = [
    "clash of clans", "clash of clans turkce", "coc", "coc turkce",
    "clash of clans taktik", "clash of clans rehber", "coc saldiri",
    "clash of clans oynanis", "coc klan savasi", "clash of clans turkiye",
]

CORE_TAGS_GLOBAL = [
    "clash of clans", "coc", "clash of clans attack", "coc strategy",
    "clash of clans gameplay", "supercell", "clash",
]

# Sik kullanilan birlik / strateji isimleri (baslikta gecerse tag'e eklenir)
STRATEGIES = {
    "hydra": ["hydra", "hidra"],
    "root rider": ["root rider", "kok binici", "rootrider"],
    "super archer": ["super archer", "super okcu", "blimp"],
    "electro titan": ["electro titan", "elektro titan", "e-titan"],
    "lalo": ["lalo", "lavaloon", "lava loon", "balon"],
    "queen charge": ["queen charge", "qc", "kralice"],
    "hog rider": ["hog", "domuz", "hog rider"],
    "dragon": ["dragon", "ejderha", "dragon spam"],
    "electro dragon": ["edrag", "electro dragon", "elektro ejderha"],
    "yeti smash": ["yeti", "yeti smash"],
    "witch slap": ["witch", "cadi", "witch slap"],
    "miner": ["miner", "madenci"],
    "valkyrie": ["valkyrie", "valkiri", "valk"],
    "sui lalo": ["sui lalo", "suicide lalo"],
    "zap dragon": ["zap dragon", "zap edrag", "zapdrag"],
    "pekka smash": ["pekka", "pekka smash", "pekkabobat"],
    "golem": ["golem", "gowipe", "govaho"],
    "furnace": ["furnace", "firin"],
}

# CTR yukselten kelimeler (baslikta ve kapakta)
POWER_WORDS_TR = [
    "SONUNDA", "INANILMAZ", "EN IYI", "YENI", "GIZLI", "KIMSE BILMIYOR",
    "SOK", "EFSANE", "BEDAVA", "HIZLI", "KOLAY", "TEK SEFERDE", "MUKEMMEL",
]

# Kapakta kullanilacak kisa, yuksek kontrastli ifadeler
THUMB_PHRASES = {
    "war_attack": ["3 YILDIZ!", "TEK HAMLEDE", "SON SANIYE", "TAM YIKIM"],
    "strategy_guide": ["ADIM ADIM", "KOLAY YOL", "TAM REHBER", "BU KADAR BASIT"],
    "base_review": ["YIKILMAZ BASE", "ANTI 3 YILDIZ", "EN IYI DUZEN"],
    "farming": ["SINIRSIZ LOOT", "HIZLI KAYNAK", "MILYONLAR"],
    "upgrade": ["DOGRU SIRA", "HIZLI GELISIM", "ONCE BUNU YAP"],
    "event": ["YENI GUNCELLEME", "HER SEY DEGISTI", "KACIRMA"],
    "legend": ["EFSANE LIG", "KUPA PATLADI", "ZIRVEYE"],
    "builder": ["YAPICI USSU", "3 YILDIZ", "HIZLI GECIS"],
    "funny": ["INANILMAZ AN", "NE OLDU BOYLE?", "SON SANIYE"],
    "general": ["CLASH OF CLANS", "BUYUK SALDIRI", "IZLE VE OGREN"],
}

# AEO: aciklamaya konacak soru-cevap kaliplari (uretken aramalar bunlari alintilar)
FAQ_TEMPLATES = [
    ("{th} icin en iyi saldiri stratejisi nedir?",
     "{strategy} kombinasyonu {th} seviyesinde en tutarli sonucu veriyor; "
     "videoda ordu kurulumu ve acilis sirasi adim adim gosteriliyor."),
    ("Bu saldiriyi yapmak icin hangi seviye birlikler gerekir?",
     "Videoda kullanilan ordu {th} seviyesinde ulasilabilir birliklerden olusuyor; "
     "eksik seviyelerde de calisan alternatif dizilim anlatiliyor."),
    ("Clash of Clans'ta 3 yildiz nasil alinir?",
     "Once savunma agirlik merkezini belirleyip kraliceyi o yone yurutmek, "
     "ardindan ana orduyu acilan koridordan sokmak gerekir."),
]

TH_PATTERN = re.compile(r"\b(?:th|kk|koy\s*kasabasi|town\s*hall)\s*[-_ ]?(\d{1,2})\b", re.I)
BH_PATTERN = re.compile(r"\b(?:bh|builder\s*hall|yapici\s*ussu)\s*[-_ ]?(\d{1,2})\b", re.I)
NUM_PATTERN = re.compile(r"\b(\d{1,3})\b")


def detect_th(text: str) -> str | None:
    """Metinden TH seviyesini cikarir: 'th15 hydra' -> 'TH15'."""
    match = TH_PATTERN.search(text or "")
    if match:
        level = int(match.group(1))
        if 1 <= level <= 20:
            return f"TH{level}"
    return None


def detect_bh(text: str) -> str | None:
    match = BH_PATTERN.search(text or "")
    if match:
        level = int(match.group(1))
        if 1 <= level <= 12:
            return f"BH{level}"
    return None


def detect_strategies(text: str) -> list[str]:
    folded = tr_fold(text or "")
    found = []
    for canonical, variants in STRATEGIES.items():
        if any(tr_fold(v) in folded for v in variants):
            found.append(canonical)
    return found


def detect_content_type(text: str) -> str:
    """Metne bakarak icerik turunu tahmin eder."""
    folded = tr_fold(text or "")
    best, best_hits = "general", 0
    for code, meta in CONTENT_TYPES.items():
        hits = sum(1 for hint in meta["hints"] if tr_fold(hint) in folded)
        if hits > best_hits:
            best, best_hits = code, hits
    return best


def keyword_pool(content_type: str, th: str | None, strategies: list[str]) -> list[str]:
    """Videoya ozgu, oncelik sirali anahtar kelime havuzu."""
    pool: list[str] = []
    meta = CONTENT_TYPES.get(content_type, CONTENT_TYPES["general"])

    if th:
        pool += [
            f"{th.lower()} saldiri", f"{th.lower()} taktik", f"{th.lower()} rehber",
            f"{th.lower()} attack strategy", f"{th.lower()} 3 star", th.lower(),
            f"clash of clans {th.lower()}",
        ]
    for strategy in strategies:
        pool += [
            strategy, f"{strategy} {th.lower()}" if th else strategy,
            f"{strategy} attack", f"{strategy} taktik",
        ]
    pool += meta["keywords"]
    pool += CORE_TAGS_TR
    pool += CORE_TAGS_GLOBAL

    seen, unique = set(), []
    for tag in pool:
        tag = " ".join(tag.split()).strip().lower()
        if tag and tag not in seen and len(tag) <= 40:
            seen.add(tag)
            unique.append(tag)
    return unique


def hashtags_for(content_type: str, th: str | None) -> list[str]:
    tags = ["#ClashOfClans"]
    if th:
        tags.append(f"#{th}")
    mapping = {
        "war_attack": "#KlanSavasi",
        "strategy_guide": "#CocRehber",
        "base_review": "#BaseDuzeni",
        "farming": "#Farming",
        "upgrade": "#Gelisim",
        "event": "#Guncelleme",
        "legend": "#EfsaneLig",
        "builder": "#YapiciUssu",
        "funny": "#CocAnlari",
        "general": "#Coc",
    }
    tags.append(mapping.get(content_type, "#Coc"))
    return tags[:3]
