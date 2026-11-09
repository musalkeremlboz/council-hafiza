# COUNCIL hafıza

Claude Code için kalıcı, yerel bir hafıza. Bir klasöre kurulur; Claude Code o klasörde her oturum açtığında hafıza özetini
alır, gerektiğinde arar ve yeni bilgileri kaydeder. Sunucu, hesap ya da API anahtarı gerekmez.

## Kurulum
Bir klasör oluşturun (örn. `Belgeler\Beynim`), Claude Code'u o klasörde açın ve şunu yazın:

> https://raw.githubusercontent.com/musalkeremlboz/council-hafiza/main/kur.md adresini oku. Bu klasöre COUNCIL hafızamı kur. Mevcut kurulum varsa notlarımı koruyarak güncelle. Gerekli indirme ve kurulum adımlarını sen yap. Sonunda örnek bir bilgiyi kaydedip yeni oturumda geri okuyarak birlikte doğrulayalım.

Ajan son sürümü indirir, SHA-256 ile doğrular, kurar ve sağlık kontrolünü çalıştırır. Sizden yalnız Claude Code'un onay
ekranlarını onaylamanız istenir. Elle kurulum: [Releases](https://github.com/musalkeremlboz/council-hafiza/releases)
sayfasından `council-hafiza-X.Y.Z.zip` dosyasını indirip açın ve `py -3 kur.py --klasor "C:\...\Beynim"`
(macOS/Linux: `python3 kur.py --klasor ~/Beynim`) çalıştırın.

Gerekenler: Windows 10/11, macOS ya da Linux; Python 3.11–3.13 (yoksa ajan kurar); Claude Code; ~5 GB boş disk ve
8 GB bellek (anlamsal arama modeli için; daha azı için `--vektorsuz`). Kâtip ve bakım için Claude aboneliği (Pro/Max) ya
da Claude Code'un çalıştığı herhangi bir giriş.

## Ne yapar
- **Hafıza araçları (MCP):** `hafiza_ozet`, `hafiza_ara`, `hafiza_kaydet`, `hafiza_gecersiz_kil`, `hafiza_arsivle`,
  `kimlik_tanimla`. Her kayıt tek bir bilgidir; eskiyen bilgi silinmez, yenisiyle "geçersiz kılınır".
- **Oturum başı özeti:** her oturumda kimlik, son kayıtlar ve sayılar otomatik gelir.
- **Kâtip:** konuşma bittiğinde (ya da uzadığında) kalıcı bilgileri kendisi çıkarıp kaydeder (Haiku). Gizli bilgiler
  (şifre, token, IBAN, kart, TC kimlik no) model çağrısından önce temizlenir ve hiç kaydedilmez.
- **Bakım:** günde en çok bir kez tekrarları arşivler, tamamlanmış ve çelişen kayıtları geçersiz kılar (Sonnet).
- **Yedek:** her gün `.council/yedek/` altına (14 gün); her güncellemeden önce ayrıca.
- **Güncelleme bildirimi:** yeni bir sürüm yayımlanınca oturum başında Claude size söyler; onaylarsanız notlarınızı
  koruyarak günceller. Bunun için günde en çok bir kez GitHub'dan yalnız son sürüm numarası okunur (veri gönderilmez);
  kapatmak için veri klasöründeki `ayar.json`'a `"guncelleme_denetimi": false` yazın.
- **Arama:** BM25 (Türkçe kök bulma, Türkçe karaktersiz yazıma duyarsız) + anlamsal arama (BGE-M3, çok dilli; ilk
  kurulumda ~2,5 GB indirilir, çalışırken 2–3 GB bellek). `--vektorsuz` ile yalnız kelime araması.

## Kanıt
Bileşenler kurgusal bir kişinin 63 oturumluk geçmişinden üretilmiş, tasarım sırasında kullanılmamış 168 soruyla ölçüldü
(Sonnet cevaplar, Opus hakem, 3 tekrar). Varsayılan yapılandırma (BM25 + BGE-M3) **%91,9**; yalnız kelime araması
%90,7 (fark +1,2 puan, %95 GA [−0,2, +3,2]: ön kayıttaki eşiği geçemediği için varsayılan değil; diller arası sorularda
%83'e karşı %92). Karşılaştırma: tek dosyalık hafıza (MEMORY.md tarzı) %73,6, not dosyası + kelime eşleştirme %76,6,
hafızasız %19. Sınırlar: tek sentetik veri seti, Claude hakemi, kısa geçmiş. Ayrıntılar: [docs/OLCUM.md](docs/OLCUM.md).

## Dosyalar
```
<klasör>/CLAUDE.md                    hafıza kuralları (COUNCIL bölümü işaretler arasında; sizin metniniz korunur)
<klasör>/.mcp.json                    "council" MCP sunucusu
<klasör>/.claude/settings.json        4 hook (SessionStart, Stop, PreCompact, SessionEnd)
<klasör>/.claude/settings.local.json  "council" sunucusunun onayı
<klasör>/.council/                    Python ortamı, hafiza.sqlite, yedekler
```
Klasör OneDrive, Dropbox ya da iCloud ile eşitleniyorsa canlı veritabanı ve Python ortamı eşitlemeye girmesin diye
yerel uygulama verisine konur (Windows: `%LOCALAPPDATA%\COUNCIL\...`); yeri `.council/konum.json`'da yazar.

## Komutlar
Klasördeki ortamın Python'u ile (`.mcp.json` içindeki `command`): `python -m council_hafiza.yerel <komut>`
- `doktor` sağlık kontrolü · `katip-durum` kâtip günlüğü · `yedekle` elle yedek · `ozet-goster` özet
- `bakim-is --kuru` bakımın önerilerini göster (uygulamadan)

## Geliştirme
```bash
python -m venv .venv && .venv/bin/pip install -e ".[test]"
.venv/bin/python -m pytest -q
```
Sürüm: `pyproject.toml` içindeki `version` artırılıp `vX.Y.Z` etiketi itildiğinde GitHub Actions paketi kurar,
`council-hafiza-X.Y.Z.zip` ve `SHA256SUMS.txt` dosyalarını sürüme ekler.

## Bilinen sınırlar
- SHA-256 doğrulaması paketi indirme hatasına karşı korur; paket ve özet aynı GitHub sürümünden geldiği için deponun
  kendisi ele geçirilirse koruma sağlamaz. Bağımlılıklar (fastmcp, numpy, torch...) PyPI'dan, pakete gömülü kilit
  dosyalarındaki sabit sürüm ve SHA-256 özetleriyle kurulur; kilitte yalnız en az 7 günlük sürümler bulunur.
- Klasörü kopyalarsanız kopyada kurucuyu yeniden çalıştırın; kopya kurulana kadar hafıza kopyada çalışmaz (uyarı verir).

Lisans: Apache-2.0.
