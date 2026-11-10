"""COUNCIL uygulamalarının (1. dalga) saf mantığı: alan doğrulama, hafıza yansıması metni, tekrarlayan etkinlikler,
alışkanlık serisi, not hesabı, oruç durumu, tarih bulma. Veritabanı ve web yok; her işlev tek başına test edilir.
Tasarım ve kararlar: tasarim/DALGA-1.md
"""
from __future__ import annotations

import datetime as dt
import math
import re

from .secrets_guard import find_secrets
from .textnorm import tr_lower

UYGULAMALAR = ("not", "gorev", "takvim", "ders", "aliskanlik", "oruc")        # öğe tutan uygulamalar
ADLAR = {"not": "Not", "gorev": "Görev", "takvim": "Takvim", "ders": "Ders", "aliskanlik": "Alışkanlık", "oruc": "Oruç",
         "ayarlar": "Ayarlar"}
SEMBOLLER = {"not": "No", "gorev": "Gr", "takvim": "Tk", "ders": "De", "aliskanlik": "Al", "oruc": "Or", "ayarlar": "Ay"}
DURUMLAR = ("acik", "bitti", "silindi")
BITEBILEN = ("gorev", "ders", "aliskanlik", "oruc")                            # 'bitti' durumu olan uygulamalar
GUN_KISA = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")
ONCELIKLER = ("dusuk", "orta", "yuksek")
TAKVIM_TURLERI = {"etkinlik": "Takvim", "sinav": "Sınav", "mesai": "Mesai"}
TEKRARLAR = {"yok": "", "gunluk": "her gün", "haftalik": "her hafta", "aylik": "her ay", "yillik": "her yıl"}
UNITE_DURUMLARI = ("yok", "calisiliyor", "bitti")
ORUC_TURLERI = {"su": "su orucu", "aralikli": "aralıklı oruç", "diger": "oruç"}
ORUC_SONUCLARI = {"tamamlandi": "tamamlandı", "erken": "erken bitirildi"}

# Oruç belirtileri. Tehlike listesindekilerden biri işaretlenirse uygulama orucu bırakmayı ve tıbbi yardım almayı söyler.
BELIRTILER = {
    "bayilma": "Bayılma ya da bayılacak gibi olma", "carpinti": "Çarpıntı ya da düzensiz kalp atışı", "gogus_agrisi": "Göğüs ağrısı",
    "bilinc": "Bilinç bulanıklığı, konuşmada zorlanma", "nefes_darligi": "Nefes darlığı", "kusma": "Durmayan kusma",
    "siddetli_kramp": "Şiddetli kas krampı ya da güçsüzlük",
    "bas_agrisi": "Baş ağrısı", "halsizlik": "Halsizlik", "bas_donmesi": "Ayağa kalkınca baş dönmesi", "mide_bulantisi": "Mide bulantısı",
    "usume": "Üşüme", "uykusuzluk": "Uykusuzluk", "agiz_kurulugu": "Ağız kuruluğu",
}
TEHLIKE = ("bayilma", "carpinti", "gogus_agrisi", "bilinc", "nefes_darligi", "kusma", "siddetli_kramp")
EVRELER = (   # (başlangıç saati, ad, açıklama) — genel bilgi; tıbbi öneri değildir
    (0, "Başlangıç", "Vücut son öğünün enerjisini kullanıyor."),
    (12, "Geçiş", "Depolanan şeker azalıyor; açlık dalgalar hâlinde gelip geçebilir."),
    (24, "İlk günler", "Vücut yağ kullanımına geçiyor. Baş ağrısı ve halsizlik sık görülür; su ve elektrolit önemli."),
    (72, "Uyum", "Açlık hissi çoğu kişide azalır. Ayağa yavaş kalk; baş dönmesine dikkat et."),
    (168, "Uzun oruç", "Bu süre tıbbi gözetim gerektirir. Tahlil ve tansiyon takibi olmadan sürdürülmemeli."),
)
UZUN_SAAT = 72
YIL_ARALIGI = (1900, 2200)          # kabul edilen tarihler (uçtaki yıllar tarih hesabını taşırır)
EN_BUYUK_KIMLIK = 2 ** 53
VARSAYILAN_AYAR = {"saat_dilimi": "Europe/Istanbul", "sessiz_acik": False, "sessiz_bas": "23:00", "sessiz_son": "08:00",
                   "yansit": {u: True for u in UYGULAMALAR}}


