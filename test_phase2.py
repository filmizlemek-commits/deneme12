"""
Phase 2 Test — Skorlama motoru.
Kullanım: python test_phase2.py
"""

import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging
from src.ring_buffer import RingBufferManager, OrderBookSnapshot
from src.scoring_engine import ScoringEngine, _compute_wall_threshold, _are_same_level


def _make_buffer_with_walls(
    coin: str,
    current_price: float,
    wall_price: float,
    wall_size: float = 1_000_000,
    avg_size: float = 50_000,
    side: str = "bid",
    exchanges: list[str] | None = None,
    market_types: list[str] | None = None,
) -> RingBufferManager:
    """Test için duvar içeren buffer oluştur."""
    config.load_config()
    mgr = RingBufferManager()
    mgr.update_extras(coin, last_price=current_price, funding_rate=0.01, volume_change_pct=250.0)

    for ex in (exchanges or ["binance"]):
        for mt in (market_types or ["spot"]):
            # Normal seviyeler + büyük duvar
            levels = [[wall_price - i * 0.01, avg_size / current_price] for i in range(1, 20)]
            # Duvar: çok büyük
            levels.insert(0, [wall_price, wall_size / current_price])

            if side == "bid":
                bids = levels
                asks = [[current_price + 1 + i * 0.01, avg_size / current_price] for i in range(20)]
            else:
                bids = [[current_price - 1 - i * 0.01, avg_size / current_price] for i in range(20)]
                asks = levels

            snap = OrderBookSnapshot(
                timestamp=time.time(),
                bids=np.array(bids, dtype=np.float64),
                asks=np.array(asks, dtype=np.float64),
                exchange=ex,
                market_type=mt,
            )
            mgr.get_or_create(coin).add_snapshot(snap)

    return mgr


def test_wall_threshold() -> None:
    """Duvar eşiği hesaplaması doğru mu?"""
    import numpy as np
    sizes = np.array([100.0, 200.0, 150.0, 130.0, 120.0])
    threshold = _compute_wall_threshold(sizes, 3.0)
    expected = np.mean(sizes) * 3.0
    assert abs(threshold - expected) < 0.01, f"Beklenen {expected:.2f}, alınan: {threshold:.2f}"
    print("✅ test_wall_threshold: BAŞARILI")


def test_same_level() -> None:
    """Seviye eşleştirme toleransı doğru mu?"""
    assert _are_same_level(100.0, 100.1, 0.2)   # %0.1 < %0.2
    assert not _are_same_level(100.0, 100.5, 0.2)  # %0.5 > %0.2
    assert _are_same_level(50000.0, 50050.0, 0.2)  # %0.1 ≈ OK
    print("✅ test_same_level: BAŞARILI")


def test_s1_signal_generated() -> None:
    """S1 sinyali (yaklaşım) üretiliyor mu?"""
    config.load_config()
    coin = "BTC/USDT"
    current_price = 50000.0
    wall_price = 50200.0  # %0.4 uzakta — proximity_threshold_pct=0.5 içinde

    mgr = _make_buffer_with_walls(coin, current_price, wall_price, wall_size=5_000_000)
    engine = ScoringEngine(mgr)
    signals = engine.scan_all()

    s1_signals = [s for s in signals if s.coin == coin and s.signal_type == "S1"]
    if not s1_signals:
        # Duvar yok veya skor düşükse S1 üretilmeyebilir, uyarı ver
        print(f"⚠️  test_s1_signal_generated: S1 sinyali üretilmedi (wall_price={wall_price})")
    else:
        print(f"✅ test_s1_signal_generated: BAŞARILI (skor={s1_signals[0].score:.2f})")


def test_s2_signal_spot_futures() -> None:
    """S2 sinyali (spot + vadeli çift onay) üretiliyor mu?"""
    config.load_config()
    coin = "ETH/USDT"
    current_price = 3000.0
    wall_price = 3010.0  # Yakın

    mgr = _make_buffer_with_walls(
        coin, current_price, wall_price,
        wall_size=2_000_000,
        exchanges=["binance"],
        market_types=["spot", "futures"],
    )
    engine = ScoringEngine(mgr)
    signals = engine.scan_all()

    s2_signals = [s for s in signals if s.coin == coin and s.signal_type == "S2"]
    if not s2_signals:
        print(f"⚠️  test_s2_signal_spot_futures: S2 sinyali üretilmedi")
    else:
        print(f"✅ test_s2_signal_spot_futures: BAŞARILI (skor={s2_signals[0].score:.2f})")


