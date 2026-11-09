"""Sistem paneli: denetim ajanının raporunu (son.json) gösteren, yönetici parolasıyla korunan web arayüzü (/panel).

Oturum: imzalı, süreli çerez (HttpOnly, Secure, SameSite=Strict, Path=/panel). İmza anahtarı yönetici parola özetinden
türetilir; parola değişince bütün oturumlar düşer. Hatalı girişler OAuth girişiyle aynı sınıra (15 dakikada 5) tabidir.
Sayfa dış kaynak yüklemez; CSP ile yalnız kendi betiğine izin verilir.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import os
import time
from pathlib import Path

OTURUM_SURE = 12 * 3600
CEREZ = "council_panel"
BURADA = Path(__file__).resolve().parent
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; connect-src 'self'; img-src 'self' data:; "
       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
# Kimlik yazıları (fontlar/): yalnız bu listedekiler sunulur. Gizli bir şey değil; giriş sayfası da kullanır, önbelleğe alınabilir.
FONTLAR = {"Anton-Regular.ttf": "font/ttf", "IBMPlexMono-Regular.ttf": "font/ttf", "IBMPlexMono-Medium.ttf": "font/ttf",
           "COUNCIL-Kapsul-Kalin.otf": "font/otf"}
GUVENLIK = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Cache-Control": "no-store", "X-Frame-Options": "DENY", "Strict-Transport-Security": "max-age=31536000"}


def _anahtar(admin_hash: str) -> bytes:
    return hashlib.sha256(("council-panel:" + (admin_hash or "")).encode()).digest()


def oturum_imzala(admin_hash: str, simdi: float | None = None) -> str:
    bitis = int((simdi or time.time()) + OTURUM_SURE)
    imza = hmac.new(_anahtar(admin_hash), str(bitis).encode(), hashlib.sha256).hexdigest()
    return f"{bitis}.{imza}"


def oturum_gecerli(admin_hash: str, deger: str | None, simdi: float | None = None) -> bool:
    if not admin_hash or not deger or "." not in deger:
        return False
    bitis, imza = deger.split(".", 1)
    if not (bitis.isascii() and bitis.isdigit()) or len(bitis) > 12 or int(bitis) < (simdi or time.time()):
        return False
    beklenen = hmac.new(_anahtar(admin_hash), bitis.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(beklenen, imza)


def panel_verisi(denetim_dir: Path) -> dict:
    son = denetim_dir / "son.json"
    if not son.exists():
        return {"hazir": False}
    rapor = json.loads(son.read_text(encoding="utf-8"))
    gecmis = []
    for p in sorted((denetim_dir / "gecmis").glob("*.json"))[-21:]:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            gecmis.append({"zaman": d.get("zaman"), "ozet": d.get("ozet", {})})
        except Exception:
            continue
    return {"hazir": True, "rapor": rapor, "gecmis": gecmis}


def _giris_sayfasi(mesaj: str | None = None) -> str:
    m = f'<p class="hata">{html.escape(mesaj)}</p>' if mesaj else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>COUNCIL paneli</title><link rel="stylesheet" href="/panel/kimlik.css"><link rel="stylesheet" href="/panel/panel.css"></head>
<body class="giris"><form method="post" action="/panel/giris" class="kart">
<div class="marka"><span class="isaret" data-isaret aria-hidden="true"></span>
<h1 class="marka-ad"><span class="kucuk" lang="en">COUNCIL</span><span class="buyuk">Panel</span></h1></div>
<p class="soluk">Yönetici parolasıyla gir (claude.ai bağlantısındaki parola).</p>{m}
<label><span class="et">Yönetici parolası</span>
<input type="password" name="parola" autocomplete="current-password" required autofocus></label>
<button class="dugme vurgu" type="submit">Giriş</button></form><script src="/panel/kimlik.js"></script></body></html>"""


