# Kripto Emir Defteri Isı Haritası & Sinyal Motoru

Binance, Bybit ve OKX borsalarından seçili coinlerin Spot ve Vadeli emir defterlerini eş zamanlı çeken, ısı haritası görselleştiren, güçlü seviyelere yaklaşan coinleri skorlayarak Telegram'a PNG kart + ısı haritası gönderen ve Claude API ile meta sinyal üreten yerel Python sistemi.

---

## Hızlı Başlangıç

```bash
# 1. Bağımlılıkları kur
pip install -r requirements.txt

# 2. Ortam değişkenlerini ayarla
cp .env.example .env
# .env dosyasını düzenle: API anahtarlarını gir

# 3. Yapılandırmayı düzenle (isteğe bağlı)
# config.yaml — tüm parametreler buradadır, kod içinde hardcode değer yok

# 4. DRY-RUN ile test et (varsayılan: dry_run: true)
python main.py

# 5. Gerçek modda çalıştır
# config.yaml içinde dry_run: false yap, sonra:
python main.py
```

---

## Proje Yapısı

```
deneme12/
├── config.yaml           # Tüm ayarlar (hardcode değer yok)
├── .env.example          # API anahtarları şablonu
├── requirements.txt      # Python bağımlılıkları
├── main.py               # Ana orkestratör
├── report.py             # CLI başarı raporu
├── src/
│   ├── config.py         # Yapılandırma yükleyici
│   ├── logger_setup.py   # Türkçe log yapılandırması
│   ├── ring_buffer.py    # RAM ring buffer (numpy)
│   ├── ws_manager.py     # WebSocket bağlantı yöneticisi
│   ├── exchange_connectors.py  # Borsa bağlantıları + REST
│   ├── coin_supervisor.py      # Dinamik coin listesi
│   ├── scoring_engine.py       # Skorlama motoru
│   ├── heatmap.py              # PNG ısı haritası üretici
│   ├── telegram_notifier.py    # Telegram gönderici
│   ├── db.py                   # SQLite sinyal logu
│   ├── meta_signal.py          # Claude API meta sinyaller
│   └── health_check.py         # HTTP health check
├── test_phase0.py   # Phase 0 testleri
├── test_phase1.py   # Phase 1 testleri
├── test_phase2.py   # Phase 2 testleri
├── test_phase3.py   # Phase 3 testleri
├── test_phase4.py   # Phase 4 testleri
└── test_phase5.py   # Phase 5 testleri
```

---

## Phase'ler

| Phase | Açıklama |
|-------|----------|
| 0 | `config.yaml` + `.env` + DRY_RUN altyapısı |
| 1 | WebSocket bağlantıları + ring buffer |
| 2 | Skorlama motoru (S1-S4 sinyal türleri) |
| 3 | Isı haritası PNG + Telegram kartı |
| 4 | SQLite sinyal logu + CLI rapor |
| 5 | Claude API meta sinyal motoru |

---

## Testler

```bash
python test_phase0.py   # Yapılandırma testleri
python test_phase1.py   # Ring buffer testleri
python test_phase2.py   # Skorlama testleri
python test_phase3.py   # PNG + Telegram testleri
python test_phase4.py   # SQLite testleri
python test_phase5.py   # Meta sinyal testleri
```

---

## Sinyal Türleri

| Tür | Açıklama | Renk |
|-----|----------|------|
| S1 YAKLAŞIM | Fiyat duvarın yakınında | Sarı |
| S2 ÇİFT ONAY | Spot + Vadeli aynı seviye | Yeşil/Kırmızı |
| S3 CROSS | 2+ borsada eş zamanlı duvar | Güçlü |
| S4 ABSORPSİYON | Büyük duvar yenildi | Sarı uyarı |

---

## Health Check

```bash
curl http://localhost:8080/health
```

---

## CLI Raporu

```bash
python report.py --days 7
```

---

## Önemli Notlar

- `ccxt` / `ccxt.pro` kullanılmaz — doğrudan `websockets` + `aiohttp`
- Tüm parametreler `config.yaml`'dan okunur, kod içinde hardcode değer yok
- Tüm loglar ve Telegram mesajları Türkçe
- Geliştirme için `dry_run: true` kullan
