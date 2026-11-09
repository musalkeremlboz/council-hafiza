"""COUNCIL Gezgin: hafıza kayıtlarını gösteren, süzen, arayan, düzelten, birleştiren ve arşivleyen yönetici arayüzü.

Panelin içinde çalışır (/panel/gezgin), aynı yönetici oturumunu kullanır. Kayıtlar hiç değiştirilmez ve silinmez:
- düzelt     = düzeltilmiş metinle yeni kayıt + eskisini geçersiz kıl
- birleştir  = birleşik yeni kayıt + kaynakların hepsini geçersiz kıl
- arşivle / arşivden çıkar
Her işlem hash zincirli olay günlüğüne 'gezgin' aracı adına yazılır.

Yazma uçları yalnız JSON kabul eder ve oturumdan türetilen bir CSRF belirteci ister (X-CSRF başlığı); ayrıca tarayıcı
başka bir siteden geldiğini bildiriyorsa (Origin / Sec-Fetch-Site) istek reddedilir.
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import hashlib
import hmac
import json
import logging
import os
import re
import time
from pathlib import Path

import numpy as np

from .secrets_guard import find_secrets
from .store import KINDS, TRUST, VISIBILITY, Actor

ARAC = "gezgin"
ANLAM_ESIK = 0.5          # BGE-M3 kosinüs benzerliği; altı "ilgisiz" sayılır
SAYFA = 50
BURADA = Path(__file__).resolve().parent
KID = re.compile(r"R\d{5}")


# ------------------------------------------------------------------ yardımcılar (saf, test edilebilir)
def csrf_belirteci(admin_hash: str, oturum: str) -> str:
    anahtar = hashlib.sha256(("council-gezgin-csrf:" + (admin_hash or "")).encode()).digest()
    return hmac.new(anahtar, (oturum or "").encode(), hashlib.sha256).hexdigest()


def etkin_tarih(r: dict) -> str:
    """Kaydın tarihi; boşsa yazıldığı günün (sunucu saatiyle) tarihi. Süzme, sıralama ve görüntüleme hep bunu kullanır."""
    return r.get("valid_from") or time.strftime("%Y-%m-%d", time.localtime(r["created_at"]))


GUVEN_SIRA = {"external": 0, "agent": 1, "user": 2}


def durum(r: dict) -> str:
    if r.get("archived"):
        return "arsiv"
    if r.get("superseded_by") or r.get("valid_to"):
        return "eski"
    return "guncel"


def disa(r: dict) -> dict:
    """Kaydı arayüzün beklediği biçime çevirir (vektör dışarı verilmez)."""
    keys = r.get("keys")
    try:
        keys = keys if isinstance(keys, list) else json.loads(keys or "[]")
    except ValueError:
        keys = []
    return {"id": r["id"], "metin": r["text"], "baglam": r.get("context") or "", "anahtarlar": keys, "tur": r["kind"],
            "gorunurluk": r["visibility"], "guven": r["trust"], "tarih": etkin_tarih(r),
            "bitis": r.get("valid_to") or "", "yerine": r.get("superseded_by") or "", "arsiv_neden": r.get("archive_reason") or "",
            "arac": r["tool"], "proje": r["project"], "olusturma": r["created_at"], "durum": durum(r)}


def _tarih(v: str | None) -> str:
    try:
        return _dt.date.fromisoformat(str(v or "").strip()).isoformat()
    except ValueError:
        return time.strftime("%Y-%m-%d")


def suz(kayitlar: list[dict], p: dict) -> list[dict]:
    """Süzgeçler: proje, arac, tur (virgülle çoklu), durum (guncel|eski|arsiv|hepsi), bas/son (YYYY-AA-GG, kaydın tarihi)."""
    def coklu(ad):
        v = (p.get(ad) or "").strip()
        return {x for x in v.split(",") if x} if v else None
    proje, arac, tur = coklu("proje"), coklu("arac"), coklu("tur")
    dur = (p.get("durum") or "guncel").strip()
    bas, son = (p.get("bas") or "").strip(), (p.get("son") or "").strip()
    out = []
    for r in kayitlar:
        if proje and r["project"] not in proje:
            continue
        if arac and r["tool"] not in arac:
            continue
        if tur and r["kind"] not in tur:
            continue
        if dur != "hepsi" and durum(r) != dur:
            continue
        t = etkin_tarih(r)
        if bas and t < bas:
            continue
        if son and t > son:
            continue
        out.append(r)
    return out


def secenekler(kayitlar: list[dict]) -> dict:
    def say(alan):
        d: dict[str, int] = {}
        for r in kayitlar:
            d[r[alan]] = d.get(r[alan], 0) + 1
        return dict(sorted(d.items(), key=lambda x: (-x[1], x[0])))
    durumlar: dict[str, int] = {"guncel": 0, "eski": 0, "arsiv": 0}
    for r in kayitlar:
        durumlar[durum(r)] += 1
    return {"proje": say("project"), "arac": say("tool"), "tur": say("kind"), "durum": durumlar}


def dogrula(v: dict) -> tuple[dict | None, str | None]:
    """Arayüzden gelen kayıt alanlarını denetler; (kayıt, hata)."""
    if not all(isinstance(v.get(k, ""), str) for k in ("metin", "baglam", "tur", "gorunurluk", "guven", "tarih")):
        return None, "Geçersiz alan türü."
    metin = str(v.get("metin") or "").strip()
    baglam = str(v.get("baglam") or "").strip()
    keys = v.get("anahtarlar") or []
    if isinstance(keys, str):
        keys = keys.split(",")
    if not isinstance(keys, list) or not all(isinstance(k, (str, int, float)) for k in keys):
        return None, "Arama anahtarları bir liste olmalı."
    keys = [str(k).strip()[:80] for k in keys if str(k).strip()][:12]
    tur, gor, guv = v.get("tur"), v.get("gorunurluk"), v.get("guven", "user")
    if tur not in KINDS or gor not in VISIBILITY or guv not in TRUST:
        return None, "Geçersiz tür, görünürlük ya da güven değeri."
    if len(metin) < 3:
        return None, "Metin boş olamaz."
    if len(metin) > 4000 or len(baglam) > 1000:
        return None, "Metin çok uzun (en fazla 4000 karakter)."
    found = find_secrets(" ".join([metin, baglam, " ".join(keys)]))
    if found:
        return None, f"Kaydedilmedi: metinde gizli bilgi var ({', '.join(found)}). Şifre, anahtar, IBAN, kart ya da kimlik numarası hafızaya yazılamaz."
    return {"text": metin, "context": baglam, "keys": keys, "kind": tur, "visibility": gor, "trust": guv,
            "valid_from": _tarih(v.get("tarih"))}, None


def kural_denetle(eskiler: list[dict], yeni: dict, guven_onay: bool = False) -> str | None:
    """MCP araçlarındaki geçersiz kılma korumalarının aynısı + projeler arası sızıntı ve sessiz güven yükseltme koruması.
    yeni: yazılacak kayıt ya da (gecersiz-kil'de) yerine geçecek mevcut kayıt; mevcut kayıtsa 'project' alanı da denetlenir."""
    if yeni.get("project") and yeni["visibility"] == "project" and any(o["project"] != yeni["project"] for o in eskiler):
        return "Bir projeye özel kayıt, başka bir projenin kaydının yerine geçemez (bilgi o projeden kaybolur)."
    if any(o["visibility"] == "project" for o in eskiler):
        projeler = {o["project"] for o in eskiler}
        if len(projeler) > 1:
            return "Farklı projelerin projeye özel kayıtları birleştirilemez."
        if any(o["visibility"] == "shared" for o in eskiler):
            return "Projeye özel ve ortak kayıtlar birleştirilemez (özel bilgi öbür projelere taşınır)."
    if yeni["visibility"] == "project" and any(o["visibility"] == "shared" for o in eskiler):
        return "Ortak bir kayıt projeye özel bir kayıtla değiştirilemez (öbür projelerden silinmiş olur). Görünürlüğü 'ortak' bırak."
    if yeni["trust"] == "external" and any(o["trust"] == "user" for o in eskiler):
        return "Dış kaynak güvenli bir kayıt, kullanıcının söylediği bir kaydın yerine geçemez."
    en_dusuk = min((GUVEN_SIRA[o["trust"]] for o in eskiler), default=2)
    if GUVEN_SIRA[yeni["trust"]] > en_dusuk and not guven_onay:
        return "Güven yükseltiliyor (ör. dış kaynak → kullanıcı). Bilgiyi doğruladıysan güveni bilerek seçip onayla."
    return None


def neden_al(v: dict, varsayilan: str = "") -> tuple[str | None, str | None]:
    neden = v.get("neden") or ""
    if not isinstance(neden, str):
        return None, "Geçersiz neden."
    neden = neden.strip()[:300] or varsayilan
    if find_secrets(neden):
        return None, "Kaydedilmedi: neden alanında gizli bilgi var. Şifre, anahtar, IBAN ya da kimlik numarası yazma."
    return neden, None


def hedef_proje(eskiler: list[dict], yeni: dict) -> str:
    projeler = {o["project"] for o in eskiler}
    if len(projeler) == 1:
        return projeler.pop()
    return "genel"


def oneriler(denetim_dir: Path, store) -> list[dict]:
    """Denetim ajanının hafıza çelişki bulguları (model katmanı ve açık görevler), kayıtlarıyla birlikte."""
    son = denetim_dir / "son.json"
    if not son.exists():
        return []
    try:
        rapor = json.loads(son.read_text(encoding="utf-8"))
    except ValueError:
        return []
    out = []
    for b in rapor.get("bulgular", []):
        bid = str(b.get("id", ""))
        if not (bid.startswith("model-") or bid.startswith("gorev-")):
            continue
        ids = list(dict.fromkeys(KID.findall(bid + " " + str(b.get("baslik", "")))))
        kayitlar = [disa(r) for r in (store.get(i) for i in ids) if r]
        if not kayitlar:
            continue
        tur = "gorev" if bid.startswith("gorev-") else (bid.split("-")[1] if bid.count("-") >= 2 else "celiski")
        out.append({"id": bid, "tur": tur, "baslik": b.get("baslik", ""), "ayrinti": b.get("ayrinti", ""),
                    "kayitlar": kayitlar, "zaman": rapor.get("zaman"),
                    "acik": all(k["durum"] == "guncel" for k in kayitlar)})
    return out


# ------------------------------------------------------------------ rotalar
def kaydet(mcp, auth, store, girisli, cerez: str, guvenlik: dict, denetim_dir: Path) -> None:
    from starlette.responses import FileResponse, JSONResponse

    from . import search

    def j(v, code=200):
        return JSONResponse(v, status_code=code, headers=guvenlik)

    def csrf_tamam(request) -> bool:
        site = request.headers.get("sec-fetch-site")
        if site and site not in ("same-origin", "none"):
            return False
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if origin.split("://", 1)[-1].rstrip("/") != host:
                return False
        verilen = request.headers.get("x-csrf", "")
        beklenen = csrf_belirteci(auth.admin_hash or "", request.cookies.get(cerez, ""))
        return bool(verilen) and hmac.compare_digest(verilen, beklenen)

    async def govde(request) -> dict | None:
        if not request.headers.get("content-type", "").startswith("application/json"):
            return None
        try:
            v = json.loads(await request.body())
        except ValueError:
            return None
        return v if isinstance(v, dict) else None

    def ilgili(kayitlar: list[dict], soru: str) -> list[dict]:
        """Arama sonuçları: kelime eşleşmesi (BM25 > 0) ya da yeterince yakın anlam (kosinüs >= ESIK). Gömme açıkken
        search.rank hiçbir kaydı elemediği için eşik burada uygulanır."""
        if not kayitlar:
            return []
        bm = search.bm25_scores([search.doc_text(r) for r in kayitlar], soru)
        gecer = {r["id"] for r, b in zip(kayitlar, bm) if b > 0}
        if search.embed_enabled():
            try:
                q = search.embed([soru])[0]
                for r in kayitlar:
                    if r.get("embedding"):
                        e = np.frombuffer(r["embedding"], dtype=np.float32)
                        if e.shape == q.shape and float(e @ q) >= ANLAM_ESIK:
                            gecer.add(r["id"])
            except Exception:
                pass
        return [r for r in search.rank(kayitlar, soru) if r["id"] in gecer]

    def vektor(rec: dict) -> None:
        if search.embed_enabled():
            try:
                rec["embedding"] = search.embed([search.doc_text(rec)])[0].tobytes()
            except Exception:
                rec.pop("embedding", None)
            rec["emb_model"] = search.EMBED_MODEL

    def yaz_korumali(fn):
        """Oturum + CSRF + JSON gövdesi denetimi; işi olay döngüsünü tıkamadan ayrı iş parçacığında çalıştırır."""
        async def sarmal(request):
            if not girisli(request):
                return j({"hata": "Giriş gerekli."}, 401)
            if not csrf_tamam(request):
                return j({"hata": "İstek doğrulanamadı (CSRF). Sayfayı yenileyip tekrar dene."}, 403)
            v = await govde(request)
            if v is None:
                return j({"hata": "Geçersiz istek gövdesi."}, 400)
            try:
                sonuc, kod = await asyncio.to_thread(fn, v)
            except ValueError as e:
                return j({"hata": str(e)}, 409)
            except Exception:
                logging.getLogger("council.gezgin").exception("gezgin yazma hatası")
                return j({"hata": "Beklenmeyen bir hata oldu; hiçbir şey değiştirilmedi."}, 500)
            return j(sonuc, kod)
        return sarmal

    # ---- sayfa ve dosyalar
    @mcp.custom_route("/panel/gezgin", methods=["GET"], include_in_schema=False)
    async def sayfa(request):
        from starlette.responses import RedirectResponse
        if not girisli(request):
            return RedirectResponse("/panel", status_code=303, headers=guvenlik)
        return FileResponse(BURADA / "gezgin.html", headers=guvenlik)

    for ad, tip in (("gezgin.js", "text/javascript"), ("gezgin.css", "text/css")):
        async def dosya(request, ad=ad, tip=tip):
            return FileResponse(BURADA / ad, media_type=tip, headers=guvenlik)
        mcp.custom_route(f"/panel/gezgin/{ad}", methods=["GET"], include_in_schema=False)(dosya)

    # ---- okuma uçları
    @mcp.custom_route("/panel/gezgin/oturum", methods=["GET"], include_in_schema=False)
    async def oturum(request):
        if not girisli(request):
            return j({"hata": "Giriş gerekli."}, 401)
        return j({"csrf": csrf_belirteci(auth.admin_hash or "", request.cookies.get(cerez, ""))})

    @mcp.custom_route("/panel/gezgin/kayitlar", methods=["GET"], include_in_schema=False)
    async def kayitlar(request):
        if not girisli(request):
            return j({"hata": "Giriş gerekli."}, 401)
        p = dict(request.query_params)

        def is_():
            soru = (p.get("q") or "").strip()[:300]
            tum = store.list_records(with_embedding=bool(soru) and search.embed_enabled())
            secim = suz(tum, p)
            if soru:
                tam = [r for r in secim if r["id"].upper() == soru.upper()]
                secim = tam or ilgili(secim, soru)
            else:
                sira = p.get("sira", "yeni")
                secim.sort(key=lambda r: (etkin_tarih(r), r["created_at"]), reverse=(sira != "eski"))
            try:
                sayfa_no = max(0, int(p.get("sayfa", "0")))
            except ValueError:
                sayfa_no = 0
            sayfa_no = min(sayfa_no, max(0, (len(secim) - 1) // SAYFA))
            parca = secim[sayfa_no * SAYFA:(sayfa_no + 1) * SAYFA]
            return {"toplam": len(secim), "sayfa": sayfa_no, "boyut": SAYFA, "kayitlar": [disa(r) for r in parca],
                    "secenekler": secenekler(tum), "hepsi": len(tum)}
        return j(await asyncio.to_thread(is_))

    @mcp.custom_route("/panel/gezgin/kayit/{rid}", methods=["GET"], include_in_schema=False)
    async def kayit(request):
        if not girisli(request):
            return j({"hata": "Giriş gerekli."}, 401)
        rid = request.path_params["rid"]

        def is_():
            r = store.get(rid)
            if not r:
                return None
            # öncüller: bu kaydın yerine geçtiği kayıtlar; ardıl zinciri: yerine geçen kayıtlar
            oncul = [disa(x) for x in (dict(y) for y in store.q(
                "SELECT id, text, context, keys, kind, visibility, trust, valid_from, valid_to, superseded_by, archived, archive_reason,"
                " tool, project, client_id, created_at FROM records WHERE superseded_by=?", (rid,)))]
            ardil, seen, cur = [], {rid}, r.get("superseded_by")
            while cur and cur not in seen and len(ardil) < 20:
                seen.add(cur)
                x = store.get(cur)
                if not x:
                    break
                ardil.append(disa(x))
                cur = x.get("superseded_by")
            gecmis = [{"zaman": e["ts"], "arac": e["tool"], "proje": e["project"], "islem": e["action"],
                       "ayrinti": {k: v for k, v in e["payload"].items() if k in ("neden", "yerine", "kaynaklar")}}
                      for e in store.record_history(rid)]
            return {"kayit": disa(r), "oncul": oncul, "ardil": ardil, "gecmis": gecmis}
        v = await asyncio.to_thread(is_)
        return j(v) if v else j({"hata": f"{rid} bulunamadı."}, 404)

    @mcp.custom_route("/panel/gezgin/oneriler", methods=["GET"], include_in_schema=False)
    async def oneri(request):
        if not girisli(request):
            return j({"hata": "Giriş gerekli."}, 401)
        return j({"oneriler": await asyncio.to_thread(oneriler, denetim_dir, store)})

    # ---- yazma uçları
    def duzelt(v):
        rid = str(v.get("id", ""))
        o = store.get(rid)
        if not o:
            return {"hata": f"{rid} bulunamadı."}, 404
        if durum(o) != "guncel":
            return {"hata": f"{rid} güncel değil; yalnız güncel kayıtlar düzeltilebilir."}, 409
        rec, hata = dogrula(v)
        if hata:
            return {"hata": hata}, 400
        hata = kural_denetle([o], rec, v.get("guven_onay") is True)
        if hata:
            return {"hata": hata}, 400
        neden, hata = neden_al(v, "elle düzeltildi")
        if hata:
            return {"hata": hata}, 400
        vektor(rec)
        yeni = store.replace_records(Actor(ARAC, o["project"]), [rid], rec, f"Gezgin: düzeltme — {neden}", "duzelt")
        return {"tamam": True, "yeni": yeni, "mesaj": f"{rid} düzeltildi; yeni kayıt {yeni}."}, 200

    def birlestir(v):
        if not isinstance(v.get("ids"), list):
            return {"hata": "Birleştirmek için kayıt seç."}, 400
        ids = [x for x in v["ids"] if isinstance(x, str)]
        ids = list(dict.fromkeys(ids))
        if len(ids) < 2 or len(ids) > 20:
            return {"hata": "Birleştirmek için 2 ile 20 arası kayıt seç."}, 400
        eskiler = [store.get(i) for i in ids]
        if not all(eskiler):
            return {"hata": "Seçilen kayıtlardan biri bulunamadı."}, 404
        if any(durum(o) != "guncel" for o in eskiler):
            return {"hata": "Yalnız güncel kayıtlar birleştirilebilir."}, 409
        rec, hata = dogrula(v)
        if hata:
            return {"hata": hata}, 400
        hata = kural_denetle(eskiler, rec, v.get("guven_onay") is True)
        if hata:
            return {"hata": hata}, 400
        if rec["visibility"] == "project" and len({o["project"] for o in eskiler}) > 1:
            return {"hata": "Farklı projelerden kayıtlar projeye özel tek kayıtta birleştirilemez."}, 400
        neden, hata = neden_al(v, "elle birleştirildi")
        if hata:
            return {"hata": hata}, 400
        vektor(rec)
        yeni = store.replace_records(Actor(ARAC, hedef_proje(eskiler, rec)), ids, rec, f"Gezgin: birleştirme — {neden}", "birlestir")
        return {"tamam": True, "yeni": yeni, "mesaj": f"{len(ids)} kayıt {yeni} kaydında birleştirildi."}, 200

    def arsivle(v):
        rid = str(v.get("id", ""))
        o = store.get(rid)
        if not o:
            return {"hata": f"{rid} bulunamadı."}, 404
        neden, hata = neden_al(v)
        if hata:
            return {"hata": hata}, 400
        if len(neden) < 3:
            return {"hata": "Arşivleme nedeni yaz."}, 400
        if not store.archive(Actor(ARAC, o["project"]), rid, f"Gezgin: {neden}"):
            return {"hata": f"{rid} zaten arşivde."}, 409
        return {"tamam": True, "mesaj": f"{rid} arşivlendi."}, 200

    def arsivden_cikar(v):
        rid = str(v.get("id", ""))
        o = store.get(rid)
        if not o:
            return {"hata": f"{rid} bulunamadı."}, 404
        neden, hata = neden_al(v, "elle geri alındı")
        if hata:
            return {"hata": hata}, 400
        if not store.unarchive(Actor(ARAC, o["project"]), rid, f"Gezgin: {neden}"):
            return {"hata": f"{rid} arşivde değil."}, 409
        return {"tamam": True, "mesaj": f"{rid} arşivden çıkarıldı."}, 200

    def gecersiz_kil(v):
        """Öneri ekranı: 'eski' kaydı 'yeni' kayıtla geçersiz kıl (iki kayıt da kalır, eskisi işaretlenir)."""
        eski, yeni = str(v.get("eski", "")), str(v.get("yeni", ""))
        o, n = store.get(eski), store.get(yeni)
        if not o or not n or eski == yeni:
            return {"hata": "Kayıtlar bulunamadı."}, 404
        if durum(o) != "guncel" or durum(n) != "guncel":
            return {"hata": "İki kayıt da güncel olmalı."}, 409
        hata = kural_denetle([o], n, guven_onay=True)   # mevcut iki kayıt; yeni kayıt yazılmıyor, güven yükselmiyor
        if hata:
            return {"hata": hata}, 400
        neden, hata = neden_al(v, "çelişki önerisinden")
        if hata:
            return {"hata": hata}, 400
        if not store.supersede(Actor(ARAC, o["project"]), eski, yeni, f"Gezgin: {neden}"):
            return {"hata": f"{eski} değiştirilemedi."}, 409
        return {"tamam": True, "mesaj": f"{eski} geçersiz kılındı, yerine {yeni}."}, 200

    for yol, fn in (("duzelt", duzelt), ("birlestir", birlestir), ("arsivle", arsivle),
                    ("arsivden-cikar", arsivden_cikar), ("gecersiz-kil", gecersiz_kil)):
        mcp.custom_route(f"/panel/gezgin/{yol}", methods=["POST"], include_in_schema=False)(yaz_korumali(fn))

    _ = os