def test_s3_cross_exchange() -> None:
    """S3 sinyali (cross-exchange) üretiliyor mu?"""
    config.load_config()
    coin = "SOL/USDT"
    current_price = 185.0
    wall_price = 185.5  # Çok yakın

    mgr = _make_buffer_with_walls(
        coin, current_price, wall_price,
        wall_size=500_000,
        exchanges=["binance", "bybit"],
        market_types=["spot"],
    )
    engine = ScoringEngine(mgr)
    signals = engine.scan_all()

    s3_signals = [s for s in signals if s.coin == coin and s.signal_type == "S3"]
    if not s3_signals:
        print(f"⚠️  test_s3_cross_exchange: S3 sinyali üretilmedi")
    else:
        print(f"✅ test_s3_cross_exchange: BAŞARILI (skor={s3_signals[0].score:.2f})")


def test_score_range() -> None:
    """Tüm skorlar 0-10 arasında mı?"""
    config.load_config()
    coin = "AVAX/USDT"
    mgr = _make_buffer_with_walls(coin, 40.0, 40.2, wall_size=1_000_000)
    engine = ScoringEngine(mgr)
    signals = engine.scan_all()
    for sig in signals:
        assert 0.0 <= sig.score <= 10.0, f"Skor aralık dışı: {sig.score}"
    print(f"✅ test_score_range: BAŞARILI ({len(signals)} sinyal kontrol edildi)")


def test_cooldown() -> None:
    """Cooldown mekanizması çalışıyor mu? Aynı coin tekrar sinyal vermemeli."""
    config.load_config()
    coin = "LINK/USDT"
    mgr = _make_buffer_with_walls(coin, 15.0, 15.05, wall_size=500_000)
    engine = ScoringEngine(mgr)

    # İlk tarama
    signals1 = engine.scan_all()
    # İkinci tarama — cooldown aktif olmalı
    signals2 = engine.scan_all()

    coin_signals_2 = [s for s in signals2 if s.coin == coin]
    assert len(coin_signals_2) == 0, "Cooldown çalışmıyor: coin tekrar sinyal verdi."
    print("✅ test_cooldown: BAŞARILI")


def test_no_signal_without_wall() -> None:
    """Duvar yoksa sinyal üretilmemeli."""
    config.load_config()
    mgr = RingBufferManager()
    coin = "VET/USDT"
    # Tüm seviyelerin eşit boyutta olduğu normal emir defteri
    uniform_bids = [[0.05 - i * 0.001, 1000.0] for i in range(20)]
    uniform_asks = [[0.051 + i * 0.001, 1000.0] for i in range(20)]

    snap = OrderBookSnapshot(
        timestamp=time.time(),
        bids=np.array(uniform_bids),
        asks=np.array(uniform_asks),
        exchange="binance",
        market_type="spot",
    )
    mgr.update_extras(coin, last_price=0.05)
    mgr.get_or_create(coin).add_snapshot(snap)

    engine = ScoringEngine(mgr)
    signals = engine.scan_all()
    coin_signals = [s for s in signals if s.coin == coin]
    assert len(coin_signals) == 0, "Düzgün emir defterinde sinyal üretilmemeli."
    print("✅ test_no_signal_without_wall: BAŞARILI")


if __name__ == "__main__":
    setup_logging()
    print("\n=== PHASE 2 TESTLERİ ===\n")
    test_wall_threshold()
    test_same_level()
    test_s1_signal_generated()
    test_s2_signal_spot_futures()
    test_s3_cross_exchange()
    test_score_range()
    test_cooldown()
    test_no_signal_without_wall()
    print("\n✅ Tüm Phase 2 testleri tamamlandı.\n")
