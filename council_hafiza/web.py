"""Panel sayfalarının ortak web koruması (Gezgin ve uygulamalar): oturum denetimi, CSRF, JSON gövdesi, hata sarmalayıcı.

Yazma uçları yalnız JSON kabul eder ve oturumdan türetilen bir CSRF belirteci ister (X-CSRF başlığı); ayrıca tarayıcı
başka bir siteden geldiğini bildiriyorsa (Origin / Sec-Fetch-Site) istek reddedilir.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging

from .store import Cakisma


def csrf_belirteci(admin_hash: str, oturum: str) -> str:
    anahtar = hashlib.sha256(("council-gezgin-csrf:" + (admin_hash or "")).encode()).digest()
    return hmac.new(anahtar, (oturum or "").encode(), hashlib.sha256).hexdigest()


class Koruma:
    def __init__(self, auth, girisli, cerez: str, guvenlik: dict, gunluk: str = "council.panel"):
        self.auth, self.girisli, self.cerez, self.guvenlik, self.gunluk = auth, girisli, cerez, guvenlik, gunluk

    def j(self, v, code: int = 200):
        from starlette.responses import JSONResponse
        return JSONResponse(v, status_code=code, headers=self.guvenlik)

    def belirtec(self, request) -> str:
        return csrf_belirteci(self.auth.admin_hash or "", request.cookies.get(self.cerez, ""))

    def csrf_tamam(self, request) -> bool:
        site = request.headers.get("sec-fetch-site")
        if site and site not in ("same-origin", "none"):
            return False
        origin = request.headers.get("origin")
        if origin:
            host = request.headers.get("host", "")
            if origin.split("://", 1)[-1].rstrip("/") != host:
                return False
        verilen = request.headers.get("x-csrf", "")
        return bool(verilen) and hmac.compare_digest(verilen, self.belirtec(request))

    @staticmethod
    async def govde(request) -> dict | None:
        if not request.headers.get("content-type", "").startswith("application/json"):
            return None
        try:
            v = json.loads(await request.body())
        except ValueError:
            return None
        return v if isinstance(v, dict) else None

    def oku(self, fn):
        """Okuma ucu: oturum denetimi; fn(request) -> gövde ya da (gövde, kod). İş ayrı iş parçacığında çalışır."""
        async def sarmal(request):
            if not self.girisli(request):
                return self.j({"hata": "Giriş gerekli."}, 401)
            try:
                v = await asyncio.to_thread(fn, request)
            except Exception:
                logging.getLogger(self.gunluk).exception("okuma hatası")
                return self.j({"hata": "Beklenmeyen bir hata oldu."}, 500)
            return self.j(*v) if isinstance(v, tuple) else self.j(v)
        return sarmal

    def yaz(self, fn):
        """Yazma ucu: oturum + CSRF + JSON gövdesi denetimi; fn(gövde) -> (sonuç, kod). İşi olay döngüsünü tıkamadan
        ayrı iş parçacığında çalıştırır."""
        async def sarmal(request):
            if not self.girisli(request):
                return self.j({"hata": "Giriş gerekli."}, 401)
            if not self.csrf_tamam(request):
                return self.j({"hata": "İstek doğrulanamadı (CSRF). Sayfayı yenileyip tekrar dene."}, 403)
            v = await self.govde(request)
            if v is None:
                return self.j({"hata": "Geçersiz istek gövdesi."}, 400)
            try:
                sonuc, kod = await asyncio.to_thread(fn, v)
            except Cakisma as e:
                return self.j({"hata": str(e)}, 409)
            except Exception:
                logging.getLogger(self.gunluk).exception("yazma hatası")
                return self.j({"hata": "Beklenmeyen bir hata oldu; hiçbir şey değiştirilmedi."}, 500)
            return self.j(sonuc, kod)
        return sarmal
