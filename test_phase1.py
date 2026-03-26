"""
Phase 1 Test — Ring buffer ve veri toplayıcı bileşenleri.
Kullanım: python test_phase1.py
"""

import asyncio
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from src import config
from src.logger_setup import setup_logging
from src.ring_buffer import RingBufferManager, OrderBookSnapshot


def test_ring_buffer_add_and_evict() -> None:
    """Ring buffer ekleme ve eski veri temizleme."""
    config.load_config()

    mgr = RingBufferManager()
    coin = "BTC/USDT"

    # 10 snapshot ekle
    for i in range(10):
        mgr.add_snapshot(
            coin=coin,
            exchange="binance",
            market_type="spot",
            bids=[[50000.0 - i, 1.0], [49999.0 - i, 2.0]],
            asks=[[50001.0 + i, 1.0], [50002.0 + i, 2.0]],
        )

    buf = mgr.get_buffer(coin)
    assert buf is not None, "Buffer None döndü."
    assert len(buf.snapshots) == 10, f"Beklenen 10, alınan: {len(buf.snapshots)}"
    print("✅ test_ring_buffer_add_and_evict: BAŞARILI")


def test_ring_buffer_latest_snapshot() -> None:
    """En son snapshot doğru döndürülüyor mu?"""
    config.load_config()
    mgr = RingBufferManager()
    coin = "ETH/USDT"

    mgr.add_snapshot(coin, "binance", "spot", [[3000.0, 1.0]], [[3001.0, 1.0]])
    mgr.add_snapshot(coin, "bybit", "futures", [[3000.5, 2.0]], [[3001.5, 2.0]])

    buf = mgr.get_buffer(coin)
    snap_spot = buf.latest_snapshot("binance", "spot")
    snap_fut = buf.latest_snapshot("bybit", "futures")
    snap_missing = buf.latest_snapshot("okx", "spot")

    assert snap_spot is not None, "Binance spot snapshot bulunamadı."
    assert snap_fut is not None, "Bybit futures snapshot bulunamadı."
    assert snap_missing is None, "Olmayan snapshot None döndürmeli."
    assert snap_spot.bids[0][0] == 3000.0, "Fiyat uyuşmuyor."
    print("✅ test_ring_buffer_latest_snapshot: BAŞARILI")


def test_ring_buffer_extras() -> None:
    """Ek veriler (funding, hacim, ATR) doğru güncelleniyor mu?"""
    config.load_config()
    mgr = RingBufferManager()
    coin = "SOL/USDT"

    mgr.update_extras(coin, funding_rate=0.01, volume_change_pct=150.0, atr=2.5, last_price=185.0)
    buf = mgr.get_buffer(coin)
    assert buf.funding_rate == 0.01
    assert buf.volume_change_pct == 150.0
    assert buf.atr == 2.5
    assert buf.last_price == 185.0
    print("✅ test_ring_buffer_extras: BAŞARILI")


def test_ring_buffer_remove_coin() -> None:
    """Coin kaldırma işlemi doğru çalışıyor mu?"""
    config.load_config()
    mgr = RingBufferManager()
    coin = "DOGE/USDT"

    mgr.add_snapshot(coin, "binance", "spot", [[0.1, 1000.0]], [[0.101, 1000.0]])
    assert mgr.get_buffer(coin) is not None

    mgr.remove_coin(coin)
    assert mgr.get_buffer(coin) is None
    print("✅ test_ring_buffer_remove_coin: BAŞARILI")


def test_ring_buffer_ram_estimate() -> None:
    """RAM tahmini sıfırdan büyük mü?"""
    config.load_config()
    mgr = RingBufferManager()
    coin = "BNB/USDT"

    for _ in range(20):
        mgr.add_snapshot(
            coin, "binance", "spot",
            [[300.0 + i * 0.1, 10.0] for i in range(20)],
            [[300.5 + i * 0.1, 10.0] for i in range(20)],
        )

    ram_mb = mgr.total_ram_mb()
    assert ram_mb > 0, "RAM tahmini 0 olmamalı."
    print(f"✅ test_ring_buffer_ram_estimate: BAŞARILI (tahmini {ram_mb:.4f} MB)")


def test_ring_buffer_eviction_by_time() -> None:
    """Eski snapshotlar zaman aşımında temizleniyor mu?"""
    config.load_config()
    mgr = RingBufferManager()
    coin = "ADA/USDT"
    buf = mgr.get_or_create(coin)

    # Çok eski snapshot ekle (31 dakika önce)
    old_snap = OrderBookSnapshot(
        timestamp=time.time() - 31 * 60,
        bids=np.array([[0.5, 100.0]]),
        asks=np.array([[0.501, 100.0]]),
        exchange="binance",
        market_type="spot",
    )
    buf.snapshots.append(old_snap)

    # Yeni snapshot ekle (eviction tetikler)
    mgr.add_snapshot(coin, "binance", "spot", [[0.5, 100.0]], [[0.501, 100.0]])

    # Eski snapshot temizlenmiş olmalı
    for snap in buf.snapshots:
        assert snap.timestamp > time.time() - 31 * 60, "Eski snapshot temizlenmedi."

    print("✅ test_ring_buffer_eviction_by_time: BAŞARILI")


def test_numpy_array_structure() -> None:
    """Snapshot numpy dizileri doğru yapıda mı?"""
    config.load_config()
    mgr = RingBufferManager()
    coin = "XRP/USDT"

    bids = [[0.6, 1000.0], [0.599, 2000.0], [0.598, 1500.0]]
    asks = [[0.601, 800.0], [0.602, 1200.0]]

    mgr.add_snapshot(coin, "binance", "spot", bids, asks)
    buf = mgr.get_buffer(coin)
    snap = buf.latest_snapshot("binance", "spot")

    assert snap is not None
    assert snap.bids.shape == (3, 2), f"Bids şekli yanlış: {snap.bids.shape}"
    assert snap.asks.shape == (2, 2), f"Asks şekli yanlış: {snap.asks.shape}"
    assert snap.bids.dtype == np.float64
    print("✅ test_numpy_array_structure: BAŞARILI")


if __name__ == "__main__":
    setup_logging()
    print("\n=== PHASE 1 TESTLERİ ===\n")
    test_ring_buffer_add_and_evict()
    test_ring_buffer_latest_snapshot()
    test_ring_buffer_extras()
    test_ring_buffer_remove_coin()
    test_ring_buffer_ram_estimate()
    test_ring_buffer_eviction_by_time()
    test_numpy_array_structure()
    print("\n✅ Tüm Phase 1 testleri tamamlandı.\n")