class Gecersiz(ValueError):
    """Kullanıcıya gösterilecek doğrulama hatası."""


# ------------------------------------------------------------------ alan denetçileri
def _metin(v: dict, ad: str, etiket: str, en_az: int, en_cok: int) -> str:
    x = v.get(ad, "")
    if not isinstance(x, str):
        raise Gecersiz(f"{etiket}: metin olmalı.")
    x = x.strip()
    if len(x) < en_az:
        raise Gecersiz(f"{etiket} boş olamaz.")
    if len(x) > en_cok:
        raise Gecersiz(f"{etiket} çok uzun (en fazla {en_cok} karakter).")
    try:
        x.encode("utf-8")
    except UnicodeEncodeError:
        raise Gecersiz(f"{etiket}: yazılamayan (bozuk) bir karakter var.") from None
    return x


def _mantik(v: dict, ad: str, etiket: str) -> bool:
    x = v.get(ad, False)
    if not isinstance(x, bool):
        raise Gecersiz(f"{etiket}: evet/hayır olmalı.")
    return x


def _secim(v: dict, ad: str, etiket: str, secenekler, varsayilan: str) -> str:
    x = v.get(ad, varsayilan)
    if not isinstance(x, str) or x not in secenekler:
        raise Gecersiz(f"{etiket}: geçersiz değer.")
    return x


