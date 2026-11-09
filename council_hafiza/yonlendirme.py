"""Model yönlendirme hafızası: hangi işin hangi model/effort ile yapılması gerektiğini geçmiş sonuçlardan önerir.

Yöntem (eval/yonlendirme/ONKAYIT.md): her yapılandırma için kalite ve maliyet, k en yakın geçmiş görevin benzerlik ağırlıklı
ortalaması ile iş türü ortalamasının karışımıyla tahmin edilir; tahmini kalitesi en iyinin en çok δ puan altında kalanlar
arasından en ucuzu seçilir. Geçmiş yoksa veriden önce yazılmış soğuk başlangıç kuralı kullanılır.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

MODELS = ("haiku", "sonnet", "opus")
EFFORTS = ("low", "medium", "high")
CONFIGS = tuple(f"{m}/{e}" for m in MODELS for e in EFFORTS)

TURLER = ("kod-yazma", "hata-bulma", "belge-soru", "veri-cikarma", "siniflandirma", "akil-yurutme", "metin-yazma", "dogrulama")

# Veri görülmeden önce yazıldı (ONKAYIT.md). Bilinmeyen tür için orta yol.
SOGUK = {
    "kod-yazma": "sonnet/medium", "hata-bulma": "sonnet/medium", "belge-soru": "haiku/low", "veri-cikarma": "haiku/low",
    "siniflandirma": "haiku/low", "akil-yurutme": "opus/medium", "metin-yazma": "sonnet/low", "dogrulama": "sonnet/low",
}
VARSAYILAN = "sonnet/medium"


@dataclass
class Ayar:
    k: int = 10                 # en yakın komşu sayısı
    m: float = 2.0              # tür ortalamasının ağırlığı (komşu benzerlik toplamıyla karışır); None = yalnız tür
    delta: float = 2.0          # kalite toleransı (puan, 0-100)
    yalniz_tur: bool = False


CANLI_AYAR = Ayar(k=20, m=2.0, delta=2.0)   # ölçümde dev'de seçilen ayar (eval/yonlendirme/RAPOR.md); canlıda yalnız bilgi
# Ölçümde (eval/yonlendirme/ONKAYIT.md, inceleme düzeltmeleri sonrası) ne kNN yönlendirici ne de en basit sabit kural kalite eşiğini
# geçti: kanıtlanmış bir kural yok, canlıda model önerilmez.
CANLI_KURAL: str | None = None
KURAL_GEREKCESI = ("2026-11-08 ölçümünde (143 görev × 9 yapılandırma) ne benzer işlere bakan yönlendirici ne de tek bir ucuz sabit "
                   "yapılandırma, opus/high ile eş kaliteyi kanıtlayabildi (ucuz seçimler birkaç görevde, özellikle hata bulma ve belge "
                   "sorularında, Haiku'nun hatası yüzünden kalite kaybettirdi). Kanıtlanmış bir öneri olmadığı için ana modeli kullan.")


@dataclass
class Gecmis:
    """Gözlem tablosu: her satır bir (görev, yapılandırma) sonucu."""
    emb: list = field(default_factory=list)     # görev gömmesi (normalize)
    tur: list = field(default_factory=list)
    config: list = field(default_factory=list)
    kalite: list = field(default_factory=list)  # 0-100
    maliyet: list = field(default_factory=list) # USD
    gorev: list = field(default_factory=list)   # görev kimliği (aynı görevin satırlarını gruplamak için)

    def ekle(self, emb, tur, config, kalite, maliyet, gorev=None):
        self.emb.append(np.asarray(emb, dtype=np.float32)); self.tur.append(tur); self.config.append(config)
        self.kalite.append(float(kalite)); self.maliyet.append(float(maliyet)); self.gorev.append(gorev)

    def __len__(self):
        return len(self.config)


def tahmin(g: Gecmis, emb, tur: str, ayar: Ayar, haric: str | None = None) -> dict[str, tuple[float, float, float]]:
    """Her yapılandırma için (tahmini kalite, tahmini maliyet, kanıt gücü). Kanıtı olmayan yapılandırma dönmez."""
    if not len(g):
        return {}
    knn = not ayar.yalniz_tur and ayar.k > 0
    sims = np.stack(g.emb) @ np.asarray(emb, dtype=np.float32) if knn else None
    turs = np.array(g.tur); cfgs = np.array(g.config)
    q = np.array(g.kalite); c = np.array(g.maliyet)
    ok = np.ones(len(g), dtype=bool) if haric is None else np.array([x != haric for x in g.gorev])
    out = {}
    for cfg in CONFIGS:
        sel = ok & (cfgs == cfg)
        if not sel.any():
            continue
        same = sel & (turs == tur)
        base = same if same.any() else sel                       # tür verisi yoksa genel ortalama
        tq, tc, tn = q[base].mean(), c[base].mean(), int(base.sum())
        if not knn:
            out[cfg] = (float(tq), float(tc), float(tn)); continue
        idx = np.where(sel)[0]
        top = idx[np.argsort(-sims[idx])[:ayar.k]]
        w = np.clip(sims[top], 0, None) ** 4                     # yakın komşular baskın
        ws = float(w.sum())
        if ws <= 1e-9:
            out[cfg] = (float(tq), float(tc), float(tn)); continue
        kq = float((w * q[top]).sum() / ws); kc = float((w * c[top]).sum() / ws)
        mm = ayar.m
        out[cfg] = ((ws * kq + mm * tq) / (ws + mm), (ws * kc + mm * tc) / (ws + mm), float(tn + len(top)))
    return out


def sec(g: Gecmis, emb, tur: str, ayar: Ayar, haric: str | None = None) -> tuple[str, dict]:
    """Önerilen yapılandırma ve gerekçe."""
    t = tahmin(g, emb, tur, ayar, haric)
    if not t:
        cfg = SOGUK.get(tur, VARSAYILAN)
        return cfg, {"kaynak": "soğuk başlangıç kuralı", "tahmin": {}}
    best = max(v[0] for v in t.values())
    aday = {k: v for k, v in t.items() if v[0] >= best - ayar.delta}
    cfg = min(aday, key=lambda k: (aday[k][1], -aday[k][0]))
    return cfg, {"kaynak": "geçmiş", "tahmin": {k: (round(v[0], 1), round(v[1], 5), int(v[2])) for k, v in t.items()}}
