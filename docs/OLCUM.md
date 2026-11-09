# Ölçüm

# Sonuç: yerel (klasör) sürümde arama motoru

*9 Kasım 2026. Ön kayıt ve sapma: `ONKAYIT.md`. Ham tablo: `RAPOR-ham.md`.*

| Kol | n | Doğruluk | %95 GA | Fark (`v01-ajansiz` −), %95 GA |
|---|---|---|---|---|
| `v01-ajansiz`: BGE-M3 + BM25 (sunucudaki yapılandırma; 7 Kasım'da ölçüldü) | 504 | %91,9 | 87,7–95,8 | — |
| `yerel-hafif`: yalnız BM25, ilk 20 puanı 0 olanlarla doldurulur | 504 | %91,3 | 86,9–95,2 | +0,6 [−0,4, +2,0] |
| **`yerel-hafif-sifirsiz`: yalnız BM25, kurulan sürümün davranışı** | 504 | **%90,7** | 86,1–94,6 | **+1,2 [−0,2, +3,2]** |

**Karar (ön kayıttaki kurala göre):** kurulan hafif sürümün farkının GA üst sınırı (+3,2) eşiğin (+2,5) üstünde.
**Yerel sürümde anlamsal arama (BGE-M3) varsayılan olarak açık**; yalnız kelime araması `kur.py --vektorsuz` ile
seçilebilir (disk ya da bellek azsa kurucu kendisi kapatır ve söyler).

## Nasıl karar verildi
- İlk ölçülen kol (`yerel-hafif`) eşiği geçti. Bağımsız inceleme bu kolun kurulan sürümden ayrıldığını buldu: test
  kolu ilk 20'yi hiç ortak kök içermeyen kayıtlarla dolduruyordu, kurulan sürüm bunları atıyor. Kurulan davranışla
  yeniden ölçüldü (`yerel-hafif-sifirsiz`) ve bu kol eşiği geçemedi. Kural sonuç görüldükten sonra değiştirilmedi;
  "doldurma" davranışını kurulan sürüme almak test kümesine bakarak ayar yapmak olacağı için yapılmadı.
- Ayrışan soru sayısı az: `yerel-hafif-sifirsiz` ile 4 soru (Q171, Q191 tamamen; Q117 3 tekrarın 1'inde referans
  lehine; Q151 1'inde hafif lehine). Sonuç birkaç soruya duyarlı; iki sürüm arasındaki fark küçük ve belirsiz.
- Eşik (+2,5), daha önce ölçülen `v01-vektorsuz` sonucu (GA üst sınırı +2,2) bilinerek seçildi.

## Soru türüne göre (betimleyici)
Diller arası sorular: anlamsal arama %92, hafif sürüm %83 (az soru). Zehirli içerik: %75'e karşı %67. Diğer türler
aynı ya da hafif sürüm lehine (kapsam %94'e karşı %92).

## Sınırlar
- Tek sentetik veri seti (63 oturum, ~80 bin token'lık geçmiş), Claude hakemi (Opus), cevaplayan Sonnet.
- Referans kol 7 Kasım'da, adaylar 9 Kasım'da koşuldu (aynı sorular, aynı puanlama); model sürümü satırlara
  yazılmadığı için aynı olduğu doğrulanamıyor. Gecikmeler farklı günlerde ölçüldüğü için karşılaştırılmaz.
- `yerel-hafif`'in 1. tekrarındaki 10 satır, ön kayıttan sonra aynı kodla yapılan `--limit` duman testinden geldi.
- Uzun geçmişte (binlerce kayıt) iki sürümün nasıl ayrıştığı ölçülmedi.


## Ön kayıt: yerel (klasör) sürümde arama motoru seçimi

*Yazıldığı tarih: 9 Kasım 2026, ölçüm başlamadan önce.*

## Soru
Kardeşin Windows bilgisayarına kurulacak yerel sürümde arama, BGE-M3 vektör modeli olmadan (yalnız BM25 + Türkçe kök) yeterince iyi mi? Vektör modeli yaklaşık 2,5 GB indirme (torch + model) ve 2–3 GB bellek istiyor; Windows'ta otomatik kurulumun en kırılgan parçası.

## Kollar
- **Referans:** `v01-ajansiz` (BGE-M3 + BM25, k=20, seçici ajan yok). Sunucuda çalışan yapılandırma. Sonucu 7 Kasım test turundan (aynı 168 test sorusu, 3 tekrar) alınır, yeniden çalıştırılmaz.
- **Aday:** `yerel-hafif` (yalnız BM25, k=20, seçici ajan yok). Yeni kol; tek fark vektör aramanın olmaması.

Daha önce ölçülen `v01-vektorsuz` (seçici ajanlı, vektörsüz) %90,9 aldı; ajanlı sürümle farkı +0,6 puan [−0,8, +2,2]. Aday onu ajansız haliyle ölçer. Seçim dev kümesinde değil, doğrudan test kümesinde yapılıyor: yeni bir ayar aranmıyor, mevcut iki yapılandırmadan biri seçiliyor. Bu yüzden ayar/test bölmesi kuralı ihlal edilmiyor; yine de bu kayıttan sonra hiçbir ayar değiştirilmeyecek.

## Ölçüm
`python -m council_eval.run ask --split test --runs 3 --arms yerel-hafif`, ardından `report --split test --ref v01-ajansiz`. Cevaplayan Sonnet, hakem Opus (yalnız kural eşleşmeyince), yardımcılar Haiku; puanlama değişmedi.

## Karar kuralı
Fark = `v01-ajansiz` − `yerel-hafif` (aynı sorular, bootstrap %95 GA).
- GA'nın **üst sınırı < +2,5 puan** ise hafif sürüm varsayılan olur; vektör modeli isteğe bağlı kurulur (`--vektor`).
- Değilse tam sürüm (BGE-M3) varsayılan olur ve kurulum onu da indirir.
- Diller arası (crosslang) sorular ayrıca raporlanır (az soru, yalnız betimleyici; kararı değiştirmez).

## Sınırlar
Tek sentetik veri seti, Claude hakemi, kısa geçmiş (~80 bin token). Kardeşin gerçek kullanımı ölçülmedi.

## Sapma (9 Kasım 2026, ilk sonuçtan sonra)
Bağımsız inceleme, ölçülen `yerel-hafif` kolunun kurulan sürümden bir noktada ayrıldığını buldu: test kolu ilk 20'yi
puanı 0 olan (hiç ortak kök içermeyen) kayıtlarla dolduruyor, canlı `search.rank` ise yalnız BM25 varken bunları atıyor.
Kurulan sürümün davranışını ölçmek için `yerel-hafif-sifirsiz` kolu eklendi (tek fark bu filtre) ve aynı 168 soru,
3 tekrarla, **aynı karar kuralıyla** ölçülüyor. Karar bu kolun sonucuna göre verilir; `yerel-hafif` sonucu da raporda kalır.
Referans kol `v01-ajansiz` 7 Kasım'da koşuldu (ilk metinde yanlışlıkla 8 Kasım yazıyordu); gecikmeler farklı günlerde
ölçüldüğü için karşılaştırılmaz. `yerel-hafif`'in 1. tekrarındaki 10 satır, ön kayıttan sonra aynı kodla yapılan
`--limit` duman testinden geldi (n=504 bunları içeriyor).


## 8 Kasım 2026 test turu (bütün kollar)


Cevaplayan model: sonnet · hakem (yalnız kural eşleşmeyince): opus · yardımcı ajanlar: haiku

| Kol | n | Doğruluk | %95 GA | Ana ajan giriş token (ort.) | Yardımcı token (ort.) | Liste fiyatı $/soru | Gecikme sn (medyan) |
|---|---|---|---|---|---|---|---|
| tum-gecmis | 504 | 99.0% | 97.4%–100.0% | 82,535 | 0 | 0.0134 | 3.6 |
| oracle | 504 | 92.7% | 88.7%–96.4% | 1,851 | 0 | 0.0045 | 4.3 |
| v01-ajansiz | 504 | 91.9% | 87.7%–95.8% | 4,286 | 0 | 0.0075 | 4.7 |
| v01-kapsamsiz | 504 | 91.7% | 87.3%–95.6% | 2,105 | 4,652 | 0.0055 | 0.0 |
| council-v01 | 504 | 91.5% | 86.9%–95.4% | 2,069 | 4,534 | 0.0053 | 3.2 |
| v01-bm25siz | 504 | 91.5% | 86.9%–95.4% | 2,085 | 4,657 | 0.0053 | 4.6 |
| v01-basliksiz | 504 | 91.3% | 86.7%–95.2% | 2,090 | 4,456 | 0.0053 | 6.1 |
| v01-vektorsuz | 504 | 90.9% | 86.3%–94.8% | 2,074 | 4,488 | 0.0053 | 4.0 |
| council | 504 | 88.7% | 83.9%–93.1% | 1,944 | 3,108 | 0.0051 | 5.1 |
| sozcuk-kasasi | 504 | 76.6% | 70.0%–82.7% | 3,690 | 0 | 0.0068 | 2.8 |
| duz-dosya | 504 | 73.6% | 66.7%–80.0% | 14,859 | 0 | 0.0057 | 3.3 |
| hafizasiz | 504 | 19.0% | 13.1%–25.0% | 1,767 | 0 | 0.0039 | 2.9 |
| plasebo | 504 | 19.0% | 13.1%–25.0% | 2,017 | 0 | 0.0044 | 4.3 |

## Soru türüne göre doğruluk

| Kol | abstain | crosslang | multihop | no_diacritic | poison | scope | secret | single | temporal | update |
|---|---|---|---|---|---|---|---|---|---|---|
| council-v01 | 100% | 92% | 71% | 100% | 78% | 92% | 100% | 95% | 85% | 100% |
| tum-gecmis | 100% | 100% | 98% | 100% | 89% | 100% | 100% | 100% | 100% | 100% |
| duz-dosya | 100% | 75% | 56% | 92% | 81% | 83% | 100% | 62% | 35% | 96% |
| sozcuk-kasasi | 100% | 42% | 75% | 92% | 83% | 100% | 100% | 62% | 60% | 92% |
| hafizasiz | 100% | 0% | 0% | 0% | 0% | 100% | 100% | 0% | 0% | 0% |
| oracle | 100% | 100% | 100% | 100% | 97% | 3% | 100% | 99% | 100% | 100% |
| plasebo | 100% | 0% | 0% | 0% | 0% | 92% | 100% | 0% | 0% | 4% |
| council | 100% | 83% | 69% | 100% | 69% | 92% | 100% | 93% | 82% | 96% |
| v01-ajansiz | 100% | 92% | 77% | 100% | 75% | 92% | 100% | 95% | 85% | 100% |
| v01-basliksiz | 100% | 100% | 79% | 100% | 67% | 92% | 100% | 95% | 78% | 100% |
| v01-kapsamsiz | 100% | 92% | 92% | 100% | 78% | 67% | 100% | 95% | 85% | 100% |
| v01-bm25siz | 100% | 100% | 75% | 100% | 67% | 92% | 100% | 95% | 85% | 99% |
| v01-vektorsuz | 100% | 83% | 75% | 100% | 75% | 92% | 100% | 95% | 83% | 100% |

## council-v01 ile eşleştirilmiş fark (aynı sorular, bootstrap %95 GA)

| Karşılaştırma | Fark | %95 GA |
|---|---|---|
| council-v01 − tum-gecmis | -7.5% | -12.3% … -3.4% |
| council-v01 − oracle | -1.2% | -7.1% … +4.4% |
| council-v01 − v01-ajansiz | -0.4% | -1.4% … +0.4% |
| council-v01 − v01-kapsamsiz | -0.2% | -3.0% … +2.6% |
| council-v01 − v01-bm25siz | -0.0% | -2.6% … +2.6% |
| council-v01 − v01-basliksiz | +0.2% | -2.0% … +2.6% |
| council-v01 − v01-vektorsuz | +0.6% | -0.8% … +2.2% |
| council-v01 − council | +2.8% | +0.8% … +5.4% |
| council-v01 − sozcuk-kasasi | +14.9% | +7.9% … +21.8% |
| council-v01 − duz-dosya | +17.9% | +10.3% … +25.4% |
| council-v01 − hafizasiz | +72.4% | +65.5% … +79.4% |
| council-v01 − plasebo | +72.4% | +65.7% … +79.0% |

Puanlama: {'kural': 6440, 'hakem': 112} · hata: 0

## Arama testi (LLM'siz, 170 soru, kanıt oturumu ilk k içinde mi)

| Yöntem | R@1 | R@3 | R@5 | R@10 |
|---|---|---|---|---|
| ham/bm25 | 0.546 | 0.833 | 0.867 | 0.903 |
| ham/qwen3 | 0.490 | 0.780 | 0.861 | 0.956 |
| ham/bge-m3 | 0.585 | 0.862 | 0.924 | 0.954 |
| ham/hibrit-qwen3 | 0.543 | 0.846 | 0.893 | 0.946 |
| ham/hibrit-bge-m3 | 0.556 | 0.842 | 0.889 | 0.944 |
| sozcuk-kasasi | 0.426 | 0.704 | 0.756 | 0.814 |
| council | 0.620 | 0.869 | 0.927 | 0.952 |
| council-bm25 | 0.603 | 0.858 | 0.906 | 0.924 |
| council-vektor | 0.580 | 0.851 | 0.917 | 0.937 |
| council-bge | 0.629 | 0.887 | 0.930 | 0.949 |
| council-basliksiz | 0.573 | 0.816 | 0.891 | 0.934 |
| council-kapsamsiz | 0.617 | 0.875 | 0.926 | 0.954 |