def _tarih(v: dict, ad: str, etiket: str, zorunlu: bool = False) -> str:
    x = v.get(ad, "")
    if x in ("", None) and not zorunlu:
        return ""
    if not isinstance(x, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", x):
        raise Gecersiz(f"{etiket}: tarih YYYY-AA-GG olmalı.")
    try:
        g = dt.date.fromisoformat(x)
    except ValueError:
        raise Gecersiz(f"{etiket}: böyle bir tarih yok.") from None
    if not YIL_ARALIGI[0] <= g.year <= YIL_ARALIGI[1]:
        raise Gecersiz(f"{etiket}: yıl {YIL_ARALIGI[0]} ile {YIL_ARALIGI[1]} arasında olmalı.")
    return g.isoformat()


def _saat(v: dict, ad: str, etiket: str) -> str:
    x = v.get(ad, "")
    if x in ("", None):
        return ""
    if not isinstance(x, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x):
        raise Gecersiz(f"{etiket}: saat SS:DD olmalı.")
    return x


def _an(v: dict, ad: str, etiket: str, zorunlu: bool = False) -> str:
    """Yerel tarih-saat: YYYY-AA-GGTSS:DD."""
    x = v.get(ad, "")
    if x in ("", None) and not zorunlu:
        return ""
    if not isinstance(x, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", x):
        raise Gecersiz(f"{etiket}: tarih ve saat YYYY-AA-GGTSS:DD olmalı.")
    try:
        an = dt.datetime.fromisoformat(x)
    except ValueError:
        raise Gecersiz(f"{etiket}: böyle bir tarih ya da saat yok.") from None
    if not YIL_ARALIGI[0] <= an.year <= YIL_ARALIGI[1]:
        raise Gecersiz(f"{etiket}: yıl {YIL_ARALIGI[0]} ile {YIL_ARALIGI[1]} arasında olmalı.")
    return an.strftime("%Y-%m-%dT%H:%M")


def _sayi(v: dict, ad: str, etiket: str, en_az: float, en_cok: float, tam: bool = False, varsayilan=None, zorunlu: bool = False):
    x = v.get(ad, varsayilan)
    if x is None:
        if zorunlu:
            raise Gecersiz(f"{etiket} boş olamaz.")
        return None
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or (tam and int(x) != x):
        raise Gecersiz(f"{etiket}: {'tam ' if tam else ''}sayı olmalı.")
    if not en_az <= x <= en_cok:
        raise Gecersiz(f"{etiket}: {en_az:g} ile {en_cok:g} arasında olmalı.")
    return int(x) if tam or float(x).is_integer() else float(x)


def _gizli_denetle(*metinler: str) -> None:
    """Her alan ayrı taranır: birleştirilirse bir alanın sonundaki sayı sonraki alandaki tarihle kart numarası gibi görünür."""
    bulunan = sorted({b for m in metinler if m for b in find_secrets(m)})
    if bulunan:
        raise Gecersiz(f"Kaydedilmedi: gizli bilgi var ({', '.join(bulunan)}). Şifre, anahtar, IBAN, kart ya da kimlik numarası yazılamaz.")


def _metinler(x) -> list[str]:
    if isinstance(x, str):
        return [x]
    if isinstance(x, dict):
        return [m for y in x.values() for m in _metinler(y)]
    if isinstance(x, list):
        return [m for y in x for m in _metinler(y)]
    return []


# ------------------------------------------------------------------ uygulama başına doğrulama
def _not(v: dict) -> dict:
    ham = v.get("etiketler", [])
    if not isinstance(ham, list) or not all(isinstance(e, str) for e in ham) or len(ham) > 8:
        raise Gecersiz("Etiketler: en fazla 8 kısa sözcük.")
    etiketler = list(dict.fromkeys(e.strip()[:40] for e in ham if e.strip()))
    try:
        " ".join(etiketler).encode("utf-8")
    except UnicodeEncodeError:
        raise Gecersiz("Etiketler: yazılamayan (bozuk) bir karakter var.") from None
    return {"metin": _metin(v, "metin", "Not", 1, 4000), "etiketler": etiketler, "sabit": _mantik(v, "sabit", "Sabit")}


def _gorev(v: dict) -> dict:
    return {"baslik": _metin(v, "baslik", "Başlık", 1, 300), "aciklama": _metin(v, "aciklama", "Açıklama", 0, 2000),
            "son_tarih": _tarih(v, "son_tarih", "Son tarih"), "oncelik": _secim(v, "oncelik", "Öncelik", ONCELIKLER, "orta"),
            "etiket": _metin(v, "etiket", "Etiket", 0, 40)}


def _takvim(v: dict) -> dict:
    o = {"baslik": _metin(v, "baslik", "Başlık", 1, 200), "tarih": _tarih(v, "tarih", "Tarih", zorunlu=True),
         "saat": _saat(v, "saat", "Saat"), "bitis_saat": _saat(v, "bitis_saat", "Bitiş saati"),
         "yer": _metin(v, "yer", "Yer", 0, 200), "aciklama": _metin(v, "aciklama", "Açıklama", 0, 2000),
         "tur": _secim(v, "tur", "Tür", TAKVIM_TURLERI, "etkinlik"), "tekrar": _secim(v, "tekrar", "Tekrar", TEKRARLAR, "yok"),
         "tekrar_bitis": _tarih(v, "tekrar_bitis", "Tekrar bitişi")}
    if o["bitis_saat"] and (not o["saat"] or o["bitis_saat"] < o["saat"]):
        raise Gecersiz("Bitiş saati başlangıçtan önce olamaz (başlangıç saati de gerekli).")
    if o["tekrar"] == "yok":
        o["tekrar_bitis"] = ""
    elif o["tekrar_bitis"] and o["tekrar_bitis"] < o["tarih"]:
        raise Gecersiz("Tekrar bitişi ilk tarihten önce olamaz.")
    ders = v.get("ders_id")
    if ders is not None and (isinstance(ders, bool) or not isinstance(ders, int) or not 1 <= ders < EN_BUYUK_KIMLIK):
        raise Gecersiz("Ders: geçersiz değer.")
    o["ders_id"] = ders
    return o


def _ders(v: dict) -> dict:
    ham = v.get("uniteler", [])
    if not isinstance(ham, list) or len(ham) > 60 or not all(isinstance(u, dict) for u in ham):
        raise Gecersiz("Üniteler: en fazla 60 ünite.")
    uniteler = [{"ad": _metin(u, "ad", "Ünite adı", 1, 160), "durum": _secim(u, "durum", "Ünite durumu", UNITE_DURUMLARI, "yok")}
                for u in ham]
    return {"ad": _metin(v, "ad", "Ders adı", 1, 120), "kurum": _metin(v, "kurum", "Kurum", 0, 80),
            "donem": _metin(v, "donem", "Dönem", 0, 40), "uniteler": uniteler,
            "ara": _sayi(v, "ara", "Ara sınav", 0, 100), "final": _sayi(v, "final", "Final", 0, 100),
            "ara_agirlik": _sayi(v, "ara_agirlik", "Ara sınav ağırlığı", 0, 100, varsayilan=30),
            "hedef": _sayi(v, "hedef", "Hedef ortalama", 0, 100), "aciklama": _metin(v, "aciklama", "Açıklama", 0, 2000)}


def _aliskanlik(v: dict) -> dict:
    ham = v.get("gunler", [])
    if not isinstance(ham, list) or not all(isinstance(g, int) and not isinstance(g, bool) and 0 <= g <= 6 for g in ham):
        raise Gecersiz("Günler: haftanın günleri seçilmeli.")
    return {"ad": _metin(v, "ad", "Alışkanlık adı", 1, 120), "gunler": sorted(set(ham)),
            "aciklama": _metin(v, "aciklama", "Açıklama", 0, 500)}


def _oruc(v: dict) -> dict:
    o = {"tur": _secim(v, "tur", "Tür", ORUC_TURLERI, "su"), "baslangic": _an(v, "baslangic", "Başlangıç", zorunlu=True),
         "hedef_saat": _sayi(v, "hedef_saat", "Hedef süre (saat)", 1, 1440, tam=True, zorunlu=True),
         "bitis": _an(v, "bitis", "Bitiş"), "sonuc": _secim(v, "sonuc", "Sonuç", ("", *ORUC_SONUCLARI), ""),
         "kirma_plani": _metin(v, "kirma_plani", "Kırma planı", 0, 3000), "aciklama": _metin(v, "aciklama", "Açıklama", 0, 1000)}
    if o["bitis"] and o["bitis"] < o["baslangic"]:
        raise Gecersiz("Bitiş başlangıçtan önce olamaz.")
    return o


_DOGRULA = {"not": _not, "gorev": _gorev, "takvim": _takvim, "ders": _ders, "aliskanlik": _aliskanlik, "oruc": _oruc}


def dogrula(uyg: str, v: dict) -> dict:
    """Arayüzden gelen ham öğeyi temiz veriye çevirir; hata varsa Gecersiz atar. Tanımsız alanlar atılır.
    Her öğede 'ozel' bulunur: True ise hafızaya yansımaz, ajanlara verilen özette görünmez."""
    if uyg not in _DOGRULA or not isinstance(v, dict):
        raise Gecersiz("Geçersiz istek.")
    temiz = _DOGRULA[uyg](v)
    temiz["ozel"] = _mantik(v, "ozel", "Özel")
    _gizli_denetle(*_metinler(temiz))
    return temiz


def dogrula_gun(uyg: str, v: dict) -> dict | None:
    """Güne bağlı veri. None: o günün verisi silinir (alışkanlık işareti kaldırıldı)."""
    if not isinstance(v, dict):
        raise Gecersiz("Geçersiz istek.")
    if uyg == "aliskanlik":
        return {"tamam": True} if _mantik(v, "tamam", "İşaret") else None
    if uyg == "oruc":
        ham = v.get("belirtiler", [])
        if not isinstance(ham, list) or not all(isinstance(b, str) and b in BELIRTILER for b in ham):
            raise Gecersiz("Belirtiler: geçersiz değer.")
        g = {"su_ml": _sayi(v, "su_ml", "Su (ml)", 0, 15000, tam=True), "elektrolit": _mantik(v, "elektrolit", "Elektrolit"),
             "kilo": _sayi(v, "kilo", "Kilo", 20, 400), "his": _sayi(v, "his", "Nasıl hissediyorsun", 1, 5, tam=True),
             "belirtiler": [b for b in BELIRTILER if b in ham], "not": _metin(v, "not", "Not", 0, 500)}
        _gizli_denetle(g["not"])
        return g
    raise Gecersiz("Bu uygulamada güne bağlı veri yok.")


# ------------------------------------------------------------------ yazım yardımcıları
def sayi_yaz(x: float) -> str:
    """Ondalık virgülle, gereksiz sıfır olmadan (kimlik kılavuzu): 74, 54,3."""
    return f"{round(float(x), 1):g}".replace(".", ",")


def sure_yaz(saat: float) -> str:
    s = int(saat)
    if s < 1:
        return "1 saatten az"
    gun, kalan = divmod(s, 24)
    return " ".join(p for p in (f"{gun} gün" if gun else "", f"{kalan} saat" if kalan else "") if p)


def _cumle(s: str) -> str:
    return s.rstrip(" .") + "."


def gunler_yaz(gunler: list[int]) -> str:
    return "her gün" if not gunler or len(gunler) == 7 else ", ".join(GUN_KISA[g] for g in gunler)


# ------------------------------------------------------------------ hafıza yansıması
def ders_ilerleme(veri: dict) -> dict:
    u = veri.get("uniteler") or []
    bitti = sum(1 for x in u if x["durum"] == "bitti")
    return {"bitti": bitti, "calisiliyor": sum(1 for x in u if x["durum"] == "calisiliyor"), "toplam": len(u),
            "yuzde": round(100 * bitti / len(u)) if u else 0}


def not_hesabi(ara, final, ara_agirlik, hedef) -> dict:
    """Ağırlıklı ortalama ve (final henüz yoksa) hedef ortalama için gereken final notu."""
    w = (30 if ara_agirlik is None else ara_agirlik) / 100
    out = {"ortalama": None, "gereken_final": None, "ulasilamaz": False}
    if ara is not None and final is not None:
        out["ortalama"] = round(ara * w + final * (1 - w), 1)
    elif ara is not None and hedef is not None and w < 1:
        gereken = (hedef - ara * w) / (1 - w)
        out["gereken_final"] = round(max(0.0, gereken), 1)
        out["ulasilamaz"] = gereken > 100
    return out


def _an_yaz(an: str) -> str:
    return an.replace("T", " ")


def kayit(uyg: str, veri: dict, durum: str) -> dict | None:
    """Öğenin hafızadaki yansıması: {text, context, keys, kind}. None: yansıma olmamalı (özel, silinmiş, bitmiş görev...).
    Metin tek bir bilgidir, kendi başına anlaşılır ve tarihleri mutlaktır (hafıza kuralları)."""
    if veri.get("ozel") or durum == "silindi":
        return None
    if uyg == "not":
        return {"text": veri["metin"], "context": "Not uygulaması", "keys": list(veri["etiketler"]), "kind": "fact"}
    if uyg == "gorev":
        if durum != "acik":
            return None
        t = "Görev: " + _cumle(veri["baslik"])
        if veri["son_tarih"]:
            t += f" Son tarih: {veri['son_tarih']}."
        if veri["oncelik"] == "yuksek":
            t += " Öncelik: yüksek."
        return {"text": t, "context": veri["aciklama"][:300] or "Görev uygulaması", "keys": [veri["etiket"]] if veri["etiket"] else [],
                "kind": "task"}
    if uyg == "takvim":
        t = f"{TAKVIM_TURLERI[veri['tur']]}: {veri['baslik'].rstrip(' .')} — {veri['tarih']}"
        if veri["saat"]:
            t += f" {veri['saat']}" + (f"–{veri['bitis_saat']}" if veri["bitis_saat"] else "")
        if veri["yer"]:
            t += f", {veri['yer'].rstrip(' .')}"
        if veri["tekrar"] != "yok":
            t += f" ({TEKRARLAR[veri['tekrar']]}" + (f", {veri['tekrar_bitis']} tarihine kadar" if veri["tekrar_bitis"] else "") + ")"
        return {"text": t + ".", "context": veri["aciklama"][:300] or "Takvim uygulaması", "keys": [], "kind": "event"}
    if uyg == "ders":
        ek = ", ".join(x for x in (veri["kurum"], veri["donem"]) if x)
        t = f"Ders: {veri['ad'].rstrip(' .')}" + (f" ({ek})" if ek else "") + "."
        i = ders_ilerleme(veri)
        if i["toplam"]:
            t += f" {i['bitti']}/{i['toplam']} ünite bitti."
        notlar = [f"ara sınav {sayi_yaz(veri['ara'])}" if veri["ara"] is not None else "",
                  f"final {sayi_yaz(veri['final'])}" if veri["final"] is not None else ""]
        ort = not_hesabi(veri["ara"], veri["final"], veri["ara_agirlik"], None)["ortalama"]
        notlar.append(f"ortalama {sayi_yaz(ort)}" if ort is not None else "")
        notlar = ", ".join(n for n in notlar if n)
        if notlar:
            t += " " + notlar[0].upper() + notlar[1:] + "."
        if durum == "bitti":
            t += " Ders tamamlandı."
        return {"text": t, "context": veri["aciklama"][:300] or "Ders uygulaması", "keys": [], "kind": "fact"}
    if uyg == "aliskanlik":
        if durum != "acik":
            return None
        return {"text": f"Alışkanlık: {veri['ad'].rstrip(' .')} ({gunler_yaz(veri['gunler'])}).",
                "context": veri["aciklama"][:300] or "Alışkanlık uygulaması", "keys": [], "kind": "plan"}
    if uyg == "oruc":
        tur = ORUC_TURLERI[veri["tur"]]
        if durum == "bitti" and veri["bitis"]:
            sure = (dt.datetime.fromisoformat(veri["bitis"]) - dt.datetime.fromisoformat(veri["baslangic"])).total_seconds() / 3600
            sonuc = ORUC_SONUCLARI.get(veri["sonuc"], "bitti")
            t = f"Oruç: {_an_yaz(veri['baslangic'])} – {_an_yaz(veri['bitis'])} ({sure_yaz(sure)}), {sonuc} ({tur})."
        else:
            t = f"Oruç başladı: {_an_yaz(veri['baslangic'])}, hedef {sure_yaz(veri['hedef_saat'])} ({tur})."
        return {"text": t, "context": "Oruç uygulaması", "keys": ["oruç", "fasting"], "kind": "event"}
    return None


def kapanis(uyg: str, durum: str) -> tuple[str, str]:
    """Yansıması kalkan öğenin hafızadaki kaydına ne olacağı: ('arsiv' | 'gecersiz', neden)."""
    ad = ADLAR[uyg]
    if durum == "silindi":
        return "arsiv", f"{ad}: uygulamadan silindi"
    if durum == "bitti":
        return "gecersiz", f"{ad}: {'bırakıldı' if uyg == 'aliskanlik' else 'tamamlandı'}"
    return "arsiv", f"{ad}: özel yapıldı, hafızadan kaldırıldı"


# ------------------------------------------------------------------ takvim
def olay_gunleri(veri: dict, bas: dt.date, son: dt.date) -> list[dt.date]:
    """Etkinliğin [bas, son] aralığına düşen günleri (tekrarlar açılmış)."""
    ilk = dt.date.fromisoformat(veri["tarih"])
    bitis = dt.date.fromisoformat(veri["tekrar_bitis"]) if veri.get("tekrar_bitis") else son
    son = min(son, bitis)
    tekrar = veri.get("tekrar", "yok")
    if tekrar == "yok":
        return [ilk] if bas <= ilk <= son else []
    out: list[dt.date] = []
    if tekrar in ("gunluk", "haftalik"):
        adim = 1 if tekrar == "gunluk" else 7
        g = ilk if ilk >= bas else ilk + dt.timedelta(days=-(-(bas - ilk).days // adim) * adim)
        while g <= son:
            out.append(g)
            g += dt.timedelta(days=adim)
        return out
    y, a = max(ilk.year, bas.year), 1
    if tekrar == "aylik":
        y, a = (bas.year, bas.month) if bas > ilk else (ilk.year, ilk.month)
    while (y, a) <= (son.year, son.month):
        ay = a if tekrar == "aylik" else ilk.month
        try:
            g = dt.date(y, ay, ilk.day)
        except ValueError:                       # o ayda/yılda bu gün yok (31, 29 Şubat): atlanır
            g = None
        if g and bas <= g <= son and g >= ilk:
            out.append(g)
        if tekrar == "aylik":
            y, a = (y, a + 1) if a < 12 else (y + 1, 1)
        else:
            y += 1
    return out


# ------------------------------------------------------------------ alışkanlık
def seri(gunler: list[int], isaretli: set[str], bugun: dt.date) -> dict:
    """Güncel seri, en uzun seri ve son 7 gün. Planlı bir gün boş geçildiyse seri biter; bugün henüz işaretlenmediyse
    bitmiş sayılmaz. Planlı olmayan günler seriyi ne bozar ne uzatır (işaretlendiyse uzatır)."""
    planli = (lambda g: True) if not gunler else (lambda g: g.weekday() in gunler)
    tamam = lambda g: g.isoformat() in isaretli      # noqa: E731
    ilk = min((dt.date.fromisoformat(x) for x in isaretli), default=bugun)

    guncel, g = 0, bugun
    while g >= ilk:
        if tamam(g):
            guncel += 1
        elif planli(g) and g != bugun:
            break
        g -= dt.timedelta(days=1)

    en_uzun = kosu = 0
    g = ilk
    while g <= bugun:
        if tamam(g):
            kosu += 1
            en_uzun = max(en_uzun, kosu)
        elif planli(g) and g != bugun:
            kosu = 0
        g += dt.timedelta(days=1)

    son7 = [{"gun": d.isoformat(), "planli": planli(d), "tamam": tamam(d)}
            for d in (bugun - dt.timedelta(days=n) for n in range(6, -1, -1))]
    return {"seri": guncel, "en_uzun": en_uzun, "bugun_planli": planli(bugun), "bugun_tamam": tamam(bugun), "son7": son7}


# ------------------------------------------------------------------ oruç
def oruc_durumu(veri: dict, durum: str, simdi: dt.datetime) -> dict:
    bas = dt.datetime.fromisoformat(veri["baslangic"])
    son = dt.datetime.fromisoformat(veri["bitis"]) if (durum == "bitti" and veri.get("bitis")) else simdi
    gecen = max(0.0, (son - bas).total_seconds() / 3600)
    hedef = veri["hedef_saat"]
    kalan = 0.0 if durum == "bitti" else max(0.0, hedef - gecen)
    ad, aciklama = next((a, c) for s, a, c in reversed(EVRELER) if gecen >= s)
    return {"gecen_saat": round(gecen, 2), "hedef_saat": hedef, "kalan_saat": round(kalan, 2),
            "yuzde": min(100, int(100 * gecen / hedef)) if hedef else 0, "gun": int(gecen // 24) + 1,
            "hedef_bitis": (bas + dt.timedelta(hours=hedef)).strftime("%Y-%m-%dT%H:%M"),
            "evre": {"ad": ad, "aciklama": aciklama}, "uzun": hedef >= UZUN_SAAT or gecen >= UZUN_SAAT}


def belirti_uyarisi(belirtiler: list[str]) -> dict:
    tehlike = [BELIRTILER[b] for b in belirtiler if b in TEHLIKE]
    if tehlike:
        return {"duzey": "tehlike", "mesaj": "Orucu şimdi bırak ve tıbbi yardım al: " + "; ".join(tehlike).lower()
                + ". Bu belirtiler beklemeye gelmez; acil durumda 112'yi ara."}
    if belirtiler:
        return {"duzey": "dikkat", "mesaj": "Bu belirtiler oruçta sık görülür. Su ve elektrolitini kontrol et, dinlen; "
                "artarsa ya da geçmezse orucu bırak."}
    return {"duzey": "", "mesaj": ""}


# ------------------------------------------------------------------ tarih bulma ve hızlı görev
_AYLAR = {"ocak": 1, "şubat": 2, "subat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "mayis": 5, "haziran": 6, "temmuz": 7,
          "ağustos": 8, "agustos": 8, "eylül": 9, "eylul": 9, "ekim": 10, "kasım": 11, "kasim": 11, "aralık": 12, "aralik": 12}
_HAFTA = {"pazartesi": 0, "salı": 1, "sali": 1, "çarşamba": 2, "carsamba": 2, "perşembe": 3, "persembe": 3, "cuma": 4,
          "cumartesi": 5, "pazar": 6}
_AY_RE = "|".join(_AYLAR)
_HAFTA_RE = "|".join(sorted(_HAFTA, key=len, reverse=True))
_TARIH_RE = re.compile(
    r"(?<![\w.])(?:"
    r"(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?P<g1>\d{1,2})[./](?P<a1>\d{1,2})[./](?P<y1>\d{4})"
    r"|(?<!saat )(?P<g2>\d{1,2})\.(?P<a2>\d{2})"            # yılsız: ay iki haneli (1.5 litre, 18.2 sürümü tarih değil); saat 9.05 de değil
    rf"|(?P<g3>\d{{1,2}})\s+(?P<a3>{_AY_RE})(?:\s+(?P<y3>\d{{4}}))?"
    r"|(?P<goreli>bugün|bugun|yarın|yarin)"
    rf"|(?P<hafta>{_HAFTA_RE})"
    r")(?!\w)(?!\.\d)")                                     # ardından harf/rakam ya da ".3" gelmez; cümle sonu noktası serbest


def tarih_bul(metin: str, bugun: dt.date, goreli: bool = True) -> tuple[str, int, int] | None:
    """Metindeki ilk tarihi bulur: (YYYY-AA-GG, başlangıç, bitiş). Yılsız tarih geçmişte kaldıysa gelecek yıl sayılır;
    gün adı her zaman bugünden sonraki ilk o gündür. Sözcüğün parçası olan eşleşmeler (yarınki, pazarlama) sayılmaz.
    goreli=False: 'bugün', 'yarın' ve gün adları tarih sayılmaz (notlarda bunlar çoğu zaman bir etkinlik değildir)."""
    for m in _TARIH_RE.finditer(tr_lower(metin)):
        if not goreli and (m["goreli"] or m["hafta"]):
            continue
        try:
            if m["iso"]:
                g = dt.date.fromisoformat(m["iso"])
            elif m["g1"]:
                g = dt.date(int(m["y1"]), int(m["a1"]), int(m["g1"]))
            elif m["g2"] or m["g3"]:
                gun = int(m["g2"] or m["g3"])
                ay = int(m["a2"]) if m["g2"] else _AYLAR[m["a3"]]
                if m["g3"] and m["y3"]:
                    g = dt.date(int(m["y3"]), ay, gun)
                else:
                    g = dt.date(bugun.year, ay, gun)
                    if g < bugun:
                        g = dt.date(bugun.year + 1, ay, gun)
            elif m["goreli"]:
                g = bugun + dt.timedelta(days=0 if m["goreli"].startswith("bug") else 1)
            else:
                g = bugun + dt.timedelta(days=(_HAFTA[m["hafta"]] - bugun.weekday() - 1) % 7 + 1)
        except ValueError:
            continue
        return g.isoformat(), m.start(), m.end()
    return None


def gorev_coz(metin: str, bugun: dt.date) -> dict:
    """Hızlı ekleme satırını çözer: 'yarın faturayı öde', '! raporu gönder cuma', '21.11 vize!'."""
    metin = " ".join(metin.split())
    oncelik = "orta"
    if metin.startswith("!") or metin.endswith("!") or " ! " in f" {metin} ":
        oncelik = "yuksek"
    baslik = " ".join(p for p in metin.strip("!").split() if p != "!")
    son_tarih = ""
    bulunan = tarih_bul(baslik, bugun)
    if bulunan:
        son_tarih = bulunan[0]
        kalan = " ".join((baslik[:bulunan[1]] + " " + baslik[bulunan[2]:]).split())
        kalan = re.sub(r"\s+([.,;:])", r"\1", kalan).strip(" .,;:")          # tarihten artakalan noktalama
        baslik = kalan or baslik
    return {"baslik": baslik, "son_tarih": son_tarih, "oncelik": oncelik}


# ------------------------------------------------------------------ ayarlar
def ayar_dogrula(v: dict) -> dict:
    if not isinstance(v, dict):
        raise Gecersiz("Geçersiz istek.")
    a = {"saat_dilimi": v.get("saat_dilimi", VARSAYILAN_AYAR["saat_dilimi"]),
         "sessiz_acik": _mantik(v, "sessiz_acik", "Sessiz saatler"),
         "sessiz_bas": _saat(v, "sessiz_bas", "Sessiz saat başlangıcı") or VARSAYILAN_AYAR["sessiz_bas"],
         "sessiz_son": _saat(v, "sessiz_son", "Sessiz saat bitişi") or VARSAYILAN_AYAR["sessiz_son"]}
    try:
        from zoneinfo import ZoneInfo
        if not isinstance(a["saat_dilimi"], str) or not re.fullmatch(r"[A-Za-z_]+(/[A-Za-z_+\-0-9]+){0,2}", a["saat_dilimi"]):
            raise KeyError
        ZoneInfo(a["saat_dilimi"])
    except Exception:
        raise Gecersiz("Saat dilimi tanınmadı (ör. Europe/Istanbul).") from None
    ham = v.get("yansit", {})
    if not isinstance(ham, dict) or any(k not in UYGULAMALAR or not isinstance(x, bool) for k, x in ham.items()):
        raise Gecersiz("Yansıtma ayarı: geçersiz değer.")
    a["yansit"] = {u: ham.get(u, True) for u in UYGULAMALAR}
    return a


def sessiz_mi(ayar: dict, saat: str) -> bool:
    if not ayar.get("sessiz_acik"):
        return False
    bas, son = ayar["sessiz_bas"], ayar["sessiz_son"]
    return bas <= saat < son if bas <= son else (saat >= bas or saat < son)


def sessiz_kaydi(ayar: dict) -> dict | None:
    if not ayar.get("sessiz_acik"):
        return None
    return {"text": f"Sessiz saatler: {ayar['sessiz_bas']}–{ayar['sessiz_son']}. Bu saatlerde bildirim ve hatırlatma gönderilmez.",
            "context": "Ayarlar uygulaması", "keys": ["sessiz saat", "bildirim", "quiet hours"], "kind": "preference"}