def kaydet(mcp, auth, store) -> None:
    """Panel rotalarını MCP sunucusuna ekler (yalnız OAuth/yönetici parolası açıkken)."""
    from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response

    from .auth import check_password, istemci_ip

    denetim_dir = Path(os.environ.get("COUNCIL_DENETIM_DIR") or Path(store.path).parent / "denetim")

    def girisli(request) -> bool:
        return oturum_gecerli(auth.admin_hash or "", request.cookies.get(CEREZ))

    @mcp.custom_route("/panel", methods=["GET"], include_in_schema=False)
    async def panel(request):
        if not girisli(request):
            return HTMLResponse(_giris_sayfasi(), headers=GUVENLIK)
        return FileResponse(BURADA / "panel.html", headers=GUVENLIK)

    @mcp.custom_route("/panel/giris", methods=["POST"], include_in_schema=False)
    async def panel_giris(request):
        form = await request.form()   # gövde ÖNCE okunur: denetim, karşılaştırma ve kayıt arasında bekleme olmasın (yarış)
        ip = istemci_ip(request)
        if auth.giris_engelli(ip):
            return HTMLResponse(_giris_sayfasi("Çok fazla hatalı deneme. 15 dakika sonra tekrar dene."), status_code=429, headers=GUVENLIK)
        ok = bool(auth.admin_hash) and check_password(str(form.get("parola", "")), auth.admin_hash)
        auth.giris_kaydet(ip, ok)
        store.log(None, "panel_giris", None, {"basarili": ok})
        if not ok:
            await asyncio.sleep(1.0)
            return HTMLResponse(_giris_sayfasi("Parola yanlış."), status_code=401, headers=GUVENLIK)
        r = RedirectResponse("/panel", status_code=303, headers=GUVENLIK)
        r.set_cookie(CEREZ, oturum_imzala(auth.admin_hash), max_age=OTURUM_SURE, path="/panel", secure=True, httponly=True,
                     samesite="strict")
        return r

    @mcp.custom_route("/panel/cikis", methods=["POST"], include_in_schema=False)
    async def panel_cikis(request):
        r = RedirectResponse("/panel", status_code=303, headers=GUVENLIK)
        r.delete_cookie(CEREZ, path="/panel")
        return r

    @mcp.custom_route("/panel/veri", methods=["GET"], include_in_schema=False)
    async def panel_veri(request):
        if not girisli(request):
            return JSONResponse({"hata": "giriş gerekli"}, status_code=401, headers=GUVENLIK)
        return JSONResponse(panel_verisi(denetim_dir), headers=GUVENLIK)

    @mcp.custom_route("/panel/panel.js", methods=["GET"], include_in_schema=False)
    async def panel_js(request):
        return FileResponse(BURADA / "panel.js", media_type="text/javascript", headers=GUVENLIK)

    @mcp.custom_route("/panel/panel.css", methods=["GET"], include_in_schema=False)
    async def panel_css(request):
        return FileResponse(BURADA / "panel.css", media_type="text/css", headers=GUVENLIK)

    # Ortak kimlik (panel, Gezgin, giriş sayfası): renkler ve yazılar, işaret, yazı dosyaları
    @mcp.custom_route("/panel/kimlik.css", methods=["GET"], include_in_schema=False)
    async def kimlik_css(request):
        return FileResponse(BURADA / "kimlik.css", media_type="text/css", headers=GUVENLIK)

    @mcp.custom_route("/panel/kimlik.js", methods=["GET"], include_in_schema=False)
    async def kimlik_js(request):
        return FileResponse(BURADA / "kimlik.js", media_type="text/javascript", headers=GUVENLIK)

    @mcp.custom_route("/panel/font/{ad}", methods=["GET"], include_in_schema=False)
    async def font(request):
        ad = request.path_params["ad"]
        if ad not in FONTLAR:                                # yalnız listedeki adlar: yol içeren ya da başka dosya isteyen 404 alır
            return Response(status_code=404, headers=GUVENLIK)
        return FileResponse(BURADA / "fontlar" / ad, media_type=FONTLAR[ad],
                            headers={**GUVENLIK, "Cache-Control": "public, max-age=604800"})

    from .gezgin import kaydet as gezgin_kaydet
    gezgin_kaydet(mcp, auth, store, girisli, CEREZ, GUVENLIK, denetim_dir)

    _ = Response
