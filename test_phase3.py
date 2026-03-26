"""
Phase 3 Test — Isı haritası PNG üretimi ve Telegram notifier.
Kullanım: python test_phase3.py
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging
from src.ring_buffer import RingBufferManager, OrderBookSnapshot
from src.scoring_engine import Signal
from src.heatmap import generate_signal_card
from src.telegram_notifier import TelegramNotifier


def _make_test_signal(direction: str = "destek", signal_type: str = "S2") -> Signal:
    """Test sinyali oluştur."""
    return Signal(
        coin="SOL/USDT",
        level=182.40,
        direction=direction,
        signal_type=signal_type,
        score=9.1,
        spot_total=3_700_000,
        futures_total=8_500_000,
        exchange_count=3,
        weighted_exchange_score=2.3,
        funding_rate=0.012,
        volume_change_pct=340.0,
        distance_pct=0.31,
        confirming_exchanges=["binance", "bybit", "okx"],
    )


def _make_test_buffer(coin: str = "SOL/USDT", current_price: float = 183.0) -> RingBufferManager:
    """Test buffer'ı oluştur."""
    mgr = RingBufferManager()
    mgr.update_extras(coin, last_price=current_price, funding_rate=0.012, volume_change_pct=340.0)

    for i in range(6):
        bids = [[current_price - j * 0.1, 500 + j * 10] for j in range(20)]
        asks = [[current_price + j * 0.1, 400 + j * 10] for j in range(20)]
        # Büyük duvar ekle
        bids[5] = [182.40, 50000]

        snap = OrderBookSnapshot(
            timestamp=time.time() - i * 5 * 60,
            bids=np.array(bids, dtype=np.float64),
            asks=np.array(asks, dtype=np.float64),
            exchange="binance",
            market_type="spot",
        )
        mgr.get_or_create(coin).add_snapshot(snap)

    return mgr


def test_png_generation_support() -> None:
    """PNG üretimi çalışıyor mu?"""
    config.load_config()
    signal = _make_test_signal("destek", "S2")
    buffer = _make_test_buffer()

    png_bytes = generate_signal_card(signal, buffer)
    assert isinstance(png_bytes, bytes), "PNG bytes döndürülmedi."
    assert len(png_bytes) > 1000, f"PNG çok küçük: {len(png_bytes)} bytes"
    # PNG magic bytes kontrolü
    assert png_bytes[:4] == b"\x89PNG", "Geçerli PNG başlığı yok."
    print(f"✅ test_png_generation_support: BAŞARILI ({len(png_bytes)//1024} KB)")


def test_png_all_signal_types() -> None:
    """Tüm sinyal türleri için PNG üretiliyor mu?"""
    config.load_config()
    buffer = _make_test_buffer()

    for stype in ["S1", "S2", "S3", "S4"]:
        for direction in ["destek", "direnc"]:
            signal = _make_test_signal(direction, stype)
            png_bytes = generate_signal_card(signal, buffer)
            assert png_bytes[:4] == b"\x89PNG", f"{stype}/{direction} için geçersiz PNG."
    print("✅ test_png_all_signal_types: BAŞARILI (8 kombinasyon)")


def test_png_empty_buffer() -> None:
    """Boş buffer'la PNG üretimi çöküyor mu?"""
    config.load_config()
    signal = _make_test_signal()
    buffer = RingBufferManager()  # Boş

    try:
        png_bytes = generate_signal_card(signal, buffer)
        assert isinstance(png_bytes, bytes)
        print(f"✅ test_png_empty_buffer: BAŞARILI (boş buffer ile {len(png_bytes)//1024} KB)")
    except Exception as exc:
        print(f"❌ test_png_empty_buffer: HATA — {exc}")


def test_telegram_dry_run_no_error() -> None:
    """DRY-RUN modunda Telegram notifier hata vermiyor mu?"""
    config.load_config()
    # dry_run=true olmalı (config.yaml'dan)
    assert config.is_dry_run(), "Bu test dry_run=true gerektirir."

    notifier = TelegramNotifier()
    signal = _make_test_signal()

    import asyncio

    async def run():
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # Sahte PNG
        await notifier.send_signal(signal, png_bytes)
        await notifier.send_system("Test sistem mesajı")
        await notifier.send_warning("Test uyarı mesajı")

    asyncio.run(run())
    print("✅ test_telegram_dry_run_no_error: BAŞARILI")


def test_signal_caption_format() -> None:
    """Sinyal mesajı formatı doğru mu?"""
    signal = _make_test_signal("destek", "S2")
    caption = TelegramNotifier._build_signal_caption(signal)

    assert "SOL/USDT" in caption, "Coin adı eksik."
    assert "182.40" in caption or "182.4" in caption, "Seviye eksik."
    assert "9.10" in caption or "9.1" in caption, "Skor eksik."
    assert "ÇİFT ONAY" in caption, "Sinyal türü etiketi eksik."
    print("✅ test_signal_caption_format: BAŞARILI")


if __name__ == "__main__":
    setup_logging()
    print("\n=== PHASE 3 TESTLERİ ===\n")
    test_png_generation_support()
    test_png_all_signal_types()
    test_png_empty_buffer()
    test_telegram_dry_run_no_error()
    test_signal_caption_format()
    print("\n✅ Tüm Phase 3 testleri tamamlandı.\n")
